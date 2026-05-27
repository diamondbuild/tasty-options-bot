from __future__ import annotations

from dataclasses import dataclass, replace

from tasty_options_bot.spreads import CreditSpread


class PaperBrokerError(Exception):
    """Raised when the paper broker rejects an operation."""


@dataclass(frozen=True)
class PaperOrder:
    id: str
    symbol: str
    side: str
    spread: CreditSpread
    order_type: str
    limit_price: float
    status: str


@dataclass(frozen=True)
class PaperPosition:
    id: str
    symbol: str
    spread: CreditSpread
    entry_credit: float
    status: str
    opening_order_id: str
    closing_order_id: str | None = None
    exit_debit: float | None = None
    realized_pnl: float | None = None


class PaperBroker:
    """In-memory broker for deterministic dry runs.

    This class never sends network requests and cannot place real orders. It is
    intentionally optimistic: valid limit orders fill immediately at the given
    limit price so strategy/risk plumbing can be tested deterministically.
    """

    is_live = False

    def __init__(self, starting_cash: float) -> None:
        self.cash = float(starting_cash)
        self.orders: list[PaperOrder] = []
        self.positions: list[PaperPosition] = []
        self._next_order_id = 1
        self._next_position_id = 1

    @property
    def open_positions(self) -> list[PaperPosition]:
        return [position for position in self.positions if position.status == "open"]

    @property
    def open_position_count(self) -> int:
        return len(self.open_positions)

    @property
    def open_risk(self) -> float:
        return round(sum(position.spread.max_loss for position in self.open_positions), 2)

    def sell_credit_spread(
        self,
        *,
        symbol: str,
        spread: CreditSpread,
        limit_credit: float,
        order_type: str = "limit",
    ) -> PaperOrder:
        if order_type != "limit":
            raise PaperBrokerError("paper broker rejects market orders")
        if limit_credit <= 0:
            raise PaperBrokerError("limit_credit must be positive")

        order = PaperOrder(
            id=self._new_order_id(),
            symbol=symbol,
            side="sell_to_open",
            spread=spread,
            order_type="limit",
            limit_price=round(limit_credit, 2),
            status="filled",
        )
        self.orders.append(order)
        self.cash = round(self.cash + spread.max_profit, 2)

        position = PaperPosition(
            id=self._new_position_id(),
            symbol=symbol,
            spread=spread,
            entry_credit=round(limit_credit, 2),
            status="open",
            opening_order_id=order.id,
        )
        self.positions.append(position)
        return order

    def close_position(
        self,
        *,
        position_id: str,
        limit_debit: float,
        order_type: str = "limit",
    ) -> PaperOrder:
        if order_type != "limit":
            raise PaperBrokerError("paper broker rejects market orders")
        if limit_debit < 0:
            raise PaperBrokerError("limit_debit must be non-negative")

        index, position = self._find_position(position_id)
        if position.status == "closed":
            raise PaperBrokerError("position is already closed")

        order = PaperOrder(
            id=self._new_order_id(),
            symbol=position.symbol,
            side="buy_to_close",
            spread=position.spread,
            order_type="limit",
            limit_price=round(limit_debit, 2),
            status="filled",
        )
        self.orders.append(order)

        close_cost = round(limit_debit * position.spread.multiplier * position.spread.quantity, 2)
        self.cash = round(self.cash - close_cost, 2)
        realized_pnl = round(
            (position.entry_credit - limit_debit)
            * position.spread.multiplier
            * position.spread.quantity,
            2,
        )
        self.positions[index] = replace(
            position,
            status="closed",
            closing_order_id=order.id,
            exit_debit=round(limit_debit, 2),
            realized_pnl=realized_pnl,
        )
        return order

    def _find_position(self, position_id: str) -> tuple[int, PaperPosition]:
        for index, position in enumerate(self.positions):
            if position.id == position_id:
                return index, position
        raise PaperBrokerError(f"position not found: {position_id}")

    def _new_order_id(self) -> str:
        order_id = f"paper-order-{self._next_order_id}"
        self._next_order_id += 1
        return order_id

    def _new_position_id(self) -> str:
        position_id = f"paper-position-{self._next_position_id}"
        self._next_position_id += 1
        return position_id
