import pytest

from scoutmini.f1_data import (
    DataNotAvailable,
    Driver,
    DriverNotFound,
    DriverSeason,
    RaceAnalysis,
    RaceEntry,
    RaceMeta,
    RaceNotFound,
    Standings,
    get_driver,
    get_driver_season,
    get_race,
    get_race_meta,
    get_standings,
    match_driver,
    match_race,
    parse_driver_results,
    parse_driver_standings,
    parse_drivers,
    parse_race_results,
    parse_schedule,
)


# --- pure parsers -----------------------------------------------------------

def test_parse_drivers(fixture):
    drivers = parse_drivers(fixture("drivers_2024.json"))

    assert len(drivers) == 3
    nor = drivers[0]
    assert isinstance(nor, Driver)
    assert nor.driver_id == "norris"
    assert nor.code == "NOR"
    assert nor.full_name == "Lando Norris"


def test_parse_driver_standings(fixture):
    standings = parse_driver_standings(fixture("driver_standings_2024.json"))

    assert len(standings) == 2
    leader = standings[0]
    assert leader.position == 1
    assert leader.driver_id == "max_verstappen"
    assert leader.points == 437.0
    assert leader.wins == 9
    assert leader.constructor == "Red Bull"


def test_parse_driver_results(fixture):
    results = parse_driver_results(fixture("norris_results_2024.json"))

    assert len(results) == 2
    win = results[1]
    assert win.round == 6
    assert win.race_name == "Miami Grand Prix"
    assert win.grid == 5
    assert win.position == 1
    assert win.points == 25.0
    assert win.status == "Finished"


def test_parse_driver_results_empty(fixture):
    assert parse_driver_results(fixture("empty_results.json")) == []


# --- driver matching --------------------------------------------------------

def test_match_driver_by_family_name_case_insensitive(fixture):
    drivers = parse_drivers(fixture("drivers_2024.json"))
    assert match_driver("norris", drivers).driver_id == "norris"
    assert match_driver("VERSTAPPEN", drivers).driver_id == "max_verstappen"


def test_match_driver_by_code(fixture):
    drivers = parse_drivers(fixture("drivers_2024.json"))
    assert match_driver("LEC", drivers).driver_id == "leclerc"


def test_match_driver_unknown_lists_suggestions(fixture):
    drivers = parse_drivers(fixture("drivers_2024.json"))
    with pytest.raises(DriverNotFound) as exc:
        match_driver("schumacher", drivers)
    msg = str(exc.value)
    assert "schumacher" in msg
    # suggestions drawn from the known drivers
    assert "Norris" in msg or "Verstappen" in msg


# --- orchestrating fetch (network injected) ---------------------------------

def _fake_fetcher(fixture):
    def fetch_json(url: str) -> dict:
        if "/drivers.json" in url:
            return fixture("drivers_2024.json")
        if "driverStandings" in url:
            return fixture("driver_standings_2024.json")
        if "/results" in url:
            return fixture("norris_results_2024.json")
        raise AssertionError(f"unexpected url: {url}")

    return fetch_json


def test_get_driver_season_assembles_clean_object(fixture):
    season = get_driver_season("Norris", 2024, fetch_json=_fake_fetcher(fixture))

    assert isinstance(season, DriverSeason)
    assert season.driver.driver_id == "norris"
    assert season.season == 2024
    assert len(season.results) == 2
    assert season.standing.position == 2
    assert season.standing.points == 374.0
    assert season.wins == 1  # one P1 in the fixture results
    # golden rule: the exact data sources are recorded for the report
    assert season.source_urls
    assert any("results" in u for u in season.source_urls)


def test_get_driver_resolves_to_code(fixture):
    d = get_driver("Norris", 2024, fetch_json=lambda url: fixture("drivers_2024.json"))
    assert d.driver_id == "norris"
    assert d.code == "NOR"


