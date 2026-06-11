"""One-off guarded YOLO buy: SMCI Jun 18 2026 $30 calls, buy to open, limit only.

Safety rails:
- Hardcoded option symbol, max quantity, and hard limit-price cap.
- Step 1 (default): re-pull live quote + broker dry-run validation. NO order placed.
- Step 2 (--submit): submit the limit order after gates pass.
- Journals the submission.
"""

import argparse
import json
import sys
from pathlib import Path

import httpx

from tasty_options_bot.cli import build_tastytrade_client, authenticate_client
from tasty_options_bot.journal import Journal, JournalEvent

OPTION_SYMBOL = "SMCI  260618C00030000"
UNDERLYING = "SMCI"
MAX_QUANTITY = 9
HARD_PRICE_CAP = 1.55  # refuse to bid above this per contract
JOURNAL_PATH = Path("data/journal.jsonl")


def build_payload(quantity: int, price: float) -> dict:
    return {
        "order-type": "Limit",
        "time-in-force": "Day",
        "price-effect": "Debit",
        "price": f"{price:.2f}",
        "source": "tasty-options-bot-manual-yolo",
        "legs": [
            {
                "action": "Buy to Open",
                "instrument-type": "Equity Option",
                "symbol": OPTION_SYMBOL,
                "quantity": quantity,
            }
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--submit", action="store_true", help="Actually submit the live order.")
    parser.add_argument("--quantity", type=int, default=MAX_QUANTITY)
    parser.add_argument("--price", type=float, default=None, help="Limit price; defaults to current ask.")
    args = parser.parse_args()

    if args.quantity < 1 or args.quantity > MAX_QUANTITY:
        sys.exit(f"quantity must be 1..{MAX_QUANTITY}")

    client = build_tastytrade_client()
    authenticate_client(client)

    items = client.get_equity_option_market_data([OPTION_SYMBOL])
    quote = {item["symbol"]: item for item in items}[OPTION_SYMBOL]
    bid, ask, mark = float(quote["bid"]), float(quote["ask"]), float(quote["mark"])
    print(f"Live quote {OPTION_SYMBOL}: bid={bid:.2f} ask={ask:.2f} mark={mark:.2f}")

    price = args.price if args.price is not None else ask
    if price > HARD_PRICE_CAP:
        sys.exit(f"refusing: limit price {price:.2f} exceeds hard cap {HARD_PRICE_CAP:.2f}")
    if price <= 0:
        sys.exit("refusing: price must be positive")

    payload = build_payload(args.quantity, price)
    total_cost = price * 100 * args.quantity
    print(f"Ticket: BUY TO OPEN {args.quantity}x {OPTION_SYMBOL} limit ${price:.2f} "
          f"(total ${total_cost:,.2f} + fees)")

    base = f"{client.config.base_url}/accounts/{client.config.account_number}/orders"

    # Broker-side dry-run validation (never places an order)
    dry = httpx.post(f"{base}/dry-run", json=payload, headers=client.authorization_headers, timeout=20)
    print(f"dry-run status: {dry.status_code}")
    body = dry.json()
    if dry.status_code >= 400:
        print(json.dumps(body, indent=2)[:2500])
        sys.exit("dry-run failed; not submitting")
    data = body.get("data", {})
    bpe = data.get("buying-power-effect", {})
    fees = data.get("fee-calculation", {})
    print(f"  BP change: {bpe.get('change-in-buying-power')} {bpe.get('change-in-buying-power-effect')}")
    print(f"  New BP: {bpe.get('new-buying-power')}")
    print(f"  Total fees: {fees.get('total-fees')}")
    warnings = data.get("warnings") or body.get("warnings")
    if warnings:
        print(f"  warnings: {warnings}")

    if not args.submit:
        print("PREVIEW ONLY — no order was placed. Re-run with --submit to place it.")
        return

    response = client.submit_order_payload(payload, approved=True)
    order = response.get("order", {})
    journal = Journal(JOURNAL_PATH)
    journal.append(
        JournalEvent(
            event_type="manual_yolo_order_submitted",
            symbol=UNDERLYING,
            decision="submitted",
            reason="user_directed_wsb_trade",
            payload={"order_payload": payload, "order_response": response},
        )
    )
    print("LIVE ORDER SUBMITTED")
    print(f"Order id: {order.get('id')}  status: {order.get('status')}")


if __name__ == "__main__":
    main()
