"""Read-only: dump recent account transactions (fills) from tastytrade.

Usage: .venv/bin/python scripts/debug_transactions.py [--days 7] [--symbol SMCI]
Never places, modifies, or cancels orders.
"""

import argparse
import json
from datetime import datetime, timedelta, timezone

import httpx

from tasty_options_bot.cli import authenticate_client, build_tastytrade_client


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--symbol", default=None, help="underlying symbol filter")
    args = parser.parse_args()

    client = build_tastytrade_client()
    authenticate_client(client)

    start = (datetime.now(timezone.utc) - timedelta(days=args.days)).date().isoformat()
    params: dict[str, str | int] = {"start-date": start, "per-page": 250}
    if args.symbol:
        params["underlying-symbol"] = args.symbol

    url = (
        f"{client.config.base_url}/accounts/"
        f"{client.config.account_number}/transactions"
    )
    response = httpx.get(
        url, params=params, headers=client.authorization_headers, timeout=15
    )
    print("status:", response.status_code)
    items = response.json().get("data", {}).get("items", [])
    print(f"{len(items)} transactions since {start}")
    for txn in items:
        summary = {
            "executed-at": txn.get("executed-at"),
            "transaction-type": txn.get("transaction-type"),
            "action": txn.get("action"),
            "symbol": txn.get("symbol"),
            "quantity": txn.get("quantity"),
            "price": txn.get("price"),
            "value": txn.get("value"),
            "value-effect": txn.get("value-effect"),
            "commission": txn.get("commission"),
            "regulatory-fees": txn.get("regulatory-fees"),
            "clearing-fees": txn.get("clearing-fees"),
            "order-id": txn.get("order-id"),
        }
        print(json.dumps(summary))


if __name__ == "__main__":
    main()
