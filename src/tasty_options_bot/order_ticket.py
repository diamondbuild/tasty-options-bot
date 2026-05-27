from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tasty_options_bot.strategy import SpreadCandidate


class OrderTicketError(Exception):
    """Raised when a dry-run order ticket preview cannot be built safely."""


@dataclass(frozen=True)
class OrderTicketLeg:
    action: str
    option_symbol: str
    quantity: int


@dataclass(frozen=True)
class OpeningCreditSpreadTicket:
    strategy: str
    symbol: str
    order_type: str
    net_price_effect: str
    net_credit: float
    max_loss: float
    account_risk_percent: str
    safety_status: str
    submission_allowed: bool
    legs: list[OrderTicketLeg]


@dataclass(frozen=True)
class ClosingCreditSpreadTicket:
    strategy: str
    symbol: str
    order_type: str
    net_price_effect: str
    estimated_debit: float
    safety_status: str
    submission_allowed: bool
    legs: list[OrderTicketLeg]


def build_opening_credit_spread_ticket(
    candidate: SpreadCandidate, *, starting_equity: float
) -> OpeningCreditSpreadTicket:
    """Build a human-reviewable, non-submitting opening ticket preview.

    This intentionally does not match a broker payload yet; it is a dry-run
    review artifact that makes the exact legs and risk explicit before any
    future order-submission implementation is attempted.
    """
    if not candidate.short_option_symbol or not candidate.long_option_symbol:
        raise OrderTicketError("short and long option symbols are required for ticket preview")

    account_risk_percent = ""
    if starting_equity > 0:
        account_risk_percent = f"{candidate.spread.max_loss / starting_equity:.1%}"

    quantity = candidate.quantity
    return OpeningCreditSpreadTicket(
        strategy=candidate.strategy_label,
        symbol=candidate.symbol,
        order_type="limit",
        net_price_effect="credit",
        net_credit=round(candidate.credit, 2),
        max_loss=candidate.spread.max_loss,
        account_risk_percent=account_risk_percent,
        safety_status="preview_only_not_submitted",
        submission_allowed=False,
        legs=[
            OrderTicketLeg(
                action="sell_to_open",
                option_symbol=candidate.short_option_symbol,
                quantity=quantity,
            ),
            OrderTicketLeg(
                action="buy_to_open",
                option_symbol=candidate.long_option_symbol,
                quantity=quantity,
            ),
        ],
    )

def build_closing_credit_spread_ticket(
    *,
    symbol: str,
    strategy: str,
    short_option_symbol: str,
    long_option_symbol: str,
    quantity: int,
    estimated_debit: float,
) -> ClosingCreditSpreadTicket:
    """Build a non-submitting ticket preview for closing an existing credit spread."""
    if not short_option_symbol.strip() or not long_option_symbol.strip():
        raise OrderTicketError("short and long option symbols are required for close ticket preview")
    if quantity <= 0:
        raise OrderTicketError("quantity must be positive")
    if estimated_debit <= 0:
        raise OrderTicketError("estimated debit must be positive")

    return ClosingCreditSpreadTicket(
        strategy=strategy,
        symbol=symbol.upper(),
        order_type="limit",
        net_price_effect="debit",
        estimated_debit=round(estimated_debit, 2),
        safety_status="close_preview_only_not_submitted",
        submission_allowed=False,
        legs=[
            OrderTicketLeg(
                action="buy_to_close",
                option_symbol=short_option_symbol,
                quantity=quantity,
            ),
            OrderTicketLeg(
                action="sell_to_close",
                option_symbol=long_option_symbol,
                quantity=quantity,
            ),
        ],
    )

def build_tastytrade_opening_order_payload(ticket: OpeningCreditSpreadTicket) -> dict[str, Any]:
    """Build a deterministic tastytrade-style payload for review only.

    The returned dict intentionally has no endpoint/account/submission fields.
    It is suitable for validation, logs, and human review before a separate
    future broker-submit layer is written.
    """
    if ticket.submission_allowed or ticket.safety_status != "preview_only_not_submitted":
        raise OrderTicketError("only preview-only tickets can be converted to payload previews")
    if ticket.order_type != "limit":
        raise OrderTicketError("only limit order ticket previews are supported")
    if ticket.net_price_effect != "credit":
        raise OrderTicketError("only credit order ticket previews are supported")
    if ticket.net_credit <= 0:
        raise OrderTicketError("net credit must be positive")
    if len(ticket.legs) != 2:
        raise OrderTicketError("opening credit spread payload requires exactly two legs")

    action_map = {
        "sell_to_open": "Sell to Open",
        "buy_to_open": "Buy to Open",
    }
    legs: list[dict[str, Any]] = []
    for leg in ticket.legs:
        if leg.action not in action_map:
            raise OrderTicketError(f"unsupported leg action: {leg.action}")
        if not leg.option_symbol:
            raise OrderTicketError("all payload legs require option symbols")
        if leg.quantity <= 0:
            raise OrderTicketError("all payload legs require positive quantity")
        legs.append(
            {
                "action": action_map[leg.action],
                "instrument-type": "Equity Option",
                "symbol": leg.option_symbol,
                "quantity": leg.quantity,
            }
        )

    payload: dict[str, Any] = {
        "order-type": "Limit",
        "time-in-force": "Day",
        "price-effect": "Credit",
        "price": f"{ticket.net_credit:.2f}",
        "source": "tasty-options-bot-preview",
        "legs": legs,
    }
    validate_tastytrade_order_payload(payload)
    return payload


