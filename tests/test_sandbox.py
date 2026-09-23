"""Guard rails for the WS4 sandbox.

These tests protect the teaching defect: if someone "fixes" the view, the demo
loses its point, and these tests fail loudly to say so.
"""
from __future__ import annotations

import csv
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "seed"))

import build_seed  # noqa: E402


@pytest.fixture()
def db(tmp_path: Path) -> Path:
    path = tmp_path / "ops.db"
    build_seed.build(path)
    return path


def rows(db: Path, sql: str) -> list[sqlite3.Row]:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def test_seed_is_deterministic(tmp_path: Path) -> None:
    a, b = tmp_path / "a.db", tmp_path / "b.db"
    build_seed.build(a)
    build_seed.build(b)
    assert a.read_bytes() == b.read_bytes()


def test_view_excludes_non_completed_work(db: Path) -> None:
    exported = {r["work_order_id"] for r in rows(db, "SELECT work_order_id FROM v_billing_export")}
    non_completed = {
        r["id"] for r in rows(db, "SELECT id FROM work_orders WHERE status <> 'completed'")
    }
    assert exported and not (exported & non_completed)


def test_the_teaching_defect_is_present(db: Path) -> None:
    """v_billing_export.amount must still be cents wearing the name 'amount'."""
    definition = rows(db, "SELECT sql FROM sqlite_master WHERE name = 'v_billing_export'")[0]["sql"]
    assert "amount_cents AS amount" in definition, (
        "The seeded mismatch has been 'fixed'. The WS4 demo depends on it; "
        "see docs/ANSWER-KEY.md before changing data/schema.sql."
    )


def test_every_row_is_off_by_one_hundred(db: Path) -> None:
    ops = {r["work_order_id"]: r["amount"] for r in rows(db, "SELECT * FROM v_billing_export")}
    with (ROOT / "data" / "finance_extract.csv").open(encoding="utf-8", newline="") as fh:
        finance = {int(r["work_order_id"]): float(r["amount_usd"]) for r in csv.DictReader(fh)}

    assert set(ops) == set(finance), "both systems must cover the same work orders"
    for wo_id, cents in ops.items():
        assert cents == pytest.approx(finance[wo_id] * 100), f"work order {wo_id}"


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE work_orders SET amount_cents = 1",
        "DELETE FROM work_orders",
        "DROP VIEW v_billing_export",
        "SELECT 1; DROP TABLE work_orders",
        "PRAGMA writable_schema = 1",
    ],
)
def test_server_refuses_writes(sql: str) -> None:
    sys.path.insert(0, str(ROOT / "server"))
    import ops_mcp_server  # noqa: E402

    with pytest.raises(ops_mcp_server.ToolError):
        ops_mcp_server.screen_sql(sql)


def test_server_allows_reads() -> None:
    sys.path.insert(0, str(ROOT / "server"))
    import ops_mcp_server  # noqa: E402

    assert ops_mcp_server.screen_sql("SELECT * FROM v_billing_export") == (
        "SELECT * FROM v_billing_export"
    )
    assert ops_mcp_server.screen_sql(
        "WITH x AS (SELECT 1 AS n) SELECT n FROM x;"
    ).startswith("WITH")
