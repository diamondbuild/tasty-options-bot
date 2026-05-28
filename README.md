# Tasty Options Bot

Defined-risk tastytrade options bot for a small account.

Initial strategy:
- ETF put credit spreads first, with call credit spread support for scanner output and tickets
- 30-45 DTE
- short-leg delta around 0.15-0.25 by absolute value
- $5-wide spreads as the default/reference width for tastytrade-style scans, with $1/$2 research overrides still supported
- minimum credit ratio 25% of width unless explicitly overridden for research
- one-lot trades only
- limit orders only
- live trading disabled by default

Read the implementation plan first:

`docs/plans/2026-05-25-tasty-options-credit-spread-bot.md`

Safe operator commands:
- `.venv/bin/python -m tasty_options_bot.cli risk-status`
- `.venv/bin/python -m tasty_options_bot.cli readiness-check`
- `.venv/bin/python -m tasty_options_bot.cli operator-runbook`
- `.venv/bin/python -m tasty_options_bot.cli live-dry-run SPY --best-only --ticket-preview`
- `.venv/bin/python -m tasty_options_bot.cli scan-watchlist --preset five-wide-research --max-contracts 500 --max-symbols 20`
- `.venv/bin/python -m tasty_options_bot.cli scheduler --symbol SPY --cycles 1` (dry-run only; skips outside regular US market hours)
- `.venv/bin/python -m tasty_options_bot.cli report --write-markdown`

Important:
This is trading automation for real-money options. Do not enable live trading until tests, dry-run mode, paper broker, read-only account checks, risk gates, reconciliation, position exits, persistent kill switch, and explicit preview-only order tickets are verified.
