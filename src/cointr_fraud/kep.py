from __future__ import annotations

from datetime import timedelta
import re
import unicodedata

import numpy as np
import pandas as pd

from .generator import KEP_CASE_COUNT, SEED


KEP_EXPECTED_COUNTS = {
    "MATCH_SORUSTURMA": 12_068,
    "MATCH_SAYI": 939,
    "EXCLUDED_ICRA": 378,
    "NOT_FOUND": 120,
    "BUSINESS_NO_RESPONSE": 63,
    "AMBIGUOUS_MULTIPLE": 135,
}


def normalize_text(value: object) -> str:
    text = str(value or "").translate(
        str.maketrans({"İ": "I", "ı": "I", "Ş": "S", "ş": "S", "Ğ": "G", "ğ": "G", "Ü": "U", "ü": "U", "Ö": "O", "ö": "O", "Ç": "C", "ç": "C"})
    )
    text = "".join(
        char for char in unicodedata.normalize("NFKD", text) if not unicodedata.combining(char)
    ).upper()
    return re.sub(r"\s+", " ", text).strip()


def normalize_identifier(value: object) -> str:
    return re.sub(r"[^A-Z0-9]", "", normalize_text(value))


def _subject_identifiers(subject: object) -> set[str]:
    normalized = normalize_text(subject)
    # Search identifiers only inside the explicit Konu: segment.  Text in sender,
    # attachment, reference or reply-chain fields must never be treated as the
    # business subject key.
    match = re.search(r"(?:^|\|)\s*KONU\s*:\s*([^|]*)(?:\||$)", normalized)
    if match is None:
        return set()
    raw_tokens = re.findall(r"[A-Z0-9]+(?:[-/][A-Z0-9]+)+", match.group(1))
    return {normalize_identifier(token) for token in raw_tokens}


def _strict_outgoing(subject: object) -> bool:
    words = set(re.findall(r"[A-Z0-9]+", normalize_text(subject)))
    return "GIDEN" in words and "ORIJINAL" in words


