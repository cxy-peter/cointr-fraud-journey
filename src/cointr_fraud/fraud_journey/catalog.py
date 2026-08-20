from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from itertools import product
from typing import Iterable


class CoverageStatus(str, Enum):
    EXACT = "EXACT"
    APPROXIMATE = "APPROXIMATE"
    DERIVABLE = "DERIVABLE"
    MISSING = "MISSING"
    LINEAGE_RISK = "LINEAGE_RISK"


@dataclass(frozen=True)
class FeatureMapping:
    source_feature: str
    github_feature: str | None
    status: CoverageStatus
    source_role: str
    note: str


@dataclass(frozen=True)
class AnalysisStep:
    order: int
    stage: str
    question: str
    source_method: str
    output: str
    gate: str


COHORT_DEFINITIONS: tuple[dict[str, str], ...] = (
    {
        "cohort": "excluded_accounts",
        "definition": "Remove internal, market-maker, test, institutional and other non-retail accounts before comparison.",
        "warning": "The current users table does not yet expose account_role.",
    },
    {
        "cohort": "silent_users",
        "definition": "No deposit, trade or withdrawal behavior; exclude from behavior-feature effectiveness analysis.",
        "warning": "Silent means no exposure for this journey, not necessarily low risk.",
    },
    {
        "cohort": "curated_white",
        "definition": "A separately curated, relatively trustworthy normal sample.",
        "warning": "fraud_label=0 is not equivalent to curated white.",
    },
    {
        "cohort": "curated_black",
        "definition": "Confirmed Fraud plus previously removed Fraud users, retaining source and observed-at.",
        "warning": "The demo currently has one synthetic label without source provenance.",
    },
    {
        "cohort": "unlabelled_population",
        "definition": "Eligible users absent from both curated black and white lists.",
        "warning": "Use for discovery, not as clean negatives by default.",
    },
    {
        "cohort": "target_try_trading_segment",
        "definition": "TRY-USDT/TRX/BTC users, with multi-pair activity retained separately.",
        "warning": "Pair concentration is a segment signal, not a universal Fraud rule.",
    },
)


SOURCE_ANALYSIS_STEPS: tuple[AnalysisStep, ...] = (
    AnalysisStep(1, "objective_and_baseline", "What gap does the current strategy leave?", "Start from confusion matrix, missed black users, user impact and review capacity.", "Baseline and evaluation contract.", "Define event, population, action and metric before modelling."),
    AnalysisStep(2, "label_and_population_contract", "Who is black, white, unlabelled, silent or excluded?", "Preserve label source/maturity and remove non-retail roles.", "Versioned cohort contract.", "Do not treat every label=0 row as clean normal."),
    AnalysisStep(3, "trading_pair_and_behavioral_scope", "Which trading paths are representative?", "Measure pair coverage/count/amount; retain TRY paths, multi-pair and small-altcoin segments.", "Pair-level cohort table.", "Pairs segment users; they do not define Fraud alone."),
    AnalysisStep(4, "bank_data_quality_and_features", "Can bank signals be calculated reliably?", "Audit masked card, bank code, user-name aliases and missingness before feature calculation.", "Bank reconciliation report.", "Resolve aliases and missingness first."),
    AnalysisStep(5, "existing_feature_family_review", "Which amount, time, ratio and count features separate cohorts?", "Compare robust per-user distributions for the funding-trade-withdrawal journey.", "Candidate feature list.", "Do not let a few whales drive cohort means."),
    AnalysisStep(6, "single_feature_effectiveness", "Is each candidate stable and interpretable?", "Check coverage, missingness, bins, AUC, KS, IV, Lift, PSI and direction consistency.", "Feature evidence cards.", "Historical cutoffs remain hypotheses."),
    AnalysisStep(7, "black_user_full_journey", "What mechanism appears from registration through withdrawal?", "Audit a small confirmed set across KYC, funding, trading, withdrawal, device/IP/address and active time.", "Case timelines and hypotheses.", "Validate small-case findings on broader cohorts."),
    AnalysisStep(8, "behavior_sequence_analysis", "Are there repeatable event-order or timing patterns?", "Use up to 200 recent events in four months for users with at least 10 events; keep user business actions only.", "Sequence and cleaned-session features.", "Remove automatic child/system events before the 60-minute gap."),
    AnalysisStep(9, "onchain_and_risk_graph", "Do users share risky destinations or strong relations?", "Classify destination type/labels and inspect controlled graph hops with super-node suppression.", "Explainable graph evidence.", "Destination preference is a hypothesis until validated."),
    AnalysisStep(10, "tree_feature_interactions", "Which interpretable combinations create high-risk branches?", "Use a constrained tree; inspect support, risk order, false positives and stability.", "Candidate rule paths.", "A deep tree is not an online strategy."),
    AnalysisStep(11, "boosting_model_comparison", "Can nonlinear ranking improve operating precision/recall?", "Compare natural, 1:3, 1:4, 1:5 samples, depths 3-6 and thresholds 0.5-0.9; select on Development and report natural OOT.", "Boosting benchmark and error review.", "1:4 is a candidate; calibrate under-sampled scores."),
    AnalysisStep(12, "strategy_translation_and_lifecycle", "How does evidence become an online/offline control?", "Specify Event + Population + Window + Threshold + Exclusion + Action; run overlap, simulation, second review and monitoring.", "Governed strategy ticket.", "High-impact actions remain human-controlled."),
)


