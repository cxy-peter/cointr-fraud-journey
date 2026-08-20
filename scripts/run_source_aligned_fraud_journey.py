from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from cointr_fraud.fraud_journey import (
    write_analysis_artifacts,
    write_focused_report,
)


def _load_events(database_path: Path) -> pd.DataFrame | None:
    if not database_path.exists():
        return None
    with sqlite3.connect(database_path) as connection:
        table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='events'"
        ).fetchone()
        if table is None:
            return None
        return pd.read_sql_query(
            "SELECT user_id, event_time, event_type, status FROM events",
            connection,
        )


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    output_dir = root / "outputs" / "fraud_journey"
    users_path = root / "outputs" / "user_feature_snapshot.csv"
    database_path = root / "outputs" / "cointr_fraud_demo.sqlite"

    users = pd.read_csv(users_path) if users_path.exists() else None
    events = _load_events(database_path)
    paths = write_analysis_artifacts(
        output_dir=output_dir,
        users=users,
        events=events,
    )
    paths["report"] = write_focused_report(
        output_dir / "FRAUD_JOURNEY_SOURCE_ALIGNED_REPORT.md",
        users,
    )
    for name, path in paths.items():
        print(f"{name}: {path}")


if __name__ == "__main__":
    main()
