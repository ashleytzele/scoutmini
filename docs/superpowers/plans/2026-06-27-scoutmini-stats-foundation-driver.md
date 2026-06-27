# ScoutMini Phase 1a — Stats Foundation + Driver Tools — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an on-disk cache, a tool registry, and the first driver-stats tools (qualifying, career, driver profile) so the v2 agent and CLI can deeply "understand a driver."

**Architecture:** New `cache.py` wraps the Jolpica fetcher (immutable past seasons cached forever, current year short-TTL). New `toolspec.py` holds a `Tool` dataclass; `agent.py` is refactored so its `TOOLS` schema and `run_tool` dispatch are derived from a registry (adding a tool = one `Tool` entry). New `f1_stats.py` holds the driver-stats functions (reusing `f1_data` dataclasses/parsers/matchers) and exposes its tools as `STATS_TOOLS`. New CLI commands `qualifying` and `career` need no OpenAI key.

**Tech Stack:** Python 3.10+, `requests`, `typer`, `pytest`. Data from Jolpica-F1 (`https://api.jolpi.ca/ergast/f1`, Ergast-compatible).

## Global Constraints

- **Golden rule:** every data function returns the fetched data **plus** `source_urls`; nothing is invented. (verbatim from spec §1)
- **History:** Jolpica stats target **2014+**. (spec §2)
- **No live network in tests:** all fetching is via an injected `fetch_json`/`fetch_text`; tests use fakes/fixtures. (existing project convention, spec §4.6)
- **Reuse, don't duplicate:** new code reuses `f1_data`'s `BASE_URL`, `_to_int`/`_to_float`, `parse_drivers`, `parse_driver_results`, `parse_driver_standings`, `match_driver`, `get_race_meta`, and URL helpers. (spec §3.3, §4)
- **Run tests with:** `.venv/bin/python -m pytest` from repo root `/Users/leleditit/Desktop/Github/scout`.

---

## File Structure

- Create `scoutmini/cache.py` — on-disk JSON cache wrapper for the Jolpica fetcher.
- Create `scoutmini/toolspec.py` — the `Tool` dataclass (neutral module, breaks an import cycle).
- Create `scoutmini/f1_stats.py` — driver-stats dataclasses, parsers, fetchers, formatters, and `STATS_TOOLS`.
- Modify `scoutmini/agent.py` — derive `TOOLS`/`run_tool` from a registry built from core tools + `f1_stats.STATS_TOOLS`.
- Modify `scoutmini/cli.py` — add `qualifying` and `career` commands; wire the cache into the `agent` command.
- Tests: create `tests/test_cache.py`, `tests/test_f1_stats.py`; extend `tests/test_cli.py`. `tests/test_agent.py` must keep passing unchanged.
- Fixture: create `tests/fixtures/qualifying_monaco_2024.json`.

Deferred to **Phase 1b** (separate plan): `driver_head_to_head`, `get_driver_circuit_record`, all constructor/team tools, `get_schedule`/`get_circuit` reference tools, `match_constructor`.

---

## Task 1: On-disk cache (`cache.py`)

**Files:**
- Create: `scoutmini/cache.py`
- Test: `tests/test_cache.py`

**Interfaces:**
- Produces: `make_cached_fetch_json(*, fetch_json, cache_dir=".jolpi_cache", current_year, ttl=3600, now=time.time) -> Callable[[str], dict]` — a drop-in replacement for a `fetch_json(url)->dict` that caches to disk. Past seasons (year in URL `< current_year`) are cached indefinitely; current/other URLs use `ttl` seconds.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_cache.py
from scoutmini.cache import make_cached_fetch_json


def test_past_season_cached_forever(tmp_path):
    calls = []
    def fetch(url):
        calls.append(url)
        return {"v": 1}
    cached = make_cached_fetch_json(
        fetch_json=fetch, cache_dir=str(tmp_path), current_year=2026, now=lambda: 1000.0
    )
    url = "https://api.jolpi.ca/ergast/f1/2020/x.json"
    assert cached(url) == {"v": 1}
    assert cached(url) == {"v": 1}
    assert len(calls) == 1  # immutable past season -> fetched once


