"""Tests for the PMCC tracker module."""

import json
import tempfile
from datetime import date
from pathlib import Path

import pytest

from tasty_options_bot.pmcc import (
    LeapPosition,
    PMCCStore,
    ShortCall,
    compute_summary,
    new_id,
)


def make_leap(**kwargs) -> LeapPosition:
    defaults = dict(
        id="abc12345",
        ticker="T",
        date_purchased=date(2025, 1, 28),
        expiration=date(2026, 1, 20),
        strike=20.0,
        premium_paid=967.0,
        contracts=2,
    )
    defaults.update(kwargs)
    return LeapPosition(**defaults)


def make_short(leap_id: str, **kwargs) -> ShortCall:
    defaults = dict(
        id="sc000001",
        leap_id=leap_id,
        ticker="T",
        date_sold=date(2025, 1, 28),
        expiration=date(2025, 2, 19),
        strike=29.0,
        premium_collected=110.0,
        contracts=2,
    )
    defaults.update(kwargs)
    return ShortCall(**defaults)


# ---------------------------------------------------------------------------
# LeapPosition
# ---------------------------------------------------------------------------


def test_leap_is_open():
    leap = make_leap()
    assert leap.is_open is True


def test_leap_is_closed():
    leap = make_leap(closed_date=date(2025, 3, 8), exit_price=1100.0)
    assert leap.is_open is False


def test_leap_round_trip():
    leap = make_leap()
    assert LeapPosition.from_dict(leap.to_dict()) == leap


def test_leap_round_trip_with_close():
    leap = make_leap(closed_date=date(2025, 6, 1), exit_price=800.0, current_price=850.0)
    assert LeapPosition.from_dict(leap.to_dict()) == leap


# ---------------------------------------------------------------------------
# ShortCall
# ---------------------------------------------------------------------------


def test_short_call_is_open():
    sc = make_short("abc12345")
    assert sc.is_open is True


def test_short_call_net_premium_open():
    sc = make_short("abc12345", premium_collected=110.0, commission=1.30)
    # no exit_price yet, so net = collected - commission
    assert sc.net_premium == pytest.approx(110.0 - 1.30)


def test_short_call_net_premium_closed():
    sc = make_short("abc12345", premium_collected=110.0, exit_price=20.0, commission=1.30)
    assert sc.net_premium == pytest.approx(110.0 - 20.0 - 1.30)


def test_short_call_round_trip():
    sc = make_short("abc12345", closed_date=date(2025, 3, 10), exit_price=5.0, prob_otm=0.75)
    assert ShortCall.from_dict(sc.to_dict()) == sc


# ---------------------------------------------------------------------------
# compute_summary — cost basis & breakeven
# ---------------------------------------------------------------------------


def test_summary_no_shorts():
    leap = make_leap(premium_paid=967.0, strike=20.0, contracts=2)
    summary = compute_summary(leap, [])
    assert summary.total_premium_collected == 0.0
    # cost basis = 967 / (2 * 100) = $4.835/share
    assert summary.cost_basis_per_share == pytest.approx(967.0 / 200)
    assert summary.breakeven_price == pytest.approx(20.0 + 967.0 / 200)


def test_summary_with_closed_short():
    leap = make_leap(premium_paid=967.0, strike=20.0, contracts=2)
    sc = make_short(
        leap.id,
        premium_collected=110.0,
        exit_price=10.0,
        closed_date=date(2025, 3, 8),
        commission=1.30,
    )
    summary = compute_summary(leap, [sc])
    net = 110.0 - 10.0 - 1.30  # 98.70
    assert summary.total_premium_collected == pytest.approx(net)
    expected_cb_total = 967.0 - net
    assert summary.cost_basis_total == pytest.approx(expected_cb_total)
    assert summary.cost_basis_per_share == pytest.approx(expected_cb_total / 200)
    assert summary.breakeven_price == pytest.approx(20.0 + expected_cb_total / 200)


def test_summary_open_short_does_not_count_as_collected():
    leap = make_leap(premium_paid=967.0, strike=20.0, contracts=2)
    sc = make_short(leap.id, premium_collected=110.0)  # open, no exit_price
    summary = compute_summary(leap, [sc])
    # Open short premium should NOT reduce cost basis
    assert summary.total_premium_collected == 0.0
    assert summary.open_short_premium == pytest.approx(110.0)
    assert summary.cost_basis_total == pytest.approx(967.0)


