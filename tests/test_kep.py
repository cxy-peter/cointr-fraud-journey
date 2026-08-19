from __future__ import annotations

import pandas as pd

from cointr_fraud.kep import KEP_EXPECTED_COUNTS, _subject_identifiers, normalize_identifier


def test_strict_konu_boundary() -> None:
    wanted = normalize_identifier("SOR-2026-000001")
    decoy = normalize_identifier("SOR-2026-999999")
    identifiers = _subject_identifiers(
        "GIDEN | Ref: SOR-2026-999999 | Konu: SOR-2026-000001 | Ek: SAYI-2026-123456"
    )
    assert identifiers == {wanted}
    assert decoy not in identifiers
    assert _subject_identifiers("GIDEN | Ref: SOR-2026-000001") == set()


def test_exact_synthetic_kep_outcomes(pipeline_result) -> None:
    results = pd.read_csv(pipeline_result.output_dir / "kep_match_results.csv")
    assert len(results) == 13_703
    assert results["match_status"].value_counts().to_dict() == KEP_EXPECTED_COUNTS
    assert results["manual_login_required_for_live_browser"].all()
    assert not results["automatic_send_allowed"].any()
    assert set(results["timeout_seconds"]) == {90}
    no_response = results[results["match_status"] == "BUSINESS_NO_RESPONSE"]
    assert no_response["qualifying_outgoing_count"].eq(0).all()
    assert no_response["incoming_evidence_count"].ge(1).all()
    assert no_response["incoming_evidence_ids"].fillna("").ne("").all()
