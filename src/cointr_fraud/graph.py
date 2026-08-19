from __future__ import annotations

from collections import defaultdict

import networkx as nx
import numpy as np
import pandas as pd


RELATION_STRENGTH = {
    "device": 1.0,
    "email": 0.85,
    "phone": 0.95,
    "kyc_id": 1.0,
    "withdraw_address": 1.0,
    "ip": 0.25,
}
STRONG_RELATIONS = {name for name, weight in RELATION_STRENGTH.items() if weight >= 0.8}


class RiskGraphAnalyzer:
    """Auditable bipartite Risk Graph with explicit noise controls."""

    def __init__(self, *, supernode_degree: int = 20) -> None:
        self.supernode_degree = supernode_degree
        self.graph = nx.Graph()
        self.user_labels: dict[str, int] = {}
        self.filtered_identifiers: set[str] = set()
        self.edge_evidence: dict[tuple[str, str], dict[str, object]] = {}

    def fit(self, users: pd.DataFrame, edges: pd.DataFrame) -> "RiskGraphAnalyzer":
        if "deposit_address" in set(edges["relation_type"].astype(str)):
            raise ValueError("deposit/exchange collection addresses are not allowed in this graph")
        self.graph.clear()
        self.user_labels = users.set_index("user_id")["fraud_label"].astype(int).to_dict()
        relation_edges = edges[edges["relation_type"].isin(RELATION_STRENGTH)].copy()
        relation_edges["identifier_node"] = (
            relation_edges["relation_type"].astype(str)
            + "::"
            + relation_edges["identifier"].astype(str)
        )
        degree = relation_edges.groupby("identifier_node")["user_id"].nunique()
        prefix_noise = relation_edges["identifier"].astype(str).str.startswith(
            ("PUBLIC_IP_", "EXCHANGE_COLLECTION_", "CORPORATE_PROXY_")
        )
        self.filtered_identifiers = set(
            relation_edges.loc[
                prefix_noise
                | relation_edges["identifier_node"].map(degree).gt(self.supernode_degree),
                "identifier_node",
            ].astype(str)
        )
        relation_edges = relation_edges[
            ~relation_edges["identifier_node"].isin(self.filtered_identifiers)
        ]

        for user_id in users["user_id"].astype(str):
            self.graph.add_node(user_id, node_type="user")
        for row in relation_edges.itertuples(index=False):
            user_id = str(row.user_id)
            identifier_node = str(row.identifier_node)
            relation = str(row.relation_type)
            self.graph.add_node(
                identifier_node,
                node_type="identifier",
                relation_type=relation,
                identifier=str(row.identifier),
            )
            self.graph.add_edge(
                user_id,
                identifier_node,
                relation_type=relation,
                weight=RELATION_STRENGTH[relation],
            )
            self.edge_evidence[(user_id, identifier_node)] = {
                "first_seen_at": pd.Timestamp(row.first_seen_at).isoformat(),
                "last_seen_at": pd.Timestamp(row.last_seen_at).isoformat(),
                "direction": str(row.direction),
                "event_count": int(row.event_count),
                "amount_usdt": float(row.amount_usdt),
            }
        return self

    def explain_unlabeled_user(self, user_id: str) -> dict[str, object]:
        if self.user_labels.get(user_id, 0) != 0:
            raise ValueError("candidate must be currently unlabeled")
        fraud_neighbors: set[str] = set()
        paths: list[dict[str, object]] = []
        relation_counts: dict[str, int] = defaultdict(int)
        weighted_path_sum = 0.0
        if user_id in self.graph:
            for identifier_node in sorted(self.graph.neighbors(user_id)):
                relation = str(self.graph.nodes[identifier_node]["relation_type"])
                for neighbor in sorted(self.graph.neighbors(identifier_node)):
                    if neighbor == user_id or self.user_labels.get(neighbor, 0) != 1:
                        continue
                    fraud_neighbors.add(neighbor)
                    relation_counts[relation] += 1
                    weight = RELATION_STRENGTH[relation]
                    weighted_path_sum += weight
                    evidence = self.edge_evidence.get((user_id, identifier_node), {})
                    target_evidence = self.edge_evidence.get((neighbor, identifier_node), {})
                    paths.append(
                        {
                            "source_user": user_id,
                            "relation": relation,
                            "identifier": self.graph.nodes[identifier_node]["identifier"],
                            "target_fraud_user": neighbor,
                            "weight": weight,
                            "first_seen_at": evidence.get("first_seen_at"),
                            "last_seen_at": evidence.get("last_seen_at"),
                            "direction": evidence.get("direction", "USER_TO_IDENTIFIER_TO_USER"),
                            "source_event_count": evidence.get("event_count", 0),
                            "source_amount_usdt": evidence.get("amount_usdt", 0.0),
                            "target_first_seen_at": target_evidence.get("first_seen_at"),
                            "target_last_seen_at": target_evidence.get("last_seen_at"),
                            "target_direction": target_evidence.get("direction", "IDENTIFIER_TO_TARGET_USER"),
                            "target_event_count": target_evidence.get("event_count", 0),
                            "target_amount_usdt": target_evidence.get("amount_usdt", 0.0),
                        }
                    )
        strong_count = sum(
            count for relation, count in relation_counts.items() if relation in STRONG_RELATIONS
        )
        graph_score = float(1.0 - np.exp(-weighted_path_sum))
        return {
            "user_id": user_id,
            "current_label": 0,
            "label_interpretation": "INCONCLUSIVE_UNCONFIRMED",
            "fraud_neighbor_count": len(fraud_neighbors),
            "strong_relation_path_count": int(strong_count),
            "ip_path_count": int(relation_counts.get("ip", 0)),
            "graph_score": graph_score,
            "fraud_neighbor_uids": "|".join(sorted(fraud_neighbors)),
            "path_examples": paths,
            "review_action": "MANUAL_REVIEW",
            "automatic_enforcement": False,
        }

    def top_unlabeled_candidates(self, users: pd.DataFrame, top_n: int = 15) -> pd.DataFrame:
        records = [
            self.explain_unlabeled_user(user_id)
            for user_id in users.loc[users["fraud_label"] == 0, "user_id"].astype(str)
        ]
        records = [row for row in records if int(row["fraud_neighbor_count"]) > 0]
        records.sort(
            key=lambda row: (
                float(row["graph_score"]),
                int(row["strong_relation_path_count"]),
                int(row["fraud_neighbor_count"]),
                str(row["user_id"]),
            ),
            reverse=True,
        )
        if len(records) < top_n:
            raise AssertionError(f"only {len(records)} explainable graph candidates were generated")
        flat: list[dict[str, object]] = []
        for rank, row in enumerate(records[:top_n], 1):
            paths = row.pop("path_examples")
            path_text = " || ".join(
                f"{item['source_user']} --{item['relation']}:{item['identifier']}--> {item['target_fraud_user']}"
                f" [source={item['first_seen_at']}..{item['last_seen_at']}; {item['direction']}; "
                f"events={item['source_event_count']}; amount_usdt={item['source_amount_usdt']:.2f}; "
                f"target={item['target_first_seen_at']}..{item['target_last_seen_at']}; {item['target_direction']}; "
                f"events={item['target_event_count']}; amount_usdt={item['target_amount_usdt']:.2f}]"
                for item in paths[:6]
            )
            flat.append({"rank": rank, **row, "path_examples": path_text})
        result = pd.DataFrame(flat)
        if len(result) != top_n or result["current_label"].ne(0).any():
            raise AssertionError("graph candidate contract failed")
        return result


def build_graph_candidates(
    users: pd.DataFrame,
    edges: pd.DataFrame,
    *,
    top_n: int = 15,
) -> tuple[pd.DataFrame, dict[str, object]]:
    analyzer = RiskGraphAnalyzer().fit(users, edges)
    candidates = analyzer.top_unlabeled_candidates(users, top_n=top_n)
    audit = {
        "top_n": top_n,
        "ip_weight": RELATION_STRENGTH["ip"],
        "strong_relation_min_weight": 0.8,
        "deposit_address_included": False,
        "filtered_supernode_or_public_identifiers": len(analyzer.filtered_identifiers),
        "path_time_direction_amount_count_included": True,
        "automatic_enforcement": False,
    }
    return candidates, audit