BUSINESS_EVENT_CODES: tuple[str, ...] = (
    "ChainOnRecharge", "FiatDeposit", "FiatFithdrawal", "UserKycStart",
    "KYCVerify", "UserKyc", "CashBalanceBuyCoin", "CashBalanceSellCoin",
    "WalletWithdraw", "ChainOnWithdraw", "UserRegister", "UserLogin",
    "CointrSpot", "InternalTransfer", "CoinTrConvert", "CoinTrAPISet",
    "REGISTER", "DEVICE_BIND", "KYC_START", "KYC_SUCCESS", "FIAT_DEPOSIT",
    "SPOT_TRADE", "API_TRADE", "CHAIN_WITHDRAW", "LOGIN", "DEVICE_LOGIN",
    "PASSWORD_CHANGE", "INTERNAL_TRANSFER",
)

SYSTEM_EVENT_CODES: tuple[str, ...] = (
    "FiatDepositPostProcess", "FiatWithdrawalPostProcess", "BroadcastMessage",
    "BatchCampaignRequest", "ReconciliationCheck", "AdminWithdrawReport",
    "BankStatementBackend", "AirdropRewardDistribution", "CustodyDeposit",
    "CustodyWithdraw", "InternalFeeAccountTransfer", "CashBalanceBuyCoinCheck",
    "CashBalanceSellCoinCheck", "FundingGoogleCodeValidation",
)

MODEL_GRID: dict[str, tuple[float | int | None, ...]] = {
    "negative_to_positive_ratio": (None, 3, 4, 5),
    "max_depth": (3, 4, 5, 6),
    "probability_threshold": (0.5, 0.6, 0.7, 0.8, 0.9),
}


def model_grid_records() -> list[dict[str, float | int | None]]:
    return [
        {"negative_to_positive_ratio": ratio, "max_depth": depth, "probability_threshold": threshold}
        for ratio, depth, threshold in product(
            MODEL_GRID["negative_to_positive_ratio"],
            MODEL_GRID["max_depth"],
            MODEL_GRID["probability_threshold"],
        )
    ]


