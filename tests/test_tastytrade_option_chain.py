from datetime import date

import httpx

from tasty_options_bot.broker.tastytrade_client import TastytradeClient, TastytradeClientConfig
from tasty_options_bot.tastytrade_option_chain import (
    TastytradeOptionContract,
    parse_nested_option_chain,
)


def make_client(handler):
    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(base_url="https://api.cert.tastyworks.com", transport=transport)
    return TastytradeClient(
        TastytradeClientConfig(username="user", password="pass", account_number="5WT00000"),
        http_client=http_client,
    )


def nested_payload():
    return {
        "data": {
            "items": [
                {
                    "underlying-symbol": "SPY",
                    "root-symbol": "SPY",
                    "option-chain-type": "Standard",
                    "shares-per-contract": 100,
                    "expirations": [
                        {
                            "expiration-type": "Regular",
                            "expiration-date": "2026-07-17",
                            "days-to-expiration": 38,
                            "settlement-type": "PM",
                            "strikes": [
                                {
                                    "strike-price": "100.0",
                                    "call": "SPY 260717C00100000",
                                    "call-streamer-symbol": ".SPY260717C100",
                                    "put": "SPY 260717P00100000",
                                    "put-streamer-symbol": ".SPY260717P100",
                                },
                                {
                                    "strike-price": "99.0",
                                    "call": "SPY 260717C00099000",
                                    "call-streamer-symbol": ".SPY260717C99",
                                    "put": "SPY 260717P00099000",
                                    "put-streamer-symbol": ".SPY260717P99",
                                },
                            ],
                        }
                    ],
                }
            ]
        }
    }


def test_get_nested_option_chain_uses_read_only_auth_and_symbol():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["authorization"] = request.headers.get("Authorization")
        return httpx.Response(200, json=nested_payload())

    client = make_client(handler)
    client.session_token = "token-abc"

    items = client.get_nested_option_chain("spy")

    assert captured["path"] == "/option-chains/SPY/nested"
    assert captured["authorization"] == "token-abc"
    assert items[0]["underlying-symbol"] == "SPY"


def test_parse_nested_option_chain_returns_put_and_call_contracts():
    items = nested_payload()["data"]["items"]

    contracts = parse_nested_option_chain(items)

    assert contracts == [
        TastytradeOptionContract(
            underlying_symbol="SPY",
            option_symbol="SPY 260717C00100000",
            streamer_symbol=".SPY260717C100",
            expiration=date(2026, 7, 17),
            dte=38,
            strike=100.0,
            option_type="call",
        ),
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
            option_symbol="SPY 260717C00099000",
            streamer_symbol=".SPY260717C99",
            expiration=date(2026, 7, 17),
            dte=38,
            strike=99.0,
            option_type="call",
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


def test_parse_nested_option_chain_can_filter_puts_by_dte_range():
    items = nested_payload()["data"]["items"]

    contracts = parse_nested_option_chain(items, option_type="put", dte_min=30, dte_max=45)

    assert len(contracts) == 2
    assert all(contract.option_type == "put" for contract in contracts)
    assert all(30 <= contract.dte <= 45 for contract in contracts)
