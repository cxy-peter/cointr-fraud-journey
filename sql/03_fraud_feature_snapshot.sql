-- Grain/key: one row per user_id.
-- State/time: SUCCESS is terminal state and event.available_at is the event-time availability field.
-- Join cardinality: events many:1 users before one-row-per-user aggregation.
-- PIT: only terminal SUCCESS rows with available_at <= label_observed_at - 7 days.
-- Window/sequence: registration-to-feature-cutoff window; sequence follows event_time only after PIT filtering.
-- Reconciliation: output sums/counts can be reconciled to user_features.
WITH eligible AS (
    SELECT e.*
    FROM events AS e
    JOIN users AS u ON u.user_id = e.user_id
    WHERE e.status = 'SUCCESS'
      AND datetime(e.available_at) <= datetime(u.label_observed_at, '-7 days')
)
SELECT
    user_id,
    SUM(CASE WHEN event_type = 'FIAT_DEPOSIT' THEN amount_usdt ELSE 0 END) AS deposit_amount,
    SUM(CASE WHEN event_type IN ('SPOT_TRADE', 'API_TRADE') THEN amount_usdt ELSE 0 END) AS trade_amount,
    SUM(CASE WHEN event_type = 'CHAIN_WITHDRAW' THEN amount_usdt ELSE 0 END) AS withdrawal_amount,
    SUM(CASE WHEN event_type = 'FIAT_DEPOSIT' THEN 1 ELSE 0 END) AS deposit_count,
    SUM(CASE WHEN event_type IN ('SPOT_TRADE', 'API_TRADE') THEN 1 ELSE 0 END) AS trade_count,
    SUM(CASE WHEN event_type = 'CHAIN_WITHDRAW' THEN 1 ELSE 0 END) AS withdrawal_count,
    COUNT(DISTINCT CASE WHEN event_type = 'CHAIN_WITHDRAW' THEN withdraw_address END) AS withdraw_address_unique_count,
    COUNT(DISTINCT CASE WHEN event_type = 'CHAIN_WITHDRAW' THEN ip_address END) AS withdraw_ip_unique_count,
    COUNT(DISTINCT CASE WHEN event_type = 'FIAT_DEPOSIT' THEN ip_address END) AS deposit_ip_unique_count,
    COUNT(DISTINCT CASE WHEN event_type IN ('SPOT_TRADE', 'API_TRADE') THEN asset_pair END) AS asset_pair_unique_count
FROM eligible
GROUP BY user_id;
