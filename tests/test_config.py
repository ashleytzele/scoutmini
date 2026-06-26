import pytest

from scoutmini.config import Config, ConfigError, load_config


def test_load_config_reads_key_and_applies_defaults():
    cfg = load_config(env={"OPENAI_API_KEY": "sk-test"})

    assert isinstance(cfg, Config)
    assert cfg.openai_api_key == "sk-test"
    assert cfg.model == "gpt-4o-mini"
    assert cfg.season == 2024


def test_load_config_allows_overrides():
    cfg = load_config(
        env={
            "OPENAI_API_KEY": "sk-test",
            "SCOUTMINI_MODEL": "gpt-4o",
            "SCOUTMINI_SEASON": "2025",
        }
    )

    assert cfg.model == "gpt-4o"
    assert cfg.season == 2025


def test_load_config_missing_key_raises_clear_error():
    with pytest.raises(ConfigError) as exc:
        load_config(env={})

    message = str(exc.value)
    assert "OPENAI_API_KEY" in message
    assert ".env" in message


def test_load_config_blank_key_is_treated_as_missing():
    with pytest.raises(ConfigError):
        load_config(env={"OPENAI_API_KEY": "   "})
