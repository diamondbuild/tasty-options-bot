# Tastytrade Defined-Risk Options Bot Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Build a Python bot that uses the tastytrade API to scan, select, execute, manage, and journal defined-risk ETF options credit spreads for a $3,000 account.

**Architecture:** The bot is rule-first, not free-form AI-first. Deterministic strategy and risk modules decide whether trades are allowed; the AI layer is only for ranking, explanations, and daily summaries. Live order placement is behind explicit configuration flags, hard risk caps, stale-data checks, and kill switches.

**Tech Stack:** Python 3.11+, pytest, pydantic, pandas, rich, httpx, SQLite, tastytrade API wrapper/custom client, yfinance or equivalent historical data source.

---

## Safety and Trading Constraints

This project must never default to live trading.

Initial account assumptions:
- Starting equity: $3,000
- Strategy: defined-risk ETF put credit spreads first
- Universe: SPY, QQQ, IWM, DIA, XLK, XLF, XLE, TLT, GLD
- Contracts: one-lot spreads only at first
- Max position loss: $100 initially, configurable up to $150
- Max open defined risk: $400 initially
- Max open positions: 3
- Max daily loss: $150
- Max weekly loss: $300
- Shutdown equity: $2,400
- No market orders
- No naked options
- No earnings trades for single stocks; ETFs only in v1
- No expiration-week holds
- Close positions around 21 DTE

Initial strategy:
- Put credit spreads only
- Expiration: 30-45 DTE
- Short put delta: 0.15-0.25
- Spread width: $1 or $2
- Minimum credit ratio: 25% of width
- Profit target: close at 50% of max profit
- Loss exit: close if spread value reaches 2x entry credit, or if risk regime flips
- Limit orders only

---

## Project Layout

```text
tasty-options-bot/
  README.md
  pyproject.toml
  .env.example
  config/
    account.yaml
    strategy.yaml
    universe.yaml
    execution.yaml
  src/
    tasty_options_bot/
      __init__.py
      cli.py
      config.py
      models.py
      risk.py
      spreads.py
      strategy.py
      market_data.py
      journal.py
      broker/
        __init__.py
        tastytrade_client.py
        paper.py
      reports.py
  tests/
    test_risk.py
    test_spreads.py
    test_strategy.py
    test_config.py
  data/
    .gitkeep
  reports/
    .gitkeep
```

---

## Task 1: Create Python project skeleton

**Objective:** Establish package layout, dependencies, and test runner.

**Files:**
- Create: `pyproject.toml`
- Create: `README.md`
- Create: `.env.example`
- Create: `src/tasty_options_bot/__init__.py`
- Create: `tests/`

**Step 1: Write minimal package metadata**

Create `pyproject.toml` with:

```toml
[project]
name = "tasty-options-bot"
version = "0.1.0"
description = "Defined-risk tastytrade options bot for small accounts"
requires-python = ">=3.11"
dependencies = [
  "httpx>=0.27",
  "pydantic>=2",
  "pydantic-settings>=2",
  "pandas>=2",
  "pyyaml>=6",
  "rich>=13",
  "typer>=0.12",
]

[project.optional-dependencies]
dev = [
  "pytest>=8",
  "pytest-cov>=5",
  "ruff>=0.5",
]

[project.scripts]
tasty-options-bot = "tasty_options_bot.cli:app"

[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]

[tool.ruff]
line-length = 100
```

**Step 2: Create `.env.example`**

```bash
TASTYTRADE_USERNAME=
TASTYTRADE_PASSWORD=
TASTYTRADE_ACCOUNT_NUMBER=
TASTYTRADE_IS_PRODUCTION=false
BOT_LIVE_TRADING=false
BOT_REQUIRE_MANUAL_APPROVAL=true
```

**Step 3: Verify project imports**

Run:

```bash
python -m pytest -q
```

Expected: pytest runs, even if no tests exist yet.

---

## Task 2: Add core trade and spread models using TDD

**Objective:** Represent option legs, credit spreads, and risk calculations safely.

**Files:**
- Create: `tests/test_spreads.py`
- Create: `src/tasty_options_bot/models.py`
- Create: `src/tasty_options_bot/spreads.py`

**Step 1: Write failing tests**

Tests should cover:
- $1-wide spread with $0.30 credit has $30 max profit and $70 max loss
- $2-wide spread with $0.60 credit has $60 max profit and $140 max loss
- credit ratio = credit / width
- invalid spreads reject negative width or negative credit

Example test:

