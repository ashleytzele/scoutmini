import pytest

from scoutmini.config import Config
from scoutmini.f1_data import (
    Driver,
    DriverSeason,
    DriverStanding,
    RaceResult,
    Standings,
)
from scoutmini.scout import (
    Intent,
    Report,
    UnsupportedQuestion,
    answer,
    format_driver_season,
    format_head_to_head,
    format_standings,
)

CFG = Config(openai_api_key="sk-test", model="gpt-4o-mini", season=2024)


def _sample_season():
    driver = Driver("norris", "NOR", "Lando", "Norris")
    results = [
        RaceResult(1, "Bahrain Grand Prix", "2024-03-02", 7, 6, 8.0, "Finished"),
        RaceResult(6, "Miami Grand Prix", "2024-05-05", 5, 1, 25.0, "Finished"),
    ]
    standing = DriverStanding(2, "norris", "Lando Norris", 374.0, 1, "McLaren")
    return DriverSeason(driver, 2024, results, standing, ["http://src/results"])


def test_format_driver_season_includes_key_facts():
    text = format_driver_season(_sample_season())
    assert "Lando Norris" in text
    assert "374" in text          # points
    assert "Miami Grand Prix" in text
    assert "McLaren" in text
    assert "P2" in text or "position 2" in text.lower()


def test_answer_driver_form_end_to_end(fixture):
    def fetch_json(url):
        if "/drivers.json" in url:
            return fixture("drivers_2024.json")
        if "driverStandings" in url:
            return fixture("driver_standings_2024.json")
        return fixture("norris_results_2024.json")

    captured = {}

    def fake_analyze(question, data_text, sources, *, model, client):
        captured["data_text"] = data_text
        captured["sources"] = sources
        captured["model"] = model
        return "Norris sits P2 with 374 points."

    report = answer(
        "How is Norris doing this season?",
        CFG,
        fetch_json=fetch_json,
        client=object(),
        analyze_fn=fake_analyze,
    )

    assert isinstance(report, Report)
    assert report.intent is Intent.DRIVER_FORM
    assert report.body == "Norris sits P2 with 374 points."
    assert report.sources  # carried through for display
    assert "374" in captured["data_text"]
    assert captured["model"] == "gpt-4o-mini"


def _multi_fetcher(fixture):
    """Route fetches to the right fixture by URL, for multi-driver questions."""
    def fetch_json(url):
        if "/drivers.json" in url:
            return fixture("drivers_2024.json")
        if "driverStandings" in url:
            return fixture("driver_standings_2024.json")
        if "/leclerc/" in url:
            return fixture("leclerc_results_2024.json")
        if "/norris/" in url:
            return fixture("norris_results_2024.json")
        raise AssertionError(f"unexpected url: {url}")

    return fetch_json


def _capturing_analyze(captured, body="report body"):
    def fake_analyze(question, data_text, sources, *, model, client):
        captured["data_text"] = data_text
        captured["sources"] = sources
        return body

    return fake_analyze


# --- standings --------------------------------------------------------------

def test_format_standings_includes_top_drivers():
    standings = Standings(
        2024,
        [
            DriverStanding(1, "max_verstappen", "Max Verstappen", 437.0, 9, "Red Bull"),
            DriverStanding(2, "norris", "Lando Norris", 374.0, 4, "McLaren"),
        ],
        ["http://src/standings"],
    )
    text = format_standings(standings)
    assert "Max Verstappen" in text
    assert "437" in text
    assert "Lando Norris" in text


def test_answer_standings_end_to_end(fixture):
    captured = {}
    report = answer(
        "Show me the current driver standings",
        CFG,
        fetch_json=_multi_fetcher(fixture),
        client=object(),
        analyze_fn=_capturing_analyze(captured, "Verstappen leads."),
    )
    assert report.intent is Intent.STANDINGS
    assert report.body == "Verstappen leads."
    assert "Verstappen" in captured["data_text"]
    assert report.sources


# --- head-to-head -----------------------------------------------------------

def test_format_head_to_head_shows_both_drivers():
    a = _sample_season()
    b = DriverSeason(
        Driver("leclerc", "LEC", "Charles", "Leclerc"),
        2024,
        [RaceResult(8, "Monaco Grand Prix", "2024-05-26", 1, 1, 25.0, "Finished")],
        DriverStanding(3, "leclerc", "Charles Leclerc", 356.0, 3, "Ferrari"),
        ["http://src/leclerc"],
    )
    text = format_head_to_head(a, b)
    assert "Lando Norris" in text
    assert "Charles Leclerc" in text


def test_answer_head_to_head_end_to_end(fixture):
    captured = {}
    report = answer(
        "Leclerc vs Norris this year",
        CFG,
        fetch_json=_multi_fetcher(fixture),
        client=object(),
        analyze_fn=_capturing_analyze(captured, "Close fight."),
    )
    assert report.intent is Intent.HEAD_TO_HEAD
    assert report.body == "Close fight."
    assert "Leclerc" in captured["data_text"] and "Norris" in captured["data_text"]
    # both drivers' source URLs are carried through
    assert len(report.sources) >= 2


def test_answer_head_to_head_needs_two_drivers(fixture):
    with pytest.raises(UnsupportedQuestion):
        answer(
            "Norris vs",
            CFG,
            fetch_json=_multi_fetcher(fixture),
            client=object(),
            analyze_fn=_capturing_analyze({}),
        )


# --- still-unsupported intent ----------------------------------------------

def test_answer_race_analysis_still_unsupported(fixture):
    with pytest.raises(UnsupportedQuestion) as exc:
        answer("What decided the Monaco Grand Prix?", CFG, fetch_json=lambda u: {},
               client=object(), analyze_fn=lambda *a, **k: "x")
    assert "race" in str(exc.value).lower() or "v1" in str(exc.value).lower()
