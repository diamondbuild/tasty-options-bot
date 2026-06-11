from datetime import date

import pytest

from tasty_options_bot.yolo.models import YoloCandidate
from tasty_options_bot.yolo.tickets import (
    YoloTicketError,
    build_yolo_opening_ticket,
    build_yolo_opening_payload_preview,
)


def make_candidate(**overrides) -> YoloCandidate:
    base = dict(
        underlying_symbol="SMCI",
        option_symbol="SMCI  260618C00030000",
        option_type="call",
        strike=30.0,
        expiration=date(2026, 6, 18),
        dte=7,
        delta=0.42,
        bid=1.30,
        ask=1.40,
        contracts=7,
        limit_price=1.40,
        total_cost=980.0,
        breakeven=31.40,
    )
    base.update(overrides)
    return YoloCandidate(**base)


def test_opening_ticket_is_preview_only_with_exact_symbol():
    ticket = build_yolo_opening_ticket(make_candidate())
    assert ticket.strategy == "Long Call (YOLO)"
    assert ticket.safety_status == "preview_only_not_submitted"
    assert ticket.submission_allowed is False
    assert ticket.order_type == "limit"
    assert ticket.net_price_effect == "debit"
    assert ticket.limit_price == 1.40
    assert ticket.total_cost == 980.0
    assert len(ticket.legs) == 1
    leg = ticket.legs[0]
    assert leg.action == "buy_to_open"
    assert leg.option_symbol == "SMCI  260618C00030000"
    assert leg.quantity == 7


def test_payload_preview_shape():
    payload = build_yolo_opening_payload_preview(build_yolo_opening_ticket(make_candidate()))
    assert payload["order-type"] == "Limit"
    assert payload["time-in-force"] == "Day"
    assert payload["price-effect"] == "Debit"
    assert payload["price"] == "1.40"
    assert payload["legs"] == [
        {
            "action": "Buy to Open",
            "instrument-type": "Equity Option",
            "symbol": "SMCI  260618C00030000",
            "quantity": 7,
        }
    ]
    assert "account" not in payload


def test_ticket_rejects_bad_inputs():
    with pytest.raises(YoloTicketError):
        build_yolo_opening_ticket(make_candidate(option_symbol=""))
    with pytest.raises(YoloTicketError):
        build_yolo_opening_ticket(make_candidate(contracts=0))
    with pytest.raises(YoloTicketError):
        build_yolo_opening_ticket(make_candidate(limit_price=0.0))
