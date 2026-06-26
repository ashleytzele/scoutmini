import scoutmini.cli as cli
from scoutmini.config import Config, ConfigError
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
        lambda q, cfg: Report(q, Intent.DRIVER_FORM, "Strong season.", ["http://src"]),
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

    def boom(q, cfg):
        raise UnsupportedQuestion("v1 only answers driver-form questions.")

    monkeypatch.setattr(cli, "answer", boom)

    result = runner.invoke(cli.app, ["ask", "show standings"])

    assert result.exit_code == 1
    assert "driver-form" in result.output


def test_driver_shortcut_builds_form_question(monkeypatch):
    monkeypatch.setattr(cli, "load_config", lambda: CFG)
    seen = {}

    def fake_answer(q, cfg):
        seen["q"] = q
        return Report(q, Intent.DRIVER_FORM, "ok", [])

    monkeypatch.setattr(cli, "answer", fake_answer)

    result = runner.invoke(cli.app, ["driver", "Norris"])

    assert result.exit_code == 0
    assert "Norris" in seen["q"]
