#!/usr/bin/env python3
"""Build ops.db deterministically from data/schema.sql + data/work_orders.json.

The same inputs always produce the same database, so a facilitator can reset
between rehearsals and the demo with `make seed` and get an identical result.

Usage:
    python seed/build_seed.py [ops.db]
"""
from __future__ import annotations

import json
import os
import sqlite3
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "data" / "schema.sql"
ORDERS = ROOT / "data" / "work_orders.json"

COLUMNS = ("id", "site_id", "status", "scheduled_on", "amount_cents")


def _make_writable(path: Path) -> None:
    """Windows refuses to unlink a read-only file; clear the bit first."""
    try:
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
    except OSError:
        pass


def build(db_path: Path, lock: bool = True) -> int:
    if db_path.exists():
        _make_writable(db_path)
        db_path.unlink()

    orders = json.loads(ORDERS.read_text(encoding="utf-8"))
    # Deterministic insert order regardless of how the JSON is edited.
    orders.sort(key=lambda row: row["id"])

    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA.read_text(encoding="utf-8"))
        conn.executemany(
            "INSERT INTO work_orders (id, site_id, status, scheduled_on, amount_cents)"
            " VALUES (?, ?, ?, ?, ?)",
            [tuple(row[c] for c in COLUMNS) for row in orders],
        )
        conn.commit()
    finally:
        conn.close()

    if lock:
        # The last line of defence. The MCP connection is read-only, but the
        # agent also has a shell, and this database is just a file. Making it
        # read-only on disk is what stops a script from writing to it.
        os.chmod(db_path, stat.S_IREAD | (stat.S_IRGRP | stat.S_IROTH if os.name != "nt" else 0))

    return len(orders)


def main() -> None:
    db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "ops.db"
    db_path = db_path if db_path.is_absolute() else Path.cwd() / db_path
    count = build(db_path)
    print(f"built {db_path} with {count} work orders")


if __name__ == "__main__":
    main()
