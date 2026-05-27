import httpx

from tasty_options_bot.broker.tastytrade_client import TastytradeClient, TastytradeClientConfig


def make_mock_client(handler):
    return httpx.Client(base_url="https://api.tastytrade.com", transport=httpx.MockTransport(handler))


def test_login_raises_device_challenge_with_token_and_message():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            headers={"X-Tastyworks-Challenge-Token": "challenge-token"},
            json={"error": {"code": "device_challenge_required", "message": "Device challenge"}},
        )

    client = TastytradeClient(
        TastytradeClientConfig(username="user", password="pass", is_production=True),
        http_client=make_mock_client(handler),
    )

    result = client.login()

    assert result == "device_challenge_required"
    assert client.challenge_token == "challenge-token"
    assert client.session_token is None


def test_start_device_challenge_returns_masked_phone_and_updates_token():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["challenge"] = request.headers.get("X-Tastyworks-Challenge-Token")
        return httpx.Response(
            200,
            headers={"X-Tastyworks-Challenge-Token": "otp-token"},
            json={"data": {"phone": "********6282", "step": "otp_verification"}},
        )

    client = TastytradeClient(
        TastytradeClientConfig(username="user", password="pass", is_production=True),
        http_client=make_mock_client(handler),
    )
    client.challenge_token = "challenge-token"

    data = client.start_device_challenge()

    assert captured == {"path": "/device-challenge", "challenge": "challenge-token"}
    assert data["phone"] == "********6282"
    assert client.challenge_token == "otp-token"


def test_complete_login_with_otp_posts_session_with_challenge_and_otp_headers():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["challenge"] = request.headers.get("X-Tastyworks-Challenge-Token")
        captured["otp"] = request.headers.get("X-Tastyworks-OTP")
        return httpx.Response(201, json={"data": {"session-token": "session-token"}})

    client = TastytradeClient(
        TastytradeClientConfig(username="user", password="pass", is_production=True),
        http_client=make_mock_client(handler),
    )
    client.challenge_token = "otp-token"

    token = client.complete_login_with_otp("123456")

    assert token == "session-token"
    assert client.session_token == "session-token"
    assert captured == {"path": "/sessions", "challenge": "otp-token", "otp": "123456"}
