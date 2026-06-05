"""Poor Man's Covered Call (PMCC) tracker.

Tracks long LEAP call positions and the short calls sold against them,
computing running cost basis, breakeven price, and strike recommendations.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class LeapPosition:
    """A long LEAP call option that anchors a PMCC position."""

    id: str
    ticker: str
    date_purchased: date
    expiration: date
    strike: float
    premium_paid: float  # total debit paid (per-contract × 100 × contracts)
    contracts: int = 1
    current_price: float | None = None  # last known mark price (per-contract × 100)
    closed_date: date | None = None
    exit_price: float | None = None  # total credit received on close

    @property
    def is_open(self) -> bool:
        return self.closed_date is None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "ticker": self.ticker,
            "date_purchased": self.date_purchased.isoformat(),
            "expiration": self.expiration.isoformat(),
            "strike": self.strike,
            "premium_paid": self.premium_paid,
            "contracts": self.contracts,
            "current_price": self.current_price,
            "closed_date": self.closed_date.isoformat() if self.closed_date else None,
            "exit_price": self.exit_price,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "LeapPosition":
        return cls(
            id=d["id"],
            ticker=d["ticker"],
            date_purchased=date.fromisoformat(d["date_purchased"]),
            expiration=date.fromisoformat(d["expiration"]),
            strike=float(d["strike"]),
            premium_paid=float(d["premium_paid"]),
            contracts=int(d.get("contracts", 1)),
            current_price=float(d["current_price"]) if d.get("current_price") is not None else None,
            closed_date=date.fromisoformat(d["closed_date"]) if d.get("closed_date") else None,
            exit_price=float(d["exit_price"]) if d.get("exit_price") is not None else None,
        )


@dataclass
class ShortCall:
    """A short call sold against a LEAP as part of a PMCC."""

    id: str
    leap_id: str  # FK → LeapPosition.id
    ticker: str
    date_sold: date
    expiration: date
    strike: float
    premium_collected: float  # total credit received (per-contract × 100 × contracts)
    contracts: int = 1
    commission: float = 0.0
    exit_price: float | None = None  # total debit to close
    closed_date: date | None = None
    prob_otm: float | None = None  # optional: probability OTM at entry (0–1)

    @property
    def is_open(self) -> bool:
        return self.closed_date is None

    @property
    def net_premium(self) -> float:
        """Net credit after commission and any closing cost."""
        closing = self.exit_price or 0.0
        return self.premium_collected - closing - self.commission

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "leap_id": self.leap_id,
            "ticker": self.ticker,
            "date_sold": self.date_sold.isoformat(),
            "expiration": self.expiration.isoformat(),
            "strike": self.strike,
            "premium_collected": self.premium_collected,
            "contracts": self.contracts,
            "commission": self.commission,
            "exit_price": self.exit_price,
            "closed_date": self.closed_date.isoformat() if self.closed_date else None,
            "prob_otm": self.prob_otm,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ShortCall":
        return cls(
            id=d["id"],
            leap_id=d["leap_id"],
            ticker=d["ticker"],
            date_sold=date.fromisoformat(d["date_sold"]),
            expiration=date.fromisoformat(d["expiration"]),
            strike=float(d["strike"]),
            premium_collected=float(d["premium_collected"]),
            contracts=int(d.get("contracts", 1)),
            commission=float(d.get("commission", 0.0)),
            exit_price=float(d["exit_price"]) if d.get("exit_price") is not None else None,
            closed_date=date.fromisoformat(d["closed_date"]) if d.get("closed_date") else None,
            prob_otm=float(d["prob_otm"]) if d.get("prob_otm") is not None else None,
        )


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------


@dataclass
class PMCCSummary:
    """Computed analytics for one LEAP + its short calls."""

    leap: LeapPosition
    short_calls: list[ShortCall]

    # -- premium accounting --
    total_premium_collected: float  # sum of net_premium for all closed shorts
    open_short_premium: float  # premium from currently open short (unrealized)

    # -- cost basis --
    cost_basis_total: float  # leap cost − closed premium (total $)
    cost_basis_per_share: float  # cost_basis_total / contracts / 100

    # -- breakeven --
    breakeven_price: float  # long_strike + cost_basis_per_share

    # -- leap P/L --
    leap_unrealized_pnl: float | None  # current_price − premium_paid (None if no mark)
    leap_realized_pnl: float | None  # exit_price − premium_paid (None if still open)

    # -- strike guidance --
    min_safe_strike: float  # lowest strike to sell without risk of assignment loss
    suggested_strike_range: tuple[float, float]  # breakeven + 1 OTM buffer bands

    @property
    def total_profit(self) -> float:
        """Realized P/L: closed short premium + leap realized P/L (if closed)."""
        pnl = self.total_premium_collected
        if self.leap_realized_pnl is not None:
            pnl += self.leap_realized_pnl
        return pnl

    @property
    def open_short(self) -> ShortCall | None:
        opens = [s for s in self.short_calls if s.is_open]
        return opens[-1] if opens else None


def compute_summary(leap: LeapPosition, short_calls: list[ShortCall]) -> PMCCSummary:
    """Compute a full PMCCSummary for a given LEAP and its associated shorts."""
    my_shorts = [s for s in short_calls if s.leap_id == leap.id]

    closed_shorts = [s for s in my_shorts if not s.is_open]
    open_shorts = [s for s in my_shorts if s.is_open]

    total_premium_collected = sum(s.net_premium for s in closed_shorts)
    open_short_premium = sum(s.premium_collected for s in open_shorts)

    cost_basis_total = leap.premium_paid - total_premium_collected
    shares = leap.contracts * 100
    cost_basis_per_share = cost_basis_total / shares if shares > 0 else 0.0

    breakeven_price = leap.strike + cost_basis_per_share

    leap_unrealized_pnl: float | None = None
    if leap.current_price is not None and leap.is_open:
        leap_unrealized_pnl = leap.current_price - leap.premium_paid

    leap_realized_pnl: float | None = None
    if not leap.is_open and leap.exit_price is not None:
        leap_realized_pnl = leap.exit_price - leap.premium_paid

    # Safe to sell calls at or above the breakeven so that if assigned the
    # spread is profitable. Add a 1-strike ($1) buffer above breakeven for
    # comfort, and suggest selling up to $5 above that.
    min_safe_strike = round(breakeven_price + 0.50, 0)  # round up to nearest $1
    suggested_low = min_safe_strike
    suggested_high = suggested_low + 5.0

    return PMCCSummary(
        leap=leap,
        short_calls=my_shorts,
        total_premium_collected=total_premium_collected,
        open_short_premium=open_short_premium,
        cost_basis_total=cost_basis_total,
        cost_basis_per_share=cost_basis_per_share,
        breakeven_price=breakeven_price,
        leap_unrealized_pnl=leap_unrealized_pnl,
        leap_realized_pnl=leap_realized_pnl,
        min_safe_strike=min_safe_strike,
        suggested_strike_range=(suggested_low, suggested_high),
    )


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


DEFAULT_PMCC_PATH = Path("data/pmcc_positions.json")


@dataclass
class PMCCStore:
    """JSON-backed store for LEAP positions and short calls."""

    path: Path = field(default_factory=lambda: DEFAULT_PMCC_PATH)

    def _load_raw(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"leaps": [], "short_calls": []}
        return json.loads(self.path.read_text())

    def _save_raw(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2))

    def load_leaps(self) -> list[LeapPosition]:
        return [LeapPosition.from_dict(d) for d in self._load_raw()["leaps"]]

    def load_short_calls(self) -> list[ShortCall]:
        return [ShortCall.from_dict(d) for d in self._load_raw()["short_calls"]]

    def add_leap(self, leap: LeapPosition) -> None:
        data = self._load_raw()
        data["leaps"].append(leap.to_dict())
        self._save_raw(data)

    def update_leap(self, leap: LeapPosition) -> None:
        data = self._load_raw()
        data["leaps"] = [d if d["id"] != leap.id else leap.to_dict() for d in data["leaps"]]
        self._save_raw(data)

    def add_short_call(self, short: ShortCall) -> None:
        data = self._load_raw()
        data["short_calls"].append(short.to_dict())
        self._save_raw(data)

    def update_short_call(self, short: ShortCall) -> None:
        data = self._load_raw()
        data["short_calls"] = [
            d if d["id"] != short.id else short.to_dict() for d in data["short_calls"]
        ]
        self._save_raw(data)

    def get_leap(self, leap_id: str) -> LeapPosition | None:
        for leap in self.load_leaps():
            if leap.id == leap_id:
                return leap
        return None

    def get_short_call(self, short_id: str) -> ShortCall | None:
        for s in self.load_short_calls():
            if s.id == short_id:
                return s
        return None

    def summaries(self) -> list[PMCCSummary]:
        leaps = self.load_leaps()
        shorts = self.load_short_calls()
        return [compute_summary(leap, shorts) for leap in leaps]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def new_id() -> str:
    return str(uuid.uuid4())[:8]
