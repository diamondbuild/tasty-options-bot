"""Read-only: list live/working orders at tastytrade for this account."""

import json

import httpx

from tasty_options_bot.cli import build_tastytrade_client, authenticate_client

client = build_tastytrade_client()
authenticate_client(client)
url = f"{client.config.base_url}/accounts/{client.config.account_number}/orders"
response = httpx.get(
    url,
    params={"status[]": ["Live", "Received", "Routed", "Contingent"], "per-page": 50},
    headers=client.authorization_headers,
    timeout=15,
)
print("status:", response.status_code)
data = response.json().get("data", {}).get("items", [])
for order in data:
    summary = {
        "id": order.get("id"),
        "status": order.get("status"),
        "order-type": order.get("order-type"),
        "price": order.get("price"),
        "price-effect": order.get("price-effect"),
        "time-in-force": order.get("time-in-force"),
        "cancellable": order.get("cancellable"),
        "received-at": order.get("received-at"),
        "legs": [
            {
                "symbol": leg.get("symbol"),
                "action": leg.get("action"),
                "quantity": leg.get("quantity"),
                "remaining-quantity": leg.get("remaining-quantity"),
            }
            for leg in order.get("legs", [])
        ],
    }
    print(json.dumps(summary, indent=2))
print(f"total working orders: {len(data)}")
