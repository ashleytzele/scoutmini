# ScoutMini

An AI sports-analysis CLI for **Formula 1**. Ask it a question in plain English and it
fetches the real numbers first, then has an LLM write a short report **citing only those
numbers**.

**The rule the whole design serves: the model never answers from its own memory.** It only
ever sees data the tools returned, and every report prints its sources. An LLM asked about
F1 will happily invent a plausible finishing position; this one cannot, because it is never
asked to recall anything.

F1 is the first sport. The adapter boundary is built so a second one slots in behind the
same engine.

```bash
python -m scoutmini ask   "How is Norris doing this season?"
python -m scoutmini agent "Who won at Monaco, and how is that driver doing overall?"
python -m scoutmini pace  Leclerc Monaco --season 2024
```

**73 tests, no network required** — every external call is fixtured. Six of them
cover the FastF1 path and skip unless the optional extra is installed, so a plain
`pip install -e ".[dev]"` runs 67 of the 73.

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env   # then add your OpenAI API key
pytest                 # 67 passed, 6 skipped (the FastF1 tests)
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

## How it answers

### `ask` — the deterministic router

Routes a question to one of four handlers, each pulling real data from the
[Jolpica-F1 API](https://github.com/jolpica/jolpica-f1) before the LLM writes a word:

| Question type | Example |
|---|---|
| Driver form | `ask "How is Norris doing this season?"` |
| Standings | `ask "Show the driver standings"` |
| Head-to-head | `ask "Leclerc vs Norris this year"` |
| Race analysis | `ask "What decided the Monaco Grand Prix?"` |

Reports also cite **recent F1 news** from a free RSS feed alongside the data sources.
Missing API key, unknown driver, unknown race and unsupported question types all fail with
a readable message rather than a stack trace.

### `agent` — function calling

```bash
python -m scoutmini agent "Who won at Monaco, and how is that driver doing overall?"
```

Hands the F1 data functions to the model **as tools** and lets it choose which to call
across multiple steps, so it can combine sources to answer open-ended questions the fixed
router can't. Same grounding rule; it prints the tools it used and the sources behind them.

`ask` stays for simple, predictable queries where a deterministic path is worth more than
flexibility.

### `pace` — deep timing data

```bash
pip install -e ".[fastf1]"          # optional, heavier dependency
python -m scoutmini pace Leclerc Monaco --season 2024
```

A driver's fastest lap, median race pace and tyre strategy for a session, straight from
FastF1's official timing data, cached on disk in `.ff1_cache/`. **No OpenAI key needed** —
this is raw data, not an LLM report.

FastF1 is an optional extra so the core install stays light; its test module skips cleanly
when it isn't present.

## Design

The [design spec](docs/superpowers/specs/2026-06-27-scout-design.md) and the
[tools design](docs/superpowers/specs/2026-06-27-scoutmini-tools-design.md) cover the
architecture: the adapter boundary, the grounding contract, and how the router and the
agent share one set of data functions.

Still open from that spec: a **second sport adapter**, to prove the "one engine, many
sports" claim rather than assert it.

## Development

```bash
pytest
```

Every external dependency is fixtured under `tests/fixtures/`, so the suite runs offline
and without an API key.
