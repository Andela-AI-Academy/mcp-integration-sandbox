#!/usr/bin/env python3
"""A tiny, dependency-free, READ-ONLY MCP server over the sandbox database.

Why this exists
---------------
The WS4 demo needs one reliable MCP connection on one facilitator machine, with
no package downloads and no network. So this ships with the sandbox: it speaks
MCP over stdio using nothing but the Python standard library.

Read-only, twice over
---------------------
1. The database is opened with SQLite's `mode=ro` URI, so writes fail at the
   driver level.
2. Statements are screened before execution: a single SELECT (or WITH ... SELECT)
   only. This exists to give a clear refusal message rather than a driver error.

Tools exposed
-------------
    list_objects     tables and views in the database
    describe_object  columns and the SQL definition of one table or view
    run_query        run one read-only SELECT and return the rows

Usage:
    python server/ops_mcp_server.py [--db PATH]
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "ops.db"

SERVER_INFO = {"name": "ops-db", "version": "1.0.0"}
FALLBACK_PROTOCOL = "2025-06-18"
MAX_ROWS = 200

# Belt and braces alongside mode=ro: refuse anything that is not a plain read.
_LEADING_READ = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)
_WRITE_WORDS = re.compile(
    r"\b(insert|update|delete|drop|alter|create|replace|truncate|attach|detach"
    r"|pragma|vacuum|reindex|begin|commit|rollback)\b",
    re.IGNORECASE,
)


class ToolError(Exception):
    """A problem the model should see as tool output rather than a crash."""


# --------------------------------------------------------------------------- db


def connect(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise ToolError(
            f"database not found at {db_path}. Run `make seed` (or "
            f"`python seed/build_seed.py`) to build it."
        )
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def screen_sql(sql: str) -> str:
    stripped = sql.strip().rstrip(";").strip()
    if not stripped:
        raise ToolError("empty query")
    if ";" in stripped:
        raise ToolError("one statement at a time, please")
    if not _LEADING_READ.match(stripped):
        raise ToolError("this connection is read-only: only SELECT / WITH ... SELECT")
    if _WRITE_WORDS.search(stripped):
        raise ToolError("this connection is read-only: the statement was refused")
    return stripped


def render_rows(rows: list[sqlite3.Row], truncated: bool) -> str:
    if not rows:
        return "(0 rows)"
    headers = list(rows[0].keys())
    table = [headers] + [[("" if r[h] is None else str(r[h])) for h in headers] for r in rows]
    widths = [max(len(r[i]) for r in table) for i in range(len(headers))]
    lines = [" | ".join(cell.ljust(widths[i]) for i, cell in enumerate(table[0]))]
    lines.append("-+-".join("-" * w for w in widths))
    lines.extend(
        " | ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)) for row in table[1:]
    )
    note = f"\n({len(rows)} rows{', truncated' if truncated else ''})"
    return "\n".join(lines) + note


# ------------------------------------------------------------------------ tools


def tool_list_objects(db_path: Path, _args: dict[str, Any]) -> str:
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT name, type FROM sqlite_master"
            " WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%'"
            " ORDER BY type, name"
        ).fetchall()
    if not rows:
        return "(no tables or views)"
    return "\n".join(f"{r['type']:<5} {r['name']}" for r in rows)


def tool_describe_object(db_path: Path, args: dict[str, Any]) -> str:
    name = str(args.get("name", "")).strip()
    if not name:
        raise ToolError("describe_object needs a `name`")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        raise ToolError(f"not a valid object name: {name!r}")

    with connect(db_path) as conn:
        meta = conn.execute(
            "SELECT name, type, sql FROM sqlite_master WHERE name = ?", (name,)
        ).fetchone()
        if meta is None:
            raise ToolError(f"no table or view named {name!r}")
        cols = conn.execute(f"PRAGMA table_info({name})").fetchall()

    lines = [f"{meta['type']} {meta['name']}", "", "columns:"]
    lines += [f"  {c['name']} {c['type'] or '(untyped)'}" for c in cols]
    if meta["sql"]:
        lines += ["", "definition:", meta["sql"].strip()]
    return "\n".join(lines)


def tool_run_query(db_path: Path, args: dict[str, Any]) -> str:
    sql = screen_sql(str(args.get("sql", "")))
    try:
        limit = int(args.get("limit", MAX_ROWS))
    except (TypeError, ValueError):
        raise ToolError("`limit` must be a number") from None
    limit = max(1, min(limit, MAX_ROWS))

    with connect(db_path) as conn:
        try:
            cur = conn.execute(sql)
        except sqlite3.Error as exc:
            raise ToolError(f"SQL error: {exc}") from None
        rows = cur.fetchmany(limit + 1)

    truncated = len(rows) > limit
    return render_rows(rows[:limit], truncated)


TOOLS: dict[str, dict[str, Any]] = {
    "list_objects": {
        "description": "List the tables and views in the operational database.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "handler": tool_list_objects,
    },
    "describe_object": {
        "description": "Show the columns and SQL definition of one table or view.",
        "inputSchema": {
            "type": "object",
            "properties": {"name": {"type": "string", "description": "Table or view name."}},
            "required": ["name"],
            "additionalProperties": False,
        },
        "handler": tool_describe_object,
    },
    "run_query": {
        "description": (
            "Run one read-only SELECT against the operational database and return the rows. "
            "Writes are refused."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "A single SELECT statement."},
                "limit": {
                    "type": "integer",
                    "description": f"Maximum rows to return (default and cap {MAX_ROWS}).",
                },
            },
            "required": ["sql"],
            "additionalProperties": False,
        },
        "handler": tool_run_query,
    },
}


# ---------------------------------------------------------------------- plumbing


def handle(message: dict[str, Any], db_path: Path) -> dict[str, Any] | None:
    """Return a JSON-RPC response, or None for notifications."""
    method = message.get("method")
    msg_id = message.get("id")
    is_notification = msg_id is None

    def ok(result: dict[str, Any]) -> dict[str, Any] | None:
        return None if is_notification else {"jsonrpc": "2.0", "id": msg_id, "result": result}

    def err(code: int, msg: str) -> dict[str, Any] | None:
        return (
            None
            if is_notification
            else {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": msg}}
        )

    if method == "initialize":
        requested = (message.get("params") or {}).get("protocolVersion")
        return ok(
            {
                "protocolVersion": requested or FALLBACK_PROTOCOL,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": SERVER_INFO,
            }
        )

    if method in ("notifications/initialized", "initialized"):
        return None

    if method == "ping":
        return ok({})

    if method == "tools/list":
        return ok(
            {
                "tools": [
                    {
                        "name": name,
                        "description": spec["description"],
                        "inputSchema": spec["inputSchema"],
                    }
                    for name, spec in TOOLS.items()
                ]
            }
        )

    if method == "tools/call":
        params = message.get("params") or {}
        name = params.get("name")
        spec = TOOLS.get(name)
        if spec is None:
            return ok(
                {
                    "content": [{"type": "text", "text": f"No such tool: {name}"}],
                    "isError": True,
                }
            )
        try:
            text = spec["handler"](db_path, params.get("arguments") or {})
            return ok({"content": [{"type": "text", "text": text}], "isError": False})
        except ToolError as exc:
            return ok({"content": [{"type": "text", "text": str(exc)}], "isError": True})
        except Exception as exc:  # defensive: never kill the session
            return ok(
                {
                    "content": [{"type": "text", "text": f"Unexpected tool failure: {exc}"}],
                    "isError": True,
                }
            )

    if isinstance(method, str) and method.startswith("notifications/"):
        return None

    return err(-32601, f"Method not found: {method}")


def serve(db_path: Path) -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            sys.stdout.write(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {"code": -32700, "message": "Parse error"},
                    }
                )
                + "\n"
            )
            sys.stdout.flush()
            continue

        response = handle(message, db_path)
        if response is not None:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only MCP server for the WS4 sandbox.")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="Path to ops.db")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.is_absolute():
        # Resolve relative to the repo, not the caller's cwd, so the client can
        # launch us from anywhere.
        candidate = (ROOT / db_path).resolve()
        db_path = candidate if candidate.exists() else db_path.resolve()

    print(f"ops-db MCP server: {db_path} (read-only)", file=sys.stderr)
    serve(db_path)


if __name__ == "__main__":
    main()
