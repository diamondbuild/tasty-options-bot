import pytest

from tasty_options_bot.broker.paper import PaperBroker, PaperBrokerError
from tasty_options_bot.spreads import CreditSpread


def make_spread(**overrides):
    data = {"short_strike": 100, "long_strike": 99, "credit": 0.30, "quantity": 1}
    data.update(overrides)
    return CreditSpread(**data)


def test_paper_broker_starts_with_no_positions_or_orders():
    broker = PaperBroker(starting_cash=3000)

    assert broker.cash == 3000
    assert broker.orders == []
    assert broker.positions == []
    assert broker.is_live is False


def test_paper_broker_records_limit_order_without_real_order_side_effects():
    broker = PaperBroker(starting_cash=3000)
    spread = make_spread()

    order = broker.sell_credit_spread(symbol="SPY", spread=spread, limit_credit=0.30)

    assert order.id == "paper-order-1"
    assert order.symbol == "SPY"
    assert order.side == "sell_to_open"
    assert order.order_type == "limit"
    assert order.limit_price == 0.30
    assert order.status == "filled"
    assert broker.orders == [order]
    assert broker.cash == 3030


def test_filled_sell_to_open_order_creates_open_position():
    broker = PaperBroker(starting_cash=3000)
    spread = make_spread()

    order = broker.sell_credit_spread(symbol="SPY", spread=spread, limit_credit=0.30)

    assert len(broker.positions) == 1
    position = broker.positions[0]
    assert position.id == "paper-position-1"
    assert position.opening_order_id == order.id
    assert position.symbol == "SPY"
    assert position.spread == spread
    assert position.entry_credit == 0.30
    assert position.status == "open"


def test_paper_broker_rejects_market_orders():
    broker = PaperBroker(starting_cash=3000)

    with pytest.raises(PaperBrokerError, match="market orders"):
        broker.sell_credit_spread(
            symbol="SPY",
            spread=make_spread(),
            limit_credit=0.30,
            order_type="market",
        )


def test_paper_broker_rejects_non_positive_limit_credit():
    broker = PaperBroker(starting_cash=3000)

    with pytest.raises(PaperBrokerError, match="limit_credit"):
        broker.sell_credit_spread(symbol="SPY", spread=make_spread(), limit_credit=0)


def test_closing_position_records_realized_profit():
    broker = PaperBroker(starting_cash=3000)
    open_order = broker.sell_credit_spread(symbol="SPY", spread=make_spread(), limit_credit=0.30)
    position = broker.positions[0]

    close_order = broker.close_position(position_id=position.id, limit_debit=0.10)

    assert close_order.side == "buy_to_close"
    assert close_order.status == "filled"
    assert broker.positions[0].status == "closed"
    assert broker.positions[0].closing_order_id == close_order.id
    assert broker.positions[0].realized_pnl == 20
    assert broker.cash == 3020
    assert open_order.id != close_order.id


def test_closing_position_records_realized_loss():
    broker = PaperBroker(starting_cash=3000)
    broker.sell_credit_spread(symbol="SPY", spread=make_spread(), limit_credit=0.30)
    position = broker.positions[0]

    broker.close_position(position_id=position.id, limit_debit=0.60)

    assert broker.positions[0].realized_pnl == -30
    assert broker.cash == 2970


def test_cannot_close_unknown_position():
    broker = PaperBroker(starting_cash=3000)

    with pytest.raises(PaperBrokerError, match="position"):
        broker.close_position(position_id="missing", limit_debit=0.10)


def test_cannot_close_already_closed_position():
    broker = PaperBroker(starting_cash=3000)
    broker.sell_credit_spread(symbol="SPY", spread=make_spread(), limit_credit=0.30)
    position = broker.positions[0]
    broker.close_position(position_id=position.id, limit_debit=0.10)

    with pytest.raises(PaperBrokerError, match="already closed"):
        broker.close_position(position_id=position.id, limit_debit=0.10)


def test_open_risk_sums_only_open_positions():
    broker = PaperBroker(starting_cash=3000)
    broker.sell_credit_spread(symbol="SPY", spread=make_spread(), limit_credit=0.30)
    broker.sell_credit_spread(symbol="QQQ", spread=make_spread(), limit_credit=0.30)
    first_position = broker.positions[0]
    broker.close_position(position_id=first_position.id, limit_debit=0.10)

    assert broker.open_risk == 70
    assert broker.open_position_count == 1
