from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from .catalog import (
    BUSINESS_EVENT_CODES,
    COHORT_DEFINITIONS,
    SOURCE_ANALYSIS_STEPS,
    SYSTEM_EVENT_CODES,
    CoverageStatus,
    mappings_for_columns,
    model_grid_records,
)


def _num(frame: pd.DataFrame, name: str) -> pd.Series:
    if name not in frame:
        return pd.Series(np.nan, index=frame.index, dtype=float)
    return pd.to_numeric(frame[name], errors="coerce")


def derive_supported_journey_features(users: pd.DataFrame) -> pd.DataFrame:
    result = users.copy()
    flow = pd.concat([
        _num(result, "deposit_amount").rename("deposit"),
        _num(result, "trade_amount").rename("trade"),
        _num(result, "withdrawal_amount").rename("withdrawal"),
    ], axis=1)
    mean = flow.mean(axis=1).replace(0, np.nan)
    result["fund_flow_cv_source_formula"] = flow.std(axis=1, ddof=1).div(mean)
    result["fund_flow_range_ratio_source_formula"] = flow.max(axis=1).sub(flow.min(axis=1)).div(mean)
    result["kyc_duration_hours_proxy"] = _num(result, "registration_to_kyc_minutes").div(60)
    result["kyc_to_first_deposit_hours"] = _num(result, "kyc_to_first_deposit_minutes").div(60)
    counts = pd.concat([_num(result, name).fillna(0) for name in ("deposit_count", "trade_count", "withdrawal_count")], axis=1)
    result["has_any_behavior_proxy"] = counts.sum(axis=1).gt(0).astype(int)
    result["silent_user_proxy"] = counts.sum(axis=1).eq(0).astype(int)
    result["multi_pair_proxy"] = _num(result, "asset_pair_unique_count").fillna(0).gt(1).astype(int)
    return result


def sessionize_user_events(
    events: pd.DataFrame,
    *,
    gap_minutes: int = 60,
    user_column: str = "user_id",
    time_column: str = "event_time",
    event_column: str = "event_type",
    status_column: str = "status",
    origin_column: str = "event_origin",
    parent_column: str = "parent_event_id",
    user_origins: Iterable[str] = ("USER", "USER_INITIATED", "user", "user_initiated"),
) -> tuple[pd.DataFrame, pd.DataFrame]:
    required = {user_column, time_column, event_column}
    missing = required.difference(events.columns)
    if missing:
        raise KeyError(f"missing event columns: {sorted(missing)}")
    work = events.copy()
    work[time_column] = pd.to_datetime(work[time_column], errors="coerce", utc=True)
    work = work.dropna(subset=[user_column, time_column])
    if status_column in work:
        work = work[work[status_column].astype(str).str.upper().eq("SUCCESS")]
    work = work[~work[event_column].astype(str).isin(set(SYSTEM_EVENT_CODES))]
    if origin_column in work:
        work = work[work[origin_column].astype(str).isin(set(user_origins))]
    else:
        work = work[work[event_column].astype(str).isin(set(BUSINESS_EVENT_CODES))]
    sort_cols = [user_column, time_column] + ([parent_column] if parent_column in work else [])
    work = work.sort_values(sort_cols, kind="stable").copy()
    previous = work.groupby(user_column)[time_column].shift(1)
    gap = work[time_column].sub(previous).dt.total_seconds().div(60)
    work["gap_minutes_from_previous_user_event"] = gap
    work["new_session"] = previous.isna() | gap.gt(gap_minutes)
    work["session_number"] = work.groupby(user_column)["new_session"].cumsum().astype(int)
    work["session_id"] = work[user_column].astype(str) + "::" + work["session_number"].astype(str)
    sessions = work.groupby([user_column, "session_id"], as_index=False).agg(
        session_start=(time_column, "min"),
        session_end=(time_column, "max"),
        user_event_count=(event_column, "size"),
        distinct_user_event_count=(event_column, "nunique"),
        median_gap_minutes=("gap_minutes_from_previous_user_event", "median"),
    )
    sessions["session_duration_minutes"] = sessions["session_end"].sub(sessions["session_start"]).dt.total_seconds().div(60)
    return work.reset_index(drop=True), sessions


def feature_coverage_frame(columns: Iterable[str]) -> pd.DataFrame:
    frame = pd.DataFrame([asdict(item) for item in mappings_for_columns(columns)])
    frame["status"] = frame["status"].map(lambda value: value.value if isinstance(value, CoverageStatus) else str(value))
    return frame


def model_grid_frame() -> pd.DataFrame:
    return pd.DataFrame(model_grid_records())


def source_playbook_frame() -> pd.DataFrame:
    return pd.DataFrame([asdict(step) for step in SOURCE_ANALYSIS_STEPS])


def cohort_contract_frame() -> pd.DataFrame:
    return pd.DataFrame(list(COHORT_DEFINITIONS))


def audit_summary(coverage: pd.DataFrame) -> dict[str, int]:
    counts = coverage["status"].value_counts().to_dict()
    return {status.value: int(counts.get(status.value, 0)) for status in CoverageStatus}


def source_contract_gaps(users: pd.DataFrame) -> dict[str, bool]:
    columns = set(users.columns)
    return {
        "has_label_source": "label_source" in columns,
        "has_label_observed_at": "label_observed_at" in columns,
        "has_account_role": "account_role" in columns,
        "has_curated_cohort_type": "cohort_type" in columns,
        "has_pair_level_flags": any(name in columns for name in ("has_usdt_try", "has_trx_try", "has_btc_try")),
    }


def write_analysis_artifacts(*, output_dir: str | Path, users: pd.DataFrame | None = None, events: pd.DataFrame | None = None) -> dict[str, Path]:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    coverage = feature_coverage_frame(users.columns if users is not None else [])
    paths = {
        "coverage": target / "fraud_journey_feature_coverage.csv",
        "playbook": target / "fraud_journey_analysis_steps.csv",
        "cohorts": target / "fraud_journey_cohort_contract.csv",
        "model_grid": target / "fraud_journey_model_grid.csv",
    }
    coverage.to_csv(paths["coverage"], index=False)
    source_playbook_frame().to_csv(paths["playbook"], index=False)
    cohort_contract_frame().to_csv(paths["cohorts"], index=False)
    model_grid_frame().to_csv(paths["model_grid"], index=False)
    if users is not None:
        derived = derive_supported_journey_features(users)
        cols = [name for name in ("user_id", "fraud_label", "fund_flow_cv_source_formula", "fund_flow_range_ratio_source_formula", "kyc_duration_hours_proxy", "kyc_to_first_deposit_hours", "has_any_behavior_proxy", "silent_user_proxy", "multi_pair_proxy") if name in derived]
        paths["derived_preview"] = target / "fraud_journey_derived_feature_preview.csv"
        derived[cols].head(500).to_csv(paths["derived_preview"], index=False)
    if events is not None:
        user_events, sessions = sessionize_user_events(events)
        paths["event_preview"] = target / "fraud_journey_user_events_preview.csv"
        paths["session_preview"] = target / "fraud_journey_sessions_preview.csv"
        user_events.head(1000).to_csv(paths["event_preview"], index=False)
        sessions.head(1000).to_csv(paths["session_preview"], index=False)
    return paths