def test_current_season_respects_ttl(tmp_path):
    calls = []
    clock = [1000.0]
    def fetch(url):
        calls.append(url)
        return {"v": 1}
    cached = make_cached_fetch_json(
        fetch_json=fetch, cache_dir=str(tmp_path), current_year=2026, ttl=100,
        now=lambda: clock[0],
    )
    url = "https://api.jolpi.ca/ergast/f1/2026/x.json"
    cached(url)
    clock[0] = 1050.0
    cached(url)
    assert len(calls) == 1  # within ttl -> cached
    clock[0] = 1200.0
    cached(url)
    assert len(calls) == 2  # expired -> refetched
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_cache.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'scoutmini.cache'`

- [ ] **Step 3: Write minimal implementation**

```python
# scoutmini/cache.py
"""On-disk JSON cache for the Jolpica fetcher.

Past seasons are immutable, so once cached they never need refetching; the
current calendar year uses a short TTL. Keeps career/history fan-out cheap and
respects Jolpica rate limits. Returns a drop-in replacement for a
``fetch_json(url) -> dict`` callable, so it plugs into the existing injection.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from typing import Callable, Optional

DEFAULT_CACHE_DIR = ".jolpi_cache"
DEFAULT_TTL = 3600  # seconds, for current-season / non-dated URLs

_SEASON_RE = re.compile(r"/f1/(\d{4})(?:[/.]|$)")


def _season_in_url(url: str) -> Optional[int]:
    m = _SEASON_RE.search(url)
    return int(m.group(1)) if m else None


def _path_for(cache_dir: str, url: str) -> str:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]
    return os.path.join(cache_dir, f"{digest}.json")


def make_cached_fetch_json(
    *,
    fetch_json: Callable[[str], dict],
    current_year: int,
    cache_dir: str = DEFAULT_CACHE_DIR,
    ttl: int = DEFAULT_TTL,
    now: Callable[[], float] = time.time,
) -> Callable[[str], dict]:
    def cached(url: str) -> dict:
        path = _path_for(cache_dir, url)
        season = _season_in_url(url)
        immutable = season is not None and season < current_year

        if os.path.exists(path):
            with open(path) as fh:
                entry = json.load(fh)
            if immutable or (now() - entry["ts"] < ttl):
                return entry["data"]

        data = fetch_json(url)
        os.makedirs(cache_dir, exist_ok=True)
        with open(path, "w") as fh:
            json.dump({"ts": now(), "data": data}, fh)
        return data

    return cached
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_cache.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add scoutmini/cache.py tests/test_cache.py
git commit -m "feat: add on-disk Jolpica cache (immutable past seasons + TTL)"
```

---

## Task 2: Tool registry (`toolspec.py` + `agent.py` refactor)

Refactor the agent so `TOOLS` and `run_tool` are derived from a registry, without changing their public behavior (existing `tests/test_agent.py` must still pass).

**Files:**
- Create: `scoutmini/toolspec.py`
- Modify: `scoutmini/agent.py`
- Test: `tests/test_agent.py` (existing — must stay green; add one registry test)

**Interfaces:**
- Produces: `toolspec.Tool(name: str, description: str, parameters: dict, dispatch: Callable)` with method `schema() -> dict` returning `{"type": "function", "function": {"name", "description", "parameters"}}`. `dispatch(args: dict, *, season_default: int, fetch_json) -> tuple[str, list[str]]`.
- Produces: `agent.REGISTRY: list[Tool]`, with `agent.TOOLS` and `agent.run_tool` unchanged in signature/behavior.

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_agent.py
from scoutmini.toolspec import Tool


def test_registry_drives_tools_and_dispatch():
    from scoutmini.agent import REGISTRY, TOOLS
    assert all(isinstance(t, Tool) for t in REGISTRY)
    # TOOLS schema is derived from the registry, one per tool
    assert len(TOOLS) == len(REGISTRY)
    assert {t.name for t in REGISTRY} == {tt["function"]["name"] for tt in TOOLS}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_agent.py::test_registry_drives_tools_and_dispatch -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'scoutmini.toolspec'`

- [ ] **Step 3: Create `toolspec.py`**

```python
# scoutmini/toolspec.py
"""The Tool record shared by the agent registry and tool modules.

Kept in its own tiny module so tool modules (e.g. f1_stats) can declare tools
without importing agent.py, avoiding a circular import.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Tuple

# dispatch(args, *, season_default, fetch_json) -> (text_for_model, source_urls)
Dispatch = Callable[..., Tuple[str, List[str]]]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict
    dispatch: Dispatch

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }
```

- [ ] **Step 4: Refactor `agent.py` to use the registry**

Replace the existing `TOOLS = [...]` list and the `run_tool` function in `scoutmini/agent.py` with the registry below. Keep `run_tool`'s signature identical. (The dispatch bodies are the same calls the old `run_tool` made.)

```python
# scoutmini/agent.py — replace the `TOOLS = [...]` block and `run_tool` def with:
from .toolspec import Tool

def _d_get_driver_season(args, *, season_default, fetch_json):
    season = int(args.get("season") or season_default)
    ds = f1_data.get_driver_season(args["driver"], season, fetch_json=fetch_json)
    return format_driver_season(ds), list(ds.source_urls)

def _d_get_standings(args, *, season_default, fetch_json):
    season = int(args.get("season") or season_default)
    st = f1_data.get_standings(season, fetch_json=fetch_json)
    return format_standings(st), list(st.source_urls)

def _d_get_race(args, *, season_default, fetch_json):
    season = int(args.get("season") or season_default)
    ra = f1_data.get_race(args["race"], season, fetch_json=fetch_json)
    return format_race_analysis(ra), list(ra.source_urls)

