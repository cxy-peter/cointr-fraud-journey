from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

import numpy as np
import pandas as pd


MODEL_FEATURES = [
    "registration_to_kyc_minutes",
    "kyc_to_first_deposit_minutes",
    "deposit_count",
    "trade_count",
    "withdrawal_count",
    "deposit_amount",
    "trade_amount",
    "withdrawal_amount",
    "withdraw_deposit_ratio",
    "trade_deposit_ratio",
    "fund_loop_cv",
    "amount_diff_ratio",
    "small_fiat_deposit_count",
    "withdraw_address_unique_count",
    "withdraw_ip_unique_count",
    "deposit_ip_unique_count",
    "withdraw_deposit_ip_ratio",
    "device_unique_count",
    "total_event_count",
    "bank_risk_max",
    "bank_risk_mean",
    "bank_name_match_ratio",
    "asset_pair_unique_count",
    "registration_channel",
    "kyc_level",
]

# Retained for descriptive context only. The source material warns that API and
# night activity do not have a universal risk direction, so neither is a model
# input or a standalone rule candidate.
CONTEXT_ONLY_FEATURES = ["api_event_ratio", "night_event_ratio"]


FEATURE_CONTRACTS = [
    ("registration_to_kyc_minutes", "Minutes from registration to successful KYC", "REGISTER,KYC_SUCCESS", "lifecycle_to_feature_cutoff", "KYC_SUCCESS.available_at", "risk_analytics"),
    ("kyc_to_first_deposit_minutes", "Minutes from successful KYC to first fiat deposit", "KYC_SUCCESS,FIAT_DEPOSIT", "lifecycle_to_feature_cutoff", "FIAT_DEPOSIT.available_at", "risk_analytics"),
    ("deposit_count", "Successful fiat deposit count", "FIAT_DEPOSIT", "registration_to_feature_cutoff", "event.available_at", "feature_platform"),
    ("trade_count", "Successful spot and API trade count across every asset pair", "SPOT_TRADE,API_TRADE", "registration_to_feature_cutoff", "event.available_at", "feature_platform"),
    ("withdrawal_count", "Successful on-chain withdrawal count", "CHAIN_WITHDRAW", "registration_to_feature_cutoff", "event.available_at", "feature_platform"),
    ("deposit_amount", "Successful fiat deposit amount sum in synthetic USDT equivalent", "FIAT_DEPOSIT", "registration_to_feature_cutoff", "event.available_at", "feature_platform"),
    ("trade_amount", "Successful spot/API amount sum across all asset pairs in synthetic USDT equivalent", "SPOT_TRADE,API_TRADE", "registration_to_feature_cutoff", "event.available_at", "feature_platform"),
    ("withdrawal_amount", "Successful on-chain withdrawal amount sum", "CHAIN_WITHDRAW", "registration_to_feature_cutoff", "event.available_at", "feature_platform"),
    ("withdraw_deposit_ratio", "Withdrawal amount divided by deposit amount", "derived", "registration_to_feature_cutoff", "all inputs available", "risk_analytics"),
    ("trade_deposit_ratio", "Trade amount divided by deposit amount", "derived", "registration_to_feature_cutoff", "all inputs available", "risk_analytics"),
    ("fund_loop_cv", "Population standard deviation of deposit/trade/withdraw totals divided by their mean", "derived", "registration_to_feature_cutoff", "all inputs available", "risk_analytics"),
    ("amount_diff_ratio", "Range of deposit/trade/withdraw totals divided by their mean", "derived", "registration_to_feature_cutoff", "all inputs available", "risk_analytics"),
    ("small_fiat_deposit_count", "Successful fiat deposits below 1000 synthetic USDT equivalent", "FIAT_DEPOSIT", "registration_to_feature_cutoff", "event.available_at", "feature_platform"),
    ("withdraw_address_unique_count", "Distinct on-chain withdrawal addresses", "CHAIN_WITHDRAW", "registration_to_feature_cutoff", "event.available_at", "feature_platform"),
    ("withdraw_ip_unique_count", "Distinct IPs used for successful withdrawals", "CHAIN_WITHDRAW", "registration_to_feature_cutoff", "event.available_at", "feature_platform"),
    ("deposit_ip_unique_count", "Distinct IPs used for successful fiat deposits", "FIAT_DEPOSIT", "registration_to_feature_cutoff", "event.available_at", "feature_platform"),
    ("withdraw_deposit_ip_ratio", "Withdrawal-IP diversity divided by deposit-IP diversity", "derived", "registration_to_feature_cutoff", "all inputs available", "risk_analytics"),
    ("device_unique_count", "Distinct observed devices", "all successful events", "registration_to_feature_cutoff", "event.available_at", "feature_platform"),
    ("api_event_ratio", "Successful API-trade events divided by all successful events", "API_TRADE", "registration_to_feature_cutoff", "event.available_at", "feature_platform"),
    ("night_event_ratio", "Successful events between 00:00 and 05:59 divided by all successful events", "all successful events", "registration_to_feature_cutoff", "event.available_at", "feature_platform"),
    ("total_event_count", "All successful events before the PIT cutoff", "all successful events", "registration_to_feature_cutoff", "event.available_at", "feature_platform"),
    ("bank_risk_max", "Maximum synthetic risk score among deposit banks", "FIAT_DEPOSIT.bank_risk_score", "registration_to_feature_cutoff", "event.available_at", "bank_feature_owner"),
    ("bank_risk_mean", "Mean synthetic risk score among deposit banks", "FIAT_DEPOSIT.bank_risk_score", "registration_to_feature_cutoff", "event.available_at", "bank_feature_owner"),
    ("bank_name_match_ratio", "Share of deposits whose canonical bank_user_name equals the synthetic customer name; bankUserName is an accepted input alias", "FIAT_DEPOSIT.bank_user_name", "registration_to_feature_cutoff", "event.available_at", "bank_feature_owner"),
    ("asset_pair_unique_count", "Distinct asset pairs across successful spot/API trades", "SPOT_TRADE,API_TRADE.asset_pair", "registration_to_feature_cutoff", "event.available_at", "feature_platform"),
    ("registration_channel", "Synthetic registration channel", "users.registration_channel", "onboarding", "registration_time", "onboarding_owner"),
    ("kyc_level", "Synthetic KYC level", "users.kyc_level", "onboarding", "KYC_SUCCESS.available_at", "onboarding_owner"),
]