```python
from tasty_options_bot.spreads import CreditSpread


def test_credit_spread_calculates_max_profit_and_loss():
    spread = CreditSpread(short_strike=100, long_strike=99, credit=0.30, quantity=1)

    assert spread.width == 1
    assert spread.max_profit == 30
    assert spread.max_loss == 70
    assert spread.credit_ratio == 0.30
```

**Step 2: Run test to verify failure**

Run:

```bash
pytest tests/test_spreads.py -q
```

Expected: FAIL because `tasty_options_bot.spreads` does not exist.

**Step 3: Implement minimal model**

Implement `CreditSpread` as a pydantic model or dataclass with:
- `short_strike`
- `long_strike`
- `credit`
- `quantity`
- `width`
- `max_profit`
- `max_loss`
- `credit_ratio`

**Step 4: Verify pass**

Run:

```bash
pytest tests/test_spreads.py -q
pytest tests/ -q
```

Expected: all tests pass.

---

## Task 3: Add account risk manager using TDD

**Objective:** Ensure no order can exceed account-level risk limits.

**Files:**
- Create: `tests/test_risk.py`
- Create: `src/tasty_options_bot/risk.py`

**Step 1: Write failing tests**

Tests should cover:
- allows a $70 max-loss spread when max position loss is $100
- rejects a $140 max-loss spread when max position loss is $100
- rejects new trade if total open risk would exceed $400
- rejects new trade if max positions already reached
- rejects live trading if kill switch is active

Example:

```python
from tasty_options_bot.risk import AccountRiskLimits, RiskManager
from tasty_options_bot.spreads import CreditSpread


def test_rejects_spread_above_max_position_loss():
    limits = AccountRiskLimits(max_position_loss=100, max_open_risk=400, max_open_positions=3)
    manager = RiskManager(limits=limits)
    spread = CreditSpread(short_strike=100, long_strike=98, credit=0.60, quantity=1)

    decision = manager.evaluate_new_position(spread=spread, open_risk=0, open_positions=0)

    assert not decision.allowed
    assert "max_position_loss" in decision.reason
```

**Step 2: Run failure**

```bash
pytest tests/test_risk.py -q
```

Expected: FAIL because risk module does not exist.

**Step 3: Implement minimal code**

Implement:
- `AccountRiskLimits`
- `RiskDecision`
- `RiskManager.evaluate_new_position(...)`

**Step 4: Verify pass**

```bash
pytest tests/test_risk.py -q
pytest tests/ -q
```

---

## Task 4: Add strategy filter for ETF put credit spreads

**Objective:** Select only spreads matching v1 high-probability criteria.

**Files:**
- Create: `tests/test_strategy.py`
- Create: `src/tasty_options_bot/strategy.py`

**Step 1: Write failing tests**

Tests should cover:
- accepts 30-45 DTE spread with short delta 0.15-0.25 and credit ratio >= 0.25
- rejects DTE less than 30
- rejects DTE greater than 45
- rejects short delta outside range
- rejects credit ratio below 0.25
- rejects non-ETF tickers in v1 unless explicitly configured

**Step 2: Run failure**

```bash
pytest tests/test_strategy.py -q
```

Expected: FAIL because strategy module does not exist.

**Step 3: Implement minimal code**

Implement:
- `StrategyConfig`
- `SpreadCandidate`
- `PutCreditSpreadStrategy.evaluate(candidate)`

**Step 4: Verify pass**

```bash
pytest tests/test_strategy.py -q
pytest tests/ -q
```

---

## Task 5: Add configuration loading

**Objective:** Load safe defaults from YAML and environment variables.

**Files:**
- Create: `tests/test_config.py`
- Create: `src/tasty_options_bot/config.py`
- Create: `config/account.yaml`
- Create: `config/strategy.yaml`
- Create: `config/universe.yaml`
- Create: `config/execution.yaml`

**Step 1: Write failing tests**

Tests should verify:
- live trading defaults to false
- manual approval defaults to true
- market orders default to disallowed
- max contracts per trade defaults to 1
- max position loss defaults to 100
- shutdown equity defaults to 2400

**Step 2: Run failure**

```bash
pytest tests/test_config.py -q
```

Expected: FAIL because config loader does not exist.

**Step 3: Implement minimal code**

Use pydantic settings and YAML loading. Config load order:
1. Safe built-in defaults
2. YAML files
3. Environment variables

**Step 4: Verify pass**

```bash
pytest tests/test_config.py -q
pytest tests/ -q
```

---

## Task 6: Add paper broker

**Objective:** Simulate order placement and position tracking before connecting to tastytrade.

