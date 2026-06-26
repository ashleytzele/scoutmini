"""Command-line interface for ScoutMini.

    scoutmini ask "How is Norris doing this season?"
    scoutmini driver Norris

Thin glue: load config, call the orchestrator, print a sourced report, and turn
the known failure modes into friendly messages instead of tracebacks.
"""

from __future__ import annotations

import requests
import typer

from .config import ConfigError, load_config
from .f1_data import DataNotAvailable, DriverNotFound
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
        report = answer(question, config)
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


def main() -> None:
    app()


if __name__ == "__main__":
    main()
