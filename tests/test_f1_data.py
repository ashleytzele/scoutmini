import pytest

from scoutmini.f1_data import (
    DataNotAvailable,
    Driver,
    DriverNotFound,
    DriverSeason,
    Standings,
    get_driver_season,
    get_standings,
    match_driver,
    parse_driver_results,
    parse_driver_standings,
    parse_drivers,
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
