from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score, roc_curve


def ks_statistic(y_true: np.ndarray, scores: np.ndarray) -> float:
    if len(np.unique(y_true)) < 2:
        raise ValueError("KS requires both positive and negative labels")
    fpr, tpr, _ = roc_curve(y_true, scores)
    return float(np.max(np.abs(tpr - fpr)))


def lift_at_fraction(y_true: np.ndarray, scores: np.ndarray, fraction: float) -> float:
    if not 0 < fraction <= 1:
        raise ValueError("fraction must be in (0, 1]")
    frame = pd.DataFrame({"label": y_true, "score": scores})
    prevalence = float(frame["label"].mean())
    if prevalence <= 0:
        return 0.0
    target = float(len(frame) * fraction)
    groups = (
        frame.groupby("score", dropna=False, sort=False)["label"]
        .agg(["size", "sum"])
        .reset_index()
        .sort_values("score", ascending=False, kind="stable", na_position="last")
    )
    selected = 0.0
    captured = 0.0
    for group in groups.itertuples(index=False):
        if selected >= target:
            break
        take = min(float(group.size), target - selected)
        captured += float(group.sum) * take / float(group.size)
        selected += take
    return float((captured / target) / prevalence)


def evaluate_scores(model_name: str, y_true: np.ndarray, scores: np.ndarray) -> dict[str, object]:
    if len(y_true) != len(scores):
        raise ValueError("label and score lengths differ")
    if len(np.unique(y_true)) < 2:
        raise ValueError("evaluation requires both positive and negative labels")
    return {
        "model_name": model_name,
        "sample_size": int(len(y_true)),
        "positive_count": int(np.sum(y_true)),
        "roc_auc": float(roc_auc_score(y_true, scores)),
        "ks": ks_statistic(y_true, scores),
        "average_precision": float(average_precision_score(y_true, scores)),
        "lift_top_10": lift_at_fraction(y_true, scores, 0.10),
        "lift_top_20": lift_at_fraction(y_true, scores, 0.20),
    }


def single_feature_metrics(
    frame: pd.DataFrame,
    features: list[str],
    target: str = "fraud_label",
) -> pd.DataFrame:
    """Return descriptive one-variable metrics with explicit risk direction.

    These full-sample diagnostics are not used to select OOF folds or tune model
    hyperparameters. Direction is learned only for presentation so low-valued
    risk signals such as a tight fund loop receive a meaningful Lift@TopK.
    """

    y = frame[target].astype(int).to_numpy()
    rows: list[dict[str, object]] = []
    for feature in features:
        values = pd.to_numeric(frame[feature], errors="coerce")
        if values.notna().sum() < 30 or values.nunique(dropna=True) < 2:
            continue
        filled = values.fillna(values.median()).to_numpy(dtype=float)
        raw_auc = float(roc_auc_score(y, filled))
        if raw_auc >= 0.5:
            oriented = filled
            direction = "higher_is_riskier"
            auc = raw_auc
        else:
            oriented = -filled
            direction = "lower_is_riskier"
            auc = 1.0 - raw_auc
        rows.append(
            {
                "feature": feature,
                "direction": direction,
                "auc_1d": auc,
                "ks_1d": ks_statistic(y, oriented),
                "lift_top_10": lift_at_fraction(y, oriented, 0.10),
                "lift_top_20": lift_at_fraction(y, oriented, 0.20),
                "missing_rate": float(values.isna().mean()),
                "unique_count": int(values.nunique(dropna=True)),
                "selection_usage": "descriptive_only_not_used_for_oof_tuning",
            }
        )
    return pd.DataFrame(rows).sort_values(
        ["auc_1d", "ks_1d", "feature"],
        ascending=[False, False, True],
        kind="stable",
    ).reset_index(drop=True)
