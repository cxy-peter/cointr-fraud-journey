from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

import numpy as np
import pandas as pd


SEED = 20260728
USER_COUNT = 1_200
FRAUD_COUNT = 19
EVENT_COUNT = 105_318
KEP_CASE_COUNT = 13_703

BASE_EVENT_TYPES = (
    "REGISTER",
    "DEVICE_BIND",
    "KYC_START",
    "KYC_SUCCESS",
    "FIAT_DEPOSIT",
    "SPOT_TRADE",
    "API_TRADE",
    "CHAIN_WITHDRAW",
)


@dataclass(frozen=True)
class SyntheticData:
    users: pd.DataFrame
    events: pd.DataFrame
    graph_edges: pd.DataFrame


def generate_users(
    user_count: int = USER_COUNT,
    fraud_count: int = FRAUD_COUNT,
    seed: int = SEED,
) -> pd.DataFrame:
    """Create a deterministic synthetic user table with an exact label count."""

    if not 5 <= fraud_count < user_count:
        raise ValueError("fraud_count must be between 5 and user_count - 1")
    rng = np.random.default_rng(seed)
    user_ids = np.array([f"U{i:07d}" for i in range(1, user_count + 1)])
    registration_time = (
        pd.Timestamp("2026-01-01", tz="UTC")
        + pd.to_timedelta(rng.integers(0, 120, user_count), unit="D")
        + pd.to_timedelta(rng.integers(0, 86_400, user_count), unit="s")
    )

    rapid_cashout = rng.binomial(1, 0.08, user_count)
    device_spread = rng.binomial(1, 0.07, user_count)
    graph_ring = rng.binomial(1, 0.06, user_count)
    bank_risk = rng.beta(1.3, 8.0, user_count)
    propensity = (
        1.8 * rapid_cashout
        + 1.3 * device_spread
        + 1.4 * graph_ring
        + 1.2 * bank_risk
        + rng.normal(0, 0.55, user_count)
    )
    fraud_indices = np.argsort(propensity, kind="stable")[-fraud_count:]
    fraud_label = np.zeros(user_count, dtype=int)
    fraud_label[fraud_indices] = 1

    channels = rng.choice(
        ["ANDROID", "IOS", "WEB", "H5"],
        user_count,
        p=[0.42, 0.30, 0.22, 0.06],
    )
    occupations = rng.choice(
        ["SALARIED", "SELF_EMPLOYED", "STUDENT", "RETIRED", "OTHER"],
        user_count,
        p=[0.45, 0.22, 0.12, 0.08, 0.13],
    )
    users = pd.DataFrame(
        {
            "user_id": user_ids,
            "customer_name": [f"Synthetic_User_{i:05d}" for i in range(1, user_count + 1)],
            "registration_time": registration_time,
            "registration_channel": channels,
            "kyc_level": rng.choice(["L1", "L2"], user_count, p=[0.18, 0.82]),
            "age": rng.integers(19, 72, user_count),
            "occupation": occupations,
            "country_code": rng.choice(["TR", "DE", "NL", "AE", "GB"], user_count, p=[0.72, 0.08, 0.06, 0.07, 0.07]),
            "ka_owner": [f"KA_{i % 12:02d}" if i % 9 == 0 else "N/A" for i in range(user_count)],
            "bd_owner": [f"BD_{i % 8:02d}" if i % 11 == 0 else "N/A" for i in range(user_count)],
            "user_restriction": np.where(risk_propensity_rank(propensity) > 0.93, "REVIEW_ONLY", "NONE"),
            "risk_tag": np.where(graph_ring == 1, "SYNTHETIC_GRAPH_SIGNAL", "BASELINE"),
            "fraud_label": fraud_label,
            # The synthetic maturity delay mirrors the approximately 52-day review window
            # described in the source methodology. It is not a company SLA.
            "label_observed_at": registration_time + pd.to_timedelta(52, unit="D"),
            "latent_rapid_cashout": rapid_cashout,
            "latent_device_spread": device_spread,
            "latent_graph_ring": graph_ring,
            "latent_bank_risk": bank_risk,
        }
    )
    if int(users["fraud_label"].sum()) != fraud_count:
        raise AssertionError("synthetic label count drifted")
    return users.sort_values(["registration_time", "user_id"], kind="stable").reset_index(drop=True)


