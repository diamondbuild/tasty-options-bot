# Tasty Options Bot

Defined-risk tastytrade options bot for a small account.

Initial strategy:
- ETF put credit spreads only
- 30-45 DTE
- short put delta 0.15-0.25
- $1/$2 wide spreads
- minimum credit ratio 25% of width
- one-lot trades only
- limit orders only
- live trading disabled by default

Read the implementation plan first:

`docs/plans/2026-05-25-tasty-options-credit-spread-bot.md`

Important:
This is trading automation for real-money options. Do not enable live trading until tests, dry-run mode, paper broker, read-only account checks, risk gates, and position exits are verified.
