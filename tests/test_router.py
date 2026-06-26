from scoutmini.scout import Intent, route


def test_route_driver_form():
    r = route("How is Norris doing this season?")
    assert r.intent is Intent.DRIVER_FORM
    assert r.subjects == ["Norris"]


def test_route_head_to_head_vs():
    r = route("Leclerc vs Sainz this year")
    assert r.intent is Intent.HEAD_TO_HEAD
    assert r.subjects == ["Leclerc", "Sainz"]


def test_route_head_to_head_compare():
    r = route("Compare Hamilton and Russell")
    assert r.intent is Intent.HEAD_TO_HEAD
    assert r.subjects == ["Hamilton", "Russell"]


def test_route_standings():
    r = route("Show me the current driver standings")
    assert r.intent is Intent.STANDINGS
    assert r.subjects == []


def test_route_standings_championship_phrasing():
    assert route("Who is leading the championship?").intent is Intent.STANDINGS


def test_route_race_analysis():
    r = route("What decided the Monaco Grand Prix?")
    assert r.intent is Intent.RACE_ANALYSIS
    assert "Monaco" in r.subjects


def test_route_defaults_to_driver_form():
    # A bare driver name with no other signal is treated as a form question.
    r = route("Verstappen")
    assert r.intent is Intent.DRIVER_FORM
    assert r.subjects == ["Verstappen"]
