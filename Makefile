# WS4 Integration Sandbox — facilitator demo environment
# No Docker, no network, no third-party packages: Python 3.12 + SQLite only.
DB ?= ops.db
PY ?= python3

.PHONY: help mcp-config claude-config seed verify selftest test ready clean

help:
	@echo "make ready         config + seed + verify + selftest — run before the session"
	@echo "make mcp-config    install .mcp.json from mcp.json.example (review it first)"
	@echo "make claude-config install .claude/ settings + the ops.db guard hook"
	@echo "make seed        build $(DB) from data/schema.sql + data/work_orders.json"
	@echo "make verify      prove the seeded mismatch is present and visible"
	@echo "make selftest    exercise the bundled MCP server over stdio"
	@echo "make test        run the pytest suite"
	@echo "make clean       remove $(DB) and caches"

# Registering an MCP server is a deliberate act — read mcp.json.example first.
# This is the same judgement the workshop teaches, so we do not auto-install it.
mcp-config:
	@if [ -f .mcp.json ]; then \
		echo ".mcp.json already exists — leaving it alone."; \
	else \
		cp mcp.json.example .mcp.json; \
		echo "installed .mcp.json (ops-db, read-only, bundled server)"; \
	fi

seed:
	$(PY) seed/build_seed.py $(DB)

verify: seed
	$(PY) scripts/verify_demo.py

selftest: seed
	$(PY) scripts/selftest_mcp.py

test: seed
	pytest -q

# The MCP connection is read-only, but the agent also has a shell. These
# settings deny writes to ops.db by other paths, and the hook refuses shell
# commands that name the file at all. See README, "the read-only boundary".
claude-config:
	@mkdir -p .claude/hooks
	@cp hooks/guard-ops-db.sh .claude/hooks/guard-ops-db.sh
	@chmod +x .claude/hooks/guard-ops-db.sh
	@if [ -f .claude/settings.json ]; then \
		echo ".claude/settings.json already exists — leaving it alone."; \
	else \
		cp claude-settings.example.json .claude/settings.json; \
		echo "installed .claude/settings.json + the ops.db guard hook"; \
	fi

ready: mcp-config claude-config verify selftest
	@echo ""
	@echo "Sandbox ready. Open Claude Code here and run /mcp to confirm ops-db is connected."

clean:
	rm -f $(DB)
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
	rm -rf .pytest_cache
