-- Grain/key: one row per synthetic internal str_case_id.
-- State/time: candidate_created_at is after its model-as-of time; status axes are current synthetic states.
-- Join cardinality: no joins in this isolated mart; str_case_id remains unique.
-- PIT/window/sequence: no future label is used to select candidates; review workflow sequencing is not inferred here.
-- Reconciliation: output count equals the internal str_cases source count.
-- Four independent status axes prevent operational-state conflation.
-- This mart is access-separated from the ordinary customer profile.
SELECT
    s.str_case_id,
    s.user_id,
    s.review_status,
    s.review_decision,
    s.report_status,
    s.overdue_status,
    s.candidate_created_at,
    s.internal_candidate_only,
    s.automatic_external_filing_allowed,
    s.synthetic_only
FROM str_cases AS s;
