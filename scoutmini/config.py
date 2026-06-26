"""Configuration: load the OpenAI key and runtime settings.

Settings come from environment variables (typically loaded from a local ``.env``).
Keeping the source as a plain dict makes this trivially testable — no real ``.env``
or live key is needed to exercise the logic.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping, Optional

from dotenv import load_dotenv

DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_SEASON = 2024


class ConfigError(Exception):
    """Raised when configuration is missing or invalid."""


@dataclass(frozen=True)
class Config:
    """Resolved settings for a ScoutMini run."""

    openai_api_key: str
    model: str = DEFAULT_MODEL
    season: int = DEFAULT_SEASON


def load_config(env: Optional[Mapping[str, str]] = None) -> Config:
    """Build a :class:`Config` from environment variables.

    If ``env`` is omitted, the process environment is used (after loading a
    local ``.env`` file). Pass an explicit mapping in tests.
    """
    if env is None:
        load_dotenv()
        env = os.environ

    key = (env.get("OPENAI_API_KEY") or "").strip()
    if not key:
        raise ConfigError(
            "OPENAI_API_KEY is not set. Add it to a .env file in the project root "
            "(copy .env.example to .env and paste your key), or export it in your shell."
        )

    season_raw = (env.get("SCOUTMINI_SEASON") or "").strip()
    try:
        season = int(season_raw) if season_raw else DEFAULT_SEASON
    except ValueError as exc:
        raise ConfigError(
            f"SCOUTMINI_SEASON must be a year like 2024, got {season_raw!r}."
        ) from exc

    model = (env.get("SCOUTMINI_MODEL") or "").strip() or DEFAULT_MODEL

    return Config(openai_api_key=key, model=model, season=season)
