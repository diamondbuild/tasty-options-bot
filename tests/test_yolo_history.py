from datetime import datetime, timezone

from tasty_options_bot.yolo.history import (
    TradeFill,
    build_trade_records,
    parse_broker_transactions,
)


def make_txn(
    *,
    executed_at: str = "2026-06-11T14:48:05.861Z",
    action: str = "Buy to Open",
    symbol: str = "SMCI  260618C00030000",
    quantity: str = "9.0",
    price: str = "1.43",
    value: str = "1287.0",
    value_effect: str = "Debit",
    commission: str = "9.0",
    regulatory_fees: str = "0.21",
    clearing_fees: str = "0.9",
    order_id: int = 475141170,
    transaction_type: str = "Trade",
) -> dict:
    return {
        "executed-at": executed_at,
        "transaction-type": transaction_type,
        "action": action,
        "symbol": symbol,
        "quantity": quantity,
        "price": price,
        "value": value,
        "value-effect": value_effect,
        "commission": commission,
        "regulatory-fees": regulatory_fees,
        "clearing-fees": clearing_fees,
        "order-id": order_id,
    }


def test_parse_skips_non_trade_transactions():
    raw = [
        make_txn(),
        make_txn(transaction_type="Money Movement", action=""),
    ]
    fills = parse_broker_transactions(raw)
    assert len(fills) == 1
    assert fills[0].action == "Buy to Open"


def test_parse_extracts_fees_and_times():
    fills = parse_broker_transactions([make_txn()])
    fill = fills[0]
    assert fill.option_symbol == "SMCI  260618C00030000"
    assert fill.quantity == 9
    assert fill.price == 1.43
    assert fill.fees == 10.11  # 9.00 commission + 0.21 reg + 0.90 clearing
    assert fill.executed_at == datetime(
        2026, 6, 11, 14, 48, 5, 861000, tzinfo=timezone.utc
    )


def test_closed_round_trip_from_real_smci_trade():
    """Reconstruct the actual first SMCI YOLO trade and verify net P/L math."""
    raw = [
        # open in two fills on one order
        make_txn(quantity="7.0", value="1001.0", commission="7.0",
                 regulatory_fees="0.16", clearing_fees="0.7"),
        make_txn(quantity="2.0", value="286.0", commission="2.0",
                 regulatory_fees="0.05", clearing_fees="0.2"),
        # close in two fills on one order
        make_txn(executed_at="2026-06-11T18:06:50.444Z", action="Sell to Close",
                 quantity="5.0", price="1.76", value="880.0", value_effect="Credit",
                 commission="0.0", regulatory_fees="0.146", clearing_fees="0.5",
                 order_id=475297676),
        make_txn(executed_at="2026-06-11T18:06:50.445Z", action="Sell to Close",
                 quantity="4.0", price="1.76", value="704.0", value_effect="Credit",
                 commission="0.0", regulatory_fees="0.123", clearing_fees="0.4",
                 order_id=475297676),
    ]
    records = build_trade_records(parse_broker_transactions(raw))
    assert len(records) == 1
    record = records[0]
    assert record.status == "CLOSED"
    assert record.option_symbol == "SMCI  260618C00030000"
    assert record.underlying_symbol == "SMCI"
    assert record.bought_quantity == 9
    assert record.sold_quantity == 9
    assert record.open_quantity == 0
    assert record.avg_entry_price == 1.43
    assert record.avg_exit_price == 1.76
    assert record.gross_realized == 297.0  # (1.76 - 1.43) * 100 * 9
    assert record.total_fees == 11.28  # 9.00 + 0.21 + 0.90 + 0.269 + 0.90
    assert record.net_realized == 285.72
    assert record.is_win is True


def test_open_position_has_no_realized_pnl():
    raw = [
        make_txn(symbol="SMCI  260821C00033000", quantity="2.0", price="4.5",
                 value="900.0", commission="2.0", regulatory_fees="0.05",
                 clearing_fees="0.2"),
    ]
    records = build_trade_records(parse_broker_transactions(raw))
    assert len(records) == 1
    record = records[0]
    assert record.status == "OPEN"
    assert record.open_quantity == 2
    assert record.gross_realized == 0.0
    assert record.net_realized == 0.0
    assert record.total_fees == 2.25
    assert record.is_win is None


def test_partial_close_is_flagged_and_realizes_only_sold_portion():
    raw = [
        make_txn(quantity="4.0", value="572.0", commission="4.0",
                 regulatory_fees="0.1", clearing_fees="0.4"),
        make_txn(executed_at="2026-06-12T15:00:00.000Z", action="Sell to Close",
                 quantity="2.0", price="2.00", value="400.0", value_effect="Credit",
                 commission="0.0", regulatory_fees="0.05", clearing_fees="0.2"),
    ]
    records = build_trade_records(parse_broker_transactions(raw))
    record = records[0]
    assert record.status == "PARTIAL"
    assert record.open_quantity == 2
    assert record.sold_quantity == 2
    # realized only on the 2 sold: (2.00 - 1.43) * 100 * 2
    assert record.gross_realized == 114.0


def test_records_sorted_newest_first_and_summary_fields():
    fills = [
        TradeFill(
            executed_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
            action="Buy to Open", option_symbol="AAA   260821C00010000",
            quantity=1, price=1.0, value=100.0, value_effect="Debit",
            fees=1.0, order_id=1,
        ),
        TradeFill(
            executed_at=datetime(2026, 6, 10, tzinfo=timezone.utc),
            action="Buy to Open", option_symbol="BBB   260821C00010000",
            quantity=1, price=1.0, value=100.0, value_effect="Debit",
            fees=1.0, order_id=2,
        ),
    ]
    records = build_trade_records(fills)
    assert [r.option_symbol[:3] for r in records] == ["BBB", "AAA"]
