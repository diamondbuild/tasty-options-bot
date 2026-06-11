"""Debug a 422 close-order rejection using tastytrade's order dry-run endpoint.

Read-only/safe: posts to /accounts/{acct}/orders/dry-run which validates but
never places an order. Prints the full error body so we can see why the real
submit returned 422.
"""

import json
import sys

import httpx

from tasty_options_bot.cli import build_tastytrade_client, authenticate_client

SYMBOL = sys.argv[1] if len(sys.argv) > 1 else "IWM"

PAYLOADS = {
    "IWM": {
        "order-type": "Limit",
        "time-in-force": "Day",
        "price-effect": "Debit",
        "price": "1.34",
        "source": "tasty-options-bot-close-preview",
        "legs": [
            {"action": "Buy to Close", "instrument-type": "Equity Option", "symbol": "IWM   260702P00278000", "quantity": 1},
            {"action": "Sell to Close", "instrument-type": "Equity Option", "symbol": "IWM   260702P00273000", "quantity": 1},
        ],
    },
    "QQQ": {
        "order-type": "Limit",
        "time-in-force": "Day",
        "price-effect": "Debit",
        "price": "2.43",
        "source": "tasty-options-bot-close-preview",
        "legs": [
            {"action": "Buy to Close", "instrument-type": "Equity Option", "symbol": "QQQ   260702P00705000", "quantity": 1},
            {"action": "Sell to Close", "instrument-type": "Equity Option", "symbol": "QQQ   260702P00700000", "quantity": 1},
        ],
    },
}

client = build_tastytrade_client()
authenticate_client(client)
payload = PAYLOADS[SYMBOL]
url = f"{client.config.base_url}/accounts/{client.config.account_number}/orders/dry-run"
response = httpx.post(url, json=payload, headers=client.authorization_headers, timeout=15)
print("status:", response.status_code)
print(json.dumps(response.json(), indent=2)[:4000])
