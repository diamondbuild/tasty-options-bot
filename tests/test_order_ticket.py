import pytest

from tasty_options_bot.order_ticket import (
    OrderTicketError,
    build_closing_credit_spread_ticket,
    build_opening_credit_spread_ticket,
    build_tastytrade_closing_order_payload,
    build_tastytrade_opening_order_payload,
    validate_tastytrade_closing_order_payload,
    validate_tastytrade_order_payload,
)
from tasty_options_bot.strategy import SpreadCandidate


def make_candidate(**overrides):
    data = {
        "symbol": "SPY",
        "expiration": "2026-07-16",
        "dte": 40,
        "short_strike": 732.0,
        "long_strike": 727.0,
        "short_delta": -0.30,
        "credit": 0.99,
        "option_type": "put",
        "short_option_symbol": "SPY 260716P00732000",
        "long_option_symbol": "SPY 260716P00727000",
    }
    data.update(overrides)
    return SpreadCandidate(**data)


def test_builds_preview_only_opening_credit_spread_ticket():
    ticket = build_opening_credit_spread_ticket(make_candidate(), starting_equity=3000)

    assert ticket.strategy == "Put Credit Spread"
    assert ticket.symbol == "SPY"
    assert ticket.order_type == "limit"
    assert ticket.net_price_effect == "credit"
    assert ticket.net_credit == 0.99
    assert ticket.max_loss == 401.0
    assert ticket.account_risk_percent == "13.4%"
    assert ticket.safety_status == "preview_only_not_submitted"
    assert ticket.submission_allowed is False
    assert ticket.legs[0].action == "sell_to_open"
    assert ticket.legs[0].option_symbol == "SPY 260716P00732000"
    assert ticket.legs[0].quantity == 1
    assert ticket.legs[1].action == "buy_to_open"
    assert ticket.legs[1].option_symbol == "SPY 260716P00727000"
    assert ticket.legs[1].quantity == 1


def test_order_ticket_preview_requires_exact_leg_symbols():
    with pytest.raises(OrderTicketError, match="option symbols"):
        build_opening_credit_spread_ticket(
            make_candidate(short_option_symbol="", long_option_symbol="SPY 260716P00727000"),
            starting_equity=3000,
        )


def test_builds_tastytrade_style_opening_order_payload_without_submission_fields():
    ticket = build_opening_credit_spread_ticket(make_candidate(), starting_equity=3000)

    payload = build_tastytrade_opening_order_payload(ticket)

    assert payload == {
        "order-type": "Limit",
        "time-in-force": "Day",
        "price-effect": "Credit",
        "price": "0.99",
        "source": "tasty-options-bot-preview",
        "legs": [
            {
                "action": "Sell to Open",
                "instrument-type": "Equity Option",
                "symbol": "SPY 260716P00732000",
                "quantity": 1,
            },
            {
                "action": "Buy to Open",
                "instrument-type": "Equity Option",
                "symbol": "SPY 260716P00727000",
                "quantity": 1,
            },
        ],
    }


def test_tastytrade_order_payload_validation_rejects_unsafe_or_ambiguous_payloads():
    valid_payload = build_tastytrade_opening_order_payload(
        build_opening_credit_spread_ticket(make_candidate(), starting_equity=3000)
    )
    valid_payload["order-type"] = "Market"

    with pytest.raises(OrderTicketError, match="Limit"):
        validate_tastytrade_order_payload(valid_payload)


def test_tastytrade_order_payload_builder_refuses_submittable_tickets():
    ticket = build_opening_credit_spread_ticket(make_candidate(), starting_equity=3000)
    unsafe_ticket = ticket.__class__(
        strategy=ticket.strategy,
        symbol=ticket.symbol,
        order_type=ticket.order_type,
        net_price_effect=ticket.net_price_effect,
        net_credit=ticket.net_credit,
        max_loss=ticket.max_loss,
        account_risk_percent=ticket.account_risk_percent,
        safety_status="approved_for_submission",
        submission_allowed=True,
        legs=ticket.legs,
    )

    with pytest.raises(OrderTicketError, match="preview-only"):
        build_tastytrade_opening_order_payload(unsafe_ticket)


def test_builds_preview_only_closing_credit_spread_ticket():
    ticket = build_closing_credit_spread_ticket(
        symbol="SPY",
        strategy="Put Credit Spread",
        short_option_symbol="SPY   260626P00732000",
        long_option_symbol="SPY   260626P00727000",
        quantity=1,
        estimated_debit=1.06,
    )

    assert ticket.strategy == "Put Credit Spread"
    assert ticket.symbol == "SPY"
    assert ticket.order_type == "limit"
    assert ticket.net_price_effect == "debit"
    assert ticket.estimated_debit == 1.06
    assert ticket.safety_status == "close_preview_only_not_submitted"
    assert ticket.submission_allowed is False
    assert ticket.legs[0].action == "buy_to_close"
    assert ticket.legs[0].option_symbol == "SPY   260626P00732000"
    assert ticket.legs[0].quantity == 1
    assert ticket.legs[1].action == "sell_to_close"
    assert ticket.legs[1].option_symbol == "SPY   260626P00727000"
    assert ticket.legs[1].quantity == 1


def test_closing_credit_spread_ticket_requires_symbols_and_positive_debit():
    with pytest.raises(OrderTicketError, match="option symbols"):
        build_closing_credit_spread_ticket(
            symbol="SPY",
            strategy="Put Credit Spread",
            short_option_symbol="",
            long_option_symbol="SPY   260626P00727000",
            quantity=1,
            estimated_debit=1.06,
        )

    with pytest.raises(OrderTicketError, match="positive"):
        build_closing_credit_spread_ticket(
            symbol="SPY",
            strategy="Put Credit Spread",
            short_option_symbol="SPY   260626P00732000",
            long_option_symbol="SPY   260626P00727000",
            quantity=1,
            estimated_debit=0,
        )


def test_builds_tastytrade_style_closing_order_payload_without_submission_fields():
    ticket = build_closing_credit_spread_ticket(
        symbol="SPY",
        strategy="Put Credit Spread",
        short_option_symbol="SPY   260626P00732000",
        long_option_symbol="SPY   260626P00727000",
        quantity=1,
        estimated_debit=1.06,
    )

    payload = build_tastytrade_closing_order_payload(ticket)

    assert payload == {
        "order-type": "Limit",
        "time-in-force": "Day",
        "price-effect": "Debit",
        "price": "1.06",
        "source": "tasty-options-bot-close-preview",
        "legs": [
            {
                "action": "Buy to Close",
                "instrument-type": "Equity Option",
                "symbol": "SPY   260626P00732000",
                "quantity": 1,
            },
            {
                "action": "Sell to Close",
                "instrument-type": "Equity Option",
                "symbol": "SPY   260626P00727000",
                "quantity": 1,
            },
        ],
    }


def test_tastytrade_closing_payload_validation_rejects_wrong_leg_order():
    ticket = build_closing_credit_spread_ticket(
        symbol="SPY",
        strategy="Put Credit Spread",
        short_option_symbol="SPY   260626P00732000",
        long_option_symbol="SPY   260626P00727000",
        quantity=1,
        estimated_debit=1.06,
    )
    payload = build_tastytrade_closing_order_payload(ticket)
    payload["legs"][0]["action"] = "Sell to Close"

    with pytest.raises(OrderTicketError, match="buy-close then sell-close"):
        validate_tastytrade_closing_order_payload(payload)
