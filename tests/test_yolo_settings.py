from datetime import date

from tasty_options_bot.yolo.settings import load_yolo_settings, parse_occ_option_symbol


def test_parse_occ_symbol_call():
    parsed = parse_occ_option_symbol("SMCI  260618C00030000")
    assert parsed is not None
    assert parsed.underlying_symbol == "SMCI"
    assert parsed.expiration == date(2026, 6, 18)
    assert parsed.option_type == "call"
    assert parsed.strike == 30.0


def test_parse_occ_symbol_put_fractional_strike():
    parsed = parse_occ_option_symbol("NVDA  261218P00117500")
    assert parsed is not None
    assert parsed.option_type == "put"
    assert parsed.strike == 117.5


def test_parse_occ_symbol_rejects_garbage():
    assert parse_occ_option_symbol("SMCI") is None
    assert parse_occ_option_symbol("") is None


def test_load_settings_missing_file_uses_defaults(tmp_path):
    settings = load_yolo_settings(tmp_path / "nope.yaml")
    assert settings.scanner.budget_per_play == 1000.0
    assert settings.exit_rules.stop_loss_pct == -50.0
    assert settings.thesis_dead_levels == {}


def test_load_settings_from_yaml(tmp_path):
    config = tmp_path / "yolo.yaml"
    config.write_text(
        "budget_per_play: 500\n"
        "delta_max: 0.60\n"
        "universe: [smci, nvda]\n"
        "exit_rules:\n"
        "  stop_loss_pct: -40\n"
        "  thesis_dead_levels:\n"
        "    smci: 27.0\n"
    )
    settings = load_yolo_settings(config)
    assert settings.scanner.budget_per_play == 500.0
    assert settings.scanner.delta_max == 0.60
    assert settings.scanner.universe == ["SMCI", "NVDA"]
    assert settings.exit_rules.stop_loss_pct == -40.0
    assert settings.thesis_dead_levels == {"SMCI": 27.0}


def test_repo_config_file_loads():
    settings = load_yolo_settings("config/yolo.yaml")
    assert settings.scanner.budget_per_play > 0
    assert "SMCI" in settings.thesis_dead_levels
