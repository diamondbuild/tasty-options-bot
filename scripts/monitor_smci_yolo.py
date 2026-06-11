"""Read-only SMCI YOLO position monitor.

Prints live quote, P/L, underlying price, DTE, and rule-based guidance for the
9x SMCI Jun 18 2026 $30 call position. Never places or cancels orders.
Exits quietly with a clear message if the position is no longer open.
"""

from datetime import date, datetime, timezone

import httpx

from tasty_options_bot.cli import build_tastytrade_client, authenticate_client

OPTION_SYMBOL = "SMCI  260618C00030000"
UNDERLYING = "SMCI"
QUANTITY = 9
ENTRY_PRICE = 1.43
ENTRY_COST = ENTRY_PRICE * 100 * QUANTITY  # 1287.00 excl fees
EXPIRY = date(2026, 6, 18)
BREAKEVEN = 31.43
THESIS_DEAD_UNDERLYING = 27.0


def main() -> None:
    client = build_tastytrade_client()
    authenticate_client(client)

    positions = client.get_positions()
    held = [
        p for p in positions
        if p.get("symbol") == OPTION_SYMBOL and int(float(p.get("quantity", 0))) > 0
    ]
    if not held:
        print(f"POSITION CLOSED OR GONE: no open {OPTION_SYMBOL} found at broker.")
        print("If this was sold, record it and remove the monitor cron job.")
        return
    quantity = int(float(held[0]["quantity"]))

    items = client.get_equity_option_market_data([OPTION_SYMBOL])
    quote = {item["symbol"]: item for item in items}[OPTION_SYMBOL]
    bid = float(quote["bid"])
    ask = float(quote["ask"])
    mark = float(quote["mark"])

    # Underlying spot via market-data endpoint
    underlying_mark = None
    try:
        url = f"{client.config.base_url}/market-data/by-type"
        response = httpx.get(
            url,
            params={"equity": UNDERLYING},
            headers=client.authorization_headers,
            timeout=15,
        )
        items = response.json().get("data", {}).get("items", [])
        if items:
            underlying_mark = float(items[0].get("mark") or items[0].get("last") or 0)
    except Exception:
        pass

    today = datetime.now(timezone.utc).date()
    dte = (EXPIRY - today).days
    value_at_bid = bid * 100 * quantity
    value_at_mark = mark * 100 * quantity
    pnl_at_bid = value_at_bid - ENTRY_COST
    pnl_pct = (pnl_at_bid / ENTRY_COST) * 100

    print(f"SMCI YOLO MONITOR — {datetime.now(timezone.utc).isoformat(timespec='minutes')}")
    print(f"Position: {quantity}x {OPTION_SYMBOL} (entry ${ENTRY_PRICE:.2f}, cost ${ENTRY_COST:,.2f})")
    if underlying_mark:
        print(f"SMCI spot: ${underlying_mark:.2f} (breakeven at expiry: ${BREAKEVEN:.2f})")
    print(f"Call quote: bid ${bid:.2f} / ask ${ask:.2f} / mark ${mark:.2f}")
    print(f"Position value at bid: ${value_at_bid:,.2f} (at mark: ${value_at_mark:,.2f})")
    print(f"P/L at bid: ${pnl_at_bid:+,.2f} ({pnl_pct:+.1f}%)")
    print(f"DTE: {dte}")

    # Rule-based guidance
    flags = []
    if pnl_pct >= 100:
        flags.append("TAKE-PROFIT ZONE: up 100%+. Strongly consider selling at least half (sell 5 recovers full cost basis).")
    elif pnl_pct >= 50:
        flags.append("PROFIT ALERT: up 50%+. Consider trimming to lock in gains; theta accelerates from here.")
    if underlying_mark and underlying_mark < THESIS_DEAD_UNDERLYING:
        flags.append(f"THESIS DEAD: SMCI below ${THESIS_DEAD_UNDERLYING:.0f} (new lows). Salvage remaining premium rather than riding to zero.")
    if pnl_pct <= -50:
        flags.append("DOWN 50%+: decide now — cut and salvage, or consciously accept full loss. Do not drift.")
    if dte <= 1:
        flags.append("EXPIRES TOMORROW/TODAY: sell anything with value before the close — do not let ITM exercise or OTM expiry happen by accident.")
    elif dte <= 3:
        flags.append(f"ONLY {dte} DTE: theta is brutal now. If SMCI is not moving up, exit value decays fast.")

    if flags:
        for flag in flags:
            print(f"!! {flag}")
    else:
        print("No exit rules triggered. Hold per plan; re-check at next tick.")
    print("Read-only monitor: no orders were placed.")


if __name__ == "__main__":
    main()