def test_summary_ignores_unrelated_shorts():
    leap = make_leap(id="leap-1", premium_paid=967.0, strike=20.0, contracts=2)
    other_leap = make_leap(id="leap-2")
    sc_mine = make_short("leap-1", premium_collected=100.0, exit_price=5.0, closed_date=date(2025, 3, 1))
    sc_other = make_short("leap-2", premium_collected=999.0, exit_price=1.0, closed_date=date(2025, 3, 1))
    summary = compute_summary(leap, [sc_mine, sc_other])
    assert summary.total_premium_collected == pytest.approx(95.0)


def test_summary_unrealized_pnl():
    leap = make_leap(premium_paid=967.0, current_price=1100.0)
    summary = compute_summary(leap, [])
    assert summary.leap_unrealized_pnl == pytest.approx(1100.0 - 967.0)


def test_summary_no_unrealized_pnl_when_no_mark():
    leap = make_leap(premium_paid=967.0, current_price=None)
    summary = compute_summary(leap, [])
    assert summary.leap_unrealized_pnl is None


def test_summary_realized_pnl_when_closed():
    leap = make_leap(premium_paid=967.0, exit_price=800.0, closed_date=date(2025, 6, 1))
    summary = compute_summary(leap, [])
    assert summary.leap_realized_pnl == pytest.approx(800.0 - 967.0)


def test_summary_suggested_strike_above_breakeven():
    leap = make_leap(premium_paid=967.0, strike=20.0, contracts=2)
    summary = compute_summary(leap, [])
    assert summary.suggested_strike_range[0] >= summary.breakeven_price
    assert summary.suggested_strike_range[1] > summary.suggested_strike_range[0]


def test_summary_open_short_accessor():
    leap = make_leap()
    sc_closed = make_short(leap.id, id="sc-1", premium_collected=100.0, exit_price=5.0, closed_date=date(2025, 2, 1))
    sc_open = make_short(leap.id, id="sc-2", premium_collected=80.0)
    summary = compute_summary(leap, [sc_closed, sc_open])
    assert summary.open_short is not None
    assert summary.open_short.id == "sc-2"


# ---------------------------------------------------------------------------
# PMCCStore persistence
# ---------------------------------------------------------------------------


def test_store_add_and_load_leap():
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        path = Path(f.name)
    # Start with empty file deleted
    path.unlink()

    store = PMCCStore(path=path)
    leap = make_leap()
    store.add_leap(leap)

    loaded = store.load_leaps()
    assert len(loaded) == 1
    assert loaded[0] == leap


def test_store_add_and_load_short():
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        path = Path(f.name)
    path.unlink()

    store = PMCCStore(path=path)
    leap = make_leap()
    store.add_leap(leap)
    sc = make_short(leap.id)
    store.add_short_call(sc)

    loaded = store.load_short_calls()
    assert len(loaded) == 1
    assert loaded[0] == sc


def test_store_update_leap():
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        path = Path(f.name)
    path.unlink()

    store = PMCCStore(path=path)
    leap = make_leap()
    store.add_leap(leap)
    leap.closed_date = date(2025, 6, 1)
    leap.exit_price = 800.0
    store.update_leap(leap)

    loaded = store.get_leap(leap.id)
    assert loaded is not None
    assert loaded.closed_date == date(2025, 6, 1)
    assert loaded.exit_price == 800.0


def test_store_update_short_call():
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        path = Path(f.name)
    path.unlink()

    store = PMCCStore(path=path)
    leap = make_leap()
    store.add_leap(leap)
    sc = make_short(leap.id)
    store.add_short_call(sc)

    sc.exit_price = 5.0
    sc.closed_date = date(2025, 3, 10)
    store.update_short_call(sc)

    loaded = store.get_short_call(sc.id)
    assert loaded is not None
    assert loaded.exit_price == 5.0
    assert loaded.closed_date == date(2025, 3, 10)


def test_store_summaries():
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        path = Path(f.name)
    path.unlink()

    store = PMCCStore(path=path)
    leap = make_leap(premium_paid=967.0, strike=20.0, contracts=2)
    sc = make_short(leap.id, premium_collected=110.0, exit_price=10.0, closed_date=date(2025, 3, 8))
    store.add_leap(leap)
    store.add_short_call(sc)

    summaries = store.summaries()
    assert len(summaries) == 1
    assert summaries[0].total_premium_collected == pytest.approx(100.0)


def test_new_id_unique():
    ids = {new_id() for _ in range(100)}
    assert len(ids) == 100