def test_get_standings_assembles_clean_object(fixture):
    standings = get_standings(
        2024, fetch_json=lambda url: fixture("driver_standings_2024.json")
    )

    assert isinstance(standings, Standings)
    assert standings.season == 2024
    assert len(standings.drivers) == 2
    assert standings.drivers[0].driver_id == "max_verstappen"
    assert standings.source_urls


def test_get_standings_no_data_raises(fixture):
    with pytest.raises(DataNotAvailable):
        get_standings(1066, fetch_json=lambda url: {"MRData": {"StandingsTable": {"StandingsLists": []}}})


# --- race analysis ----------------------------------------------------------

def test_parse_schedule(fixture):
    races = parse_schedule(fixture("schedule_2024.json"))
    assert len(races) == 2
    monaco = races[1]
    assert isinstance(monaco, RaceMeta)
    assert monaco.round == 8
    assert monaco.race_name == "Monaco Grand Prix"
    assert monaco.country == "Monaco"


def test_match_race_by_name(fixture):
    races = parse_schedule(fixture("schedule_2024.json"))
    assert match_race("Monaco", races).round == 8
    assert match_race("monaco grand prix", races).round == 8


def test_match_race_by_country(fixture):
    races = parse_schedule(fixture("schedule_2024.json"))
    assert match_race("Bahrain", races).round == 1


def test_match_race_unknown_raises(fixture):
    races = parse_schedule(fixture("schedule_2024.json"))
    with pytest.raises(RaceNotFound) as exc:
        match_race("Nürburgring", races)
    assert "Monaco" in str(exc.value) or "Bahrain" in str(exc.value)


def test_parse_race_results_full_field(fixture):
    entries = parse_race_results(fixture("race_monaco_2024.json"))
    assert len(entries) == 6
    winner = entries[0]
    assert isinstance(winner, RaceEntry)
    assert winner.position == 1
    assert winner.full_name == "Charles Leclerc"
    assert winner.grid == 1
    assert winner.constructor == "Ferrari"
    dnf = entries[-1]
    assert dnf.status == "Accident"


def test_race_entry_classification_uses_position_text(fixture):
    by_name = {e.full_name: e for e in parse_race_results(fixture("race_monaco_2024.json"))}
    # A "Lapped" driver still finished the race -> classified.
    assert by_name["Yuki Tsunoda"].status == "Lapped"
    assert by_name["Yuki Tsunoda"].is_classified is True
    # A retirement (positionText "R") is NOT classified.
    assert by_name["Sergio Perez"].is_classified is False


def test_get_race_assembles(fixture):
    def fetch_json(url):
        if url.endswith("/2024.json"):
            return fixture("schedule_2024.json")
        if "/8/results" in url:
            return fixture("race_monaco_2024.json")
        raise AssertionError(f"unexpected url: {url}")

    race = get_race("Monaco", 2024, fetch_json=fetch_json)
    assert isinstance(race, RaceAnalysis)
    assert race.meta.race_name == "Monaco Grand Prix"
    assert len(race.entries) == 6
    assert race.source_urls


def test_get_race_unknown_race_raises(fixture):
    with pytest.raises(RaceNotFound):
        get_race("Imola", 2024, fetch_json=lambda u: fixture("schedule_2024.json"))


def test_get_race_meta_resolves_round(fixture):
    meta = get_race_meta("Monaco", 2024, fetch_json=lambda u: fixture("schedule_2024.json"))
    assert meta.round == 8
    assert meta.race_name == "Monaco Grand Prix"


def test_get_driver_season_unknown_driver_raises(fixture):
    with pytest.raises(DriverNotFound):
        get_driver_season("Schumacher", 2024, fetch_json=_fake_fetcher(fixture))


def test_get_driver_season_no_data_raises(fixture):
    def fetch_json(url: str) -> dict:
        if "/drivers.json" in url:
            return fixture("drivers_2024.json")
        if "driverStandings" in url:
            return fixture("driver_standings_2024.json")
        return fixture("empty_results.json")

    with pytest.raises(DataNotAvailable):
        get_driver_season("Norris", 2024, fetch_json=fetch_json)
