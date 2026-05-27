from datetime import date, datetime, timezone

import httpx

from tasty_options_bot.broker.tastytrade_client import TastytradeClient, TastytradeClientConfig
from tasty_options_bot.tastytrade_market_data import parse_equity_option_market_data
from tasty_options_bot.tastytrade_option_chain import TastytradeOptionContract


def make_client(handler):
    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(base_url="https://api.cert.tastyworks.com", transport=transport)
    return TastytradeClient(
        TastytradeClientConfig(username="user", password="pass", account_number="5WT00000"),
        http_client=http_client,
    )


def test_get_equity_option_market_data_uses_by_type_endpoint_and_auth():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["query"] = dict(request.url.params)
        captured["authorization"] = request.headers.get("Authorization")
        return httpx.Response(
            200,
            json={
                "data": {
                    "items": [
                        {
                            "symbol": "SPY 260717P00100000",
                            "instrument-type": "Equity Option",
                            "updated-at": "2026-06-01T14:30:00.000Z",
                            "bid": "0.30",
                            "ask": "0.34",
                            "delta": "-0.20",
                        }
                    ]
                }
            },
        )

    client = make_client(handler)
    client.session_token = "token-abc"

    items = client.get_equity_option_market_data(["SPY 260717P00100000", "SPY 260717P00099000"])

    assert captured["path"] == "/market-data/by-type"
    assert captured["query"] == {"equity-option": "SPY 260717P00100000,SPY 260717P00099000"}
    assert captured["authorization"] == "token-abc"
    assert items[0]["bid"] == "0.30"


def test_get_equity_option_market_data_batches_large_symbol_lists():
    seen_batches = []

    def handler(request: httpx.Request) -> httpx.Response:
        symbols = dict(request.url.params)["equity-option"].split(",")
        seen_batches.append(symbols)
        return httpx.Response(
            200,
            json={"data": {"items": [{"symbol": symbol, "bid": "0.10", "ask": "0.12", "delta": "-0.20"} for symbol in symbols]}},
        )

    client = make_client(handler)
    client.session_token = "token-abc"
    symbols = [f"SPY 260717P{i:08d}" for i in range(121)]

    items = client.get_equity_option_market_data(symbols, batch_size=50)

    assert [len(batch) for batch in seen_batches] == [50, 50, 21]
    assert len(items) == 121


def test_parse_equity_option_market_data_to_option_quotes():
    contracts = [
        TastytradeOptionContract(
            underlying_symbol="SPY",
            option_symbol="SPY 260717P00100000",
            streamer_symbol=".SPY260717P100",
            expiration=date(2026, 7, 17),
            dte=38,
            strike=100.0,
            option_type="put",
        ),
        TastytradeOptionContract(
            underlying_symbol="SPY",
            option_symbol="SPY 260717P00099000",
            streamer_symbol=".SPY260717P99",
            expiration=date(2026, 7, 17),
            dte=38,
            strike=99.0,
            option_type="put",
        ),
    ]
    items = [
        {
            "symbol": "SPY 260717P00100000",
            "instrument-type": "Equity Option",
            "updated-at": "2026-06-01T14:30:00.000Z",
            "bid": "0.30",
            "ask": "0.34",
            "delta": "-0.20",
        },
        {
            "symbol": "SPY 260717P00099000",
            "instrument-type": "Equity Option",
            "updated-at": "2026-06-01T14:30:00.000Z",
            "bid": "0.02",
            "ask": "0.04",
            "delta": "-0.10",
        },
    ]

    quotes = parse_equity_option_market_data(items, contracts)

    assert len(quotes) == 2
    assert quotes[0].symbol == "SPY"
    assert quotes[0].option_symbol == "SPY 260717P00100000"
    assert quotes[0].expiration == date(2026, 7, 17)
    assert quotes[0].option_type == "put"
    assert quotes[0].strike == 100.0
    assert quotes[0].bid == 0.30
    assert quotes[0].ask == 0.34
    assert quotes[0].delta == -0.20
    assert quotes[0].quote_time == datetime(2026, 6, 1, 14, 30, tzinfo=timezone.utc)


def test_parse_equity_option_market_data_skips_items_without_delta():
    contract = TastytradeOptionContract(
        underlying_symbol="SPY",
        option_symbol="SPY 260717P00100000",
        streamer_symbol=".SPY260717P100",
        expiration=date(2026, 7, 17),
        dte=38,
        strike=100.0,
        option_type="put",
    )

    quotes = parse_equity_option_market_data(
        [{"symbol": "SPY 260717P00100000", "updated-at": "2026-06-01T14:30:00.000Z", "bid": "0.30", "ask": "0.34"}],
        [contract],
    )

    assert quotes == []
