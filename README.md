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

Reports also cite **recent F1 news** (pulled from a free RSS feed) alongside the
data sources. Plus friendly errors for a missing API key, an unknown driver/race,
or a not-yet-supported question type.

### v2 — the function-calling agent

```bash
python -m scoutmini agent "Who won at Monaco, and how is that driver doing overall?"
```

`agent` hands the F1 data functions to the model as **tools** and lets it decide
which to call, across multiple steps — so it can combine data to answer
open-ended questions that the fixed `ask` router can't. It still obeys the golden
rule (it only ever sees data the tools return) and prints the tools it used plus
the sources. `ask` (the deterministic v1 router) remains for simple, predictable
queries.

### Deep timing data (FastF1)

```bash
pip install -e ".[fastf1]"          # optional, heavier dependency
python -m scoutmini pace Leclerc Monaco --season 2024
```

`pace` prints a driver's fastest lap, median race pace, and tyre strategy for a
session, straight from FastF1's official timing data (on-disk cached in
`.ff1_cache/`). No OpenAI key needed — it's raw data, not an LLM report.

The v2 function-calling agent (above) is now built too. The remaining stretch
from the [design spec](docs/superpowers/specs/2026-06-27-scout-design.md) is a
second sport adapter ("one engine, many sports").

## Development

```bash
pytest
```
