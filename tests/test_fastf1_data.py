import pytest

# fastf1/pandas is an optional extra; skip this module when it is absent
pd = pytest.importorskip("pandas")

from scoutmini.fastf1_data import (
    DriverPace,
    Stint,
    compute_pace,
    compute_stints,
    format_pace,
    get_driver_pace,
)


def _laps_df():
    """A tiny synthetic FastF1-style laps frame for two drivers."""
    return pd.DataFrame(
        [
            # Driver, LapNumber, Stint, Compound, LapTime(s), IsAccurate
            ("VER", 1, 1, "SOFT", 95.0, False),   # slow opening lap
            ("VER", 2, 1, "SOFT", 78.5, True),
            ("VER", 3, 1, "SOFT", 78.2, True),
            ("VER", 4, 2, "HARD", 90.0, False),   # out lap after pit
            ("VER", 5, 2, "HARD", 79.8, True),
            ("HAM", 2, 1, "MEDIUM", 79.0, True),  # different driver, ignored
        ],
        columns=["Driver", "LapNumber", "Stint", "Compound", "_secs", "IsAccurate"],
    ).assign(LapTime=lambda d: pd.to_timedelta(d["_secs"], unit="s"))


def test_compute_pace_uses_only_accurate_laps():
    pace = compute_pace(_laps_df(), "VER")
    assert isinstance(pace, DriverPace)
    assert pace.driver == "VER"
    assert pace.laps_counted == 3                 # laps 2, 3, 5
    assert pace.fastest_lap == pytest.approx(78.2)
    assert pace.median_lap == pytest.approx(78.5)


def test_compute_pace_no_laps_returns_empty():
    pace = compute_pace(_laps_df(), "LEC")
    assert pace.laps_counted == 0
    assert pace.fastest_lap is None
    assert pace.median_lap is None


def test_compute_stints():
    stints = compute_stints(_laps_df(), "VER")
    assert stints == [
        Stint(compound="SOFT", laps=3, start_lap=1, end_lap=3),
        Stint(compound="HARD", laps=2, start_lap=4, end_lap=5),
    ]


def test_get_driver_pace_injects_loader():
    df = _laps_df()
    pace = get_driver_pace(2024, "Monaco", "VER", load_laps=lambda s, r, k: df)
    assert pace.driver == "VER"
    assert pace.fastest_lap == pytest.approx(78.2)
    assert len(pace.stints) == 2


def test_format_pace_renders_times_and_stints():
    pace = compute_pace(_laps_df(), "VER")
    text = format_pace(pace)
    assert "VER" in text
    assert "1:18.2" in text or "78.2" in text   # fastest lap formatted
    assert "SOFT" in text and "HARD" in text     # tyre stints listed


def test_format_pace_handles_no_data():
    text = format_pace(compute_pace(_laps_df(), "LEC"))
    assert "no" in text.lower() or "n/a" in text.lower()
