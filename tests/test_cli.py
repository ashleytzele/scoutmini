import scoutmini.cli as cli
from scoutmini.agent import AgentResult
from scoutmini.config import Config, ConfigError
from scoutmini.f1_data import Driver, RaceMeta
from scoutmini.fastf1_data import DriverPace, Stint
from scoutmini.scout import Intent, Report, UnsupportedQuestion
from typer.testing import CliRunner

runner = CliRunner()
CFG = Config(openai_api_key="sk-test", model="gpt-4o-mini", season=2024)


def test_render_report_shows_body_and_sources():
    report = Report(
        question="q",
        intent=Intent.DRIVER_FORM,
        body="Norris is P2.",
        sources=["http://a", "http://b"],
    )
    text = cli.render_report(report)
    assert "Norris is P2." in text
    assert "http://a" in text
    assert "http://b" in text
    assert "Sources" in text


def test_ask_happy_path(monkeypatch):
    monkeypatch.setattr(cli, "load_config", lambda: CFG)
    monkeypatch.setattr(
        cli,
        "answer",
        lambda q, cfg, **kw: Report(q, Intent.DRIVER_FORM, "Strong season.", ["http://src"]),
    )

    result = runner.invoke(cli.app, ["ask", "How is Norris doing?"])

    assert result.exit_code == 0
    assert "Strong season." in result.stdout
    assert "http://src" in result.stdout


def test_ask_missing_key_is_friendly(monkeypatch):
    def boom():
        raise ConfigError("OPENAI_API_KEY is not set. Add it to a .env file.")

    monkeypatch.setattr(cli, "load_config", boom)

    result = runner.invoke(cli.app, ["ask", "anything"])

    assert result.exit_code == 1
    assert "OPENAI_API_KEY" in result.output


def test_ask_unsupported_question_is_friendly(monkeypatch):
    monkeypatch.setattr(cli, "load_config", lambda: CFG)

    def boom(q, cfg, **kw):
        raise UnsupportedQuestion("v1 only answers driver-form questions.")

    monkeypatch.setattr(cli, "answer", boom)

    result = runner.invoke(cli.app, ["ask", "show standings"])

    assert result.exit_code == 1
    assert "driver-form" in result.output


def test_agent_command(monkeypatch):
    monkeypatch.setattr(cli, "load_config", lambda: CFG)
    monkeypatch.setattr(
        cli, "run_agent",
        lambda q, cfg: AgentResult(
            answer="Verstappen leads.",
            sources=["http://src/standings"],
            steps=2,
            tool_calls=["get_standings"],
        ),
    )

    result = runner.invoke(cli.app, ["agent", "Who is winning?"])

    assert result.exit_code == 0
    assert "Verstappen leads." in result.stdout
    assert "get_standings" in result.stdout      # tools-used line
    assert "http://src/standings" in result.stdout


def test_pace_command(monkeypatch):
    monkeypatch.setattr(
        cli.f1_data, "get_driver",
        lambda name, season: Driver("leclerc", "LEC", "Charles", "Leclerc"),
    )
    # get_race_meta was previously unpatched, so this test made a live call to
    # the Jolpica API on every run: slow, flaky, and failing with no network.
    monkeypatch.setattr(
        cli.f1_data, "get_race_meta",
        lambda race, season: RaceMeta(
            round=6, race_name="Monaco Grand Prix", circuit_name="Circuit de Monaco",
            locality="Monte-Carlo", country="Monaco", date="2024-05-26",
        ),
    )
    monkeypatch.setattr(
        cli, "get_driver_pace",
        lambda season, race, code, kind="R": DriverPace(
            "LEC", 78.2, 79.0, 40, [Stint("SOFT", 20, 1, 20), Stint("HARD", 20, 21, 40)]
        ),
    )

    result = runner.invoke(cli.app, ["pace", "Leclerc", "Monaco"])

    assert result.exit_code == 0
    assert "Charles Leclerc" in result.stdout
    assert "SOFT" in result.stdout and "HARD" in result.stdout


def test_driver_shortcut_builds_form_question(monkeypatch):
    monkeypatch.setattr(cli, "load_config", lambda: CFG)
    seen = {}

    def fake_answer(q, cfg, **kw):
        seen["q"] = q
        return Report(q, Intent.DRIVER_FORM, "ok", [])

    monkeypatch.setattr(cli, "answer", fake_answer)

    result = runner.invoke(cli.app, ["driver", "Norris"])

    assert result.exit_code == 0
    assert "Norris" in seen["q"]
