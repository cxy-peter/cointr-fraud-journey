from __future__ import annotations

import numpy as np
import pandas as pd

from cointr_fraud.fraud_journey import (
    derive_supported_journey_features,
    feature_coverage_frame,
    model_grid_frame,
    render_focused_report,
    sessionize_user_events,
    source_contract_gaps,
)


def test_model_grid_treats_one_to_four_as_candidate() -> None:
    grid = model_grid_frame()
    ratios = set(grid["negative_to_positive_ratio"].dropna().astype(int))
    assert ratios == {3, 4, 5}
    assert grid["negative_to_positive_ratio"].isna().any()


def test_sessionization_filters_nonterminal_and_system_events_first() -> None:
    events = pd.DataFrame(
        {
            "user_id": ["U1", "U1", "U1", "U1", "U1"],
            "event_time": [
                "2026-01-01 10:00:00+00:00",
                "2026-01-01 10:00:01+00:00",
                "2026-01-01 10:02:00+00:00",
                "2026-01-01 10:05:00+00:00",
                "2026-01-01 11:10:00+00:00",
            ],
            "event_type": [
                "FIAT_DEPOSIT",
                "ReconciliationCheck",
                "SPOT_TRADE",
                "SPOT_TRADE",
                "CHAIN_WITHDRAW",
            ],
            "status": ["SUCCESS", "SUCCESS", "PENDING", "SUCCESS", "SUCCESS"],
            "event_origin": ["USER", "SYSTEM", "USER", "USER", "USER"],
        }
    )
    filtered, sessions = sessionize_user_events(events, gap_minutes=60)
    assert set(filtered["event_type"]) == {
        "FIAT_DEPOSIT",
        "SPOT_TRADE",
        "CHAIN_WITHDRAW",
    }
    assert len(filtered) == 3
    assert sessions.shape[0] == 2
    assert sessions.iloc[0]["user_event_count"] == 2


def test_source_fund_flow_formulas_and_silent_proxy() -> None:
    users = pd.DataFrame(
        {
            "user_id": ["U1", "U2"],
            "deposit_amount": [100.0, 0.0],
            "trade_amount": [100.0, 0.0],
            "withdrawal_amount": [100.0, 0.0],
            "deposit_count": [1, 0],
            "trade_count": [1, 0],
            "withdrawal_count": [1, 0],
            "asset_pair_unique_count": [2, 0],
            "registration_to_kyc_minutes": [120.0, 60.0],
            "kyc_to_first_deposit_minutes": [180.0, np.nan],
        }
    )
    derived = derive_supported_journey_features(users)
    assert np.isclose(derived.loc[0, "fund_flow_cv_source_formula"], 0.0)
    assert np.isclose(
        derived.loc[0, "fund_flow_range_ratio_source_formula"], 0.0
    )
    assert derived.loc[0, "multi_pair_proxy"] == 1
    assert derived.loc[1, "silent_user_proxy"] == 1
    assert np.isclose(derived.loc[0, "kyc_duration_hours_proxy"], 2.0)


def test_coverage_uses_current_repository_column_names() -> None:
    coverage = feature_coverage_frame(
        [
            "registration_channel",
            "kyc_level",
            "fund_loop_cv",
            "amount_diff_ratio",
            "label_observed_at",
        ]
    )
    status = coverage.set_index("source_feature")["status"].to_dict()
    assert status["registration_device_side"] == "EXACT"
    assert status["fund_flow_cv"] == "EXACT"
    assert status["USDTTRY_TRXTRY_BTCTRY_flags"] == "MISSING"
    assert status["strategy_hit_frequency"] == "LINEAGE_RISK"


def test_contract_audit_does_not_invent_curated_white_or_account_role() -> None:
    users = pd.DataFrame(
        {
            "fraud_label": [0, 1],
            "label_observed_at": ["2026-01-01", "2026-01-02"],
        }
    )
    gaps = source_contract_gaps(users)
    assert gaps["has_label_observed_at"] is True
    assert gaps["has_label_source"] is False
    assert gaps["has_account_role"] is False
    assert gaps["has_curated_cohort_type"] is False


def test_report_preserves_truthfulness_and_sampling_boundaries() -> None:
    report = render_focused_report()
    assert "Curated white users are not equivalent" in report
    assert "1:4 remains the existing demo default" in report
    assert "raw 60-minute session-density" in report
