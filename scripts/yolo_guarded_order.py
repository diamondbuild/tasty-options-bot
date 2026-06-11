"""Guarded YOLO long-option order: preview by default, --submit to place.

Generalized from the one-off SMCI June script. Safety rails:
- Option symbol, max quantity, and hard limit-price cap are REQUIRED flags —
  no defaults that could buy the wrong thing.
- Step 1 (default): re-pull live quote + broker dry-run validation. NO order placed.
- Step 2 (--submit): submit the limit order after gates pass.
- Refuses if limit > hard cap, if quote is missing/stale, or qty out of range.
- Journals the submission.

Example (preview):
  .venv/bin/python scripts/yolo_guarded_order.py \
    --option-symbol "SMCI  260821C00033000" --underlying SMCI \
    --quantity 2 --max-quantity 2 --price-cap 4.65
"""

import argparse
import json
import sys
from pathlib import Path

import httpx

from tasty_options_bot.cli import build_tastytrade_client, authenticate_client
from tasty_options_bot.journal import Journal, JournalEvent

JOURNAL_PATH = Path("data/journal.jsonl")


def build_payload(option_symbol: str, quantity: int, price: float) -> dict:
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
                "symbol": option_symbol,
                "quantity": quantity,
            }
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--option-symbol", required=True, help="Exact tastytrade option symbol (incl. spaces).")
    parser.add_argument("--underlying", required=True)
    parser.add_argument("--quantity", type=int, required=True)
    parser.add_argument("--max-quantity", type=int, required=True, help="Hard cap on contracts.")
    parser.add_argument("--price-cap", type=float, required=True, help="Refuse to bid above this per contract.")
    parser.add_argument("--price", type=float, default=None, help="Limit price; defaults to current ask.")
    parser.add_argument("--submit", action="store_true", help="Actually submit the live order.")
    args = parser.parse_args()

    if args.quantity < 1 or args.quantity > args.max_quantity:
        sys.exit(f"quantity must be 1..{args.max_quantity}")

    client = build_tastytrade_client()
    authenticate_client(client)

    items = client.get_equity_option_market_data([args.option_symbol])
    by_symbol = {item["symbol"]: item for item in items}
    if args.option_symbol not in by_symbol:
        sys.exit(f"refusing: no live quote returned for {args.option_symbol!r}")
    quote = by_symbol[args.option_symbol]
    bid, ask, mark = float(quote["bid"]), float(quote["ask"]), float(quote["mark"])
    print(f"Live quote {args.option_symbol}: bid={bid:.2f} ask={ask:.2f} mark={mark:.2f}")
    if bid <= 0 or ask <= 0:
        sys.exit("refusing: missing/zero bid or ask — market may be closed or symbol wrong")

    price = args.price if args.price is not None else ask
    if price > args.price_cap:
        sys.exit(f"refusing: limit price {price:.2f} exceeds hard cap {args.price_cap:.2f}")
    if price <= 0:
        sys.exit("refusing: price must be positive")

    payload = build_payload(args.option_symbol, args.quantity, price)
    total_cost = price * 100 * args.quantity
    print(
        f"Ticket: BUY TO OPEN {args.quantity}x {args.option_symbol} limit ${price:.2f} "
        f"(total ${total_cost:,.2f} + fees)"
    )

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
            symbol=args.underlying,
            decision="submitted",
            reason="user_directed_yolo_trade",
            payload={"order_payload": payload, "order_response": response},
        )
    )
    print("LIVE ORDER SUBMITTED")
    print(f"Order id: {order.get('id')}  status: {order.get('status')}")


if __name__ == "__main__":
    main()
