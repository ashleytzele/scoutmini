from types import SimpleNamespace

from scoutmini.agent import TOOLS, AgentResult, run_agent, run_tool
from scoutmini.config import Config

CFG = Config(openai_api_key="sk-test", model="gpt-4o-mini", season=2024)


# --- fakes that mimic the OpenAI SDK response objects ----------------------

def _tool_call(call_id, name, arguments):
    return SimpleNamespace(
        id=call_id, type="function",
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def _message(content=None, tool_calls=None):
    return SimpleNamespace(content=content, tool_calls=tool_calls)


def _response(message):
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class FakeClient:
    """Returns a scripted list of responses, one per create() call."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self._create)
        )

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return _response(self._responses.pop(0))


def _fetcher(fixture):
    def fetch_json(url):
        if "/drivers.json" in url:
            return fixture("drivers_2024.json")
        if "driverStandings" in url:
            return fixture("driver_standings_2024.json")
        if "/norris/" in url:
            return fixture("norris_results_2024.json")
        if url.endswith("/2024.json"):
            return fixture("schedule_2024.json")
        if "/8/results" in url:
            return fixture("race_monaco_2024.json")
        raise AssertionError(f"unexpected url: {url}")
    return fetch_json


# --- tool schema + dispatch -------------------------------------------------

def test_tools_expose_the_data_functions():
    names = {t["function"]["name"] for t in TOOLS}
    assert {"get_driver_season", "get_standings", "get_race"} <= names
    # each tool is a valid OpenAI function spec
    for t in TOOLS:
        assert t["type"] == "function"
        assert "parameters" in t["function"]


def test_run_tool_get_standings(fixture):
    text, sources = run_tool(
        "get_standings", {"season": 2024},
        season_default=2024, fetch_json=_fetcher(fixture),
    )
    assert "Verstappen" in text
    assert any("driverStandings" in s for s in sources)


def test_run_tool_unknown_raises(fixture):
    import pytest
    with pytest.raises(ValueError):
        run_tool("get_weather", {}, season_default=2024, fetch_json=_fetcher(fixture))


# --- the agent loop ---------------------------------------------------------

def test_agent_single_tool_then_answer(fixture):
    client = FakeClient([
        _message(tool_calls=[_tool_call("c1", "get_standings", '{"season": 2024}')]),
        _message(content="Verstappen leads on 437 points."),
    ])

    result = run_agent("Who leads the championship?", CFG,
                       client=client, fetch_json=_fetcher(fixture))

    assert isinstance(result, AgentResult)
    assert result.answer == "Verstappen leads on 437 points."
    assert result.tool_calls == ["get_standings"]
    assert result.steps == 2
    assert any("driverStandings" in s for s in result.sources)
    # the model was actually offered the tools
    assert "tools" in client.calls[0]


def test_agent_multi_step_gathers_multiple_sources(fixture):
    client = FakeClient([
        _message(tool_calls=[_tool_call("c1", "get_driver_season", '{"driver": "Norris"}')]),
        _message(tool_calls=[_tool_call("c2", "get_race", '{"race": "Monaco"}')]),
        _message(content="Norris is P2; Leclerc won Monaco from pole."),
    ])

    result = run_agent("How is Norris doing and what happened at Monaco?", CFG,
                       client=client, fetch_json=_fetcher(fixture))

    assert result.tool_calls == ["get_driver_season", "get_race"]
    assert result.steps == 3
    # sources from both tools, de-duplicated
    assert len(result.sources) == len(set(result.sources))
    assert any("norris" in s for s in result.sources)
    assert any("/8/results" in s for s in result.sources)


def test_agent_tool_error_is_fed_back_not_raised(fixture):
    client = FakeClient([
        _message(tool_calls=[_tool_call("c1", "get_driver_season", '{"driver": "Nobody"}')]),
        _message(content="I couldn't find that driver in the data."),
    ])

    result = run_agent("How is Nobody doing?", CFG,
                       client=client, fetch_json=_fetcher(fixture))

    assert result.answer == "I couldn't find that driver in the data."
    # the failing tool result was passed back to the model as a tool message
    tool_msgs = [m for m in client.calls[1]["messages"] if m.get("role") == "tool"]
    assert tool_msgs and "ERROR" in tool_msgs[0]["content"]


def test_agent_stops_at_max_steps(fixture):
    # model keeps asking for tools forever; agent must stop and force an answer
    responses = [
        _message(tool_calls=[_tool_call(f"c{i}", "get_standings", "{}")])
        for i in range(3)
    ] + [_message(content="Best effort from gathered data.")]
    client = FakeClient(responses)

    result = run_agent("loop please", CFG, client=client,
                       fetch_json=_fetcher(fixture), max_steps=3)

    assert result.steps == 3
    assert result.answer == "Best effort from gathered data."
    # the final, forced call was made WITHOUT tools
    assert "tools" not in client.calls[-1]