CORE_TOOLS = [
    Tool("get_driver_season",
         "A driver's full season: every race result (grid vs finish, points, "
         "status) plus championship position, points, wins. Use for form, "
         "consistency, or single-driver questions.",
         {"type": "object",
          "properties": {"driver": {"type": "string", "description": "Driver name, e.g. 'Norris'."},
                         "season": {"type": "integer", "description": "Season year, e.g. 2024."}},
          "required": ["driver"]},
         _d_get_driver_season),
    Tool("get_standings",
         "The driver championship standings table (all drivers) for a season.",
         {"type": "object",
          "properties": {"season": {"type": "integer", "description": "Season year, e.g. 2024."}},
          "required": []},
         _d_get_standings),
    Tool("get_race",
         "Full classification of a single race: winner, pole, every driver's "
         "grid vs finish, and who retired. Use for 'what happened at <race>'.",
         {"type": "object",
          "properties": {"race": {"type": "string", "description": "Race name, e.g. 'Monaco'."},
                         "season": {"type": "integer", "description": "Season year, e.g. 2024."}},
          "required": ["race"]},
         _d_get_race),
]

from . import f1_stats  # noqa: E402  (provides STATS_TOOLS)

REGISTRY = CORE_TOOLS + f1_stats.STATS_TOOLS
TOOLS = [t.schema() for t in REGISTRY]


def run_tool(name, args, *, season_default, fetch_json):
    for tool in REGISTRY:
        if tool.name == name:
            return tool.dispatch(args, season_default=season_default, fetch_json=fetch_json)
    raise ValueError(f"Unknown tool: {name}")
```

NOTE: this step references `f1_stats.STATS_TOOLS`, created in Task 3. To keep Task 2 independently runnable, temporarily set `REGISTRY = CORE_TOOLS` and remove the `from . import f1_stats` line; Task 3 restores both lines. (Steps below assume that temporary form for Task 2's test run.)

- [ ] **Step 5: Run the full agent test file to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_agent.py -q`
Expected: PASS (8 passed — the 7 existing + the new registry test)

- [ ] **Step 6: Commit**

```bash
git add scoutmini/toolspec.py scoutmini/agent.py tests/test_agent.py
git commit -m "refactor: derive agent TOOLS/run_tool from a tool registry"
```

---

## Task 3: `get_qualifying` (`f1_stats.py`) + agent tool + CLI

**Files:**
- Create: `scoutmini/f1_stats.py`
- Create: `tests/fixtures/qualifying_monaco_2024.json`
- Create: `tests/test_f1_stats.py`
- Modify: `scoutmini/agent.py` (restore `from . import f1_stats` and `REGISTRY = CORE_TOOLS + f1_stats.STATS_TOOLS`)
- Modify: `scoutmini/cli.py` (add `qualifying` command)
- Test: `tests/test_cli.py` (add a command test)

**Interfaces:**
- Produces: `QualifyingResult(position:int, full_name:str, code:str, q1:str, q2:str, q3:str)`.
- Produces: `QualifyingSession(season:int, round:int, race_name:str, entries:list[QualifyingResult], source_urls:list[str])`.
- Produces: `parse_qualifying(payload: dict) -> list[QualifyingResult]`.
- Produces: `get_qualifying(race: str, season: int, *, fetch_json=f1_data._default_fetch_json) -> QualifyingSession`.
- Produces: `format_qualifying(q: QualifyingSession) -> str`.
- Produces: `STATS_TOOLS: list[Tool]` (starts with the qualifying tool).

- [ ] **Step 1: Create the fixture**

```json
{
  "MRData": {
    "RaceTable": {
      "season": "2024", "round": "8",
      "Races": [
        {
          "season": "2024", "round": "8", "raceName": "Monaco Grand Prix",
          "QualifyingResults": [
            {"position": "1", "Driver": {"driverId": "leclerc", "givenName": "Charles", "familyName": "Leclerc", "code": "LEC"}, "Q1": "1:11.5", "Q2": "1:10.9", "Q3": "1:10.270"},
            {"position": "2", "Driver": {"driverId": "piastri", "givenName": "Oscar", "familyName": "Piastri", "code": "PIA"}, "Q1": "1:11.7", "Q2": "1:11.0", "Q3": "1:10.424"}
          ]
        }
      ]
    }
  }
}
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_f1_stats.py
import pytest

from scoutmini.f1_stats import (
    QualifyingSession,
    format_qualifying,
    get_qualifying,
    parse_qualifying,
)


def test_parse_qualifying(fixture):
    entries = parse_qualifying(fixture("qualifying_monaco_2024.json"))
    assert len(entries) == 2
    assert entries[0].full_name == "Charles Leclerc"
    assert entries[0].code == "LEC"
    assert entries[0].q3 == "1:10.270"


def test_get_qualifying_resolves_round_and_assembles(fixture):
    def fetch_json(url):
        if url.endswith("/2024.json"):
            return fixture("schedule_2024.json")
        if "/8/qualifying" in url:
            return fixture("qualifying_monaco_2024.json")
        raise AssertionError(f"unexpected url: {url}")

    q = get_qualifying("Monaco", 2024, fetch_json=fetch_json)
    assert isinstance(q, QualifyingSession)
    assert q.round == 8
    assert q.race_name == "Monaco Grand Prix"
    assert len(q.entries) == 2
    assert q.source_urls


def test_format_qualifying_lists_pole(fixture):
    q = get_qualifying("Monaco", 2024, fetch_json=lambda u: (
        fixture("schedule_2024.json") if u.endswith("/2024.json")
        else fixture("qualifying_monaco_2024.json")))
    text = format_qualifying(q)
    assert "Charles Leclerc" in text
    assert "1:10.270" in text
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_f1_stats.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'scoutmini.f1_stats'`