def generate_kep_stress_data(
    user_ids: list[str],
    *,
    case_count: int = KEP_CASE_COUNT,
    seed: int = SEED + 3,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if case_count != sum(KEP_EXPECTED_COUNTS.values()):
        raise ValueError("the fixed stress contract requires exactly 13,703 cases")
    rng = np.random.default_rng(seed)
    scenarios = [
        status
        for status, count in KEP_EXPECTED_COUNTS.items()
        for _ in range(count)
    ]
    rng.shuffle(scenarios)
    cases: list[dict[str, object]] = []
    emails: list[dict[str, object]] = []
    email_index = 1
    base = pd.Timestamp("2026-05-01", tz="UTC")
    for index, scenario in enumerate(scenarios, 1):
        case_id = f"KEPCASE{index:06d}"
        sorusturma_no = f"SOR-2026-{index:06d}"
        sayi = f"SAYI-2026-{index:06d}"
        case_type = "ICRA" if scenario == "EXCLUDED_ICRA" else "REGULATORY_REVIEW"
        created_at = base + timedelta(minutes=index * 3)
        cases.append(
            {
                "case_id": case_id,
                "user_id": user_ids[(index - 1) % len(user_ids)],
                "sorusturma_no": sorusturma_no,
                "sayi": sayi,
                "case_type": case_type,
                "created_at": created_at,
                "reply_deadline": created_at + timedelta(days=10),
                "synthetic_expected_outcome": scenario,
            }
        )

        def add_email(subject: str, direction: str) -> None:
            nonlocal email_index
            emails.append(
                {
                    "email_id": f"MAIL{email_index:07d}",
                    "sent_at": created_at + timedelta(hours=6 + email_index % 24),
                    "direction": direction,
                    "subject": subject,
                    "synthetic_only": True,
                }
            )
            email_index += 1

        if scenario == "MATCH_SORUSTURMA":
            add_email(f"GIDEN | ORİJİNAL | Konu: {sorusturma_no}", "OUTGOING")
        elif scenario == "MATCH_SAYI":
            add_email(f"GIDEN | ORİJİNAL | Konu: {sayi}", "OUTGOING")
        elif scenario == "AMBIGUOUS_MULTIPLE":
            add_email(f"GIDEN | ORİJİNAL | Konu: {sorusturma_no}", "OUTGOING")
            add_email(f"GIDEN | ORİJİNAL | Konu: {sorusturma_no} | EK", "OUTGOING")
        elif scenario == "BUSINESS_NO_RESPONSE":
            add_email(f"GELEN | ORİJİNAL | Konu: {sorusturma_no}", "INCOMING")
        elif scenario == "NOT_FOUND" and index % 3 == 0:
            add_email(f"GIDEN | TASLAK | Konu: unrelated-{index:06d}", "OUTGOING")
    return pd.DataFrame(cases), pd.DataFrame(emails)


def match_kep_subjects(cases: pd.DataFrame, emails: pd.DataFrame) -> pd.DataFrame:
    """Deterministic two-stage KEP subject match for a synthetic offline dataset.

    The function does not log in, send mail, or touch a production KEP/CMS system.
    A live Playwright wrapper would require manual login and would only provide
    read/search/checkpoint orchestration around this deterministic matcher.
    """

    outgoing_index: dict[str, list[dict[str, object]]] = {}
    incoming_index: dict[str, list[dict[str, object]]] = {}
    for email in emails.to_dict("records"):
        identifiers = _subject_identifiers(email["subject"])
        strict = _strict_outgoing(email["subject"])
        if email["direction"] == "OUTGOING" and strict:
            target = outgoing_index
        elif email["direction"] == "INCOMING":
            target = incoming_index
        else:
            # Draft/non-original outgoing mail is neither a qualifying response
            # nor evidence that the business has not responded.
            continue
        for identifier in identifiers:
            target.setdefault(identifier, []).append(email)

    rows: list[dict[str, object]] = []
    for case in cases.sort_values("case_id", kind="stable").to_dict("records"):
        sor_token = normalize_identifier(case["sorusturma_no"])
        sayi_token = normalize_identifier(case["sayi"])
        case_type = normalize_identifier(case["case_type"])
        matched: list[dict[str, object]] = []
        incoming_evidence: list[dict[str, object]] = []
        query_key = ""
        if "ICRA" in case_type:
            status = "EXCLUDED_ICRA"
        else:
            matched = outgoing_index.get(sor_token, [])
            query_key = "sorusturma_no"
            if len(matched) == 1:
                status = "MATCH_SORUSTURMA"
            elif len(matched) > 1:
                status = "AMBIGUOUS_MULTIPLE"
            else:
                matched = outgoing_index.get(sayi_token, [])
                query_key = "sayi"
                if len(matched) == 1:
                    status = "MATCH_SAYI"
                elif len(matched) > 1:
                    status = "AMBIGUOUS_MULTIPLE"
                elif incoming_index.get(sor_token) or incoming_index.get(sayi_token):
                    incoming_evidence = incoming_index.get(sor_token, []) + incoming_index.get(sayi_token, [])
                    status = "BUSINESS_NO_RESPONSE"
                else:
                    status = "NOT_FOUND"
        rows.append(
            {
                "case_id": case["case_id"],
                "match_status": status,
                "query_key_used": query_key,
                "matched_email_count": len(matched),
                "matched_email_ids": "|".join(str(item["email_id"]) for item in matched),
                "qualifying_outgoing_count": len(matched),
                "incoming_evidence_count": len(incoming_evidence),
                "incoming_evidence_ids": "|".join(str(item["email_id"]) for item in incoming_evidence),
                "review_status": "PENDING" if status in {"AMBIGUOUS_MULTIPLE", "BUSINESS_NO_RESPONSE", "NOT_FOUND"} else "NOT_REQUIRED",
                "manual_login_required_for_live_browser": True,
                "strict_konu_boundary": True,
                "timeout_seconds": 90,
                "resume_key": case["case_id"],
                "automatic_send_allowed": False,
                "synthetic_only": True,
            }
        )
    result = pd.DataFrame(rows)
    counts = result["match_status"].value_counts().to_dict()
    if counts != KEP_EXPECTED_COUNTS:
        raise AssertionError(f"KEP outcome counts drifted: {counts}")
    return result
