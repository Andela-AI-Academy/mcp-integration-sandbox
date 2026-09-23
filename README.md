# WS4 Integration Sandbox

A safe, self-contained environment for the **Workshop 4 (Integration: MCP, Data & SQL)**
facilitator demo. One machine, no Siemens systems, no network, no production data.

This exists because Siemens had not approved an MCP server in time for cohort 1,
so WS4 runs as **concepts + facilitator demo**. The facilitator drives everything
here; learners watch and reason. See
`programme-adoption/course-claude-siemens/Workshop 4 - Integration/07-facilitator-demo-pack.md`.

## What it contains

Two "systems" that disagree with each other.

**System A — the operational database** (`ops.db`, SQLite), reached through a
bundled **read-only MCP server**. It holds field-service work orders and a
`v_billing_export` view.

**System B — the finance extract** (`data/finance_extract.csv`), a flat file the
"finance system" produced, which Claude reads with its ordinary file tools.

The teaching defect lives in the gap between them. Do not fix it — the demo
depends on it, and the test suite fails on purpose if you do. The explanation is
in `docs/ANSWER-KEY.md` (facilitator only).

## Stack

Python 3.12 and SQLite. **No third-party packages** and no network: the MCP
server is written against the standard library and ships in `server/`. `pytest`
is needed only if you want to run the test suite.

## Quick start

```bash
make ready
```

That installs the MCP config, builds the database, proves the seeded mismatch is
present, and exercises the MCP server over stdio. Then open Claude Code in this
folder and run `/mcp` — you should see `ops-db` connected.

Individually:

```bash
make mcp-config   # copy mcp.json.example -> .mcp.json (read it first)
make seed         # build ops.db (deterministic)
make verify       # prove the mismatch is visible
make selftest     # exercise the MCP server the way a client does
make test         # pytest
make clean        # remove ops.db and caches
```

### On Windows

`make` may not be present, and `python3` is often just `python`. Run the steps
directly and adjust the command in `.mcp.json` to match:

```powershell
copy mcp.json.example .mcp.json
python seed\build_seed.py
python scripts\verify_demo.py
python scripts\selftest_mcp.py
```

## Why the MCP config is not pre-installed

`.mcp.json` is deliberately *not* committed. Registering an MCP server means
granting an agent a new reach, and reading the config before you install it is
exactly the judgement WS4 teaches. `make mcp-config` copies the example into
place once you have looked at it.

## The connection is read-only, twice over

1. SQLite is opened with a `mode=ro` URI, so writes fail at the driver level.
2. Statements are screened before execution — one `SELECT` (or `WITH … SELECT`)
   at a time, nothing else — so a refused write returns a clear message instead
   of a driver error.

Try it during the demo: ask the agent to update a row and read the refusal aloud.
That is the scoped-to-need rule made visible.

## Layout

```
data/schema.sql           table + the v_billing_export view (the defect lives here)
data/work_orders.json     deterministic seed data
data/finance_extract.csv  System B
seed/build_seed.py        builds ops.db
server/ops_mcp_server.py  bundled read-only MCP server (stdlib only)
scripts/verify_demo.py    proves the mismatch before you present
scripts/selftest_mcp.py   exercises the MCP handshake, tools, and refusals
tests/test_sandbox.py     guards the seeded defect and the read-only screening
docs/DEMO-SCRIPT.md       the run sheet, mapped to the slides
docs/ANSWER-KEY.md        the defect explained — facilitator only
docs/DATA-DICTIONARY.md   the (stale) doc that helps cause the trap
```

## Troubleshooting

**`disk I/O error` when seeding.** SQLite needs real file locking. Building
`ops.db` on a network drive, a synced folder, or a mounted share can fail. Clone
to a local disk.

**`/mcp` shows nothing, or `ops-db` is missing.** Check `.mcp.json` exists
(`make mcp-config`), that the `command` matches your Python (`python` vs
`python3`), and that Claude Code was started from this folder. `make selftest`
tells you whether the server itself is healthy, independently of the client.

**`database not found`.** Run `make seed`.
