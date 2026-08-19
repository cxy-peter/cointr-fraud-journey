-- Grain/key: one row per users.user_id.
-- State/time: current immutable risk snapshot plus PIT-built user features.
-- Cardinality: users 1:1 user_features, 1:1 current risk snapshot.
-- PIT/window/sequence: features were frozen at their available_at cutoff; current history row is selected after ordered snapshots.
-- Reconciliation: output must equal users row count and have one row per user_id.
-- Confidentiality: ordinary customer profile deliberately excludes STR case details.
SELECT
    u.user_id,
    u.registration_time,
    u.registration_channel,
    u.kyc_level,
    u.age,
    CASE
        WHEN u.age < 25 THEN '18-24'
        WHEN u.age < 35 THEN '25-34'
        WHEN u.age < 50 THEN '35-49'
        ELSE '50+'
    END AS age_band,
    u.occupation,
    u.country_code,
    u.ka_owner,
    u.bd_owner,
    u.user_restriction,
    u.risk_tag,
    u.fraud_label,
    f.deposit_amount,
    f.trade_amount,
    f.withdrawal_amount,
    f.deposit_amount - f.withdrawal_amount AS net_fund_flow,
    f.withdraw_address_unique_count,
    f.withdraw_ip_unique_count,
    f.fund_loop_cv,
    f.amount_diff_ratio,
    r.risk_level,
    r.risk_source,
    r.operator AS risk_operator,
    r.reason AS risk_reason,
    r.recorded_at AS risk_recorded_at
FROM users AS u
JOIN user_features AS f
  ON f.user_id = u.user_id
JOIN risk_profile_history AS r
  ON r.user_id = u.user_id
 AND r.is_current = 1;
