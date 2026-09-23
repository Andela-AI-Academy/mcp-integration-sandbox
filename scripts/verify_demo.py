#!/usr/bin/env python3
"""Prove the demo works before you stand in front of the room.

Runs the reconciliation the demo runs, and asserts that the seeded mismatch is
present and visible: every completed work order disagrees with finance by
exactly 100x, because v_billing_export.amount is cents wearing the name of an
amount.

Usage:
    python scripts/verify_demo.py
"""
from __future__ import annotations

import csv
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "ops.db"
EXTRACT = ROOT / "data" / "finance_extract.csv"


def main() -> int:
    if not DB.exists():
        print(f"FAIL: {DB} not found. Run `make seed` first.")
        return 1

    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    ops = {
        r["work_order_id"]: r["amount"]
        for r in conn.execute(
            "SELECT work_order_id, amount FROM v_billing_export ORDER BY work_order_id"
        )
    }
    conn.close()

    with EXTRACT.open(encoding="utf-8", newline="") as fh:
        finance = {int(r["work_order_id"]): float(r["amount_usd"]) for r in csv.DictReader(fh)}

    print("Reconciliation: v_billing_export.amount  vs  finance amount_usd\n")
    header = f"{'work_order':>10} | {'ops amount':>12} | {'finance usd':>12} | {'ratio':>7}"
    print(header)
    print("-" * len(header))

    problems: list[str] = []
    ratios: list[float] = []

    for wo_id in sorted(set(ops) | set(finance)):
        a = ops.get(wo_id)
        b = finance.get(wo_id)
        if a is None or b is None:
            problems.append(f"work order {wo_id} appears in only one system")
            print(f"{wo_id:>10} | {str(a):>12} | {str(b):>12} | {'-':>7}")
            continue
        ratio = a / b if b else 0.0
        ratios.append(ratio)
        print(f"{wo_id:>10} | {a:>12,} | {b:>12,.2f} | {ratio:>7.1f}")

    print()

    # The teaching assertions.
    checks: list[tuple[str, bool]] = []
    checks.append(("both systems cover the same work orders", not problems))
    checks.append(("every row is off by exactly 100x", bool(ratios) and all(abs(r - 100.0) < 1e-9 for r in ratios)))

    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    view_sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE name = 'v_billing_export'"
    ).fetchone()[0]
    cancelled_excluded = (
        conn.execute(
            "SELECT COUNT(*) FROM v_billing_export WHERE work_order_id IN"
            " (SELECT id FROM work_orders WHERE status <> 'completed')"
        ).fetchone()[0]
        == 0
    )
    conn.close()

    checks.append(("the view exposes amount_cents as `amount`", "amount_cents AS amount" in view_sql))
    checks.append(("the view correctly excludes non-completed work", cancelled_excluded))

    ok = True
    for label, passed in checks:
        print(f"  [{'ok' if passed else 'FAIL'}] {label}")
        ok = ok and passed

    print()
    if ok:
        print("Demo is ready: the mismatch is present and visible.")
        return 0
    print("Demo is NOT ready. Re-run `make seed` and check data/schema.sql.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