**Files:**
- Create: `tests/test_paper_broker.py`
- Create: `src/tasty_options_bot/broker/paper.py`

**Step 1: Write failing tests**

Tests should verify:
- limit orders record requested price
- paper broker never sends real orders
- filled orders become open positions
- closing a position records realized P/L

**Step 2: Run failure**

```bash
pytest tests/test_paper_broker.py -q
```

**Step 3: Implement minimal code**

Implement a pure in-memory paper broker.

**Step 4: Verify pass**

```bash
pytest tests/test_paper_broker.py -q
pytest tests/ -q
```

---

## Task 7: Add tastytrade client shell with live-trading safety gate

**Objective:** Add API client structure without allowing accidental live orders.

**Files:**
- Create: `tests/test_tastytrade_client.py`
- Create: `src/tasty_options_bot/broker/tastytrade_client.py`

**Step 1: Write failing tests**

Tests should verify:
- client refuses to place order when `live_trading=false`
- client refuses market orders always
- client refuses orders without account number
- client requires explicit confirmation flag for live mode

**Step 2: Run failure**

```bash
pytest tests/test_tastytrade_client.py -q
```

**Step 3: Implement minimal code**

Implement:
- authentication stub/interface
- account number checks
- live-trading gate
- limit-order-only validation

Do not implement real order placement until tests prove all safety gates.

**Step 4: Verify pass**

```bash
pytest tests/test_tastytrade_client.py -q
pytest tests/ -q
```

---

## Task 8: Implement tastytrade authentication and read-only account calls

**Objective:** Authenticate and fetch account/position data without trading.

**Files:**
- Modify: `src/tasty_options_bot/broker/tastytrade_client.py`
- Create: `tests/test_tastytrade_client_auth.py`

**Step 1: Write failing tests using mocked HTTP transport**

Tests should verify:
- login stores session token
- failed login raises clear error
- account fetch includes authorization header
- no credentials are logged

**Step 2: Run failure**

```bash
pytest tests/test_tastytrade_client_auth.py -q
```

**Step 3: Implement authentication**

Use httpx with base URL depending on environment:
- production only when explicitly configured
- sandbox/certification by default if supported

**Step 4: Verify pass**

```bash
pytest tests/test_tastytrade_client_auth.py -q
pytest tests/ -q
```

---

## Task 9: Implement option chain ingestion and candidate construction

**Objective:** Convert tastytrade option chain data into spread candidates.

**Files:**
- Create: `tests/test_option_chain.py`
- Create: `src/tasty_options_bot/option_chain.py`

**Step 1: Write failing tests**

Tests should verify:
- picks expirations between 30 and 45 DTE
- filters put options by delta range
- pairs short and long puts into $1/$2 width spreads
- computes mid credit from bid/ask
- rejects stale or missing quotes
- rejects wide markets if bid/ask spread too large

**Step 2: Run failure**

```bash
pytest tests/test_option_chain.py -q
```

**Step 3: Implement minimal option chain parser**

Use fixture data first, not live API.

**Step 4: Verify pass**

```bash
pytest tests/test_option_chain.py -q
pytest tests/ -q
```

---

## Task 10: Add CLI scanner command

**Objective:** Produce ranked put credit spread candidates without placing trades.

**Files:**
- Create: `tests/test_cli.py`
- Create: `src/tasty_options_bot/cli.py`

**Step 1: Write failing tests**

Tests should verify:
- `scan` command prints candidates
- `scan` does not place orders
- rejected candidates include reasons
- no credentials are printed

**Step 2: Run failure**

```bash
pytest tests/test_cli.py -q
```

**Step 3: Implement CLI**

Commands:

```bash
tasty-options-bot scan --symbols SPY QQQ IWM
tasty-options-bot account
tasty-options-bot positions
tasty-options-bot risk-status
```

**Step 4: Verify pass**

```bash
pytest tests/test_cli.py -q
pytest tests/ -q
```

---

## Task 11: Add journal database

**Objective:** Persist candidates, orders, fills, positions, exits, and risk decisions.

**Files:**
- Create: `tests/test_journal.py`
- Create: `src/tasty_options_bot/journal.py`

**Step 1: Write failing tests**

Tests should verify:
- logs candidate decisions
- logs order submissions
- logs fills
- logs position exits
- redacts secrets

**Step 2: Run failure**

```bash
pytest tests/test_journal.py -q
```

**Step 3: Implement SQLite journal**

Tables:
- `candidates`
- `orders`
- `fills`
- `positions`
- `risk_decisions`
- `daily_account_snapshots`

