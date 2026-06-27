"""Command-line interface for ScoutMini.

    scoutmini ask "How is Norris doing this season?"
    scoutmini driver Norris

Thin glue: load config, call the orchestrator, print a sourced report, and turn
the known failure modes into friendly messages instead of tracebacks.
"""

from __future__ import annotations

import requests
import typer

from . import f1_data, news
from .agent import run_agent
from .config import DEFAULT_SEASON, ConfigError, load_config
from .f1_data import DataNotAvailable, DriverNotFound, RaceNotFound
from .fastf1_data import FastF1NotInstalled, format_pace, get_driver_pace
from .scout import Report, UnsupportedQuestion, answer

app = typer.Typer(
    add_completion=False,
    help="ScoutMini — F1 analysis from real, sourced data.",
)


def render_report(report: Report) -> str:
    lines = [report.body.strip(), ""]
    if report.sources:
        lines.append("Sources:")
        lines.extend(f"  - {url}" for url in report.sources)
    return "\n".join(lines).rstrip()


def _run(question: str) -> None:
    try:
        config = load_config()
    except ConfigError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    try:
        report = answer(question, config, news_fn=news.get_news)
    except (DriverNotFound, DataNotAvailable, UnsupportedQuestion) as exc:
        typer.secho(str(exc), fg=typer.colors.YELLOW, err=True)
        raise typer.Exit(code=1)
    except requests.exceptions.RequestException as exc:
        typer.secho(f"Could not reach the F1 data service: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    except Exception as exc:  # OpenAI / unexpected — surface cleanly, no traceback
        typer.secho(f"Something went wrong calling the model: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    typer.echo(render_report(report))


@app.command()
def ask(question: str = typer.Argument(..., help="A question about F1.")) -> None:
    """Answer a free-text F1 question."""
    _run(question)


@app.command()
def driver(name: str = typer.Argument(..., help="A driver's name, e.g. Norris.")) -> None:
    """Shortcut for a driver's season-form report."""
    _run(f"How is {name} doing this season?")


@app.command()
def agent(question: str = typer.Argument(..., help="Any F1 question.")) -> None:
    """v2: let the model choose which data tools to call, across multiple steps.

    Unlike `ask` (a fixed router), this can combine tools to answer open-ended
    questions. Still grounded only in fetched data, with sources shown.
    """
    try:
        config = load_config()
    except ConfigError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    try:
        result = run_agent(question, config)
    except requests.exceptions.RequestException as exc:
        typer.secho(f"Could not reach the F1 data service: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    except Exception as exc:  # OpenAI / unexpected — surface cleanly
        typer.secho(f"Something went wrong: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    typer.echo(result.answer.strip())
    if result.tool_calls:
        typer.secho(f"\n[tools used: {', '.join(result.tool_calls)}]", fg=typer.colors.CYAN)
    if result.sources:
        typer.echo("\nSources:")
        for url in result.sources:
            typer.echo(f"  - {url}")


@app.command()
def pace(
    driver_name: str = typer.Argument(..., help="A driver's name, e.g. Leclerc."),
    race: str = typer.Argument(..., help="A race, e.g. Monaco."),
    season: int = typer.Option(DEFAULT_SEASON, help="Season year."),
    kind: str = typer.Option("R", help="Session: R (race), Q (qualifying), S (sprint)."),
) -> None:
    """FastF1 deep data: a driver's pace and tyre strategy for a session.

    No OpenAI key needed — this prints the raw timing data directly.
    """
    try:
        d = f1_data.get_driver(driver_name, season)
        # Resolve the race to a round number via Jolpica and pass the integer to
        # FastF1 — its own name matching is unreliable when its schedule backend
        # is degraded (it has mis-resolved "Monaco" to the Italian GP).
        meta = f1_data.get_race_meta(race, season)
        result = get_driver_pace(season, meta.round, d.code, kind=kind)
    except (DriverNotFound, RaceNotFound, FastF1NotInstalled) as exc:
        typer.secho(str(exc), fg=typer.colors.YELLOW, err=True)
        raise typer.Exit(code=1)
    except Exception as exc:  # FastF1 load / network — keep it clean
        typer.secho(
            f"Could not load FastF1 data for {race} {season}: {exc}",
            fg=typer.colors.RED, err=True,
        )
        raise typer.Exit(code=1)
    typer.echo(f"{d.full_name} — {meta.race_name} {season} ({kind})")
    typer.echo(format_pace(result))


def main() -> None:
    app()


if __name__ == "__main__":
    main()
