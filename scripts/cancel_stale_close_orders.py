"""Cancel two specific stale GTC closing orders by id. Explicit ids only — no discovery."""

import json
import sys

import httpx

from tasty_options_bot.cli import build_tastytrade_client, authenticate_client

ORDER_IDS = [int(arg) for arg in sys.argv[1:]]
if not ORDER_IDS:
    raise SystemExit("usage: cancel_orders.py ORDER_ID [ORDER_ID ...]")

ALLOWED = {471045444, 471046065}
for order_id in ORDER_IDS:
    if order_id not in ALLOWED:
        raise SystemExit(f"refusing to cancel unexpected order id {order_id}")

client = build_tastytrade_client()
authenticate_client(client)
for order_id in ORDER_IDS:
    url = f"{client.config.base_url}/accounts/{client.config.account_number}/orders/{order_id}"
    response = httpx.delete(url, headers=client.authorization_headers, timeout=15)
    body = response.json()
    status = body.get("data", {}).get("status") if isinstance(body.get("data"), dict) else None
    print(f"order {order_id}: http={response.status_code} status={status}")
    if response.status_code >= 400:
        print(json.dumps(body, indent=2)[:1500])