- [ ] **Step 4: Create `f1_stats.py` with qualifying + the tools list**

```python
# scoutmini/f1_stats.py
"""Driver & team statistics over Jolpica-F1 (2014+).

Reuses f1_data's dataclasses, parsers, matchers, and URL helpers. Each public
fetcher returns a frozen dataclass carrying source_urls (golden rule). Tools are
exposed as STATS_TOOLS for the agent registry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from . import f1_data
from .f1_data import BASE_URL, FetchJson, _default_fetch_json, _to_int
from .toolspec import Tool


# --- qualifying -------------------------------------------------------------

@dataclass(frozen=True)
class QualifyingResult:
    position: int
    full_name: str
    code: str
    q1: str = ""
    q2: str = ""
    q3: str = ""


@dataclass(frozen=True)
class QualifyingSession:
    season: int
    round: int
    race_name: str
    entries: List[QualifyingResult]
    source_urls: List[str] = field(default_factory=list)


def parse_qualifying(payload: dict) -> List[QualifyingResult]:
    races = payload.get("MRData", {}).get("RaceTable", {}).get("Races", [])
    if not races:
        return []
    out: List[QualifyingResult] = []
    for r in races[0].get("QualifyingResults", []):
        d = r.get("Driver", {})
        out.append(
            QualifyingResult(
                position=_to_int(r.get("position")),
                full_name=f"{d.get('givenName', '')} {d.get('familyName', '')}".strip(),
                code=d.get("code", ""),
                q1=r.get("Q1", ""),
                q2=r.get("Q2", ""),
                q3=r.get("Q3", ""),
            )
        )
    return out


def _url_qualifying(season: int, rnd: int) -> str:
    return f"{BASE_URL}/{season}/{rnd}/qualifying.json"


def get_qualifying(
    race: str,
    season: int,
    *,
    fetch_json: FetchJson = _default_fetch_json,
) -> QualifyingSession:
    meta = f1_data.get_race_meta(race, season, fetch_json=fetch_json)
    url = _url_qualifying(season, meta.round)
    entries = parse_qualifying(fetch_json(url))
    if not entries:
        raise f1_data.DataNotAvailable(
            f"No qualifying data for the {meta.race_name} ({season}) yet."
        )
    return QualifyingSession(
        season=season, round=meta.round, race_name=meta.race_name,
        entries=entries, source_urls=[url, f"{BASE_URL}/{season}.json"],
    )


def format_qualifying(q: QualifyingSession) -> str:
    lines = [
        f"Qualifying — {q.race_name} {q.season} (round {q.round}):",
        "(pos | driver | Q1 | Q2 | Q3)",
    ]
    for e in q.entries:
        lines.append(f"  P{e.position:>2} | {e.full_name} ({e.code}) | {e.q1} | {e.q2} | {e.q3}")
    return "\n".join(lines)


# --- agent tool registrations ----------------------------------------------

def _d_get_qualifying(args, *, season_default, fetch_json):
    season = int(args.get("season") or season_default)
    q = get_qualifying(args["race"], season, fetch_json=fetch_json)
    return format_qualifying(q), list(q.source_urls)


STATS_TOOLS: List[Tool] = [
    Tool(
        "get_qualifying",
        "Qualifying / grid order for a single race (Q1-Q3 times, pole). Use for "
        "'who was on pole' or 'qualifying result' questions.",
        {"type": "object",
         "properties": {"race": {"type": "string", "description": "Race name, e.g. 'Monaco'."},
                        "season": {"type": "integer", "description": "Season year, e.g. 2024."}},
         "required": ["race"]},
        _d_get_qualifying,
    ),
]
```

- [ ] **Step 5: Restore the f1_stats wiring in `agent.py`**

In `scoutmini/agent.py`, ensure these two lines are present (replacing the Task 2 temporary `REGISTRY = CORE_TOOLS`):

```python
from . import f1_stats  # noqa: E402

REGISTRY = CORE_TOOLS + f1_stats.STATS_TOOLS
TOOLS = [t.schema() for t in REGISTRY]
```