def risk_propensity_rank(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="stable")
    ranks = np.empty(len(values), dtype=float)
    ranks[order] = np.arange(len(values), dtype=float)
    return ranks / max(len(values) - 1, 1)


def _allocate_amounts(
    records: list[dict[str, object]],
    rng: np.random.Generator,
    fraud: bool,
) -> None:
    deposit_total = float(rng.lognormal(np.log(9_000 if fraud else 6_000), 0.78 if fraud else 0.82))
    if fraud:
        trade_total = deposit_total * float(rng.uniform(0.94, 1.035))
        withdraw_total = deposit_total * float(rng.uniform(0.88, 0.995))
    elif rng.random() < 0.28:
        # Legitimate high-throughput users prevent a synthetic perfect separator.
        trade_total = deposit_total * float(rng.uniform(0.82, 1.12))
        withdraw_total = deposit_total * float(rng.uniform(0.66, 0.96))
    else:
        trade_total = deposit_total * float(rng.uniform(0.20, 1.45))
        withdraw_total = deposit_total * float(rng.uniform(0.04, 0.78))

    groups = {
        "deposit": ("FIAT_DEPOSIT",),
        "trade": ("SPOT_TRADE", "API_TRADE"),
        "withdraw": ("CHAIN_WITHDRAW",),
    }
    totals = {"deposit": deposit_total, "trade": trade_total, "withdraw": withdraw_total}
    for name, event_types in groups.items():
        indices = [
            idx
            for idx, row in enumerate(records)
            if row["event_type"] in event_types and row["status"] == "SUCCESS"
        ]
        weights = rng.lognormal(0.0, 0.55, len(indices))
        weights = weights / weights.sum()
        for idx, weight in zip(indices, weights):
            records[idx]["amount_usdt"] = round(float(totals[name] * weight), 6)
    for row in records:
        if row["event_type"] == "INTERNAL_TRANSFER" and row["status"] == "SUCCESS":
            row["amount_usdt"] = round(float(rng.lognormal(np.log(350), 0.9)), 6)


