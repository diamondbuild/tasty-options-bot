from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tasty_options_bot.yolo.models import YoloCandidate


class YoloTicketError(Exception):
    """Raised when a YOLO opening ticket preview cannot be built safely."""


@dataclass(frozen=True)
class YoloTicketLeg:
    action: str
    option_symbol: str
    quantity: int


@dataclass(frozen=True)
class YoloOpeningTicket:
    strategy: str
    underlying_symbol: str
    order_type: str
    net_price_effect: str
    limit_price: float
    total_cost: float
    breakeven: float
    safety_status: str
    submission_allowed: bool
    legs: list[YoloTicketLeg]


def build_yolo_opening_ticket(candidate: YoloCandidate) -> YoloOpeningTicket:
    """Build a human-reviewable, non-submitting opening ticket preview."""
    if not candidate.option_symbol.strip():
        raise YoloTicketError("option symbol is required for ticket preview")
    if candidate.contracts <= 0:
        raise YoloTicketError("contracts must be positive")
    if candidate.limit_price <= 0:
        raise YoloTicketError("limit price must be positive")

    return YoloOpeningTicket(
        strategy=candidate.strategy_label,
        underlying_symbol=candidate.underlying_symbol,
        order_type="limit",
        net_price_effect="debit",
        limit_price=round(candidate.limit_price, 2),
        total_cost=round(candidate.total_cost, 2),
        breakeven=candidate.breakeven,
        safety_status="preview_only_not_submitted",
        submission_allowed=False,
        legs=[
            YoloTicketLeg(
                action="buy_to_open",
                option_symbol=candidate.option_symbol,
                quantity=candidate.contracts,
            )
        ],
    )


def build_yolo_opening_payload_preview(ticket: YoloOpeningTicket) -> dict[str, Any]:
    """Build a tastytrade-style payload for review only — never submitted.

    Has no endpoint/account/submission fields; suitable for validation, logs,
    and human review before the separate gated submit layer is used.
    """
    if ticket.submission_allowed or ticket.safety_status != "preview_only_not_submitted":
        raise YoloTicketError("only preview-only tickets can be converted to payload previews")
    if ticket.order_type != "limit":
        raise YoloTicketError("only limit order ticket previews are supported")
    if ticket.net_price_effect != "debit":
        raise YoloTicketError("YOLO opening orders must be debit (long options only)")
    if len(ticket.legs) != 1:
        raise YoloTicketError("YOLO opening payload requires exactly one leg")

    leg = ticket.legs[0]
    if leg.action != "buy_to_open":
        raise YoloTicketError("YOLO opening leg must be buy_to_open")
    if not leg.option_symbol or leg.quantity <= 0:
        raise YoloTicketError("payload leg requires symbol and positive quantity")

    return {
        "order-type": "Limit",
        "time-in-force": "Day",
        "price-effect": "Debit",
        "price": f"{ticket.limit_price:.2f}",
        "source": "tasty-options-bot-yolo-preview",
        "legs": [
            {
                "action": "Buy to Open",
                "instrument-type": "Equity Option",
                "symbol": leg.option_symbol,
                "quantity": leg.quantity,
            }
        ],
    }
