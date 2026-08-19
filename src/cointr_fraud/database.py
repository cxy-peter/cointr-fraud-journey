from __future__ import annotations

from datetime import timedelta
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd


def _sqlite_frame(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    for column in result.columns:
        if isinstance(result[column].dtype, pd.DatetimeTZDtype) or pd.api.types.is_datetime64_any_dtype(result[column]):
            result[column] = pd.to_datetime(result[column], utc=True).map(
                lambda value: value.isoformat() if pd.notna(value) else None
            )
        elif pd.api.types.is_bool_dtype(result[column]):
            result[column] = result[column].astype(int)
    return result.replace({np.nan: None})


def build_risk_history(
    users: pd.DataFrame,
    scored: pd.DataFrame,
    events: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.Timestamp]:
    """Create immutable onboarding, T+1, model-cutoff and override snapshots."""

    score_lookup = scored.set_index("user_id")
    available = events.copy()
    available["available_at"] = pd.to_datetime(available["available_at"], utc=True)
    model_as_of = max(
        pd.to_datetime(available["available_at"], utc=True).max(),
        pd.to_datetime(users["label_observed_at"], utc=True).max(),
    ) + timedelta(days=1)
    rows: list[dict[str, object]] = []
    for position, user in enumerate(users.sort_values("user_id", kind="stable").itertuples(index=False)):
        registered = pd.Timestamp(user.registration_time)
        rows.append(
            {
                "snapshot_id": f"ONBOARD_{user.user_id}",
                "user_id": user.user_id,
                "snapshot_type": "ONBOARDING_STATIC",
                "risk_level": "MEDIUM" if user.kyc_level == "L1" else "LOW",
                "risk_source": "SYNTHETIC_ONBOARDING_RULE",
                "operator": "SYSTEM_DEMO",
                "reason": "Static onboarding snapshot; immutable history",
                "recorded_at": registered,
                "is_current": False,
            }
        )
        t1_cutoff = registered + timedelta(days=1)
        t1_events = available[
            (available["user_id"] == user.user_id)
            & (available["available_at"] <= t1_cutoff)
            & (available["status"] == "SUCCESS")
        ]
        t1_withdrawal = bool(t1_events["event_type"].eq("CHAIN_WITHDRAW").any())
        t1_device_count = int(t1_events["device_id"].nunique())
        t1_level = "MEDIUM" if t1_withdrawal or t1_device_count >= 3 else "LOW"
        rows.append(
            {
                "snapshot_id": f"T1_{user.user_id}",
                "user_id": user.user_id,
                "snapshot_type": "T_PLUS_1_DYNAMIC",
                "risk_level": t1_level,
                "risk_source": "SYNTHETIC_T1_AVAILABLE_EVENT_RULE",
                "operator": "SYSTEM_DEMO",
                "reason": f"Registration+1d available events only; withdrawal={t1_withdrawal}; device_count={t1_device_count}",
                "recorded_at": t1_cutoff,
                "is_current": False,
            }
        )
        score = float(score_lookup.loc[user.user_id, "combined_review_score"])
        level = "HIGH" if score >= 0.70 else ("MEDIUM" if score >= 0.35 else "LOW")
        rows.append(
            {
                "snapshot_id": f"MODEL_{user.user_id}",
                "user_id": user.user_id,
                "snapshot_type": "MODEL_CUTOFF_DYNAMIC",
                "risk_level": level,
                "risk_source": "SYNTHETIC_UNCALIBRATED_OOF_RANK_PLUS_GRAPH",
                "operator": "SYSTEM_DEMO",
                "reason": "Demo-only band from uncalibrated ranking evidence; recorded after all inputs were available",
                "recorded_at": model_as_of,
                "is_current": position % 211 != 0,
            }
        )
        if position % 211 == 0:
            rows.append(
                {
                    "snapshot_id": f"MANUAL_{user.user_id}",
                    "user_id": user.user_id,
                    "snapshot_type": "MANUAL_OVERRIDE",
                    "risk_level": "MEDIUM",
                    "risk_source": "MANUAL_REVIEW_SYNTHETIC",
                    "operator": "REVIEWER_DEMO",
                    "reason": "Synthetic documented override; T+1 must not overwrite",
                    "recorded_at": model_as_of + timedelta(hours=1),
                    "is_current": True,
                }
            )
    history = pd.DataFrame(rows).sort_values(["user_id", "recorded_at", "snapshot_id"], kind="stable")
    if history.groupby("user_id")["is_current"].sum().ne(1).any():
        raise AssertionError("each user must have exactly one current risk snapshot")
    return history.reset_index(drop=True), model_as_of


def build_str_cases(scored: pd.DataFrame, model_as_of: pd.Timestamp) -> pd.DataFrame:
    """Create synthetic internal STR candidates; never an external filing feed."""

    selected = scored.sort_values(
        ["combined_review_score", "user_id"], ascending=[False, True], kind="stable"
    ).head(80)
    rows: list[dict[str, object]] = []
    for index, user in enumerate(selected.itertuples(index=False), 1):
        review_status = ["PENDING", "IN_REVIEW", "COMPLETED"][index % 3]
        review_decision = "ESCALATE_INTERNAL" if review_status == "COMPLETED" and index % 2 == 0 else "UNDECIDED"
        rows.append(
            {
                "str_case_id": f"STR_SYN_{index:05d}",
                "user_id": user.user_id,
                "review_status": review_status,
                "review_decision": review_decision,
                "report_status": "NOT_FILED",
                "overdue_status": "OVERDUE" if review_status != "COMPLETED" and index % 7 == 0 else "ON_TIME",
                "candidate_created_at": model_as_of + timedelta(days=1),
                "internal_candidate_only": True,
                "automatic_external_filing_allowed": False,
                "synthetic_only": True,
            }
        )
    return pd.DataFrame(rows)


def write_demo_database(
    database_path: Path,
    *,
    users: pd.DataFrame,
    events: pd.DataFrame,
    features: pd.DataFrame,
    scored: pd.DataFrame,
    review_queue: pd.DataFrame,
    graph_candidates: pd.DataFrame,
    kep_cases: pd.DataFrame,
    kep_emails: pd.DataFrame,
    kep_results: pd.DataFrame,
) -> dict[str, int]:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    if database_path.exists():
        database_path.unlink()

    public_users = users.drop(columns=[column for column in users if column.startswith("latent_")])
    risk_history, model_as_of = build_risk_history(users, scored, events)
    str_cases = build_str_cases(scored, model_as_of)
    tables = {
        "users": public_users,
        "events": events,
        "user_features": features,
        "model_scores": scored,
        "human_review_queue": review_queue,
        "graph_candidates": graph_candidates,
        "risk_profile_history": risk_history,
        "str_cases": str_cases,
        "kep_cases": kep_cases,
        "kep_emails": kep_emails,
        "kep_match_results": kep_results,
    }
    with sqlite3.connect(database_path) as connection:
        for name, frame in tables.items():
            _sqlite_frame(frame).to_sql(name, connection, if_exists="replace", index=False)
        connection.execute("CREATE UNIQUE INDEX idx_users_user_id ON users(user_id)")
        connection.execute("CREATE INDEX idx_events_user_time ON events(user_id, event_time)")
        connection.execute("CREATE INDEX idx_events_state_time ON events(status, available_at)")
        connection.execute("CREATE INDEX idx_risk_current ON risk_profile_history(user_id, is_current)")
        connection.execute("CREATE INDEX idx_str_user ON str_cases(user_id)")
        connection.commit()
    return {name: int(len(frame)) for name, frame in tables.items()}


def execute_sql_files(database_path: Path, sql_dir: Path, output_dir: Path) -> dict[str, int]:
    output_dir.mkdir(parents=True, exist_ok=True)
    row_counts: dict[str, int] = {}
    with sqlite3.connect(database_path) as connection:
        for sql_path in sorted(sql_dir.glob("*.sql")):
            result = pd.read_sql_query(sql_path.read_text(encoding="utf-8"), connection)
            output_path = output_dir / f"{sql_path.stem}.csv"
            result.to_csv(output_path, index=False)
            row_counts[sql_path.name] = int(len(result))
    return row_counts