- [ ] **Step 6: Run f1_stats + agent tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_f1_stats.py tests/test_agent.py -q`
Expected: PASS (qualifying tests + agent tests; `get_qualifying` now appears in `TOOLS`)

- [ ] **Step 7: Add the `qualifying` CLI command**

In `scoutmini/cli.py`, add imports and a command. Add near the other imports:

```python
from . import cache, f1_stats
from datetime import datetime
```

Add this command (after `pace`):

```python
@app.command()
def qualifying(
    race: str = typer.Argument(..., help="A race, e.g. Monaco."),
    season: int = typer.Option(DEFAULT_SEASON, help="Season year."),
) -> None:
    """Qualifying result for a race (no OpenAI key needed)."""
    fetch = cache.make_cached_fetch_json(
        fetch_json=f1_data._default_fetch_json, current_year=datetime.now().year
    )
    try:
        q = f1_stats.get_qualifying(race, season, fetch_json=fetch)
    except (RaceNotFound, DataNotAvailable) as exc:
        typer.secho(str(exc), fg=typer.colors.YELLOW, err=True)
        raise typer.Exit(code=1)
    except requests.exceptions.RequestException as exc:
        typer.secho(f"Could not reach the F1 data service: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    typer.echo(f1_stats.format_qualifying(q))
```

- [ ] **Step 8: Add a CLI test**

```python
# add to tests/test_cli.py
from scoutmini.f1_stats import QualifyingResult, QualifyingSession


def test_qualifying_command(monkeypatch):
    session = QualifyingSession(
        2024, 8, "Monaco Grand Prix",
        [QualifyingResult(1, "Charles Leclerc", "LEC", "1:11", "1:10.9", "1:10.270")],
        ["http://src/quali"],
    )
    monkeypatch.setattr(cli.f1_stats, "get_qualifying", lambda race, season, fetch_json: session)
    result = runner.invoke(cli.app, ["qualifying", "Monaco"])
    assert result.exit_code == 0
    assert "Charles Leclerc" in result.stdout
    assert "1:10.270" in result.stdout
```

- [ ] **Step 9: Run the full suite to verify everything passes**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS (all tests green)

- [ ] **Step 10: Commit**

```bash
git add scoutmini/f1_stats.py scoutmini/agent.py scoutmini/cli.py tests/test_f1_stats.py tests/test_cli.py tests/fixtures/qualifying_monaco_2024.json
git commit -m "feat: add get_qualifying tool (f1_stats) + agent tool + CLI"
```

---

## Task 4: `get_driver_career` (`f1_stats.py`) + agent tool + CLI

**Files:**
- Modify: `scoutmini/f1_stats.py`
- Modify: `scoutmini/cli.py` (add `career` command)
- Test: `tests/test_f1_stats.py`, `tests/test_cli.py`

**Interfaces:**
- Produces: `CareerSeason(season:int, team:str, races:int, wins:int, podiums:int, points:float, championship_position:int)`.
- Produces: `DriverCareer(driver:f1_data.Driver, seasons:list[CareerSeason], source_urls:list[str])` with properties `total_races`, `total_wins`, `total_podiums`, `total_points`, `titles`, `best_championship`.
- Produces: `get_driver_career(driver:str, since:int=2014, *, fetch_json=..., current_year:int|None=None) -> DriverCareer`.
- Produces: `format_driver_career(c: DriverCareer) -> str`.
- Consumes: `f1_data.parse_drivers`, `f1_data.match_driver`, `f1_data.parse_driver_results`, `f1_data.parse_driver_standings`, `f1_data._url_drivers`, `f1_data.DriverNotFound`, `f1_data.DataNotAvailable`.

- [ ] **Step 1: Write the failing tests**

```python
# add to tests/test_f1_stats.py
from scoutmini.f1_stats import DriverCareer, format_driver_career, get_driver_career
from scoutmini.f1_data import DriverNotFound


def _career_fetcher():
    """Two seasons (2023, 2024) for 'norris', empty otherwise."""
    drivers = {"MRData": {"DriverTable": {"Drivers": [
        {"driverId": "norris", "code": "NOR", "givenName": "Lando", "familyName": "Norris"}]}}}
    def results(pos, pts):
        return {"MRData": {"RaceTable": {"Races": [
            {"round": "1", "raceName": "R1", "date": "x",
             "Results": [{"position": pos, "points": pts, "grid": "3", "status": "Finished",
                          "Driver": {"driverId": "norris"}, "Constructor": {"name": "McLaren"}}]}]}}}
    def standing(pos, pts, wins):
        return {"MRData": {"StandingsTable": {"StandingsLists": [
            {"DriverStandings": [{"position": pos, "points": pts, "wins": wins,
              "Driver": {"driverId": "norris", "givenName": "Lando", "familyName": "Norris"},
              "Constructors": [{"name": "McLaren"}]}]}]}}}
    def fetch_json(url):
        if "/drivers.json" in url:
            return drivers
        if "/2023/drivers/norris/results" in url:
            return results("2", "205")
        if "/2024/drivers/norris/results" in url:
            return results("1", "374")
        if "/2023/drivers/norris/driverStandings" in url:
            return standing("6", "205", "0")
        if "/2024/drivers/norris/driverStandings" in url:
            return standing("2", "374", "4")
        return {"MRData": {"RaceTable": {"Races": []}}}  # other seasons: no data
    return fetch_json


def test_get_driver_career_aggregates(fixture):
    c = get_driver_career("Norris", since=2023, fetch_json=_career_fetcher(), current_year=2024)
    assert isinstance(c, DriverCareer)
    assert [s.season for s in c.seasons] == [2023, 2024]
    assert c.total_wins == 1            # one P1 across the two seasons
    assert c.total_points == 579.0      # 205 + 374
    assert c.best_championship == 2     # best (lowest) championship position
    assert c.seasons[1].team == "McLaren"


def test_get_driver_career_unknown_driver():
    def fetch_json(url):
        return {"MRData": {"DriverTable": {"Drivers": []}}}
    with pytest.raises(DriverNotFound):
        get_driver_career("Nobody", since=2023, fetch_json=fetch_json, current_year=2024)


def test_format_driver_career_has_totals():
    c = get_driver_career("Norris", since=2023, fetch_json=_career_fetcher(), current_year=2024)
    text = format_driver_career(c)
    assert "Lando Norris" in text
    assert "579" in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_f1_stats.py -k career -q`
Expected: FAIL with `ImportError: cannot import name 'get_driver_career'`

- [ ] **Step 3: Add the implementation to `f1_stats.py`**

Add these imports at the top of `f1_stats.py` (extend the existing import line):

```python
from datetime import datetime
from typing import List, Optional
```

Add before the `# --- agent tool registrations ---` section:

```python
# --- driver career ----------------------------------------------------------

@dataclass(frozen=True)
class CareerSeason:
    season: int
    team: str
    races: int
    wins: int
    podiums: int
    points: float
    championship_position: int  # 0 = unknown


@dataclass(frozen=True)
class DriverCareer:
    driver: f1_data.Driver
    seasons: List[CareerSeason]
    source_urls: List[str] = field(default_factory=list)

    @property
    def total_races(self) -> int:
        return sum(s.races for s in self.seasons)

    @property
    def total_wins(self) -> int:
        return sum(s.wins for s in self.seasons)

    @property
    def total_podiums(self) -> int:
        return sum(s.podiums for s in self.seasons)

    @property
    def total_points(self) -> float:
        return sum(s.points for s in self.seasons)

    @property
    def titles(self) -> int:
        return sum(1 for s in self.seasons if s.championship_position == 1)

    @property
    def best_championship(self) -> int:
        finishes = [s.championship_position for s in self.seasons if s.championship_position > 0]
        return min(finishes) if finishes else 0


def _this_year() -> int:
    return datetime.now().year


def _url_driver_standings_for(driver_id: str, season: int) -> str:
    return f"{BASE_URL}/{season}/drivers/{driver_id}/driverStandings.json"


def _resolve_driver(query: str, since: int, current_year: int, fetch_json: FetchJson) -> f1_data.Driver:
    for year in range(current_year, since - 1, -1):
        drivers = f1_data.parse_drivers(fetch_json(f1_data._url_drivers(year)))
        try:
            return f1_data.match_driver(query, drivers)
        except f1_data.DriverNotFound:
            continue
    raise f1_data.DriverNotFound(
        f"Could not find a driver matching {query!r} in seasons {since}-{current_year}."
    )


def get_driver_career(
    query: str,
    since: int = 2014,
    *,
    fetch_json: FetchJson = _default_fetch_json,
    current_year: Optional[int] = None,
) -> DriverCareer:
    cy = current_year or _this_year()
    driver = _resolve_driver(query, since, cy, fetch_json)

    seasons: List[CareerSeason] = []
    sources: List[str] = []
    for year in range(since, cy + 1):
        results_url = f1_data._url_driver_results(driver.driver_id, year)
        results = f1_data.parse_driver_results(fetch_json(results_url))
        if not results:
            continue  # driver didn't race this season
        standings_url = _url_driver_standings_for(driver.driver_id, year)
        standing_list = f1_data.parse_driver_standings(fetch_json(standings_url))
        standing = standing_list[0] if standing_list else None
        seasons.append(
            CareerSeason(
                season=year,
                team=standing.constructor if standing else "",
                races=len(results),
                wins=sum(1 for r in results if r.position == 1),
                podiums=sum(1 for r in results if 1 <= r.position <= 3),
                points=standing.points if standing else 0.0,
                championship_position=standing.position if standing else 0,
            )
        )
        sources.extend([results_url, standings_url])

    if not seasons:
        raise f1_data.DataNotAvailable(
            f"No race data for {driver.full_name} in {since}-{cy}."
        )
    return DriverCareer(driver=driver, seasons=seasons, source_urls=sources)


def format_driver_career(c: DriverCareer) -> str:
    span = f"{c.seasons[0].season}-{c.seasons[-1].season}"
    lines = [
        f"{c.driver.full_name} ({c.driver.code}) — career {span}:",
        (f"Totals: {c.total_races} races, {c.total_wins} wins, {c.total_podiums} "
         f"podiums, {c.total_points:g} pts, {c.titles} titles, best championship "
         f"P{c.best_championship}"),
        "(season | team | races | wins | podiums | pts | championship)",
    ]
    for s in c.seasons:
        lines.append(
            f"  {s.season} | {s.team} | {s.races} | {s.wins} | {s.podiums} | "
            f"{s.points:g} | P{s.championship_position}"
        )
    return "\n".join(lines)
```

- [ ] **Step 4: Register the career tool**

Add this dispatch and append to `STATS_TOOLS` in `f1_stats.py`:

```python
def _d_get_driver_career(args, *, season_default, fetch_json):
    c = get_driver_career(args["driver"], int(args.get("since", 2014)), fetch_json=fetch_json)
    return format_driver_career(c), list(c.source_urls)
```

Append to the `STATS_TOOLS` list:

```python
    Tool(
        "get_driver_career",
        "A driver's career across seasons (2014+): per-season team, races, wins, "
        "podiums, points, championship finish, plus totals. Use for 'career', "
        "'how many wins', or multi-season questions.",
        {"type": "object",
         "properties": {"driver": {"type": "string", "description": "Driver name, e.g. 'Hamilton'."},
                        "since": {"type": "integer", "description": "First season to include (>=2014)."}},
         "required": ["driver"]},
        _d_get_driver_career,
    ),
```

- [ ] **Step 5: Run f1_stats + agent tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_f1_stats.py tests/test_agent.py -q`
Expected: PASS

- [ ] **Step 6: Add the `career` CLI command**

In `scoutmini/cli.py`, add (after `qualifying`):

```python
@app.command()
def career(
    name: str = typer.Argument(..., help="A driver's name, e.g. Hamilton."),
    since: int = typer.Option(2014, help="First season to include (>=2014)."),
) -> None:
    """A driver's multi-season career stats (no OpenAI key needed)."""
    fetch = cache.make_cached_fetch_json(
        fetch_json=f1_data._default_fetch_json, current_year=datetime.now().year
    )
    try:
        c = f1_stats.get_driver_career(name, since, fetch_json=fetch)
    except (DriverNotFound, DataNotAvailable) as exc:
        typer.secho(str(exc), fg=typer.colors.YELLOW, err=True)
        raise typer.Exit(code=1)
    except requests.exceptions.RequestException as exc:
        typer.secho(f"Could not reach the F1 data service: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    typer.echo(f1_stats.format_driver_career(c))
```

- [ ] **Step 7: Add a CLI test**

```python
# add to tests/test_cli.py
from scoutmini.f1_stats import CareerSeason, DriverCareer
from scoutmini.f1_data import Driver as _Driver


def test_career_command(monkeypatch):
    c = DriverCareer(
        _Driver("norris", "NOR", "Lando", "Norris"),
        [CareerSeason(2024, "McLaren", 24, 4, 13, 374.0, 2)],
        ["http://src/career"],
    )
    monkeypatch.setattr(cli.f1_stats, "get_driver_career", lambda name, since, fetch_json: c)
    result = runner.invoke(cli.app, ["career", "Norris"])
    assert result.exit_code == 0
    assert "Lando Norris" in result.stdout
    assert "McLaren" in result.stdout
```

- [ ] **Step 8: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS (all green)

- [ ] **Step 9: Commit**

```bash
git add scoutmini/f1_stats.py scoutmini/cli.py tests/test_f1_stats.py tests/test_cli.py
git commit -m "feat: add get_driver_career tool (f1_stats) + agent tool + CLI"
```

---

## Task 5: `driver_profile` curated tool (`f1_stats.py`) + agent tool

A single high-level tool combining career + current season, for "tell me about <driver>".

**Files:**
- Modify: `scoutmini/f1_stats.py`
- Test: `tests/test_f1_stats.py`

**Interfaces:**
- Produces: `DriverProfile(career:DriverCareer, current_season:Optional[f1_data.DriverSeason], source_urls:list[str])`.
- Produces: `get_driver_profile(driver:str, *, fetch_json=..., current_year:int|None=None) -> DriverProfile`.
- Produces: `format_driver_profile(p: DriverProfile) -> str`.
- Consumes: `get_driver_career`, `f1_data.get_driver_season`, `format_driver_career`, `f1_data.DataNotAvailable`.

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_f1_stats.py
from scoutmini.f1_stats import DriverProfile, format_driver_profile, get_driver_profile


def test_get_driver_profile_combines_career_and_current(fixture):
    def fetch_json(url):
        # career path (2023-2024) via the career fetcher
        base = _career_fetcher()
        if "driverStandings.json" in url and "/drivers/norris/" not in url:
            # season-wide standings used by get_driver_season
            return fixture("driver_standings_2024.json")
        if "/drivers.json" in url:
            return fixture("drivers_2024.json")
        if "/2024/drivers/norris/results" in url:
            return fixture("norris_results_2024.json")
        return base(url)

    p = get_driver_profile("Norris", fetch_json=fetch_json, current_year=2024)
    assert isinstance(p, DriverProfile)
    assert p.career.total_points > 0
    assert p.source_urls
    text = format_driver_profile(p)
    assert "Lando Norris" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_f1_stats.py -k profile -q`
Expected: FAIL with `ImportError: cannot import name 'get_driver_profile'`

- [ ] **Step 3: Add the implementation to `f1_stats.py`**

Add before the agent-tool section:

```python
# --- driver profile (curated) ----------------------------------------------

@dataclass(frozen=True)
class DriverProfile:
    career: DriverCareer
    current_season: Optional[f1_data.DriverSeason]
    source_urls: List[str] = field(default_factory=list)


def get_driver_profile(
    driver: str,
    *,
    fetch_json: FetchJson = _default_fetch_json,
    current_year: Optional[int] = None,
) -> DriverProfile:
    cy = current_year or _this_year()
    career = get_driver_career(driver, fetch_json=fetch_json, current_year=cy)
    try:
        current = f1_data.get_driver_season(driver, cy, fetch_json=fetch_json)
    except f1_data.DataNotAvailable:
        current = None
    sources = list(career.source_urls)
    if current:
        sources.extend(current.source_urls)
    return DriverProfile(career=career, current_season=current,
                         source_urls=list(dict.fromkeys(sources)))


def format_driver_profile(p: DriverProfile) -> str:
    parts = [format_driver_career(p.career)]
    if p.current_season:
        from .scout import format_driver_season  # local import avoids a cycle
        parts.append("\nCurrent season:\n" + format_driver_season(p.current_season))
    return "\n".join(parts)
```

- [ ] **Step 4: Register the profile tool**

Add the dispatch and append to `STATS_TOOLS`:

```python
def _d_get_driver_profile(args, *, season_default, fetch_json):
    p = get_driver_profile(args["driver"], fetch_json=fetch_json)
    return format_driver_profile(p), list(p.source_urls)
```

```python
    Tool(
        "driver_profile",
        "A rounded profile of a driver: full career totals/seasons plus their "
        "current season. Use for open-ended 'tell me about <driver>' questions.",
        {"type": "object",
         "properties": {"driver": {"type": "string", "description": "Driver name, e.g. 'Verstappen'."}},
         "required": ["driver"]},
        _d_get_driver_profile,
    ),
```

- [ ] **Step 5: Run the full suite to verify it passes**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS (all green)

- [ ] **Step 6: Commit**

```bash
git add scoutmini/f1_stats.py tests/test_f1_stats.py
git commit -m "feat: add curated driver_profile tool (career + current season)"
```

---

## Task 6: Wire the cache into the live `agent` command

So real agent runs benefit from caching (tests still inject their own fetchers).

**Files:**
- Modify: `scoutmini/cli.py` (the `agent` command)

**Interfaces:**
- Consumes: `cache.make_cached_fetch_json`, `agent.run_agent` (already accepts `fetch_json`).

- [ ] **Step 1: Update the `agent` command**

In `scoutmini/cli.py`, change the `run_agent(question, config)` call inside the `agent` command to pass a cached fetcher:

```python
    fetch = cache.make_cached_fetch_json(
        fetch_json=f1_data._default_fetch_json, current_year=datetime.now().year
    )
    try:
        result = run_agent(question, config, fetch_json=fetch)
```

- [ ] **Step 2: Run the full suite to verify nothing broke**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS (all green — the agent CLI test monkeypatches `run_agent`, so the new `fetch_json` arg is ignored there)

- [ ] **Step 3: Commit**

```bash
git add scoutmini/cli.py
git commit -m "feat: cache Jolpica calls in the agent command"
```

---

## Self-Review (completed)

- **Spec coverage (Phase 1a slice):** cache (§3.2) → Task 1; tool registry (§3.1) → Task 2; `get_qualifying` (§4.1) → Task 3; `get_driver_career` (§4.1) → Task 4; `driver_profile` (§4.1) → Task 5; cache wired to agent → Task 6. Deferred (driver_head_to_head, circuit_record, all team tools, reference tools, match_constructor) are explicitly listed for Phase 1b — not gaps.
- **Placeholders:** none — every code/test step contains complete code.
- **Type consistency:** `Tool(name, description, parameters, dispatch)` + `schema()` used consistently; dispatch signature `(args, *, season_default, fetch_json) -> (str, list[str])` matches `run_tool`; `get_driver_career(..., current_year=None)` and cache `current_year` are threaded consistently; `STATS_TOOLS` referenced by `agent.REGISTRY`.
- **Import-cycle check:** `toolspec` imports nothing internal; `f1_stats` imports `f1_data`, `toolspec` (and `scout.format_driver_season` lazily inside a function); `agent` imports `f1_stats`. No cycle.

## Notes for the implementer

- Task 2 has a temporary `REGISTRY = CORE_TOOLS` form so it runs standalone; Task 3 Step 5 restores the `f1_stats` wiring. Do them in order.
- The `.jolpi_cache/` directory should be added to `.gitignore` (one line) when you first run a cached command — include it in Task 1's commit if you prefer.
