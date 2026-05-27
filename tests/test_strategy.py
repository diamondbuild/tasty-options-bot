from tasty_options_bot.strategy import PutCreditSpreadStrategy, SpreadCandidate, StrategyConfig


def make_candidate(**overrides):
    data = {
        "symbol": "SPY",
        "expiration": "2026-07-17",
        "dte": 38,
        "short_strike": 600,
        "long_strike": 599,
        "short_delta": -0.20,
        "credit": 0.30,
        "underlying_type": "ETF",
    }
    data.update(overrides)
    return SpreadCandidate(**data)


def test_accepts_valid_etf_put_credit_spread_candidate():
    strategy = PutCreditSpreadStrategy(StrategyConfig())
    candidate = make_candidate()

    decision = strategy.evaluate(candidate)

    assert decision.allowed
    assert decision.reason == "allowed"


def test_rejects_candidate_below_minimum_dte():
    strategy = PutCreditSpreadStrategy(StrategyConfig())
    candidate = make_candidate(dte=29)

    decision = strategy.evaluate(candidate)

    assert not decision.allowed
    assert "dte_min" in decision.reason


def test_rejects_candidate_above_maximum_dte():
    strategy = PutCreditSpreadStrategy(StrategyConfig())
    candidate = make_candidate(dte=46)

    decision = strategy.evaluate(candidate)

    assert not decision.allowed
    assert "dte_max" in decision.reason


def test_rejects_short_delta_below_range():
    strategy = PutCreditSpreadStrategy(StrategyConfig())
    candidate = make_candidate(short_delta=-0.14)

    decision = strategy.evaluate(candidate)

    assert not decision.allowed
    assert "short_delta_min" in decision.reason


def test_rejects_short_delta_above_range():
    strategy = PutCreditSpreadStrategy(StrategyConfig())
    candidate = make_candidate(short_delta=-0.26)

    decision = strategy.evaluate(candidate)

    assert not decision.allowed
    assert "short_delta_max" in decision.reason


def test_rejects_credit_ratio_below_minimum():
    strategy = PutCreditSpreadStrategy(StrategyConfig())
    candidate = make_candidate(credit=0.24)

    decision = strategy.evaluate(candidate)

    assert not decision.allowed
    assert "min_credit_ratio" in decision.reason


def test_rejects_non_etf_candidate_by_default():
    strategy = PutCreditSpreadStrategy(StrategyConfig())
    candidate = make_candidate(symbol="AAPL", underlying_type="EQUITY")

    decision = strategy.evaluate(candidate)

    assert not decision.allowed
    assert "underlying_type" in decision.reason


def test_rejects_symbol_not_in_universe():
    strategy = PutCreditSpreadStrategy(StrategyConfig(universe=["SPY", "QQQ"]))
    candidate = make_candidate(symbol="IWM")

    decision = strategy.evaluate(candidate)

    assert not decision.allowed
    assert "universe" in decision.reason


def test_accepts_positive_delta_inputs_by_absolute_value():
    strategy = PutCreditSpreadStrategy(StrategyConfig())
    candidate = make_candidate(short_delta=0.20)

    decision = strategy.evaluate(candidate)

    assert decision.allowed


def test_candidate_exposes_credit_spread_risk_metrics():
    candidate = make_candidate(short_strike=600, long_strike=599, credit=0.30)

    assert candidate.spread.width == 1
    assert candidate.spread.max_profit == 30
    assert candidate.spread.max_loss == 70
    assert candidate.credit_ratio == 0.30


def test_candidate_labels_put_and_call_credit_spreads():
    assert make_candidate(option_type="put").strategy_label == "Put Credit Spread"
    assert make_candidate(option_type="call").strategy_label == "Call Credit Spread"
