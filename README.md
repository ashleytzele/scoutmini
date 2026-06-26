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

- **Driver form** — `python -m scoutmini ask "How is Norris doing this season?"`
  fetches the driver's full season from the Jolpica-F1 API (results + standing),
  and the LLM writes a short report citing only those numbers.
- Friendly errors for a missing API key, an unknown driver, or a not-yet-supported
  question type.

Head-to-head, race analysis, standings, news sources, and FastF1 deep data are the
next steps (see the [design spec](docs/superpowers/specs/2026-06-27-scout-design.md)).

## Development

```bash
pytest
```