def generate_events(
    users: pd.DataFrame,
    event_count: int = EVENT_COUNT,
    seed: int = SEED + 1,
) -> pd.DataFrame:
    """Generate exact-count event data with one ordered lifecycle per user.

    Pending and failed attempts remain in the raw event table. Downstream feature
    engineering deliberately counts only SUCCESS rows so state transitions are
    not double-counted.
    """

    if event_count < len(users) * len(BASE_EVENT_TYPES):
        raise ValueError("event_count is too small for one complete lifecycle per user")
    rng = np.random.default_rng(seed)
    fraud_flags = users["fraud_label"].astype(int).to_numpy()
    activity_weight = rng.lognormal(0.0, 0.48, len(users)) * (1.0 + 0.60 * fraud_flags)
    extras = rng.multinomial(
        event_count - len(users) * len(BASE_EVENT_TYPES),
        activity_weight / activity_weight.sum(),
    )
    all_rows: list[dict[str, object]] = []

    normal_extra_types = np.array(
        ["LOGIN", "DEVICE_LOGIN", "FIAT_DEPOSIT", "SPOT_TRADE", "API_TRADE", "CHAIN_WITHDRAW", "PASSWORD_CHANGE", "INTERNAL_TRANSFER"]
    )
    normal_probs = np.array([0.27, 0.13, 0.12, 0.15, 0.14, 0.08, 0.04, 0.07])
    fraud_probs = np.array([0.21, 0.13, 0.16, 0.17, 0.10, 0.12, 0.04, 0.07])

    for user_pos, user in enumerate(users.itertuples(index=False)):
        fraud = bool(user.fraud_label)
        registration = pd.Timestamp(user.registration_time)
        kyc_start = registration + timedelta(minutes=int(rng.integers(3, 20)))
        # Fraud has directional tendencies but every interval deliberately
        # overlaps the benign distribution; no feature is a label proxy.
        kyc_success = kyc_start + timedelta(minutes=int(rng.integers(5, 430) if fraud else rng.integers(3, 650)))
        first_deposit = kyc_success + timedelta(minutes=int(rng.integers(10, 1_800) if fraud else rng.integers(20, 5_000)))
        first_spot = first_deposit + timedelta(minutes=int(rng.integers(5, 800) if fraud else rng.integers(10, 1_500)))
        first_api = first_spot + timedelta(minutes=int(rng.integers(3, 500) if fraud else rng.integers(5, 900)))
        first_withdraw = first_api + timedelta(minutes=int(rng.integers(10, 2_400) if fraud else rng.integers(30, 8_000)))

        base_times = [
            registration,
            registration + timedelta(minutes=1),
            kyc_start,
            kyc_success,
            first_deposit,
            first_spot,
            first_api,
            first_withdraw,
        ]
        n_devices = int(rng.integers(1, 5) if fraud else rng.integers(1, 4))
        n_deposit_ips = int(rng.integers(1, 3))
        n_withdraw_ips = int(rng.integers(1, 5) if fraud else rng.integers(1, 4))
        n_addresses = int(rng.integers(1, 5) if fraud else rng.integers(1, 4))
        devices = [f"DEV_{user.user_id}_{i:02d}" for i in range(n_devices)]
        deposit_ips = [f"10.{(user_pos // 250) % 250}.{user_pos % 250}.{10 + i}" for i in range(n_deposit_ips)]
        withdraw_ips = [f"172.{(user_pos // 250) % 250}.{user_pos % 250}.{20 + i}" for i in range(n_withdraw_ips)]
        addresses = [f"WALLET_{user.user_id}_{i:02d}" for i in range(n_addresses)]

        records: list[dict[str, object]] = []
        for seq, (event_type, timestamp) in enumerate(zip(BASE_EVENT_TYPES, base_times)):
            records.append(
                _event_record(
                    user_id=user.user_id,
                    event_type=event_type,
                    timestamp=timestamp,
                    status="SUCCESS",
                    device_id=devices[seq % len(devices)],
                    ip_address=(withdraw_ips[0] if event_type == "CHAIN_WITHDRAW" else deposit_ips[0]),
                    withdraw_address=(addresses[0] if event_type == "CHAIN_WITHDRAW" else ""),
                    bank_id=(f"BANK_{user_pos % 31:03d}" if event_type == "FIAT_DEPOSIT" else ""),
                )
            )

        chosen = rng.choice(
            normal_extra_types,
            size=int(extras[user_pos]),
            replace=True,
            p=fraud_probs if fraud else normal_probs,
        )
        for event_type in chosen:
            day_offset = int(rng.integers(1, 61))
            # Context only: night activity is deliberately near-neutral and is
            # not encoded as a universal Fraud direction.
            night = rng.random() < (0.22 if fraud else 0.25)
            hour = int(rng.choice([0, 1, 2, 3, 4, 5])) if night else int(rng.integers(7, 24))
            timestamp = first_withdraw.normalize() + timedelta(
                days=day_offset,
                hours=hour,
                minutes=int(rng.integers(0, 60)),
                seconds=int(rng.integers(0, 60)),
            )
            status_roll = rng.random()
            status = "SUCCESS" if status_roll < 0.92 else ("FAILED" if status_roll < 0.97 else "PENDING")
            if event_type == "CHAIN_WITHDRAW":
                ip = str(rng.choice(withdraw_ips))
                address = str(rng.choice(addresses))
            elif event_type == "FIAT_DEPOSIT":
                ip = str(rng.choice(deposit_ips))
                address = ""
            else:
                ip = str(rng.choice(deposit_ips + withdraw_ips))
                address = ""
            records.append(
                _event_record(
                    user_id=user.user_id,
                    event_type=str(event_type),
                    timestamp=timestamp,
                    status=status,
                    device_id=str(rng.choice(devices)),
                    ip_address=ip,
                    withdraw_address=address,
                    bank_id=(f"BANK_{int(rng.integers(0, 31)):03d}" if event_type == "FIAT_DEPOSIT" else ""),
                )
            )
        _allocate_amounts(records, rng, fraud)
        all_rows.extend(records)

    events = pd.DataFrame(all_rows)
    events = events.sort_values(["event_time", "user_id", "event_type"], kind="stable").reset_index(drop=True)
    trade_mask = events["event_type"].isin(["SPOT_TRADE", "API_TRADE"])
    events.loc[trade_mask, "asset_pair"] = rng.choice(
        ["USDT_TRY", "BTC_USDT", "ETH_USDT", "BTC_TRY", "ETH_TRY", "USDC_USDT"],
        size=int(trade_mask.sum()),
        p=[0.34, 0.24, 0.18, 0.10, 0.08, 0.06],
    )
    deposit_mask = events["event_type"].eq("FIAT_DEPOSIT")
    customer_lookup = users.set_index("user_id")["customer_name"].astype(str)
    events.loc[deposit_mask, "bank_user_name"] = events.loc[deposit_mask, "user_id"].map(customer_lookup)
    mismatch_indices = events.index[deposit_mask & (rng.random(len(events)) < 0.045)]
    events.loc[mismatch_indices, "bank_user_name"] = "Synthetic_Third_Party"
    events["bank_risk_score"] = 0.0
    events.loc[deposit_mask, "bank_risk_score"] = (
        events.loc[deposit_mask, "bank_id"].str.extract(r"(\d+)", expand=False).astype(float).fillna(0) % 11
    ) / 10.0
    events.insert(0, "event_id", [f"EVT{i:09d}" for i in range(1, len(events) + 1)])
    if len(events) != event_count:
        raise AssertionError(f"event count drifted: {len(events)} != {event_count}")
    return events


