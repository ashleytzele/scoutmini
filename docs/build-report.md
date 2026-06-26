# ScoutMini — Build Report

**Date:** 2026-06-27
**Status:** v1 complete and verified live, plus the Day 4–5 deep-data features.
**Tests:** 65 passing. **Source:** ~1,186 lines across 9 modules.

This report documents everything built so far, how it works, the bugs found and
fixed, and how to run it. It complements the
[design spec](superpowers/specs/2026-06-27-scout-design.md).

---

## 1. What ScoutMini is

A command-line tool that answers analytical **Formula 1** questions by fetching
real data, then having an LLM (OpenAI `gpt-4o-mini`) write a short, **sourced**
report. The defining rule — the *golden rule* — is that the model may analyse
**only the data we fetched**, never its own memory, and must cite the numbers it
used. F1 is the first sport; the architecture is built so other sports can be
added behind the same interface.

```bash
python -m scoutmini ask "How is Norris doing this season?"
```

> The project was renamed from "Scout" to **ScoutMini** during the build:
> package `scoutmini`, CLI command `scoutmini` / `python -m scoutmini`.

---

## 2. Architecture

```
question ─▶ scout.route()      classify intent (driver form / standings /
                │                head-to-head / race analysis)
                ▼
           fetch real data ──▶ f1_data.py   (Jolpica-F1, Ergast-compatible)
                │          └─▶ news.py       (RSS headlines, optional)
                ▼
           scout.format_*()    build a fact-only data block
                ▼
           llm.analyze()       OpenAI writes a sourced report (golden rule)
                ▼
           report + sources  ─▶ printed to the terminal
```

Each file does one job and is independently testable. Deep timing data
(`fastf1_data.py`) is a separate, optional path exposed via the `pace` command.

### Modules

| File | Lines | Responsibility |
|---|---:|---|
| `config.py` | 60 | Load the OpenAI key + settings from `.env`; clear error if missing. |
| `f1_data.py` | 434 | F1 adapter over Jolpica-F1: parsers, driver/race matching, fetch+assemble. |
| `news.py` | 94 | Recent F1 news via RSS (stdlib XML, failure-tolerant). |
| `llm.py` | 57 | OpenAI wrapper + the anti-hallucination `GOLDEN_RULE` prompt. |
| `scout.py` | 268 | Router + orchestrator + the per-intent fact formatters. |
| `fastf1_data.py` | 159 | FastF1 deep data: pace + tyre strategy, on-disk cached. |
| `cli.py` | 105 | Typer CLI: `ask`, `driver`, `pace`; friendly error handling. |
| `__main__.py` | 6 | Enables `python -m scoutmini`. |

---

## 3. Features delivered

### 3.1 Question types (v1 — all four wired)

Each maps to a deterministic data fetch, so the data step never relies on the LLM:

| Type | Example | Data used |
|---|---|---|
| **Driver form** | `ask "How is Norris doing this season?"` | driver's full season results + standing |
| **Standings** | `ask "Show the driver standings"` | driver championship table |
| **Head-to-head** | `ask "Leclerc vs Norris this year"` | both drivers' seasons, side by side |
| **Race analysis** | `ask "What decided the Monaco Grand Prix?"` | a single race's full classification |

A small keyword/proper-noun **router** (`scout.route`) picks the intent and
extracts the driver/race names. Unsupported or ambiguous questions get a friendly
message (e.g. head-to-head with only one driver named).

### 3.2 Sourced reports + the golden rule

`llm.GOLDEN_RULE` instructs the model to use only the provided data and cite
specific numbers. Every report prints the exact **source URLs** it relied on.
Verified live across all four types — e.g. the driver-form report correctly
surfaced Norris's P2 / 374 pts / 4 wins / 13 podiums and even a P20 lapped race,
all from fetched data.

### 3.3 Recent news (RSS)

`news.py` fetches headlines from a free F1 RSS feed (Autosport), filtered by the
question's subject, and appends them to the report with links. News is
**non-critical**: any fetch/parse failure returns nothing rather than breaking the
report. Enabled by default in the CLI.

### 3.4 Deep timing data (FastF1)

```bash
pip install -e ".[fastf1]"
python -m scoutmini pace Leclerc Monaco --season 2024
```

`fastf1_data.py` computes a driver's **fastest lap, median race pace, and tyre
strategy** from FastF1's official timing data, cached on disk in `.ff1_cache/`.
The `pace` command needs **no OpenAI key** — it prints raw data. The pure
computation (`compute_pace`, `compute_stints`) operates on a plain DataFrame, so
it's tested without FastF1 or the network.

