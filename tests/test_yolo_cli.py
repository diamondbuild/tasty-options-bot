import json

from typer.testing import CliRunner

from tasty_options_bot.cli import app


class FakeScanClient:
    session_token = "token"

    def __init__(self):
        self.chain_requests = []

    def get_nested_option_chain(self, symbol):
        self.chain_requests.append(symbol)
        return [
            {
                "underlying-symbol": symbol,
                "expirations": [
                    {
                        "expiration-date": "2026-06-26",
                        "days-to-expiration": 15,
                        "strikes": [
                            {
                                "strike-price": "30.0",
                                "call": f"{symbol}  260626C00030000",
                                "call-streamer-symbol": f".{symbol}260626C30",
                                "put": f"{symbol}  260626P00030000",
                                "put-streamer-symbol": f".{symbol}260626P30",
                            }
                        ],
                    }
                ],
            }
        ]

    def get_equity_option_market_data(self, symbols, **kwargs):
        from datetime import datetime, timezone

        now_iso = datetime.now(timezone.utc).isoformat()
        return [
            {
                "symbol": symbol,
                "bid": "1.30",
                "ask": "1.40",
                "mark": "1.35",
                "delta": "0.42",
                "updated-at": now_iso,
            }
            for symbol in symbols
        ]


def test_yolo_scan_finds_candidate_and_previews_ticket(monkeypatch, tmp_path):
    client = FakeScanClient()
    monkeypatch.setattr("tasty_options_bot.cli.build_tastytrade_client", lambda: client)
    monkeypatch.setattr("tasty_options_bot.cli.authenticate_client", lambda c: None)
    journal_path = tmp_path / "journal.jsonl"

    result = CliRunner().invoke(
        app,
        [
            "yolo-scan",
            "--symbol", "SMCI",
            "--journal-path", str(journal_path),
            "--yolo-config-path", str(tmp_path / "missing-yolo.yaml"),
        ],
    )

    assert result.exit_code == 0, result.output
    assert client.chain_requests == ["SMCI"]
    assert "Long Call (YOLO)" in result.output
    assert "SMCI  260626C00030000" in result.output
    assert "preview_only_not_submitted" in result.output
    assert "No orders were placed" in result.output

    events = [json.loads(line) for line in journal_path.read_text().splitlines()]
    assert events[0]["event_type"] == "yolo_scan"
    assert events[0]["decision"] == "candidates_found"


def test_yolo_scan_rejects_bad_option_type(monkeypatch):
    result = CliRunner().invoke(app, ["yolo-scan", "--option-type", "straddle"])
    assert result.exit_code != 0


def test_yolo_positions_reports_hold(monkeypatch, tmp_path):
    class FakePositionsClient(FakeScanClient):
        class config:  # noqa: N801 - mimic client attribute
            base_url = "https://example.invalid"

        authorization_headers = {"Authorization": "token"}

        def get_positions(self):
            return [
                {
                    "symbol": "SMCI  260626C00030000",
                    "instrument-type": "Equity Option",
                    "quantity-direction": "Long",
                    "quantity": "9",
                    "average-open-price": "1.43",
                }
            ]

    client = FakePositionsClient()
    monkeypatch.setattr("tasty_options_bot.cli.build_tastytrade_client", lambda: client)
    monkeypatch.setattr("tasty_options_bot.cli.authenticate_client", lambda c: None)
    journal_path = tmp_path / "journal.jsonl"

    result = CliRunner().invoke(
        app,
        [
            "yolo-positions",
            "--journal-path", str(journal_path),
            "--yolo-config-path", str(tmp_path / "missing-yolo.yaml"),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Recommendation:" in result.output
    assert "no orders were placed" in result.output.lower()

    events = [json.loads(line) for line in journal_path.read_text().splitlines()]
    assert events[0]["event_type"] == "yolo_position_check"


def test_yolo_positions_no_long_options(monkeypatch, tmp_path):
    class EmptyClient(FakeScanClient):
        def get_positions(self):
            return []

    monkeypatch.setattr("tasty_options_bot.cli.build_tastytrade_client", lambda: EmptyClient())
    monkeypatch.setattr("tasty_options_bot.cli.authenticate_client", lambda c: None)

    result = CliRunner().invoke(
        app,
        ["yolo-positions", "--yolo-config-path", str(tmp_path / "missing.yaml")],
    )
    assert result.exit_code == 0, result.output
    assert "No open long-option positions" in result.output
