import pytest

from tasty_options_bot.broker.tastytrade_client import (
    TastytradeClient,
    TastytradeClientConfig,
    TastytradeClientError,
)
from tasty_options_bot.spreads import CreditSpread


def make_client(**overrides):
    data = {
        "username": "user",
        "password": "pass",
        "account_number": "5WT00000",
        "is_production": False,
        "live_trading": False,
        "require_manual_approval": True,
    }
    data.update(overrides)
    return TastytradeClient(TastytradeClientConfig(**data))


def make_spread():
    return CreditSpread(short_strike=100, long_strike=99, credit=0.30, quantity=1)


def test_client_defaults_to_certification_base_url():
    client = make_client()

    assert client.config.base_url == "https://api.cert.tastyworks.com"


def test_client_uses_production_base_url_only_when_configured():
    client = make_client(is_production=True)

    assert client.config.base_url == "https://api.tastyworks.com"


def test_place_order_refuses_when_live_trading_is_disabled():
    client = make_client(live_trading=False)

    with pytest.raises(TastytradeClientError, match="live_trading"):
        client.place_credit_spread_order(
            symbol="SPY",
            spread=make_spread(),
            limit_credit=0.30,
            order_type="limit",
            approved=True,
        )


def test_place_order_refuses_market_orders_even_when_live_trading_enabled():
    client = make_client(live_trading=True)

    with pytest.raises(TastytradeClientError, match="market orders"):
        client.place_credit_spread_order(
            symbol="SPY",
            spread=make_spread(),
            limit_credit=0.30,
            order_type="market",
            approved=True,
        )


def test_place_order_refuses_without_account_number():
    client = make_client(live_trading=True, account_number="")

    with pytest.raises(TastytradeClientError, match="account_number"):
        client.place_credit_spread_order(
            symbol="SPY",
            spread=make_spread(),
            limit_credit=0.30,
            order_type="limit",
            approved=True,
        )


def test_place_order_refuses_without_manual_approval_when_required():
    client = make_client(live_trading=True, require_manual_approval=True)

    with pytest.raises(TastytradeClientError, match="manual approval"):
        client.place_credit_spread_order(
            symbol="SPY",
            spread=make_spread(),
            limit_credit=0.30,
            order_type="limit",
            approved=False,
        )


def test_place_order_refuses_before_authentication():
    client = make_client(live_trading=True, require_manual_approval=False)

    with pytest.raises(TastytradeClientError, match="authenticate"):
        client.place_credit_spread_order(
            symbol="SPY",
            spread=make_spread(),
            limit_credit=0.30,
            order_type="limit",
            approved=True,
        )


def test_submit_order_payload_refuses_when_live_trading_is_disabled():
    client = make_client(live_trading=False)

    with pytest.raises(TastytradeClientError, match="live_trading"):
        client.submit_order_payload(
            {"order-type": "Limit", "price-effect": "Debit", "price": "1.05", "legs": []},
            approved=True,
        )


def test_submit_order_payload_posts_validated_limit_order_when_all_gates_pass():
    requests = []

    class FakeHttpClient:
        def post(self, path, *, json=None, headers=None):
            requests.append({"path": path, "json": json, "headers": headers})

            class Response:
                status_code = 201

                def json(self):
                    return {"data": {"order": {"id": "order-123", "status": "Received"}}}

            return Response()

    client = make_client(live_trading=True, require_manual_approval=True)
    client.session_token = "session-token"
    client._client = FakeHttpClient()
    payload = {
        "order-type": "Limit",
        "time-in-force": "Day",
        "price-effect": "Debit",
        "price": "1.05",
        "source": "tasty-options-bot-close-submit",
        "legs": [
            {
                "action": "Buy to Close",
                "instrument-type": "Equity Option",
                "symbol": "SPY   260626P00732000",
                "quantity": 1,
            },
            {
                "action": "Sell to Close",
                "instrument-type": "Equity Option",
                "symbol": "SPY   260626P00727000",
                "quantity": 1,
            },
        ],
    }

    result = client.submit_order_payload(payload, approved=True)

    assert result == {"order": {"id": "order-123", "status": "Received"}}
    assert requests == [
        {
            "path": "/accounts/5WT00000/orders",
            "json": payload,
            "headers": {"Authorization": "session-token"},
        }
    ]


def test_get_order_fetches_order_by_id_read_only():
    requests = []

    class FakeHttpClient:
        def get(self, path, *, headers=None):
            requests.append({"path": path, "headers": headers})

            class Response:
                status_code = 200

                def json(self):
                    return {"data": {"order": {"id": "order-123", "status": "Filled"}}}

            return Response()

    client = make_client(live_trading=True, require_manual_approval=False)
    client.session_token = "session-token"
    client._client = FakeHttpClient()

    result = client.get_order("order-123")

    assert result == {"order": {"id": "order-123", "status": "Filled"}}
    assert requests == [
        {
            "path": "/accounts/5WT00000/orders/order-123",
            "headers": {"Authorization": "session-token"},
        }
    ]


def test_get_order_requires_order_id():
    client = make_client(live_trading=True, require_manual_approval=False)
    client.session_token = "session-token"

    with pytest.raises(TastytradeClientError, match="order_id is required"):
        client.get_order(" ")
