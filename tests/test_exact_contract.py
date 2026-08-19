from __future__ import annotations

import json
import sqlite3

import pandas as pd

from cointr_fraud.generator import EVENT_COUNT, FRAUD_COUNT, USER_COUNT


def test_exact_counts_and_manual_boundaries(pipeline_result) -> None:
    summary = pipeline_result.summary
    assert summary["user_count"] == USER_COUNT == 1_200
    assert summary["fraud_count"] == FRAUD_COUNT == 19
    assert summary["event_count"] == EVENT_COUNT == 105_318
    assert summary["graph_candidate_count"] == 15
    assert summary["review_queue_count"] == 50
    assert summary["alert_capacity"]["model_lane_capacity"] == 35
    assert summary["alert_capacity"]["graph_lane_capacity"] == 15
    assert summary["alert_capacity"]["swap_in_count"] > 0
    queue = pd.read_csv(pipeline_result.output_dir / "human_review_queue.csv")
    assert len(queue) == 50
    assert queue["selection_lane"].eq("GRAPH_RECALL").sum() == 15
    assert not queue["automatic_relabel_allowed"].any()
    assert not queue["automatic_external_filing_allowed"].any()
    assert queue["label_interpretation"].eq("INCONCLUSIVE_UNCONFIRMED").all()
    model_metrics = pd.read_csv(pipeline_result.output_dir / "model_metrics.csv")
    single_metrics = pd.read_csv(pipeline_result.output_dir / "single_feature_metrics.csv")
    assert model_metrics["roc_auc"].between(0.5, 0.995, inclusive="neither").all()
    assert 0.5 < single_metrics["auc_1d"].max() < 0.995
    context = single_metrics[single_metrics["feature"].isin(["api_event_ratio", "night_event_ratio"])]
    assert not context["model_input"].any()


def test_feature_graph_and_tree_audits(pipeline_result) -> None:
    output = pipeline_result.output_dir
    feature_audit = json.loads((output / "feature_build_audit.json").read_text(encoding="utf-8"))
    graph_audit = json.loads((output / "graph_audit.json").read_text(encoding="utf-8"))
    assert feature_audit["point_in_time_safe"] is True
    assert feature_audit["label_maturity_days"] == 52
    assert feature_audit["bankUserName_alias_accepted"] is True
    assert len(feature_audit["asset_pairs"]) == 6
    assert graph_audit["ip_weight"] == 0.25
    assert graph_audit["deposit_address_included"] is False
    assert graph_audit["path_time_direction_amount_count_included"] is True
    paths = pd.read_csv(output / "graph_top15_candidates.csv")["path_examples"].str.cat(sep=" ")
    assert "source=" in paths and "target=" in paths and "events=" in paths and "amount_usdt=" in paths
    rules = (output / "tree_rules.txt").read_text(encoding="utf-8")
    assert "exploratory_full_fit_not_oof_validated" in rules


def test_sql_confidentiality_pit_history_and_four_results(pipeline_result) -> None:
    output = pipeline_result.output_dir
    results = sorted(path.name for path in (output / "sql_results").glob("*.csv"))
    assert results == [
        "01_customer_risk_profile.csv",
        "02_str_case_mart.csv",
        "03_fraud_feature_snapshot.csv",
        "04_kep_case_input.csv",
    ]
    customer = pd.read_csv(output / "sql_results" / "01_customer_risk_profile.csv")
    assert len(customer) == 1_200
    assert not {
        "str_case_id", "review_status", "review_decision", "report_status", "overdue_status"
    }.intersection(customer.columns)
    str_mart = pd.read_csv(output / "sql_results" / "02_str_case_mart.csv")
    assert {"review_status", "review_decision", "report_status", "overdue_status"}.issubset(str_mart)
    assert not str_mart["automatic_external_filing_allowed"].any()

    with sqlite3.connect(pipeline_result.database_path) as connection:
        history = pd.read_sql_query("SELECT * FROM risk_profile_history", connection)
        max_event = pd.read_sql_query("SELECT MAX(available_at) AS value FROM events", connection).iloc[0, 0]
        str_created = pd.read_sql_query("SELECT MIN(candidate_created_at) AS value FROM str_cases", connection).iloc[0, 0]
    history["recorded_at"] = pd.to_datetime(history["recorded_at"], utc=True)
    model = history[history["snapshot_type"] == "MODEL_CUTOFF_DYNAMIC"]
    t1 = history[history["snapshot_type"] == "T_PLUS_1_DYNAMIC"]
    assert model["recorded_at"].min() > pd.Timestamp(max_event)
    assert t1.merge(model, on="user_id", suffixes=("_t1", "_model"))["recorded_at_t1"].lt(
        t1.merge(model, on="user_id", suffixes=("_t1", "_model"))["recorded_at_model"]
    ).all()
    assert pd.Timestamp(str_created) > model["recorded_at"].max()
    assert history.groupby("user_id")["is_current"].sum().eq(1).all()