@dataclass(frozen=True)
class FeatureBuildResult:
    features: pd.DataFrame
    audit: dict[str, object]


def feature_contract_frame() -> pd.DataFrame:
    return pd.DataFrame(
        FEATURE_CONTRACTS,
        columns=["feature", "definition", "source", "window", "available_at", "owner"],
    )


def _first_time(frame: pd.DataFrame, event_type: str) -> pd.Series:
    return frame.loc[frame["event_type"] == event_type].groupby("user_id")["event_time"].min()


def _safe_ratio(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    return numerator.astype(float) / denominator.astype(float).clip(lower=1e-9)


def engineer_user_features(users: pd.DataFrame, events: pd.DataFrame) -> FeatureBuildResult:
    """Build point-in-time user features using only terminal SUCCESS events."""

    required = {
        "user_id",
        "event_time",
        "available_at",
        "event_type",
        "status",
        "amount_usdt",
        "device_id",
        "ip_address",
        "withdraw_address",
        "bank_id",
        "bank_risk_score",
        "asset_pair",
    }
    frame = events.copy()
    if "bank_user_name" not in frame and "bankUserName" in frame:
        frame = frame.rename(columns={"bankUserName": "bank_user_name"})
        alias_used = True
    else:
        alias_used = False
    required.add("bank_user_name")
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"event table missing required columns: {missing}")

    frame["event_time"] = pd.to_datetime(frame["event_time"], utc=True)
    frame["available_at"] = pd.to_datetime(frame["available_at"], utc=True)
    user_meta = users[
        [
            "user_id",
            "customer_name",
            "registration_time",
            "registration_channel",
            "kyc_level",
            "fraud_label",
            "label_observed_at",
        ]
    ].copy()
    user_meta["label_observed_at"] = pd.to_datetime(user_meta["label_observed_at"], utc=True)
    user_meta["feature_cutoff"] = user_meta["label_observed_at"] - timedelta(days=7)
    frame = frame.merge(user_meta[["user_id", "feature_cutoff"]], on="user_id", how="left", validate="many_to_one")
    terminal = frame[
        (frame["status"] == "SUCCESS")
        & (frame["available_at"] <= frame["feature_cutoff"])
    ].copy()
    if terminal.empty:
        raise ValueError("no point-in-time eligible events")

    registration = _first_time(terminal, "REGISTER")
    kyc = _first_time(terminal, "KYC_SUCCESS")
    first_deposit = _first_time(terminal, "FIAT_DEPOSIT")
    features = user_meta.set_index("user_id")
    features["registration_to_kyc_minutes"] = (kyc - registration).dt.total_seconds() / 60
    features["kyc_to_first_deposit_minutes"] = (first_deposit - kyc).dt.total_seconds() / 60

    deposits = terminal[terminal["event_type"] == "FIAT_DEPOSIT"].copy()
    trades = terminal[terminal["event_type"].isin(["SPOT_TRADE", "API_TRADE"])].copy()
    withdrawals = terminal[terminal["event_type"] == "CHAIN_WITHDRAW"].copy()
    features["deposit_count"] = deposits.groupby("user_id").size()
    features["trade_count"] = trades.groupby("user_id").size()
    features["withdrawal_count"] = withdrawals.groupby("user_id").size()
    features["deposit_amount"] = deposits.groupby("user_id")["amount_usdt"].sum()
    features["trade_amount"] = trades.groupby("user_id")["amount_usdt"].sum()
    features["withdrawal_amount"] = withdrawals.groupby("user_id")["amount_usdt"].sum()
    for column in ["deposit_count", "trade_count", "withdrawal_count", "deposit_amount", "trade_amount", "withdrawal_amount"]:
        features[column] = features[column].fillna(0)
    features["withdraw_deposit_ratio"] = _safe_ratio(features["withdrawal_amount"], features["deposit_amount"])
    features["trade_deposit_ratio"] = _safe_ratio(features["trade_amount"], features["deposit_amount"])

    flow = features[["deposit_amount", "trade_amount", "withdrawal_amount"]].to_numpy(dtype=float)
    flow_mean = np.maximum(flow.mean(axis=1), 1e-9)
    features["fund_loop_cv"] = flow.std(axis=1, ddof=0) / flow_mean
    features["amount_diff_ratio"] = (flow.max(axis=1) - flow.min(axis=1)) / flow_mean
    features["small_fiat_deposit_count"] = deposits.loc[deposits["amount_usdt"] < 1_000].groupby("user_id").size()
    features["withdraw_address_unique_count"] = withdrawals.groupby("user_id")["withdraw_address"].nunique()
    features["withdraw_ip_unique_count"] = withdrawals.groupby("user_id")["ip_address"].nunique()
    features["deposit_ip_unique_count"] = deposits.groupby("user_id")["ip_address"].nunique()
    features["device_unique_count"] = terminal.groupby("user_id")["device_id"].nunique()
    features["api_event_ratio"] = terminal["event_type"].eq("API_TRADE").groupby(terminal["user_id"]).mean()
    features["night_event_ratio"] = terminal["event_time"].dt.hour.lt(6).groupby(terminal["user_id"]).mean()
    features["total_event_count"] = terminal.groupby("user_id").size()
    features["bank_risk_max"] = deposits.groupby("user_id")["bank_risk_score"].max()
    features["bank_risk_mean"] = deposits.groupby("user_id")["bank_risk_score"].mean()
    deposit_names = deposits.merge(
        user_meta[["user_id", "customer_name"]], on="user_id", how="left", validate="many_to_one"
    )
    deposit_names["name_match"] = deposit_names["bank_user_name"].fillna("").eq(deposit_names["customer_name"])
    features["bank_name_match_ratio"] = deposit_names.groupby("user_id")["name_match"].mean()
    features["asset_pair_unique_count"] = trades.groupby("user_id")["asset_pair"].nunique()

    count_like = [
        "small_fiat_deposit_count",
        "withdraw_address_unique_count",
        "withdraw_ip_unique_count",
        "deposit_ip_unique_count",
        "device_unique_count",
        "total_event_count",
        "asset_pair_unique_count",
    ]
    features[count_like] = features[count_like].fillna(0)
    features["withdraw_deposit_ip_ratio"] = _safe_ratio(
        features["withdraw_ip_unique_count"], features["deposit_ip_unique_count"].clip(lower=1)
    )
    features = features.fillna(
        {
            "api_event_ratio": 0.0,
            "night_event_ratio": 0.0,
            "bank_risk_max": 0.0,
            "bank_risk_mean": 0.0,
            "bank_name_match_ratio": 0.0,
        }
    )
    features = features.reset_index().sort_values("user_id", kind="stable").reset_index(drop=True)
    if features[MODEL_FEATURES].isna().any().any():
        missing_features = features[MODEL_FEATURES].columns[features[MODEL_FEATURES].isna().any()].tolist()
        raise AssertionError(f"engineered features contain nulls: {missing_features}")

    audit = {
        "input_events": int(len(events)),
        "terminal_success_events": int((events["status"] == "SUCCESS").sum()),
        "pit_eligible_events": int(len(terminal)),
        "pit_excluded_events": int(len(events) - len(terminal)),
        "feature_cutoff_rule": "label_observed_at_minus_7_days",
        "label_maturity_days": 52,
        "bank_user_name_canonical": "bank_user_name",
        "bankUserName_alias_accepted": True,
        "bankUserName_alias_used": alias_used,
        "bank_user_name_non_null_coverage": float(deposits["bank_user_name"].fillna("").ne("").mean()),
        "asset_pairs": sorted(trades.loc[trades["asset_pair"] != "", "asset_pair"].unique().tolist()),
        "all_asset_pairs_included": True,
        "point_in_time_safe": bool((terminal["available_at"] <= terminal["feature_cutoff"]).all()),
    }
    return FeatureBuildResult(features=features, audit=audit)
