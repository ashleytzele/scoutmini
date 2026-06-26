# ScoutMini

An AI sports-analysis CLI. It answers analytical **Formula 1** questions by fetching
real data, then having an LLM write a short, **sourced** report — never guessing from
the model's own memory. F1 is the first sport; the architecture is built to add more.

> Status: in development. See [the design spec](docs/superpowers/specs/2026-06-27-scout-design.md).

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env   # then add your OpenAI API key
```

Run it from the project root with the module entry point (works everywhere):

```bash
python -m scoutmini ask "How is Norris doing this season?"
python -m scoutmini driver Norris
```

> The `pip install` also creates a `scoutmini` console command. On some Python
> builds (e.g. the python.org 3.13 framework build on macOS) the editable
> install's `.pth` file is ignored, so the bare `scoutmini` command may not find
> the package — `python -m scoutmini` always works. A non-editable `pip install .`
> makes the `scoutmini` command work too.

## What works today (v1, in progress)

Three question types, each fetching real data from the Jolpica-F1 API and having
the LLM write a short report that cites only those numbers:

- **Driver form** — `python -m scoutmini ask "How is Norris doing this season?"`
- **Standings** — `python -m scoutmini ask "Show the driver standings"`
- **Head-to-head** — `python -m scoutmini ask "Leclerc vs Norris this year"`
- **Race analysis** — `python -m scoutmini ask "What decided the Monaco Grand Prix?"`

Plus friendly errors for a missing API key, an unknown driver/race, or a
not-yet-supported question type.

All four v1 question types are wired. News sources (RSS) and FastF1 deep data are
the next steps (see the [design spec](docs/superpowers/specs/2026-06-27-scout-design.md)).

## Development

```bash
pytest
```