FEATURE_MAPPINGS: tuple[FeatureMapping, ...] = (
    FeatureMapping("registration_device_side", "registration_channel", CoverageStatus.EXACT, "registration", "Device-side channel exists."),
    FeatureMapping("registration_source", "registration_channel", CoverageStatus.APPROXIMATE, "registration", "Organic/ads source is not separate."),
    FeatureMapping("no_inviter_flag", None, CoverageStatus.MISSING, "registration", "No inviter field."),
    FeatureMapping("kyc_l1_only_flag", "kyc_level", CoverageStatus.EXACT, "kyc", "L1/L2 exists."),
    FeatureMapping("kyc_duration_hours", "registration_to_kyc_minutes", CoverageStatus.APPROXIMATE, "kyc", "Registration-to-success, not KYC-start-to-success."),
    FeatureMapping("first_fiat_in_to_kyc_hours", "kyc_to_first_deposit_minutes", CoverageStatus.DERIVABLE, "time", "Convert minutes to hours."),
    FeatureMapping("first_chain_out_5min_cnt", None, CoverageStatus.MISSING, "time", "Exact counter is absent."),
    FeatureMapping("fiat_in_amt", "deposit_amount", CoverageStatus.APPROXIMATE, "fund_flow", "Lifecycle synthetic aggregate."),
    FeatureMapping("fiat_out_amt", None, CoverageStatus.MISSING, "fund_flow", "No fiat-withdrawal event family."),
    FeatureMapping("chain_in_amt", None, CoverageStatus.MISSING, "fund_flow", "No on-chain deposit family."),
    FeatureMapping("chain_out_amt", "withdrawal_amount", CoverageStatus.APPROXIMATE, "fund_flow", "Lifecycle synthetic aggregate."),
    FeatureMapping("spot_trade_amt", "trade_amount", CoverageStatus.APPROXIMATE, "trading", "Spot/API combined; no side split."),
    FeatureMapping("spot_trade_count", "trade_count", CoverageStatus.APPROXIMATE, "trading", "Spot/API combined."),
    FeatureMapping("trade_pair_count", "asset_pair_unique_count", CoverageStatus.EXACT, "trading", "Distinct pair count exists."),
    FeatureMapping("USDTTRY_TRXTRY_BTCTRY_flags", None, CoverageStatus.MISSING, "trading", "Pair flags are not persisted in snapshot."),
    FeatureMapping("small_altcoin_under_1000u", None, CoverageStatus.MISSING, "trading", "Requires pair, side and order amount."),
    FeatureMapping("fund_flow_cv", "fund_loop_cv", CoverageStatus.EXACT, "fund_flow", "Existing consistency ratio."),
    FeatureMapping("fund_flow_range_ratio", "amount_diff_ratio", CoverageStatus.EXACT, "fund_flow", "Existing range/mean ratio."),
    FeatureMapping("withdraw_deposit_ratio", "withdraw_deposit_ratio", CoverageStatus.EXACT, "fund_flow", "Exists."),
    FeatureMapping("trade_deposit_ratio", "trade_deposit_ratio", CoverageStatus.EXACT, "fund_flow", "Exists."),
    FeatureMapping("fund_stay_time", None, CoverageStatus.MISSING, "fund_flow", "No matched dwell time."),
    FeatureMapping("large_single_deposit_count", None, CoverageStatus.MISSING, "fund_flow", "No >10000 counter."),
    FeatureMapping("small_fiat_deposit_count", "small_fiat_deposit_count", CoverageStatus.EXACT, "fund_flow", "Synthetic <1000 count."),
    FeatureMapping("avg_bank_fraud_ratio", "bank_risk_mean", CoverageStatus.EXACT, "bank", "Mean bank risk exists."),
    FeatureMapping("max_bank_risk", "bank_risk_max", CoverageStatus.EXACT, "bank", "Max bank risk exists."),
    FeatureMapping("withdrawal_unique_bankcards", None, CoverageStatus.MISSING, "bank", "No fiat-withdrawal card event."),
    FeatureMapping("bank_identity_reconciliation", "bank_name_match_ratio", CoverageStatus.APPROXIMATE, "bank", "Name ratio exists; masked-card linkage does not."),
    FeatureMapping("withdraw_address_count", "withdraw_address_unique_count", CoverageStatus.EXACT, "address", "Distinct withdrawal destinations."),
    FeatureMapping("withdraw_ip_count", "withdraw_ip_unique_count", CoverageStatus.EXACT, "device_ip", "Distinct withdrawal IPs."),
    FeatureMapping("deposit_ip_count", "deposit_ip_unique_count", CoverageStatus.EXACT, "device_ip", "Distinct deposit IPs."),
    FeatureMapping("device_count", "device_unique_count", CoverageStatus.EXACT, "device_ip", "Distinct devices."),
    FeatureMapping("api_use_ratio", "api_event_ratio", CoverageStatus.APPROXIMATE, "behavior", "Context-only; no universal direction."),
    FeatureMapping("night_activity_ratio", "night_event_ratio", CoverageStatus.EXACT, "behavior", "Context-only."),
    FeatureMapping("behavior_event_count", "total_event_count", CoverageStatus.EXACT, "behavior", "Successful event count."),
    FeatureMapping("behavior_event_diversity", None, CoverageStatus.MISSING, "behavior", "Not persisted."),
    FeatureMapping("strategy_hit_frequency", None, CoverageStatus.LINEAGE_RISK, "behavior", "Future disposition must not leak target."),
    FeatureMapping("fraud_graph_score", None, CoverageStatus.MISSING, "graph", "Graph output is separate."),
    FeatureMapping("destination_entity_type", None, CoverageStatus.MISSING, "onchain", "Exchange/private/unknown absent."),
    FeatureMapping("account_role_exclusion", None, CoverageStatus.MISSING, "population", "account_role absent."),
    FeatureMapping("label_source", None, CoverageStatus.MISSING, "label", "Confirmation source absent."),
    FeatureMapping("curated_white_semantics", None, CoverageStatus.MISSING, "label", "label=0 remains unconfirmed."),
    FeatureMapping("label_observed_at", "label_observed_at", CoverageStatus.EXACT, "label", "Delayed timestamp exists."),
    FeatureMapping("event_origin", None, CoverageStatus.MISSING, "sequence", "User/system origin absent."),
    FeatureMapping("parent_event_id", None, CoverageStatus.MISSING, "sequence", "Parent-child lineage absent."),
)


def mappings_for_columns(columns: Iterable[str]) -> list[FeatureMapping]:
    available = set(columns)
    resolved: list[FeatureMapping] = []
    checkable = {CoverageStatus.EXACT, CoverageStatus.APPROXIMATE, CoverageStatus.DERIVABLE}
    for item in FEATURE_MAPPINGS:
        if item.github_feature and item.status in checkable:
            required = [part.strip() for part in item.github_feature.split(",") if part.strip()]
            if not all(name in available for name in required):
                resolved.append(FeatureMapping(item.source_feature, item.github_feature, CoverageStatus.MISSING, item.source_role, f"Required columns absent: {required}."))
                continue
        resolved.append(item)
    return resolved
