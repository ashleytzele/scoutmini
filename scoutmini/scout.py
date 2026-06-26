"""Orchestrator: route a question to an intent, fetch the data it needs, and
hand it to the LLM for a sourced report.

v1 keeps the data step deterministic by mapping each question to one of a small,
known set of intents (see the design spec, section 7). The router is intentionally
simple keyword/proper-noun matching — v2 replaces it with LLM function-calling.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import List

from . import f1_data, llm
from .config import Config


class UnsupportedQuestion(Exception):
    """The question type isn't wired up in v1 yet."""


class Intent(str, Enum):
    DRIVER_FORM = "driver_form"
    HEAD_TO_HEAD = "head_to_head"
    RACE_ANALYSIS = "race_analysis"
    STANDINGS = "standings"


# Words that are never a driver/race proper noun even when capitalised.
_STOPWORDS = {
    "how", "what", "who", "when", "where", "which", "why", "is", "are", "does",
    "do", "did", "show", "me", "the", "this", "that", "their", "his", "her",
    "season", "year", "compare", "vs", "versus", "and", "in", "of", "a", "an",
    "grand", "prix", "gp", "race", "results", "result", "form", "doing",
    "standings", "championship", "leading", "current", "tell", "about",
}

_PROPER_NOUN = re.compile(r"\b[A-Z][A-Za-z]+\b")

_STANDINGS_HINTS = ("standing", "championship", "leaderboard", "leading", "leader")
_RACE_HINTS = ("grand prix", " gp", "race")


@dataclass
class Route:
    intent: Intent
    subjects: List[str] = field(default_factory=list)


def _proper_nouns(question: str) -> List[str]:
    seen: List[str] = []
    for token in _PROPER_NOUN.findall(question):
        if token.lower() in _STOPWORDS:
            continue
        if token not in seen:
            seen.append(token)
    return seen


def route(question: str) -> Route:
    text = question.lower()
    subjects = _proper_nouns(question)

    if any(h in text for h in _STANDINGS_HINTS):
        return Route(Intent.STANDINGS, [])

    if " vs " in f" {text} " or "versus" in text:
        return Route(Intent.HEAD_TO_HEAD, subjects)
    if "compare" in text and len(subjects) >= 2:
        return Route(Intent.HEAD_TO_HEAD, subjects)

    if any(h in text for h in _RACE_HINTS):
        return Route(Intent.RACE_ANALYSIS, subjects)

    return Route(Intent.DRIVER_FORM, subjects)


# --- report assembly --------------------------------------------------------

@dataclass
class Report:
    question: str
    intent: Intent
    body: str
    sources: List[str] = field(default_factory=list)


def format_driver_season(season: f1_data.DriverSeason) -> str:
    """Render a DriverSeason as a compact, fact-dense block for the LLM.

    Only fetched numbers go in here — this block is the *entire* set of facts the
    model is allowed to use (the golden rule)."""
    d = season.driver
    lines = [f"Driver: {d.full_name} ({d.code}) — {season.season} season"]

    s = season.standing
    if s is not None:
        lines.append(
            f"Championship: P{s.position}, {s.points:g} points, "
            f"{s.wins} wins, team {s.constructor}"
        )
    lines.append(
        f"Season totals from results: {season.wins} wins, {season.podiums} podiums, "
        f"{len(season.results)} races"
    )
    lines.append("")
    lines.append("Race-by-race (round | race | grid -> finish | points | status):")
    for r in season.results:
        lines.append(
            f"  R{r.round:>2} | {r.race_name} | P{r.grid} -> P{r.position} "
            f"| {r.points:g} pts | {r.status}"
        )
    return "\n".join(lines)


def answer(
    question: str,
    config: Config,
    *,
    fetch_json=f1_data._default_fetch_json,
    client=None,
    analyze_fn=llm.analyze,
) -> Report:
    """Route the question, fetch the data it needs, and produce a sourced report.

    ``fetch_json``, ``client``, and ``analyze_fn`` are injectable for testing.
    """
    routed = route(question)

    if routed.intent is Intent.DRIVER_FORM:
        subject = routed.subjects[0] if routed.subjects else question
        season = f1_data.get_driver_season(
            subject, config.season, fetch_json=fetch_json
        )
        data_text = format_driver_season(season)
        if client is None:
            client = llm.make_client(config)
        body = analyze_fn(
            question,
            data_text,
            "\n".join(season.source_urls),
            model=config.model,
            client=client,
        )
        return Report(question, routed.intent, body, season.source_urls)

    raise UnsupportedQuestion(
        f"That looks like a '{routed.intent.value}' question. v1 of ScoutMini only "
        "answers driver-form questions so far (e.g. \"How is Norris doing this "
        "season?\"). Head-to-head, race analysis, and standings are coming next."
    )