def validate_tastytrade_order_payload(payload: dict[str, Any]) -> None:
    if payload.get("order-type") != "Limit":
        raise OrderTicketError("tastytrade payload preview must be a Limit order")
    if payload.get("time-in-force") != "Day":
        raise OrderTicketError("tastytrade payload preview must use Day time-in-force")
    if payload.get("price-effect") != "Credit":
        raise OrderTicketError("tastytrade payload preview must use Credit price effect")
    try:
        price = float(payload.get("price", 0))
    except (TypeError, ValueError) as exc:
        raise OrderTicketError("tastytrade payload preview price must be numeric") from exc
    if price <= 0:
        raise OrderTicketError("tastytrade payload preview price must be positive")

    legs = payload.get("legs")
    if not isinstance(legs, list) or len(legs) != 2:
        raise OrderTicketError("tastytrade payload preview requires exactly two legs")
    expected_actions = ["Sell to Open", "Buy to Open"]
    for leg, expected_action in zip(legs, expected_actions, strict=True):
        if leg.get("action") != expected_action:
            raise OrderTicketError("tastytrade payload preview legs must be sell-open then buy-open")
        if leg.get("instrument-type") != "Equity Option":
            raise OrderTicketError("tastytrade payload preview legs must be equity options")
        if not leg.get("symbol"):
            raise OrderTicketError("tastytrade payload preview legs require symbols")
        if leg.get("quantity") != 1:
            raise OrderTicketError("tastytrade payload preview currently requires one-lot legs")


def build_tastytrade_closing_order_payload(ticket: ClosingCreditSpreadTicket) -> dict[str, Any]:
    """Build a deterministic tastytrade-style close payload for review only."""
    if ticket.submission_allowed or ticket.safety_status != "close_preview_only_not_submitted":
        raise OrderTicketError("only close preview-only tickets can be converted to payload previews")
    if ticket.order_type != "limit":
        raise OrderTicketError("only limit close ticket previews are supported")
    if ticket.net_price_effect != "debit":
        raise OrderTicketError("only debit close ticket previews are supported")
    if ticket.estimated_debit <= 0:
        raise OrderTicketError("estimated debit must be positive")
    if len(ticket.legs) != 2:
        raise OrderTicketError("closing credit spread payload requires exactly two legs")

    action_map = {
        "buy_to_close": "Buy to Close",
        "sell_to_close": "Sell to Close",
    }
    legs: list[dict[str, Any]] = []
    for leg in ticket.legs:
        if leg.action not in action_map:
            raise OrderTicketError(f"unsupported leg action: {leg.action}")
        if not leg.option_symbol:
            raise OrderTicketError("all payload legs require option symbols")
        if leg.quantity <= 0:
            raise OrderTicketError("all payload legs require positive quantity")
        legs.append(
            {
                "action": action_map[leg.action],
                "instrument-type": "Equity Option",
                "symbol": leg.option_symbol,
                "quantity": leg.quantity,
            }
        )

    payload: dict[str, Any] = {
        "order-type": "Limit",
        "time-in-force": "Day",
        "price-effect": "Debit",
        "price": f"{ticket.estimated_debit:.2f}",
        "source": "tasty-options-bot-close-preview",
        "legs": legs,
    }
    validate_tastytrade_closing_order_payload(payload)
    return payload


def validate_tastytrade_closing_order_payload(payload: dict[str, Any]) -> None:
    if payload.get("order-type") != "Limit":
        raise OrderTicketError("tastytrade closing payload preview must be a Limit order")
    if payload.get("time-in-force") != "Day":
        raise OrderTicketError("tastytrade closing payload preview must use Day time-in-force")
    if payload.get("price-effect") != "Debit":
        raise OrderTicketError("tastytrade closing payload preview must use Debit price effect")
    try:
        price = float(payload.get("price", 0))
    except (TypeError, ValueError) as exc:
        raise OrderTicketError("tastytrade closing payload preview price must be numeric") from exc
    if price <= 0:
        raise OrderTicketError("tastytrade closing payload preview price must be positive")

    legs = payload.get("legs")
    if not isinstance(legs, list) or len(legs) != 2:
        raise OrderTicketError("tastytrade closing payload preview requires exactly two legs")
    expected_actions = ["Buy to Close", "Sell to Close"]
    for leg, expected_action in zip(legs, expected_actions, strict=True):
        if leg.get("action") != expected_action:
            raise OrderTicketError("tastytrade closing payload preview legs must be buy-close then sell-close")
        if leg.get("instrument-type") != "Equity Option":
            raise OrderTicketError("tastytrade closing payload preview legs must be equity options")
        if not leg.get("symbol"):
            raise OrderTicketError("tastytrade closing payload preview legs require symbols")
        if leg.get("quantity") != 1:
            raise OrderTicketError("tastytrade closing payload preview currently requires one-lot legs")
