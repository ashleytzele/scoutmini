"""FastF1 deep-data adapter: race/quali pace and tyre strategy.

FastF1 exposes detailed timing (lap times, tyre compounds, stints) that Ergast
doesn't. It's a heavy, optional dependency, so it's imported lazily — the pure
computation functions work on a plain pandas DataFrame and need neither FastF1
nor the network, which keeps them fast to test.

On-disk caching is enabled (``.ff1_cache/``, git-ignored) so repeat runs are fast.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable, List, Optional

DEFAULT_CACHE_DIR = ".ff1_cache"
SOURCE = "FastF1 (official F1 timing data)"

# load_laps(season, race, kind) -> pandas.DataFrame of laps
LoadLaps = Callable[[int, str, str], "object"]


class FastF1NotInstalled(Exception):
    """Raised when the optional FastF1 dependency is missing."""


@dataclass(frozen=True)
class Stint:
    compound: str
    laps: int
    start_lap: int
    end_lap: int


@dataclass(frozen=True)
class DriverPace:
    driver: str
    fastest_lap: Optional[float]   # seconds
    median_lap: Optional[float]    # seconds — representative race pace
    laps_counted: int
    stints: List[Stint] = field(default_factory=list)
    source: str = SOURCE


# --- pure computation (operate on a laps DataFrame) -------------------------

def compute_stints(laps, driver: str) -> List[Stint]:
    """Tyre stints for a driver, in order, from a FastF1-style laps frame."""
    rows = laps[laps["Driver"] == driver]
    stints: List[Stint] = []
    for stint_no in sorted(rows["Stint"].dropna().unique()):
        s = rows[rows["Stint"] == stint_no]
        compound = next((c for c in s["Compound"] if isinstance(c, str) and c), "")
        stints.append(
            Stint(
                compound=compound,
                laps=int(len(s)),
                start_lap=int(s["LapNumber"].min()),
                end_lap=int(s["LapNumber"].max()),
            )
        )
    return stints


def compute_pace(laps, driver: str) -> DriverPace:
    """Fastest and representative (median) lap for a driver.

    Uses only *accurate* laps (FastF1's ``IsAccurate`` flag, which excludes
    in/out laps, safety-car laps, etc.) so the median reflects true race pace."""
    rows = laps[laps["Driver"] == driver]
    accurate = rows[rows["IsAccurate"] & rows["LapTime"].notna()]
    secs = accurate["LapTime"].dt.total_seconds()

    if len(secs) == 0:
        return DriverPace(driver, None, None, 0, compute_stints(laps, driver))

    return DriverPace(
        driver=driver,
        fastest_lap=float(secs.min()),
        median_lap=float(secs.median()),
        laps_counted=int(len(secs)),
        stints=compute_stints(laps, driver),
    )


def _fmt_laptime(seconds: Optional[float]) -> str:
    if seconds is None:
        return "n/a"
    minutes, secs = divmod(seconds, 60)
    return f"{int(minutes)}:{secs:06.3f}"


def format_pace(pace: DriverPace) -> str:
    """Human/LLM-readable pace + tyre-strategy block."""
    if pace.laps_counted == 0:
        return f"{pace.driver}: no accurate lap data available. Source: {pace.source}"

    lines = [
        f"{pace.driver} — fastest {_fmt_laptime(pace.fastest_lap)}, "
        f"median race pace {_fmt_laptime(pace.median_lap)} "
        f"over {pace.laps_counted} accurate laps.",
    ]
    if pace.stints:
        strategy = ", ".join(
            f"{s.compound} (L{s.start_lap}-{s.end_lap}, {s.laps} laps)"
            for s in pace.stints
        )
        lines.append(f"Tyre strategy: {strategy}")
    lines.append(f"Source: {pace.source}")
    return "\n".join(lines)


# --- live loading (FastF1 + cache) ------------------------------------------

def enable_cache(path: str = DEFAULT_CACHE_DIR) -> None:
    """Point FastF1 at an on-disk cache, creating the directory if needed."""
    import fastf1  # lazy

    os.makedirs(path, exist_ok=True)
    fastf1.Cache.enable_cache(path)


def _load_laps(season: int, race, kind: str):
    """Load a session's laps via FastF1 (network on first call, cached after).

    Resolves the event through FastF1's *Ergast* schedule backend: the default
    backend can return a partial schedule (only recent rounds) for historical
    seasons, which mis-resolves events. ``race`` is normally a round number (int).
    """
    try:
        import fastf1  # lazy
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise FastF1NotInstalled(
            "FastF1 is not installed. Install it with: pip install 'scoutmini[fastf1]'"
        ) from exc

    enable_cache()
    schedule = fastf1.get_event_schedule(season, backend="ergast")
    if isinstance(race, int) or (isinstance(race, str) and race.isdigit()):
        event = schedule.get_event_by_round(int(race))
    else:
        event = schedule.get_event_by_name(race, strict_search=False)
    session = event.get_session(kind)
    session.load(telemetry=False, weather=False, messages=False)
    return session.laps


def get_driver_pace(
    season: int,
    race,  # round number (int, preferred) or event name (str)
    driver: str,
    *,
    kind: str = "R",
    load_laps: LoadLaps = _load_laps,
) -> DriverPace:
    """Pace + tyre strategy for one driver in a session (``kind`` R/Q/S)."""
    laps = load_laps(season, race, kind)
    return compute_pace(laps, driver)
