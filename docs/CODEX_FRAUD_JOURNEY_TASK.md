# Codex Task — Source-Aligned Fraud Journey v2

## Objective

Continue the public synthetic project by following the source-aligned analysis order rather than expanding a generic AI-agent architecture:

```text
baseline and current-strategy problem
→ black / curated-white / unlabelled population contract
→ pair and behavioral scope
→ bank data-quality audit
→ amount/time, ratio and count feature review
→ single-feature effectiveness
→ audited black-user full journey
→ cleaned behavior sequence
→ on-chain and Risk Graph evidence
→ constrained Decision Tree
→ XGBoost / optional LightGBM benchmark
→ online/offline strategy and governed lifecycle
```

The repository must remain synthetic, reproducible and public-safe. Do not import raw screenshots, internal tables, real user identifiers, credentials, production thresholds or external filing capability.

## Current source-aligned layer

The repository now includes:

- `src/cointr_fraud/fraud_journey/` — cohort contract, source-to-demo coverage audit, source-formula feature derivation, cleaned 60-minute sessionization and model-grid policy;
- `scripts/run_source_aligned_fraud_journey.py` — generates source-aligned analysis artefacts from the existing synthetic outputs;
- `docs/COINTR_FRAUD_JOURNEY_ANALYSIS_CN.md` — public, desensitized methodology and interview report;
- `configs/fraud_journey_analysis.yaml` — explicit population, feature, model and governance contract;
- `tests/test_source_aligned_fraud_journey.py` — focused controls.

## P0 — data and label contract

1. Add explicit `label_source`, `label_observed_at`, investigation status and `cohort_type`.
2. Preserve three populations: confirmed black, curated white and unlabelled. Never convert the entire unlabelled population to clean negatives.
3. Add `account_role` for internal, market-maker, test, institution and retail accounts; exclude or separately model non-retail roles.
4. Add pair-level user fields for `USDT_TRY`, `TRX_TRY`, `BTC_TRY`, multi-pair activity and small-altcoin trades below the defined amount threshold.
5. Add on-chain destination type (`EXCHANGE`, `PRIVATE`, `UNKNOWN`) as an auditable hypothesis field, not a predetermined risk direction.
6. Add `event_origin`, `parent_event_id` and business transaction key. Reconcile state transitions before any session-density feature.

## P0 — model experiment contract

1. Keep the current 1:4 five-fold OOF run for backward-compatible demo reproduction, but do not call 1:4 a source rule or global optimum.
2. Add Development-only comparison of natural distribution, 1:3, 1:4 and 1:5 training samples.
3. Compare depths 3–6 and probability thresholds 0.5–0.9 under a declared review-capacity constraint.
4. Add chronological Train/Development/OOT partitions with natural class distribution in OOT.
5. Calibrate under-sampled model scores before describing them as probabilities.
6. Report precision, recall, F1, PR-AUC/AP, KS, Lift at operating depth, alert rate, existing-strategy overlap and incremental recall.

## P1 — analysis and error review

- Recompute user counters from event-level data and reconcile them with snapshot fields.
- Add bank-field fixtures covering masked card number, bank code and canonical/legacy user-name aliases.
- Add hard negatives: legitimate API traders, market makers, treasury users, public-IP users and exchange collection addresses.
- Produce missed-black, high-score-unlabelled and high-confidence-false-positive review artefacts.
- Keep API/night activity context-only unless repeated cross-period evidence establishes a stable direction.
- Add LightGBM only as an optional benchmark; do not describe it as part of the historical source report.

## Acceptance criteria

- No target label or future disposition can reach model input through feature generation.
- System-derived child events cannot create artificial high-density sessions.
- Black, curated white and unlabelled populations remain distinct in every output.
- Pair concentration remains a segment signal, not a universal Fraud definition.
- Existing and new strategies are compared using overlap, swap-in, swap-out and incremental TP/recall.
- AI may propose or explain; deterministic code calculates metrics and state; humans approve high-impact actions and regulatory outcomes.
- All tests and the repository CI pass.
