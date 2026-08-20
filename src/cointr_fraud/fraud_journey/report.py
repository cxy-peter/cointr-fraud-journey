from __future__ import annotations

from pathlib import Path

import pandas as pd

from .analysis import audit_summary, feature_coverage_frame, source_contract_gaps
from .catalog import COHORT_DEFINITIONS, MODEL_GRID, SOURCE_ANALYSIS_STEPS


def _table(frame: pd.DataFrame) -> str:
    def esc(value: object) -> str:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return ""
        return str(value).replace("|", "\\|").replace("\n", " ")

    columns = [str(column) for column in frame.columns]
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    lines += [
        "| " + " | ".join(esc(value) for value in row) + " |"
        for row in frame.itertuples(index=False, name=None)
    ]
    return "\n".join(lines)


def render_focused_report(users: pd.DataFrame | None = None) -> str:
    coverage = feature_coverage_frame(users.columns if users is not None else [])
    summary = audit_summary(coverage)
    lines = [
        "# CoinTR Fraud Journey — Source-Aligned Analysis Plan",
        "",
        "> Public synthetic analysis layer; no raw internal records or production claims.",
        "",
        "## 1. Core workflow",
        "",
    ]
    for step in SOURCE_ANALYSIS_STEPS:
        lines += [
            f"### {step.order}. {step.stage}",
            f"- Question: {step.question}",
            f"- Source method: {step.source_method}",
            f"- Output: {step.output}",
            f"- Gate: {step.gate}",
            "",
        ]
    lines += ["## 2. Cohort contract", ""]
    for item in COHORT_DEFINITIONS:
        lines += [
            f"### {item['cohort']}",
            f"- Definition: {item['definition']}",
            f"- Warning: {item['warning']}",
            "",
        ]
    lines += [
        "## 3. Model policy",
        "",
        f"- Negative:positive candidates: {list(MODEL_GRID['negative_to_positive_ratio'])}",
        f"- Depth candidates: {list(MODEL_GRID['max_depth'])}",
        f"- Thresholds: {list(MODEL_GRID['probability_threshold'])}",
        "- 1:4 remains the existing demo default, but is only one experiment candidate.",
        "- Select on Development; evaluate chronological natural-distribution OOT.",
        "- Calibrate under-sampled scores before probability interpretation.",
        "",
        "## 4. Feature coverage",
        "",
        f"- Exact: {summary['EXACT']}; Derivable: {summary['DERIVABLE']}; Approximate: {summary['APPROXIMATE']}; Missing: {summary['MISSING']}; Lineage risk: {summary['LINEAGE_RISK']}",
        "",
        _table(coverage[["source_feature", "github_feature", "status", "note"]]),
    ]
    if users is not None:
        gaps = pd.DataFrame(
            [
                {"contract": name, "present": present}
                for name, present in source_contract_gaps(users).items()
            ]
        )
        lines += ["", "## 5. High-impact contract audit", "", _table(gaps)]
    lines += [
        "",
        "## 6. Truthfulness boundary",
        "",
        "- Curated white users are not equivalent to all fraud_label=0 rows.",
        "- Pair concentration is a segment signal, not a universal Fraud definition.",
        "- A raw 60-minute session-density feature is invalid until system/child events are removed.",
        "- Historical cutoffs and metrics are analysis artefacts, not production targets.",
        "- This repository uses deterministic synthetic data only.",
    ]
    return "\n".join(lines)


def write_focused_report(
    path: str | Path, users: pd.DataFrame | None = None
) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_focused_report(users), encoding="utf-8")
    return target