**Step 4: Verify pass**

```bash
pytest tests/test_journal.py -q
pytest tests/ -q
```

---

## Task 12: Add live order placement with strict gates

**Objective:** Place limit orders only when all safety rules pass.

**Files:**
- Modify: `src/tasty_options_bot/broker/tastytrade_client.py`
- Modify: `src/tasty_options_bot/cli.py`
- Create: `tests/test_live_order_safety.py`

**Step 1: Write failing tests**

Tests should verify:
- live order rejected if `BOT_LIVE_TRADING=false`
- live order rejected if manual approval required and not provided
- market orders rejected
- order rejected if risk manager denies it
- order rejected if quote stale
- order rejected if spread credit below minimum
- order rejected if open risk exceeds max

**Step 2: Run failure**

```bash
pytest tests/test_live_order_safety.py -q
```

**Step 3: Implement order placement**

Only after all safety tests exist. Use limit orders. Never use market orders.

**Step 4: Verify pass**

```bash
pytest tests/test_live_order_safety.py -q
pytest tests/ -q
```

---

## Task 13: Add position manager and exits

**Objective:** Automatically close spreads based on profit target, loss threshold, and DTE.

**Files:**
- Create: `tests/test_position_manager.py`
- Create: `src/tasty_options_bot/position_manager.py`

**Step 1: Write failing tests**

Tests should verify:
- close at 50% profit target
- close if spread value reaches 2x credit
- close at or below 21 DTE
- do not open new trades while exit orders pending
- close orders are limit orders only

**Step 2: Run failure**

```bash
pytest tests/test_position_manager.py -q
```

**Step 3: Implement position manager**

Use broker abstraction so the same logic works for paper and tastytrade.

**Step 4: Verify pass**

```bash
pytest tests/test_position_manager.py -q
pytest tests/ -q
```

---

## Task 14: Add scheduler/daemon mode

**Objective:** Run scan/entry/exit cycles automatically during market hours.

**Files:**
- Create: `tests/test_scheduler.py`
- Create: `src/tasty_options_bot/scheduler.py`

**Step 1: Write failing tests**

Tests should verify:
- scheduler does nothing outside market hours
- exits are evaluated before entries
- kill switch prevents new entries
- stale account state stops the cycle

**Step 2: Run failure**

```bash
pytest tests/test_scheduler.py -q
```

**Step 3: Implement scheduler**

Keep it simple:
- run every 5-15 minutes during market hours
- manage exits first
- scan for entries second
- place at most one new trade per cycle

**Step 4: Verify pass**

```bash
pytest tests/test_scheduler.py -q
pytest tests/ -q
```

---

## Task 15: Add reporting

**Objective:** Provide daily human-readable status and audit trail.

**Files:**
- Create: `tests/test_reports.py`
- Create: `src/tasty_options_bot/reports.py`

**Step 1: Write failing tests**

Tests should verify report includes:
- account equity
- realized P/L
- unrealized P/L
- open risk
- open positions
- candidates found
- rejected candidates and reasons
- orders submitted
- kill switch status

**Step 2: Run failure**

```bash
pytest tests/test_reports.py -q
```

**Step 3: Implement reports**

Generate terminal output and markdown files under `reports/`.

**Step 4: Verify pass**

```bash
pytest tests/test_reports.py -q
pytest tests/ -q
```

---

## Verification Before Any Live Trading

Before enabling live trading:

```bash
pytest tests/ -q
ruff check src tests
```

Manual checklist:
- [ ] `.env` has correct tastytrade credentials
- [ ] `BOT_LIVE_TRADING=false` for first run
- [ ] Account fetch works read-only
- [ ] Position fetch works read-only
- [ ] Scanner prints candidates only
- [ ] Paper broker logs fake orders correctly
- [ ] Risk manager rejects oversize spreads
- [ ] Live client rejects market orders
- [ ] Live client rejects orders when live trading flag is false
- [ ] Live client rejects orders when manual approval is required
- [ ] Kill switch tested
- [ ] One live trade max for first production run

Only then set:

```bash
BOT_LIVE_TRADING=true
BOT_REQUIRE_MANUAL_APPROVAL=true
```

Do not disable manual approval until one-trade automation has been observed and exits have been tested.

---

## First Live Deployment Rule

First live deployment must use:
- ETFs only
- one open position max
- $1-wide spread only
- one contract only
- limit orders only
- manual approval enabled
- no automatic scaling

After several successful full trade lifecycles, increase max open positions from 1 to 3 if desired.
