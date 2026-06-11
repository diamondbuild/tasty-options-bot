"""Read-only: fetch the two just-submitted close orders and print fill details."""

import httpx

from tasty_options_bot.cli import build_tastytrade_client, authenticate_client

client = build_tastytrade_client()
authenticate_client(client)
for order_id in (475128061, 475128470):
    url = f"{client.config.base_url}/accounts/{client.config.account_number}/orders/{order_id}"
    response = httpx.get(url, headers=client.authorization_headers, timeout=15)
    order = response.json().get("data", {})
    symbol = order.get("underlying-symbol")
    legs = order.get("legs", [])
    fill_prices = []
    for leg in legs:
        for fill in leg.get("fills", []):
            fill_prices.append((leg.get("action"), leg.get("symbol"), fill.get("fill-price"), fill.get("filled-at")))
    print(f"order {order_id} {symbol}: status={order.get('status')} price={order.get('price')} effect={order.get('price-effect')}")
    for action, leg_symbol, price, filled_at in fill_prices:
        print(f"  {action} {leg_symbol} fill={price} at={filled_at}")
