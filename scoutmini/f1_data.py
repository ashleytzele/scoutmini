"""F1 data adapter over the Ergast-compatible Jolpica-F1 API.

This is the first *sport adapter*. Other sports get their own module exposing the
same shape of functions ("one engine, many sports"). The public surface here:

  * pure parsers   — turn raw API JSON into clean dataclasses (easy to unit-test)
  * matchers       — resolve a human name ("Norris") to an Ergast driverId
  * fetch helpers  — hit the live API and assemble structured results

Network access is injected (``fetch_json``) so the orchestration can be tested
against saved fixtures without live calls.

Ergast was frozen; Jolpica-F1 is the maintained, drop-in successor with the same
JSON schema. Docs: https://github.com/jolpica/jolpica-f1
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Optional

import requests

BASE_URL = "https://api.jolpi.ca/ergast/f1"
_TIMEOUT = 20

FetchJson = Callable[[str], dict]


# --- errors -----------------------------------------------------------------

class DriverNotFound(Exception):
    """The requested driver could not be matched to a known entry."""


class DataNotAvailable(Exception):
    """The data we need does not exist yet (e.g. a season with no results)."""


# --- data shapes ------------------------------------------------------------

@dataclass(frozen=True)
class Driver:
    driver_id: str
    code: str
    given_name: str
    family_name: str

    @property
    def full_name(self) -> str:
        return f"{self.given_name} {self.family_name}".strip()


@dataclass(frozen=True)
class DriverStanding:
    position: int
    driver_id: str
    full_name: str
    points: float
    wins: int
    constructor: str


@dataclass(frozen=True)
class RaceResult:
    round: int
    race_name: str
    date: str
    grid: int
    position: int
    points: float
    status: str


@dataclass(frozen=True)
class Standings:
    season: int
    drivers: List[DriverStanding]
    source_urls: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class DriverSeason:
    driver: Driver
    season: int
    results: List[RaceResult]
    standing: Optional[DriverStanding] = None
    source_urls: List[str] = field(default_factory=list)

    @property
    def wins(self) -> int:
        return sum(1 for r in self.results if r.position == 1)

    @property
    def podiums(self) -> int:
        return sum(1 for r in self.results if 1 <= r.position <= 3)


# --- helpers ----------------------------------------------------------------

def _to_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# --- pure parsers -----------------------------------------------------------

def parse_drivers(payload: dict) -> List[Driver]:
    raw = payload.get("MRData", {}).get("DriverTable", {}).get("Drivers", [])
    return [
        Driver(
            driver_id=d.get("driverId", ""),
            code=d.get("code", ""),
            given_name=d.get("givenName", ""),
            family_name=d.get("familyName", ""),
        )
        for d in raw
    ]


def parse_driver_standings(payload: dict) -> List[DriverStanding]:
    lists = payload.get("MRData", {}).get("StandingsTable", {}).get("StandingsLists", [])
    if not lists:
        return []
    rows = lists[0].get("DriverStandings", [])
    out: List[DriverStanding] = []
    for row in rows:
        driver = row.get("Driver", {})
        constructors = row.get("Constructors", [])
        out.append(
            DriverStanding(
                position=_to_int(row.get("position")),
                driver_id=driver.get("driverId", ""),
                full_name=f"{driver.get('givenName', '')} {driver.get('familyName', '')}".strip(),
                points=_to_float(row.get("points")),
                wins=_to_int(row.get("wins")),
                constructor=constructors[0].get("name", "") if constructors else "",
            )
        )
    return out


def parse_driver_results(payload: dict) -> List[RaceResult]:
    races = payload.get("MRData", {}).get("RaceTable", {}).get("Races", [])
    out: List[RaceResult] = []
    for race in races:
        results = race.get("Results", [])
        if not results:
            continue
        res = results[0]
        out.append(
            RaceResult(
                round=_to_int(race.get("round")),
                race_name=race.get("raceName", ""),
                date=race.get("date", ""),
                grid=_to_int(res.get("grid")),
                position=_to_int(res.get("position")),
                points=_to_float(res.get("points")),
                status=res.get("status", ""),
            )
        )
    return out


# --- matchers ---------------------------------------------------------------

def match_driver(query: str, drivers: List[Driver]) -> Driver:
    """Resolve a free-text driver query against a known driver list.

    Matches (case-insensitively) on family name, full name, three-letter code,
    or Ergast driverId. Raises :class:`DriverNotFound` with suggestions otherwise.
    """
    q = query.strip().lower()
    for d in drivers:
        candidates = {
            d.family_name.lower(),
            d.full_name.lower(),
            d.code.lower(),
            d.driver_id.lower(),
        }
        if q in candidates:
            return d
    # fall back to a loose contains-match on family name before giving up
    for d in drivers:
        if q and q in d.family_name.lower():
            return d

    suggestions = ", ".join(d.full_name for d in drivers[:8])
    raise DriverNotFound(
        f"Could not find a driver matching {query!r}. "
        f"Some drivers this season: {suggestions}."
    )


# --- URLs -------------------------------------------------------------------

def _url_drivers(season: int) -> str:
    return f"{BASE_URL}/{season}/drivers.json?limit=100"


def _url_driver_results(driver_id: str, season: int) -> str:
    return f"{BASE_URL}/{season}/drivers/{driver_id}/results.json?limit=100"


def _url_driver_standings(season: int) -> str:
    return f"{BASE_URL}/{season}/driverStandings.json"


# --- live fetch -------------------------------------------------------------

def _default_fetch_json(url: str) -> dict:
    resp = requests.get(url, timeout=_TIMEOUT, headers={"User-Agent": "ScoutMini/0.1"})
    resp.raise_for_status()
    return resp.json()


def get_driver_season(
    query: str,
    season: int,
    *,
    fetch_json: FetchJson = _default_fetch_json,
) -> DriverSeason:
    """Fetch and assemble a driver's full season: results + standing + sources."""
    drivers = parse_drivers(fetch_json(_url_drivers(season)))
    if not drivers:
        raise DataNotAvailable(f"No driver list available for the {season} season yet.")
    driver = match_driver(query, drivers)

    results_url = _url_driver_results(driver.driver_id, season)
    standings_url = _url_driver_standings(season)

    results = parse_driver_results(fetch_json(results_url))
    if not results:
        raise DataNotAvailable(
            f"No race results available for {driver.full_name} in {season} yet."
        )

    standings = parse_driver_standings(fetch_json(standings_url))
    standing = next((s for s in standings if s.driver_id == driver.driver_id), None)

    return DriverSeason(
        driver=driver,
        season=season,
        results=results,
        standing=standing,
        source_urls=[results_url, standings_url],
    )


def get_standings(
    season: int,
    *,
    fetch_json: FetchJson = _default_fetch_json,
) -> Standings:
    """Fetch the driver championship standings for a season."""
    url = _url_driver_standings(season)
    drivers = parse_driver_standings(fetch_json(url))
    if not drivers:
        raise DataNotAvailable(
            f"No championship standings available for the {season} season yet."
        )
    return Standings(season=season, drivers=drivers, source_urls=[url])
