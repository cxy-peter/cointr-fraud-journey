from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .database import execute_sql_files, write_demo_database
from .features import CONTEXT_ONLY_FEATURES, MODEL_FEATURES, engineer_user_features, feature_contract_frame
from .generator import EVENT_COUNT, FRAUD_COUNT, KEP_CASE_COUNT, SEED, USER_COUNT, build_synthetic_data
from .graph import build_graph_candidates
from .kep import KEP_EXPECTED_COUNTS, generate_kep_stress_data, match_kep_subjects
from .metrics import single_feature_metrics
from .models import run_oof_models


@dataclass(frozen=True)
class PipelineResult:
    output_dir: Path
    database_path: Path
    summary: dict[str, Any]


def _json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    return value


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(_json_ready(payload), indent=2, ensure_ascii=False), encoding="utf-8")


def _build_scores(
    users: pd.DataFrame,
    oof_scores: pd.DataFrame,
    graph_candidates: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    scored = users[["user_id", "fraud_label", "label_observed_at"]].merge(
        oof_scores.drop(columns=["fraud_label"]), on="user_id", how="left", validate="one_to_one"
    )
    graph_scores = graph_candidates.set_index("user_id")["graph_score"]
    scored["graph_score"] = scored["user_id"].map(graph_scores).fillna(0.0)
    scored["xgboost_oof_percentile"] = scored["xgboost_oof_score"].rank(
        method="average", pct=True
    )
    scored["combined_review_score"] = (
        0.50 * scored["xgboost_oof_percentile"] + 0.50 * scored["graph_score"]
    )
    scored["label_interpretation"] = np.where(
        scored["fraud_label"].eq(0), "INCONCLUSIVE_UNCONFIRMED", "CONFIRMED_SYNTHETIC_FRAUD"
    )
    scored["automatic_relabel_allowed"] = False
    scored["automatic_enforcement_allowed"] = False
    scored = scored.sort_values("user_id", kind="stable").reset_index(drop=True)

    unlabeled = scored[scored["fraud_label"] == 0].copy()
    model_top = set(
        unlabeled.sort_values(["xgboost_oof_score", "user_id"], ascending=[False, True], kind="stable")
        .head(50)["user_id"]
    )
    graph_set = set(graph_candidates["user_id"])
    graph_lane_ids = graph_candidates.sort_values(["rank", "user_id"], kind="stable")["user_id"].tolist()
    graph_lane = unlabeled[unlabeled["user_id"].isin(graph_lane_ids)].copy()
    graph_rank = {user_id: rank for rank, user_id in enumerate(graph_lane_ids, 1)}
    graph_lane["selection_lane"] = "GRAPH_RECALL"
    graph_lane["lane_rank"] = graph_lane["user_id"].map(graph_rank)
    model_lane = (
        unlabeled[~unlabeled["user_id"].isin(graph_set)]
        .sort_values(["xgboost_oof_score", "user_id"], ascending=[False, True], kind="stable")
        .head(50 - len(graph_lane))
        .copy()
    )
    model_lane["selection_lane"] = "MODEL_RANK"
    model_lane["lane_rank"] = range(1, len(model_lane) + 1)
    queue = pd.concat([model_lane, graph_lane], ignore_index=True).sort_values(
        ["combined_review_score", "selection_lane", "lane_rank", "user_id"],
        ascending=[False, True, True, True],
        kind="stable",
    ).reset_index(drop=True)
    queue.insert(0, "review_rank", range(1, len(queue) + 1))
    queue["model_graph_overlap"] = queue["user_id"].isin(graph_set)
    queue["swap_in_vs_model_only"] = ~queue["user_id"].isin(model_top)
    queue["review_status"] = "PENDING_MANUAL_REVIEW"
    queue["review_reason"] = np.where(
        queue["selection_lane"].eq("GRAPH_RECALL"),
        "EXPLAINABLE_GRAPH_RECALL_PATH",
        "HIGH_XGBOOST_OOF_RANK",
    )
    queue["current_label"] = 0
    queue["false_positive_conclusion_allowed"] = False
    queue["internal_str_candidate_only"] = True
    queue["automatic_external_filing_allowed"] = False
    queue["review_capacity"] = 50
    if len(queue) != 50 or queue["automatic_relabel_allowed"].any() or queue["current_label"].ne(0).any():
        raise AssertionError("manual review queue contract failed")

    queue_set = set(queue["user_id"])
    capacity = {
        "queue_capacity": 50,
        "queue_alert_rate": 50 / USER_COUNT,
        "model_lane_capacity": int(queue["selection_lane"].eq("MODEL_RANK").sum()),
        "graph_lane_capacity": int(queue["selection_lane"].eq("GRAPH_RECALL").sum()),
        "graph_candidate_capacity": 15,
        "model_top50_graph_overlap": len(model_top & graph_set),
        "combined_queue_graph_overlap": len(queue_set & graph_set),
        "swap_in_count": len(queue_set - model_top),
        "swap_out_count": len(model_top - queue_set),
        "automatic_relabel_allowed": False,
        "automatic_external_filing_allowed": False,
    }
    return scored, queue.reset_index(drop=True), capacity


def _event_summary(events: pd.DataFrame) -> pd.DataFrame:
    return (
        events.groupby(["event_type", "status", "asset_pair"], dropna=False)
        .agg(event_count=("event_id", "count"), amount_usdt=("amount_usdt", "sum"))
        .reset_index()
        .sort_values(["event_type", "status", "asset_pair"], kind="stable")
    )


def _write_tree_rules(path: Path, rules: list[dict[str, object]]) -> None:
    lines = [
        "EXPLORATORY FULL-FIT TREE RULES — NOT OOF VALIDATED",
        "Leaf positive rates are same-sample diagnostics, not validation results or production thresholds.",
        "",
    ]
    for rule in rules:
        lines.append(json.dumps(_json_ready(rule), ensure_ascii=False, sort_keys=True))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_run_report(path: Path, summary: dict[str, Any], metrics: pd.DataFrame) -> None:
    metric_lines = [
        f"| {row.model_name} | {row.roc_auc:.6f} | {row.ks:.6f} | {row.average_precision:.6f} | {row.lift_top_10:.6f} | {row.lift_top_20:.6f} |"
        for row in metrics.itertuples(index=False)
    ]
    kep_counts = summary["kep_status_counts"]
    text = f"""# CoinTR Fraud Journey 合成运行报告

## 本次实际运行

- 固定随机种子：`{SEED}`
- 用户：**{summary['user_count']}**
- 已确认合成 Fraud 标签：**{summary['fraud_count']}**
- 时间戳事件：**{summary['event_count']}**
- 可解释未标记 Graph 候选：**{summary['graph_candidate_count']}**
- 人工复核队列：**{summary['review_queue_count']}**
- KEP 合成案件：**{summary['kep_case_count']}**

| 模型 | OOF AUC | OOF KS | OOF Average Precision | Tie-aware Lift@10% | Tie-aware Lift@20% |
|---|---:|---:|---:|---:|---:|
{chr(10).join(metric_lines)}

Tree 文本是全量样本拟合后的探索性规则，全部标记为 `exploratory_full_fit_not_oof_validated`；其中叶节点正例率不是验证结果。XGBoost/Tree 指标来自五折随机 Stratified OOF；每折预处理和 XGBoost 1:4 负样本抽样不读取验证折标签。这里没有宣称 OOT/时间外推验证，也没有输出 OOT 指标。

## 资料约束如何落地

- **Feature contract**：`feature_contracts.csv` 为每个变量给出定义、来源、窗口、`available_at` 和 owner。金额仅是候选之一；资金闭环、时间差、小额入金、银行、设备/IP/地址与图谱变量优先并列呈现，交易覆盖全部合成币对。API/夜间占比只做 context-only 描述，不进入 Tree/XGBoost，也不能单独转规则。
- **约 52 天标签成熟期与 PIT**：标签观察时间固定为注册后 52 天；特征截止为标签观察日前 7 天，只使用截止时已到达且状态为 `SUCCESS` 的事件。当前标签 0 表示未确认/未观察到，不等于真实正常。
- **Graph**：Device/Email/Phone/KYC/Withdraw Address 为强边，IP 权重仅 0.25；公共 IP、交易所归集/企业代理前缀和度数超阈值 supernode 被过滤；入金地址不建图。路径证据含两侧时间、方向、金额和事件数。
- **审核容量**：50 个席位采用可审计双通道，35 个来自 XGBoost OOF 排序，15 个来自可解释 Graph 补召回；去重后补满，并输出 overlap/swap-in/swap-out。XGBoost 因训练折 1:4 下采样而未做概率校准；综合分使用 OOF 百分位与图证据，仅用于队列内排序，不解释为欺诈概率。SQLite risk band 也仅是 synthetic/demo-only 展示。
- **人工复核与 STR**：15 个 Graph 候选和 50 条高分 label-0 记录只进入人工复核，`automatic_relabel_allowed=false`。STR 是隔离的内部候选表，不进入普通客户画像，不自动外部报送。
- **风险画像历史**：Onboarding 静态快照；注册后 T+1 只用截至当天 `available_at` 的弱规则；综合模型另在所有模型/Graph 输入已可用后的 `MODEL_CUTOFF_DYNAMIC` 记录；人工 override 分行保存。风险来源、operator、reason、timestamp 完整保留，动态刷新不会覆盖当前人工 override。
- **SQL**：四份 SQL 都注明 grain/key、状态/时间、join cardinality、PIT 与 reconciliation 口径；仅使用本项目合成 schema，不映射生产表。
- **KEP**：现场浏览器必须人工登录；离线确定性匹配先 `sorusturma_no` 后 `sayi/reference`，只读 `Konu:` 边界，排除 icra，并将 `NOT_FOUND` 与业务未回复拆开；结果含 90 秒 timeout 与 case_id resume key。
- **AI/Playwright**：AI 只建议抽取/摘要；编号匹配、状态迁移、权限、对外提交和资金处置保持确定性校验与人工确认。

## KEP 压力测试（全部为合成）

- MATCH_SORUSTURMA: {kep_counts.get('MATCH_SORUSTURMA', 0)}
- MATCH_SAYI: {kep_counts.get('MATCH_SAYI', 0)}
- EXCLUDED_ICRA: {kep_counts.get('EXCLUDED_ICRA', 0)}
- NOT_FOUND: {kep_counts.get('NOT_FOUND', 0)}
- BUSINESS_NO_RESPONSE: {kep_counts.get('BUSINESS_NO_RESPONSE', 0)}
- AMBIGUOUS_MULTIPLE: {kep_counts.get('AMBIGUOUS_MULTIPLE', 0)}

**数字口径隔离**：上传资料中可核验的是 1,273 条 CMS 记录、184 条疑似异常、抽样 20 条根因复核；上面的 13,703 条只是本仓库的合成压力测试。两组数字不可混称。

## 真实性边界

所有实体、事件、案件、邮件、阈值和结果均为确定性合成。本报告没有复用材料中的历史混淆矩阵，也不声称代表 CoinTR 生产系统或真实策略效果。材料提到的“链上出金策略 Precision 可接受但 Recall 偏低”仅作为为何要探索模型与图谱补充召回的业务动机；此处指标只证明代码链路可运行。
"""
    path.write_text(text, encoding="utf-8")


def run_pipeline(output_dir: str | Path | None = None) -> PipelineResult:
    project_root = Path(__file__).resolve().parents[2]
    out = Path(output_dir).resolve() if output_dir is not None else project_root / "outputs"
    out.mkdir(parents=True, exist_ok=True)
    (out / "sql_results").mkdir(parents=True, exist_ok=True)
    data_manifest_dir = project_root / "data" / "synthetic"
    data_manifest_dir.mkdir(parents=True, exist_ok=True)

    synthetic = build_synthetic_data()
    users, events, graph_edges = synthetic.users, synthetic.events, synthetic.graph_edges
    feature_result = engineer_user_features(users, events)
    features = feature_result.features
    diagnostics = single_feature_metrics(
        features,
        [name for name in MODEL_FEATURES + CONTEXT_ONLY_FEATURES if pd.api.types.is_numeric_dtype(features[name])],
    )
    diagnostics["model_input"] = ~diagnostics["feature"].isin(CONTEXT_ONLY_FEATURES)
    diagnostics["context_note"] = np.where(
        diagnostics["feature"].isin(CONTEXT_ONLY_FEATURES),
        "context_only_not_a_standalone_rule_or_model_input",
        "candidate_model_input",
    )
    oof = run_oof_models(features, MODEL_FEATURES)
    if not (0.5 < float(diagnostics["auc_1d"].max()) < 0.995):
        raise AssertionError("synthetic single-feature performance must be directional but non-perfect")
    if oof.metrics["roc_auc"].ge(0.995).any():
        raise AssertionError("synthetic OOF performance must remain below 0.995")
    graph_candidates, graph_audit = build_graph_candidates(users, graph_edges, top_n=15)
    scored, review_queue, capacity = _build_scores(users, oof.scores, graph_candidates)

    kep_cases, kep_emails = generate_kep_stress_data(users["user_id"].astype(str).tolist())
    kep_results = match_kep_subjects(kep_cases, kep_emails)
    kep_counts = {key: int(value) for key, value in kep_results["match_status"].value_counts().to_dict().items()}

    assert len(users) == USER_COUNT
    assert int(users["fraud_label"].sum()) == FRAUD_COUNT
    assert len(events) == EVENT_COUNT
    assert len(graph_candidates) == 15
    assert len(review_queue) == 50
    assert len(kep_cases) == KEP_CASE_COUNT
    assert kep_counts == KEP_EXPECTED_COUNTS

    features.to_csv(out / "user_feature_snapshot.csv", index=False)
    feature_contract_frame().to_csv(out / "feature_contracts.csv", index=False)
    diagnostics.to_csv(out / "single_feature_metrics.csv", index=False)
    oof.metrics.to_csv(out / "model_metrics.csv", index=False)
    scored.to_csv(out / "model_scores.csv", index=False)
    graph_candidates.to_csv(out / "graph_top15_candidates.csv", index=False)
    review_queue.to_csv(out / "human_review_queue.csv", index=False)
    _event_summary(events).to_csv(out / "event_summary.csv", index=False)
    kep_results.to_csv(out / "kep_match_results.csv", index=False)
    pd.DataFrame([{"match_status": key, "case_count": value} for key, value in sorted(kep_counts.items())]).to_csv(out / "kep_match_summary.csv", index=False)
    _write_tree_rules(out / "tree_rules.txt", oof.tree_rules)
    _write_json(out / "oof_fold_manifests.json", oof.manifests)
    _write_json(out / "feature_build_audit.json", feature_result.audit)
    _write_json(out / "graph_audit.json", graph_audit)
    _write_json(out / "alert_capacity.json", capacity)

    database_path = out / "cointr_fraud_demo.sqlite"
    table_counts = write_demo_database(
        database_path,
        users=users,
        events=events,
        features=features,
        scored=scored,
        review_queue=review_queue,
        graph_candidates=graph_candidates,
        kep_cases=kep_cases,
        kep_emails=kep_emails,
        kep_results=kep_results,
    )
    sql_counts = execute_sql_files(database_path, project_root / "sql", out / "sql_results")

    summary: dict[str, Any] = {
        "seed": SEED,
        "user_count": len(users),
        "fraud_count": int(users["fraud_label"].sum()),
        "event_count": len(events),
        "graph_candidate_count": len(graph_candidates),
        "review_queue_count": len(review_queue),
        "kep_case_count": len(kep_cases),
        "kep_status_counts": kep_counts,
        "model_metrics": oof.metrics.to_dict("records"),
        "feature_build_audit": feature_result.audit,
        "graph_audit": graph_audit,
        "alert_capacity": capacity,
        "sqlite_table_counts": table_counts,
        "sql_result_row_counts": sql_counts,
        "raw_event_export_written": False,
    }
    _write_json(out / "run_summary.json", summary)
    _write_json(data_manifest_dir / "dataset_manifest.json", {
        "synthetic_only": True,
        "seed": SEED,
        "users": len(users),
        "fraud_labels": int(users["fraud_label"].sum()),
        "events_in_sqlite_only": len(events),
        "raw_event_export_written": False,
    })
    _write_run_report(out / "RUN_REPORT.md", summary, oof.metrics)
    return PipelineResult(output_dir=out, database_path=database_path, summary=summary)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the deterministic synthetic CoinTR Fraud demo")
    parser.add_argument("--output-dir", type=Path, default=None)
    arguments = parser.parse_args()
    result = run_pipeline(arguments.output_dir)
    print(json.dumps(_json_ready(result.summary), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
