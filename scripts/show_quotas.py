#!/usr/bin/env python3
"""Report matchmaking quotas using the repository .env and live game database."""

import argparse
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "human_trials"))

from db import DEFAULT_LOG_DIR, completed_matchmaking_counts  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, help="Inspect a database snapshot instead of the live database")
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")
    database = args.db or Path(os.getenv("EXPERIMENT_PATH", str(DEFAULT_LOG_DIR))).expanduser() / "game_data.db"
    database = database.expanduser().resolve()
    try:
        target = int(os.getenv("MATCHMAKING_QUOTA_PER_CONFIGURATION", "100"))
        start_date = os.getenv("MATCHMAKING_QUOTA_START_DATE", "2026-09-07")
        start_at = datetime.fromisoformat(start_date).replace(tzinfo=ZoneInfo("America/New_York"))
        counts = completed_matchmaking_counts(start_at.isoformat(), database)
    except (ValueError, sqlite3.Error) as error:
        print(f"Cannot read quota report from {database}: {error}", file=sys.stderr)
        return 1

    unrestricted = target <= 0 or all(count >= target for count in counts.values())
    print(f"Database: {database}")
    print(f"Since: {start_date} (America/New_York)")
    print(f"Target: {target} completed games per configuration")
    print()
    print(f"{'Humans':>6} {'AI':>3} {'Completed':>10} {'Remaining':>10}  Status")
    for humans in range(5, 0, -1):
        completed = counts[humans]
        remaining = max(0, target - completed)
        status = "Eligible" if unrestricted or completed < target else "Quota met"
        print(f"{humans:>6} {5 - humans:>3} {completed:>10} {remaining:>10}  {status}")
    print()
    if target <= 0:
        print("Quotas disabled; normal matchmaking.")
    elif unrestricted:
        print("All quotas met; normal matchmaking has resumed.")
    else:
        print(f"Quota matchmaking active. {sum(max(0, target - n) for n in counts.values())} completions remaining.")
    print("Counts use original rosters and recorded winners; games without a winner are excluded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
