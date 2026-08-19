from __future__ import annotations

import numpy as np
import pandas as pd

from cointr_fraud.metrics import lift_at_fraction
from cointr_fraud.models import fit_fold_predict, split_condition_pair


def test_lift_is_tie_aware_and_order_invariant() -> None:
    labels = np.array([1, 0, 0, 0])
    scores = np.ones(4)
    assert lift_at_fraction(labels, scores, 0.25) == 1.0
    assert lift_at_fraction(labels[::-1], scores, 0.25) == 1.0


def test_validation_labels_do_not_change_fold_predictions() -> None:
    train = pd.DataFrame(
        {
            "numeric": np.arange(40, dtype=float),
            "category": ["A", "B"] * 20,
            "fraud_label": [0, 1] * 20,
        }
    )
    validation = pd.DataFrame(
        {"numeric": np.arange(40, 50, dtype=float), "category": ["A", "B"] * 5, "fraud_label": [0, 1] * 5}
    )
    changed = validation.copy()
    changed["fraud_label"] = 1 - changed["fraud_label"]
    first, _, first_manifest = fit_fold_predict(
        train, validation, features=["numeric", "category"], model_name="decision_tree_depth3"
    )
    second, _, second_manifest = fit_fold_predict(
        train, changed, features=["numeric", "category"], model_name="decision_tree_depth3"
    )
    np.testing.assert_allclose(first, second)
    assert first_manifest["validation_labels_read_during_fit"] is False
    assert second_manifest["validation_labels_read_during_fit"] is False


def test_tree_conditions_map_to_business_units_and_categories() -> None:
    assert split_condition_pair("num__amount_diff_ratio", 1.25, {"amount_diff_ratio"}, set()) == (
        "amount_diff_ratio <= 1.25",
        "amount_diff_ratio > 1.25",
    )
    assert split_condition_pair("cat__channel_ANDROID", 0.5, set(), {"channel"}) == (
        "channel != ANDROID",
        "channel == ANDROID",
    )
