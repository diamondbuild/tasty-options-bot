import json

import httpx
import pytest

from tasty_options_bot.broker.tastytrade_client import (
    TastytradeClient,
    TastytradeClientConfig,
    TastytradeClientError,
)


def make_mock_client(handler):
    transport = httpx.MockTransport(handler)
    return httpx.Client(base_url="https://api.cert.tastyworks.com", transport=transport)


def make_client(handler, **overrides):
    data = {
        "username": "user",
        "password": "pass",
        "account_number": "5WT00000",
        "is_production": False,
    }
    data.update(overrides)
    return TastytradeClient(TastytradeClientConfig(**data), http_client=make_mock_client(handler))


def test_login_stores_session_token_and_does_not_return_password():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(201, json={"data": {"session-token": "token-123"}})

    client = make_client(handler)

    token = client.login()

    assert token == "token-123"
    assert client.session_token == "token-123"
    assert captured["path"] == "/sessions"
    assert captured["body"] == {"login": "user", "password": "pass"}


def test_login_failure_raises_clear_error_without_secret_in_message():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "invalid login"}})

    client = make_client(handler, password="super-secret-password")

    with pytest.raises(TastytradeClientError) as exc_info:
        client.login()

    message = str(exc_info.value)
    assert "login failed" in message
    assert "super-secret-password" not in message


def test_login_requires_credentials():
    client = make_client(lambda request: httpx.Response(500), username="")

    with pytest.raises(TastytradeClientError, match="username"):
        client.login()


def test_get_account_uses_authorization_header_and_account_number():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["authorization"] = request.headers.get("Authorization")
        return httpx.Response(200, json={"data": {"account-number": "5WT00000", "nickname": "Bot"}})

    client = make_client(handler)
    client.session_token = "token-abc"

    account = client.get_account()

    assert captured["path"] == "/customers/me/accounts/5WT00000"
    assert captured["authorization"] == "token-abc"
    assert account["account-number"] == "5WT00000"


def test_get_positions_uses_authorization_header_and_account_number():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["authorization"] = request.headers.get("Authorization")
        return httpx.Response(200, json={"data": {"items": [{"symbol": "SPY"}]}})

    client = make_client(handler)
    client.session_token = "token-abc"

    positions = client.get_positions()

    assert captured["path"] == "/accounts/5WT00000/positions"
    assert captured["authorization"] == "token-abc"
    assert positions == [{"symbol": "SPY"}]


def test_get_balance_uses_authorization_header_and_account_number():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["authorization"] = request.headers.get("Authorization")
        return httpx.Response(
            200,
            json={
                "data": {
                    "cash-balance": "3000.00",
                    "net-liquidating-value": "3000.00",
                    "option-buying-power": "3000.00",
                }
            },
        )

    client = make_client(handler)
    client.session_token = "token-abc"

    balance = client.get_balance()

    assert captured["path"] == "/accounts/5WT00000/balances"
    assert captured["authorization"] == "token-abc"
    assert balance["net-liquidating-value"] == "3000.00"


def test_read_only_calls_require_authentication():
    client = make_client(lambda request: httpx.Response(500))

    with pytest.raises(TastytradeClientError, match="authenticate"):
        client.get_account()

    with pytest.raises(TastytradeClientError, match="authenticate"):
        client.get_positions()

    with pytest.raises(TastytradeClientError, match="authenticate"):
        client.get_balance()
