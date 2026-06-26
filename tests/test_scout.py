import pytest

from scoutmini.config import Config
from scoutmini.f1_data import Driver, DriverSeason, DriverStanding, RaceResult
from scoutmini.scout import (
    Intent,
    Report,
    UnsupportedQuestion,
    answer,
    format_driver_season,
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


def test_answer_unsupported_intent_is_friendly(fixture):
    with pytest.raises(UnsupportedQuestion) as exc:
        answer("Show me the standings", CFG, fetch_json=lambda u: {}, client=object(),
               analyze_fn=lambda *a, **k: "x")
    assert "v1" in str(exc.value).lower() or "support" in str(exc.value).lower()