Verified live — Leclerc, Monaco 2024: 78 laps, fastest 1:15.162, MEDIUM (L1) →
HARD (L2–78), matching his real race (a lap-1 red-flag pit stop).

---

## 4. Data sources

- **Jolpica-F1** (`https://api.jolpi.ca/ergast/f1`) — the maintained, drop-in
  successor to the frozen Ergast API. Standings, results, schedule, drivers.
- **FastF1** — official F1 lap timing, tyre, and stint data (optional).
- **Autosport RSS** — recent news headlines.

---

## 5. Bugs found and fixed during the build

1. **DNF mis-classification (race analysis).** Drivers running "Lapped" (who
   *finished* a lap down) were being reported as retirements. Root cause: keying
   off the free-text `status` field. **Fix:** use Ergast's canonical
   `positionText` (a number = classified finisher; a letter like `R` =
   retirement). Now Monaco 2024 correctly shows only the 4 real lap-1 retirements.

2. **FastF1 resolving the wrong race.** `pace ... Monaco` loaded **Monza**
   (Italian GP) data. Root cause: FastF1's default schedule backend returned only
   a *partial* schedule (rounds 10–24) for the historical season, so its name
   matcher mis-resolved "Monaco" and integer rounds failed ("Invalid round: 8").
   **Fix:** resolve the race to a round number via our reliable Jolpica schedule,
   then load the event through FastF1's **Ergast** schedule backend (full 24-round
   schedule). Verified correct afterwards.

3. **Duplicate sources (head-to-head).** Two drivers share the standings
   endpoint, so it was listed twice. **Fix:** order-preserving de-duplication.

4. **Editable-install quirk (Python 3.13).** `pip install -e .` produces an
   `__editable__.*.pth` that this python.org 3.13 framework build ignores, so the
   bare `scoutmini` command couldn't import the package. **Fix/workaround:** added
   `__main__.py` so `python -m scoutmini` always works; documented `pip install .`
   for the console command.

---

## 6. Testing

TDD throughout — every behaviour got a failing test first. **65 tests, all
passing**, with no live network calls in the suite (HTTP, OpenAI, and FastF1 are
all dependency-injected and fed fixtures/fakes).

| Test file | Tests | Covers |
|---|---:|---|
| `test_config.py` | 4 | key loading, defaults, missing-key error |
| `test_f1_data.py` | 22 | parsers, driver/race matching, fetch assembly, classification |
| `test_router.py` | 7 | intent classification |
| `test_scout.py` | 11 | formatters + end-to-end orchestration (incl. news) |
| `test_llm.py` | 3 | prompt building, golden rule, OpenAI call (mocked) |
| `test_news.py` | 6 | RSS parsing, filtering, failure tolerance |
| `test_fastf1_data.py` | 6 | pace/stint computation, formatting, loader injection |
| `test_cli.py` | 6 | commands + friendly errors |

```bash
pytest        # all 65
```

---

## 7. How to run

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"            # add ",fastf1" for the pace command
cp .env.example .env               # then paste your OpenAI API key

python -m scoutmini ask "How is Norris doing this season?"
python -m scoutmini ask "Leclerc vs Norris this year"
python -m scoutmini ask "What decided the Monaco Grand Prix?"
python -m scoutmini pace Leclerc Monaco --season 2024
```

Cost: each `ask` runs on `gpt-4o-mini` for a fraction of a cent. `pace` is free
(no LLM). Secrets live in `.env`, which is git-ignored.

---

## 8. Commit history

| Commit | Summary |
|---|---|
| `35137c2` | Add Scout design spec |
| `71e8e2b` | Implement v1 driver-form pipeline |
| `8be5da6` | Wire standings and head-to-head |
| `47afb8e` | Wire race analysis (completes v1 intents) + DNF fix |
| `ae7df33` | Dedup head-to-head sources |
| `49b4b75` | Add news.py (RSS) and wire headlines into reports |
| `d83b98f` | Add FastF1 deep-data adapter and `pace` command |

---

## 9. What's left

Only the **v2 stretch** from the spec: a real agent using OpenAI
function-calling, where the model chooses which `f1_data` tools to call and
reasons in multiple steps — removing the fixed question-type list. Everything in
the v1 scope (plus news and FastF1 deep data) is done and verified live.