def _event_record(
    *,
    user_id: str,
    event_type: str,
    timestamp: pd.Timestamp,
    status: str,
    device_id: str,
    ip_address: str,
    withdraw_address: str,
    bank_id: str,
) -> dict[str, object]:
    return {
        "user_id": user_id,
        "event_time": timestamp,
        "available_at": timestamp + timedelta(minutes=2),
        "event_type": event_type,
        "status": status,
        "amount_usdt": 0.0,
        "device_id": device_id,
        "ip_address": ip_address,
        "withdraw_address": withdraw_address,
        "bank_id": bank_id,
        "bank_user_name": "",
        "bank_risk_score": 0.0,
        "asset_pair": "",
        "api_flag": int(event_type == "API_TRADE"),
        "night_flag": int(timestamp.hour < 6),
        "source_system": "synthetic_event_hub",
    }


def generate_graph_edges(
    users: pd.DataFrame,
    events: pd.DataFrame,
    seed: int = SEED + 2,
) -> pd.DataFrame:
    """Create a user-identifier graph without deposit-address nodes."""

    rng = np.random.default_rng(seed)
    strengths = {
        "device": 1.0,
        "email": 0.85,
        "phone": 0.95,
        "kyc_id": 1.0,
        "withdraw_address": 1.0,
        "ip": 0.25,
    }
    rows: list[dict[str, object]] = []

    registration_lookup = users.set_index("user_id")["registration_time"].to_dict()

    def add(
        user_id: str,
        relation: str,
        identifier: str,
        *,
        first_seen_at: object | None = None,
        last_seen_at: object | None = None,
        direction: str = "USER_TO_IDENTIFIER",
        event_count: int = 1,
        amount_usdt: float = 0.0,
    ) -> None:
        first = pd.Timestamp(first_seen_at if first_seen_at is not None else registration_lookup[user_id])
        last = pd.Timestamp(last_seen_at if last_seen_at is not None else first)
        rows.append(
            {
                "user_id": user_id,
                "relation_type": relation,
                "identifier": identifier,
                "relation_weight": strengths[relation],
                "first_seen_at": first,
                "last_seen_at": last,
                "direction": direction,
                "event_count": int(event_count),
                "amount_usdt": float(amount_usdt),
            }
        )

    for user in users.itertuples(index=False):
        add(user.user_id, "email", f"EMAIL_{user.user_id}")
        add(user.user_id, "phone", f"PHONE_{user.user_id}")
        add(user.user_id, "kyc_id", f"KYC_{user.user_id}")

    for user_id, group in events.groupby("user_id", sort=True):
        for value in sorted(set(group["device_id"].astype(str))):
            if value:
                subset = group[group["device_id"].astype(str) == value]
                add(str(user_id), "device", value, first_seen_at=subset["event_time"].min(), last_seen_at=subset["event_time"].max(), event_count=len(subset), amount_usdt=subset["amount_usdt"].sum())
        for value in sorted(set(group["ip_address"].astype(str))):
            if value:
                subset = group[group["ip_address"].astype(str) == value]
                add(str(user_id), "ip", value, first_seen_at=subset["event_time"].min(), last_seen_at=subset["event_time"].max(), event_count=len(subset), amount_usdt=subset["amount_usdt"].sum())
        for value in sorted(set(group.loc[group["withdraw_address"] != "", "withdraw_address"].astype(str))):
            subset = group[group["withdraw_address"].astype(str) == value]
            add(str(user_id), "withdraw_address", value, first_seen_at=subset["event_time"].min(), last_seen_at=subset["event_time"].max(), event_count=len(subset), amount_usdt=subset["amount_usdt"].sum())

    fraud_ids = sorted(users.loc[users["fraud_label"] == 1, "user_id"].astype(str))
    normal_ids = sorted(users.loc[users["fraud_label"] == 0, "user_id"].astype(str))
    candidate_positions = np.linspace(7, len(normal_ids) - 8, 15, dtype=int)
    candidate_ids = [normal_ids[int(pos)] for pos in candidate_positions]
    strong_relations = ["device", "email", "phone", "kyc_id", "withdraw_address"]
    for idx, candidate_id in enumerate(candidate_ids):
        fraud_id = fraud_ids[idx % len(fraud_ids)]
        relation = strong_relations[idx % len(strong_relations)]
        shared = f"SHARED_{relation.upper()}_{idx:02d}"
        add(fraud_id, relation, shared, direction="SHARED_IDENTIFIER_EVIDENCE")
        add(candidate_id, relation, shared, direction="SHARED_IDENTIFIER_EVIDENCE")

    # Public/corporate networks are intentionally weak evidence and add benign noise.
    for idx, user_id in enumerate(sorted(users["user_id"].astype(str))):
        if idx % 23 == 0:
            add(user_id, "ip", f"PUBLIC_IP_{idx % 7:02d}")
    edges = pd.DataFrame(rows).drop_duplicates(
        ["user_id", "relation_type", "identifier"], keep="first"
    )
    if (edges["relation_type"] == "deposit_address").any():
        raise AssertionError("deposit addresses must not enter the Risk Graph")
    return edges.sort_values(["user_id", "relation_type", "identifier"], kind="stable").reset_index(drop=True)


def build_synthetic_data(
    user_count: int = USER_COUNT,
    fraud_count: int = FRAUD_COUNT,
    event_count: int = EVENT_COUNT,
    seed: int = SEED,
) -> SyntheticData:
    users = generate_users(user_count=user_count, fraud_count=fraud_count, seed=seed)
    events = generate_events(users, event_count=event_count, seed=seed + 1)
    graph_edges = generate_graph_edges(users, events, seed=seed + 2)
    return SyntheticData(users=users, events=events, graph_edges=graph_edges)
