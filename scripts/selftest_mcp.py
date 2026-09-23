#!/usr/bin/env python3
"""Exercise the bundled MCP server over stdio, exactly as a client would.

Confirms the handshake, the tool list, a successful read, and that writes are
refused — so you know the connection will work before the session, without
needing Claude Code in front of you.

Usage:
    python scripts/selftest_mcp.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "server" / "ops_mcp_server.py"


class Client:
    def __init__(self, proc: subprocess.Popen) -> None:
        self.proc = proc
        self._id = 0

    def send(self, method: str, params: dict | None = None, notify: bool = False):
        msg: dict = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        if not notify:
            self._id += 1
            msg["id"] = self._id
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()
        if notify:
            return None
        line = self.proc.stdout.readline()
        if not line:
            raise RuntimeError(f"server closed the connection during {method}")
        return json.loads(line)


def check(label: str, condition: bool, detail: str = "") -> bool:
    print(f"  [{'ok' if condition else 'FAIL'}] {label}" + (f" — {detail}" if detail and not condition else ""))
    return condition


def main() -> int:
    proc = subprocess.Popen(
        [sys.executable, str(SERVER)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1,
    )
    ok = True
    try:
        c = Client(proc)

        r = c.send(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "selftest", "version": "1.0"},
            },
        )
        res = r.get("result", {})
        ok &= check("initialize responds", "result" in r, json.dumps(r)[:200])
        ok &= check("protocol version echoed", res.get("protocolVersion") == "2025-06-18")
        ok &= check("advertises tools capability", "tools" in res.get("capabilities", {}))
        ok &= check("names itself", res.get("serverInfo", {}).get("name") == "ops-db")

        c.send("notifications/initialized", {}, notify=True)

        r = c.send("tools/list")
        names = {t["name"] for t in r.get("result", {}).get("tools", [])}
        ok &= check("tools/list returns the three tools",
                    names == {"list_objects", "describe_object", "run_query"}, str(names))

        r = c.send("tools/call", {"name": "list_objects", "arguments": {}})
        text = r.get("result", {}).get("content", [{}])[0].get("text", "")
        ok &= check("list_objects sees the view", "v_billing_export" in text, text[:200])

        r = c.send("tools/call", {"name": "describe_object", "arguments": {"name": "v_billing_export"}})
        text = r.get("result", {}).get("content", [{}])[0].get("text", "")
        ok &= check("describe_object reveals the definition", "amount_cents AS amount" in text, text[:200])

        r = c.send("tools/call", {"name": "run_query", "arguments": {
            "sql": "SELECT work_order_id, amount FROM v_billing_export ORDER BY work_order_id"}})
        result = r.get("result", {})
        text = result.get("content", [{}])[0].get("text", "")
        ok &= check("run_query returns the export rows",
                    result.get("isError") is False and "4101" in text and "128000" in text, text[:200])

        r = c.send("tools/call", {"name": "run_query", "arguments": {
            "sql": "UPDATE work_orders SET amount_cents = 1"}})
        result = r.get("result", {})
        ok &= check("writes are refused",
                    result.get("isError") is True and "read-only" in result["content"][0]["text"].lower(),
                    json.dumps(result)[:200])

        r = c.send("tools/call", {"name": "run_query", "arguments": {
            "sql": "SELECT 1; DROP TABLE work_orders"}})
        ok &= check("stacked statements are refused", r["result"].get("isError") is True)

        r = c.send("nonsense/method")
        ok &= check("unknown method returns a JSON-RPC error", r.get("error", {}).get("code") == -32601)

    finally:
        try:
            proc.stdin.close()
        except Exception:
            pass
        proc.wait(timeout=5)

    print()
    print("MCP server self-test passed." if ok else "MCP server self-test FAILED.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
