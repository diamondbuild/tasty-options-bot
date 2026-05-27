from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from tasty_options_bot.spreads import CreditSpread


class TastytradeClientError(Exception):
    """Raised when tastytrade client validation or requests fail."""


@dataclass(frozen=True)
class TastytradeClientConfig:
    username: str = ""
    password: str = ""
    account_number: str = ""
    is_production: bool = False
    live_trading: bool = False
    require_manual_approval: bool = True
    timeout_seconds: float = 10.0

    @property
    def base_url(self) -> str:
        if self.is_production:
            return "https://api.tastyworks.com"
        return "https://api.cert.tastyworks.com"


class TastytradeClient:
    """Minimal tastytrade API client with safety-first order gates.

    The client supports mocked/read-only account flows first. Live order sending
    remains blocked unless explicit config flags, account number, approval, and
    authentication state all pass validation.
    """

    def __init__(self, config: TastytradeClientConfig, http_client: httpx.Client | None = None) -> None:
        self.config = config
        self._client = http_client or httpx.Client(base_url=config.base_url, timeout=config.timeout_seconds)
        self.session_token: str | None = None
        self.challenge_token: str | None = None

    @property
    def is_authenticated(self) -> bool:
        return self.session_token is not None

    @property
    def authorization_headers(self) -> dict[str, str]:
        if not self.session_token:
            raise TastytradeClientError("client must authenticate before authorized requests")
        return {"Authorization": self.session_token}

    def login(self) -> str:
        if not self.config.username:
            raise TastytradeClientError("username is required")
        if not self.config.password:
            raise TastytradeClientError("password is required")

        response = self._client.post(
            "/sessions",
            json={"login": self.config.username, "password": self.config.password},
        )
        if self._is_device_challenge_required(response):
            self.challenge_token = response.headers.get("X-Tastyworks-Challenge-Token")
            return "device_challenge_required"
        if response.status_code >= 400:
            raise TastytradeClientError(f"login failed with status {response.status_code}")

        token = response.json().get("data", {}).get("session-token")
        if not token:
            raise TastytradeClientError("login failed: response did not include session token")
        self.session_token = token
        return token

    def start_device_challenge(self) -> dict[str, Any]:
        if not self.challenge_token:
            raise TastytradeClientError("device challenge token is required")
        response = self._client.post(
            "/device-challenge",
            headers={"X-Tastyworks-Challenge-Token": self.challenge_token},
        )
        data = self._read_data(response, action="start device challenge")
        next_token = response.headers.get("X-Tastyworks-Challenge-Token")
        if next_token:
            self.challenge_token = next_token
        return data

    def complete_login_with_otp(self, otp: str) -> str:
        if not self.challenge_token:
            raise TastytradeClientError("device challenge token is required")
        if not otp:
            raise TastytradeClientError("otp is required")
        response = self._client.post(
            "/sessions",
            json={"login": self.config.username, "password": self.config.password},
            headers={
                "X-Tastyworks-Challenge-Token": self.challenge_token,
                "X-Tastyworks-OTP": otp,
            },
        )
        if response.status_code >= 400:
            raise TastytradeClientError(f"otp login failed with status {response.status_code}")
        token = response.json().get("data", {}).get("session-token")
        if not token:
            raise TastytradeClientError("otp login failed: response did not include session token")
        self.session_token = token
        return token

    def get_account(self) -> dict[str, Any]:
        self._validate_read_only_request()
        response = self._client.get(
            f"/customers/me/accounts/{self.config.account_number}",
            headers=self.authorization_headers,
        )
        return self._read_data(response, action="get account")

    def get_positions(self) -> list[dict[str, Any]]:
        self._validate_read_only_request()
        response = self._client.get(
            f"/accounts/{self.config.account_number}/positions",
            headers=self.authorization_headers,
        )
        data = self._read_data(response, action="get positions")
        items = data.get("items", [])
        if not isinstance(items, list):
            raise TastytradeClientError("get positions failed: response data.items was not a list")
        return items

    def get_balance(self) -> dict[str, Any]:
        self._validate_read_only_request()
        response = self._client.get(
            f"/accounts/{self.config.account_number}/balances",
            headers=self.authorization_headers,
        )
        return self._read_data(response, action="get balance")

    def get_order(self, order_id: str) -> dict[str, Any]:
        """Fetch a single tastytrade order by id for read-only status reconciliation."""
        self._validate_read_only_request()
        normalized_order_id = order_id.strip()
        if not normalized_order_id:
            raise TastytradeClientError("order_id is required")
        response = self._client.get(
            f"/accounts/{self.config.account_number}/orders/{normalized_order_id}",
            headers=self.authorization_headers,
        )
        return self._read_data(response, action="get order")

    def get_nested_option_chain(self, symbol: str) -> list[dict[str, Any]]:
        self._validate_read_only_request()
        normalized_symbol = symbol.upper().strip()
        if not normalized_symbol:
            raise TastytradeClientError("symbol is required")
        response = self._client.get(
            f"/option-chains/{normalized_symbol}/nested",
            headers=self.authorization_headers,
        )
        data = self._read_data(response, action="get nested option chain")
        items = data.get("items", [])
        if not isinstance(items, list):
            raise TastytradeClientError("get nested option chain failed: response data.items was not a list")
        return items

    def get_equity_option_market_data(self, symbols: list[str], *, batch_size: int = 50) -> list[dict[str, Any]]:
        self._validate_read_only_request()
        normalized_symbols = [symbol.strip() for symbol in symbols if symbol.strip()]
        if not normalized_symbols:
            raise TastytradeClientError("at least one equity option symbol is required")
        if batch_size <= 0:
            raise TastytradeClientError("batch_size must be positive")

        all_items: list[dict[str, Any]] = []
        for start in range(0, len(normalized_symbols), batch_size):
            batch = normalized_symbols[start : start + batch_size]
            response = self._client.get(
                "/market-data/by-type",
                params={"equity-option": ",".join(batch)},
                headers=self.authorization_headers,
            )
            data = self._read_data(response, action="get equity option market data")
            items = data.get("items", [])
            if not isinstance(items, list):
                raise TastytradeClientError("get equity option market data failed: response data.items was not a list")
            all_items.extend(items)
        return all_items

    def place_credit_spread_order(
        self,
        *,
        symbol: str,
        spread: CreditSpread,
        limit_credit: float,
        order_type: str = "limit",
        approved: bool = False,
    ) -> dict[str, Any]:
        self._validate_order_gate(order_type=order_type, approved=approved)
        if limit_credit <= 0:
            raise TastytradeClientError("limit_credit must be positive")
        # Actual opening-order payload/submission intentionally comes later after the
        # scanner, risk manager, journal, and close-order logic are integrated.
        raise TastytradeClientError("live opening order submission is not implemented yet")

    def submit_order_payload(self, payload: dict[str, Any], *, approved: bool = False) -> dict[str, Any]:
        """Submit a pre-built tastytrade order payload after all live-order gates pass."""
        order_type = str(payload.get("order-type", "")).lower()
        if order_type != "limit":
            raise TastytradeClientError("only limit order payloads can be submitted")
        self._validate_order_gate(order_type=order_type, approved=approved)
        if not payload.get("legs"):
            raise TastytradeClientError("order payload requires legs")
        try:
            price = float(payload.get("price", 0))
        except (TypeError, ValueError) as exc:
            raise TastytradeClientError("order payload price must be numeric") from exc
        if price <= 0:
            raise TastytradeClientError("order payload price must be positive")

        response = self._client.post(
            f"/accounts/{self.config.account_number}/orders",
            json=payload,
            headers=self.authorization_headers,
        )
        return self._read_data(response, action="submit order")

    def _validate_order_gate(self, *, order_type: str, approved: bool) -> None:
        if not self.config.live_trading:
            raise TastytradeClientError("live_trading is disabled")
        if order_type != "limit":
            raise TastytradeClientError("market orders are not allowed")
        if not self.config.account_number:
            raise TastytradeClientError("account_number is required")
        if self.config.require_manual_approval and not approved:
            raise TastytradeClientError("manual approval is required")
        if not self.is_authenticated:
            raise TastytradeClientError("client must authenticate before placing orders")

    def _validate_read_only_request(self) -> None:
        if not self.config.account_number:
            raise TastytradeClientError("account_number is required")
        if not self.is_authenticated:
            raise TastytradeClientError("client must authenticate before read-only requests")

    @staticmethod
    def _read_data(response: httpx.Response, *, action: str) -> dict[str, Any]:
        if response.status_code >= 400:
            raise TastytradeClientError(f"{action} failed with status {response.status_code}")
        data = response.json().get("data")
        if not isinstance(data, dict):
            raise TastytradeClientError(f"{action} failed: response data was not an object")
        return data

    @staticmethod
    def _is_device_challenge_required(response: httpx.Response) -> bool:
        if response.status_code != 403:
            return False
        try:
            code = response.json().get("error", {}).get("code")
        except ValueError:
            return False
        return code == "device_challenge_required"
