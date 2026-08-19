from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.model_selection import StratifiedKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder
from sklearn.tree import DecisionTreeClassifier, _tree
from xgboost import XGBClassifier

from .generator import SEED
from .metrics import evaluate_scores


@dataclass(frozen=True)
class OOFRun:
    scores: pd.DataFrame
    metrics: pd.DataFrame
    manifests: list[dict[str, object]]
    final_tree_pipeline: Pipeline
    tree_rules: list[dict[str, object]]


def make_fold_assignments(y: pd.Series, n_splits: int = 5, seed: int = SEED) -> np.ndarray:
    labels = y.astype(int).to_numpy()
    if int(labels.sum()) < n_splits:
        raise ValueError("each stratified fold needs at least one positive label")
    assignments = np.full(len(labels), -1, dtype=int)
    splitter = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=seed)
    placeholder = np.zeros((len(labels), 1))
    for fold, (_, validation_index) in enumerate(splitter.split(placeholder, labels)):
        assignments[validation_index] = fold
    if (assignments < 0).any():
        raise AssertionError("fold assignment is incomplete")
    return assignments


def _preprocessor(frame: pd.DataFrame, features: list[str]) -> tuple[ColumnTransformer, list[str], list[str]]:
    numeric = [
        feature
        for feature in features
        if pd.api.types.is_numeric_dtype(frame[feature]) or pd.api.types.is_bool_dtype(frame[feature])
    ]
    categorical = [feature for feature in features if feature not in numeric]
    transformer = ColumnTransformer(
        [
            ("num", Pipeline([("imputer", SimpleImputer(strategy="median"))]), numeric),
            (
                "cat",
                Pipeline(
                    [
                        ("imputer", SimpleImputer(strategy="most_frequent")),
                        ("onehot", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
                    ]
                ),
                categorical,
            ),
        ],
        remainder="drop",
        verbose_feature_names_out=True,
    )
    return transformer, numeric, categorical


def _estimator(model_name: str, seed: int) -> Any:
    if model_name == "decision_tree_depth3":
        return DecisionTreeClassifier(
            max_depth=3,
            min_samples_leaf=8,
            class_weight="balanced",
            random_state=seed,
        )
    if model_name == "xgboost_oof":
        return XGBClassifier(
            n_estimators=160,
            max_depth=3,
            learning_rate=0.045,
            subsample=0.85,
            colsample_bytree=0.85,
            min_child_weight=2,
            reg_lambda=2.0,
            reg_alpha=0.15,
            eval_metric="logloss",
            random_state=seed,
            n_jobs=2,
            verbosity=0,
        )
    raise ValueError(f"unknown model: {model_name}")


def fit_fold_predict(
    train: pd.DataFrame,
    validation: pd.DataFrame,
    *,
    features: list[str],
    model_name: str,
    target: str = "fraud_label",
    seed: int = SEED,
) -> tuple[np.ndarray, Pipeline, dict[str, object]]:
    """Fit on one fold and score validation without reading validation labels."""

    fit_frame = train.copy()
    manifest: dict[str, object] = {
        "model_name": model_name,
        "partition": "fold_train_only",
        "input_train_rows": int(len(train)),
        "fit_rows": int(len(train)),
        "negative_undersampling": False,
        "validation_resampled": False,
        "validation_labels_read_during_fit": False,
    }
    if model_name == "xgboost_oof":
        positive = train[train[target].astype(int) == 1]
        negative = train[train[target].astype(int) == 0]
        if positive.empty:
            raise ValueError("XGBoost fold has no positive training labels")
        maximum_negative = min(len(negative), len(positive) * 4)
        if len(negative) > maximum_negative:
            sampled_negative = negative.sample(
                n=maximum_negative,
                replace=False,
                random_state=seed,
            )
            fit_frame = pd.concat([positive, sampled_negative], axis=0).sort_index(kind="stable")
            manifest.update(
                {
                    "fit_rows": int(len(fit_frame)),
                    "positive_rows": int(len(positive)),
                    "negative_rows": int(len(sampled_negative)),
                    "negative_to_positive_ratio": float(len(sampled_negative) / len(positive)),
                    "negative_undersampling": True,
                }
            )
    transformer, _, _ = _preprocessor(fit_frame, features)
    pipeline = Pipeline(
        [("preprocess", transformer), ("model", _estimator(model_name, seed))]
    )
    pipeline.fit(fit_frame[features], fit_frame[target].astype(int))
    scores = pipeline.predict_proba(validation[features])[:, 1]
    return scores, pipeline, manifest


def split_condition_pair(
    transformed_name: str,
    threshold: float,
    numeric_features: set[str],
    categorical_features: set[str],
) -> tuple[str, str] | None:
    """Map transformed tree splits back to original business conditions."""

    prefix, clean = (
        transformed_name.split("__", 1)
        if "__" in transformed_name
        else ("num", transformed_name)
    )
    if prefix == "num" and clean in numeric_features:
        return f"{clean} <= {threshold:.6g}", f"{clean} > {threshold:.6g}"
    if prefix == "cat":
        original = next(
            (
                name
                for name in sorted(categorical_features, key=len, reverse=True)
                if clean.startswith(name + "_")
            ),
            None,
        )
        if original is None:
            return None
        category = clean[len(original) + 1 :]
        return f"{original} != {category}", f"{original} == {category}"
    if clean in numeric_features:
        return f"{clean} <= {threshold:.6g}", f"{clean} > {threshold:.6g}"
    return None


def extract_tree_rules(
    pipeline: Pipeline,
    frame: pd.DataFrame,
    features: list[str],
    *,
    target: str = "fraud_label",
    max_rules: int = 8,
) -> list[dict[str, object]]:
    transformer: ColumnTransformer = pipeline.named_steps["preprocess"]
    model: DecisionTreeClassifier = pipeline.named_steps["model"]
    transformed_names = transformer.get_feature_names_out().tolist()
    numeric = {
        feature
        for feature in features
        if pd.api.types.is_numeric_dtype(frame[feature]) or pd.api.types.is_bool_dtype(frame[feature])
    }
    categorical = set(features) - numeric
    transformed = transformer.transform(frame[features])
    leaf_ids = model.apply(transformed)
    tree = model.tree_
    paths: dict[int, list[str]] = {}

    def walk(node: int, conditions: list[str]) -> None:
        if tree.feature[node] == _tree.TREE_UNDEFINED:
            paths[node] = conditions
            return
        pair = split_condition_pair(
            transformed_names[tree.feature[node]],
            float(tree.threshold[node]),
            numeric,
            categorical,
        )
        if pair is None:
            return
        left, right = pair
        walk(int(tree.children_left[node]), conditions + [left])
        walk(int(tree.children_right[node]), conditions + [right])

    walk(0, [])
    rows: list[dict[str, object]] = []
    y = frame[target].astype(int).to_numpy()
    for leaf_id, conditions in paths.items():
        mask = leaf_ids == leaf_id
        samples = int(mask.sum())
        positives = int(y[mask].sum())
        positive_rate = float(positives / max(samples, 1))
        if samples >= 8 and positives >= 1 and conditions:
            rows.append(
                {
                    "rule_id": f"TREE_RULE_{leaf_id:03d}",
                    "conditions": " AND ".join(conditions),
                    "sample_count": samples,
                    "positive_count": positives,
                    "full_fit_positive_rate": positive_rate,
                    "validation_status": "exploratory_full_fit_not_oof_validated",
                    "action": "MANUAL_REVIEW",
                    "automatic_enforcement": False,
                }
            )
    rows.sort(
        key=lambda row: (
            float(row["full_fit_positive_rate"]),
            int(row["positive_count"]),
            int(row["sample_count"]),
            str(row["rule_id"]),
        ),
        reverse=True,
    )
    return rows[:max_rules]


def run_oof_models(
    frame: pd.DataFrame,
    features: list[str],
    *,
    target: str = "fraud_label",
    seed: int = SEED,
) -> OOFRun:
    ordered = frame.sort_values("user_id", kind="stable").reset_index(drop=True).copy()
    assignments = make_fold_assignments(ordered[target], n_splits=5, seed=seed)
    score_frame = ordered[["user_id", target]].copy()
    score_frame["fold"] = assignments
    metric_rows: list[dict[str, object]] = []
    manifests: list[dict[str, object]] = []
    for model_name in ["decision_tree_depth3", "xgboost_oof"]:
        scores = np.full(len(ordered), np.nan, dtype=float)
        for fold in range(5):
            train = ordered[assignments != fold]
            validation = ordered[assignments == fold]
            fold_scores, _, manifest = fit_fold_predict(
                train,
                validation,
                features=features,
                model_name=model_name,
                target=target,
                seed=seed + fold,
            )
            scores[assignments == fold] = fold_scores
            manifest.update(
                {
                    "fold": fold,
                    "validation_rows": int((assignments == fold).sum()),
                    "validation_positive_rows": int(validation[target].sum()),
                }
            )
            manifests.append(manifest)
        if np.isnan(scores).any():
            raise AssertionError(f"{model_name} OOF predictions are incomplete")
        score_frame[f"{model_name}_score"] = scores
        metric_rows.append(
            evaluate_scores(model_name, ordered[target].astype(int).to_numpy(), scores)
        )

    transformer, _, _ = _preprocessor(ordered, features)
    final_tree = Pipeline(
        [
            ("preprocess", transformer),
            ("model", _estimator("decision_tree_depth3", seed)),
        ]
    )
    final_tree.fit(ordered[features], ordered[target].astype(int))
    tree_rules = extract_tree_rules(final_tree, ordered, features, target=target)
    return OOFRun(
        scores=score_frame,
        metrics=pd.DataFrame(metric_rows),
        manifests=manifests,
        final_tree_pipeline=final_tree,
        tree_rules=tree_rules,
    )
