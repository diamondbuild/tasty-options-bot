"""Read-only: SMCI near-term call chain with live bid/ask via bot's tastytrade client."""

from tasty_options_bot.cli import build_tastytrade_client, authenticate_client

import httpx

client = build_tastytrade_client()
authenticate_client(client)

url = f"{client.config.base_url}/option-chains/SMCI/nested"
response = httpx.get(url, headers=client.authorization_headers, timeout=20)
data = response.json()["data"]["items"][0]

expirations = data["expirations"]
candidates = []
for exp in expirations:
    dte = int(exp["days-to-expiration"])
    if not (1 <= dte <= 40):
        continue
    for strike in exp["strikes"]:
        strike_price = float(strike["strike-price"])
        if 28 <= strike_price <= 40:
            candidates.append((exp["expiration-date"], dte, strike_price, strike["call"]))

symbols = [c[3] for c in candidates]
quotes = {}
for i in range(0, len(symbols), 90):
    items = client.get_equity_option_market_data(symbols[i:i+90])
    for item in items:
        quotes[item["symbol"]] = item

print(f"{'expiry':<12} {'dte':>3} {'strike':>7} {'bid':>7} {'ask':>7} {'mark':>7}  symbol")
for exp_date, dte, strike_price, sym in candidates:
    quote = quotes.get(sym, {})
    bid = quote.get("bid")
    ask = quote.get("ask")
    mark = quote.get("mark")
    print(f"{exp_date:<12} {dte:>3} {strike_price:>7.1f} {str(bid):>7} {str(ask):>7} {str(mark):>7}  {sym}")
