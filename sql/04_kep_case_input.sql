-- Grain/key: one row per synthetic KEP case_id.
-- State/time: created_at and reply_deadline are retained; no mailbox status is inferred.
-- Join cardinality: no join; case_id remains unique.
-- PIT/window/sequence: deterministic input snapshot only; matching later searches sorusturma_no before sayi.
-- Reconciliation: output count equals kep_cases and normalized keys remain non-empty.
-- This is an offline deterministic search input, not a live KEP action feed.
SELECT
    case_id,
    user_id,
    UPPER(REPLACE(REPLACE(sorusturma_no, '-', ''), '/', '')) AS normalized_sorusturma_no,
    UPPER(REPLACE(REPLACE(sayi, '-', ''), '/', '')) AS normalized_sayi,
    UPPER(TRIM(case_type)) AS normalized_case_type,
    created_at,
    reply_deadline
FROM kep_cases;
