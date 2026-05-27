# Tasty Options Bot - Current Status

Project path: /opt/data/home/tasty-options-bot

Baseline commit:
- cafee35 Recover tasty options bot baseline

Status:
- Git branch: main
- Working tree: clean
- Python package version: 0.1.0
- Tests passing: 170 passed
- Ruff lint passing
- Safety-first tastytrade defined-risk options bot
- Live trading disabled by default
- Current state: dry-run / paper / read-only tastytrade integration is strong
- Local read-only dashboard is available for monitoring risk, open positions, exit guidance, and journal history
- Live order submission exists only behind strict gates
- Dry-run scheduler, readiness preflight, persistent kill switch, reconciliation, reporting, and operator runbook are available
- Scheduler skips automated cycles outside regular US market hours (9:30-16:00 ET weekdays)

Important commands:
- Check repo: git status
- Run tests: .venv/bin/python -m pytest -q
- Run lint: .venv/bin/python -m ruff check .
- CLI help: .venv/bin/python -m tasty_options_bot.cli --help
- CLI version: .venv/bin/python -m tasty_options_bot.cli version
- Local dashboard: .venv/bin/python -m tasty_options_bot.cli dashboard

Available CLI commands:
- version
- risk-status
- kill-switch
- readiness-check
- operator-runbook
- login-check
- account
- positions
- balance
- option-chain
- live-dry-run
- scheduler
- dashboard
- dry-run-demo
- record-manual-trade
- reconcile-submitted-orders
- manage-live-positions
- record-manual-close
- manage-manual-trade
- journal
- report

Notes:
- Use .venv/bin/python, not system python.
- Do not start over. Continue from the existing project files.
