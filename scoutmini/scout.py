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


def format_standings(standings: f1_data.Standings) -> str:
    """Render the championship table as a compact fact block for the LLM."""
    lines = [f"Driver championship standings — {standings.season} season:"]
    lines.append("(position | driver | points | wins | team)")
    for s in standings.drivers:
        lines.append(
            f"  P{s.position:>2} | {s.full_name} | {s.points:g} pts | "
            f"{s.wins} wins | {s.constructor}"
        )
    return "\n".join(lines)


def format_head_to_head(a: f1_data.DriverSeason, b: f1_data.DriverSeason) -> str:
    """Render two drivers' seasons side by side as a fact block for the LLM."""
    season = a.season
    lines = [
        f"Head-to-head — {a.driver.full_name} vs {b.driver.full_name}, "
        f"{season} season:",
        "",
    ]
    for s in (a, b):
        pos = f"P{s.standing.position}" if s.standing else "n/a"
        pts = f"{s.standing.points:g}" if s.standing else "n/a"
        lines.append(
            f"{s.driver.full_name}: championship {pos}, {pts} pts, "
            f"{s.wins} wins, {s.podiums} podiums, {len(s.results)} races"
        )
    lines.append("")
    lines.append("Race-by-race finishes (round | race | "
                 f"{a.driver.code} | {b.driver.code}):")
    by_round_b = {r.round: r for r in b.results}
    for ra in a.results:
        rb = by_round_b.get(ra.round)
        b_pos = f"P{rb.position}" if rb else "-"
        lines.append(f"  R{ra.round:>2} | {ra.race_name} | P{ra.position} | {b_pos}")
    return "\n".join(lines)


def _is_finisher(entry: f1_data.RaceEntry) -> bool:
    return entry.is_classified


def format_race_analysis(race: f1_data.RaceAnalysis) -> str:
    """Render a single race's classification + a few computed highlights."""
    m = race.meta
    lines = [
        f"{m.race_name} ({m.country}), round {m.round}, {m.date} — {m.circuit_name}",
        "",
    ]

    finishers = [e for e in race.entries if _is_finisher(e)]
    pole = next((e for e in race.entries if e.grid == 1), None)
    if pole:
        lines.append(f"Pole (started P1): {pole.full_name} ({pole.constructor})")
    if finishers:
        mover = max(finishers, key=lambda e: e.places_gained)
        if mover.places_gained > 0:
            lines.append(
                f"Biggest climber: {mover.full_name} "
                f"P{mover.grid} -> P{mover.position} (+{mover.places_gained})"
            )
    dnfs = [e for e in race.entries if not _is_finisher(e)]
    if dnfs:
        lines.append(
            "Did not finish: "
            + ", ".join(f"{e.full_name} ({e.status})" for e in dnfs)
        )

    lines.append("")
    lines.append("Full classification (finish | driver | team | grid | status):")
    for e in race.entries:
        lines.append(
            f"  P{e.position:>2} | {e.full_name} | {e.constructor} "
            f"| started P{e.grid} | {e.status}"
        )
    return "\n".join(lines)


def format_news(items) -> str:
    """Render recent headlines as a clearly-labelled context block."""
    lines = ["Recent F1 news headlines (context — cite by title only if relevant):"]
    for it in items:
        when = f" ({it.published})" if it.published else ""
        lines.append(f"  - {it.title}{when} — {it.link}")
    return "\n".join(lines)


def answer(
    question: str,
    config: Config,
    *,
    fetch_json=f1_data._default_fetch_json,
    client=None,
    analyze_fn=llm.analyze,
    news_fn=None,
) -> Report:
    """Route the question, fetch the data it needs, and produce a sourced report.

    ``fetch_json``, ``client``, ``analyze_fn``, and ``news_fn`` are injectable for
    testing. ``news_fn`` (e.g. ``news.get_news``) is optional — when given, recent
    headlines are appended to the data block and their links added to the sources.
    """
    routed = route(question)

    def finish(data_text: str, sources, news_query):
        sources = list(sources)
        if news_fn is not None:
            items = news_fn(news_query)
            if items:
                data_text = data_text + "\n\n" + format_news(items)
                sources = list(dict.fromkeys(sources + [it.link for it in items if it.link]))
        nonlocal client
        if client is None:
            client = llm.make_client(config)
        body = analyze_fn(
            question, data_text, "\n".join(sources), model=config.model, client=client
        )
        return Report(question, routed.intent, body, sources)

    if routed.intent is Intent.DRIVER_FORM:
        subject = routed.subjects[0] if routed.subjects else question
        season = f1_data.get_driver_season(subject, config.season, fetch_json=fetch_json)
        return finish(format_driver_season(season), season.source_urls, season.driver.full_name)

    if routed.intent is Intent.STANDINGS:
        standings = f1_data.get_standings(config.season, fetch_json=fetch_json)
        return finish(format_standings(standings), standings.source_urls, None)

    if routed.intent is Intent.HEAD_TO_HEAD:
        if len(routed.subjects) < 2:
            raise UnsupportedQuestion(
                "Head-to-head needs two drivers, e.g. \"Leclerc vs Norris\"."
            )
        a = f1_data.get_driver_season(routed.subjects[0], config.season, fetch_json=fetch_json)
        b = f1_data.get_driver_season(routed.subjects[1], config.season, fetch_json=fetch_json)
        sources = list(dict.fromkeys(a.source_urls + b.source_urls))  # dedup, keep order
        return finish(format_head_to_head(a, b), sources, a.driver.full_name)

    if routed.intent is Intent.RACE_ANALYSIS:
        if not routed.subjects:
            raise UnsupportedQuestion(
                "Which race? Name it, e.g. \"What decided the Monaco Grand Prix?\"."
            )
        race = f1_data.get_race(" ".join(routed.subjects), config.season, fetch_json=fetch_json)
        return finish(format_race_analysis(race), race.source_urls, race.meta.race_name)

    raise UnsupportedQuestion(
        f"ScoutMini can't answer that kind of question yet ('{routed.intent.value}'). "
        "Try driver form (\"How is Norris doing?\"), a head-to-head "
        "(\"Leclerc vs Norris\"), standings, or a race (\"what decided Monaco?\")."
    )
