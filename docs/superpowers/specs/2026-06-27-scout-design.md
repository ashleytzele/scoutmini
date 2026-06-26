# Scout — Design Spec

**Date:** 2026-06-27
**Author:** (student project, built with Claude Code)
**Status:** Approved design, ready for implementation planning

---

## 1. What Scout is

Scout is a command-line tool that answers **analytical questions about Formula 1** by
fetching real data (and recent news), then having an LLM write a short, **sourced**
report. It is the first sport in a design meant to extend to other sports later
(baseball, basketball, …) by adding new data adapters behind a shared interface —
"one engine, many sports."

Example:

```
scout ask "How does Verstappen's race pace compare to his qualifying this season?"
```

Scout fetches the relevant F1 data, sends it to OpenAI, and prints an analysis that
shows the exact stats and news links it used.

## 2. Goals and non-goals

**Goals (v1):**
- Answer a focused set of F1 question types from real fetched data.
- Always ground answers in fetched data and show sources (no hallucinated facts).
- Clean, swappable architecture so other sports can be added later.
- Be genuinely runnable and useful to the author, who follows F1.

**Non-goals (v1):**
- Not a fully open-ended autonomous agent (that is v2).
- Not multi-sport yet (F1 only; the structure makes adding sports cheap).
- Not a web UI (CLI first; web is a later stretch).
- Not predictions/betting models.

## 3. The golden rule (anti-hallucination)

**Scout analyzes only the data we fetched — never the model's own memory.**
The LLM prompt explicitly instructs: *"Analyze only the data provided below. If the
answer is not in the data, say so. Cite the specific numbers you used."* This is what
separates Scout from a chatbot guessing, and it is the project's core quality bar.

## 4. Tech stack

- **Language:** Python 3.10+
- **CLI:** `typer`
- **LLM:** OpenAI API via the `openai` SDK (small prepaid balance, key in `.env`)
- **F1 data:**
  - `FastF1` — lap times, race/quali pace, tyre strategy, telemetry (free)
  - **Ergast / Jolpica-F1** API — standings, results, schedule (free)
- **News:** a free source (F1/Autosport RSS, or a simple web-search step) — minimal in v1
- **Config:** `python-dotenv`
- **Tests:** `pytest`

## 5. Architecture

```
        your question
            │
            ▼
      ┌───────────┐   route: what data does this question need?
      │  scout.py │ ──────────────┐
      └───────────┘               │
            │ fetch               ▼
            ├──────────▶ f1_data.py      ◀── SWAPPABLE SPORT ADAPTER
            │            (FastF1 + Ergast)     (later: baseball_data.py, nba_data.py)
            ├──────────▶ news.py
            │
            ▼
        llm.py (OpenAI) ──▶ writes a sourced report
            │
            ▼
        report + sources (printed to terminal)
```

Every sport adapter exposes the **same interface** (e.g. `get_driver_stats`,
`get_results`, `get_standings`). Adding a sport later = write one new adapter file;
`scout.py`, `llm.py`, and `cli.py` do not change.

## 6. Components (one file, one job)

| File | Responsibility | Depends on |
|---|---|---|
| `config.py` | Load OpenAI key from `.env`; hold settings (model name, season, data limits). | `python-dotenv` |
| `f1_data.py` | F1 adapter. Functions returning clean structured data (driver season, results, standings, pace). | `FastF1`, Ergast/Jolpica |
| `news.py` | Fetch recent F1 news relevant to the question. | RSS / web search |
| `llm.py` | OpenAI wrapper. Input: question + data + news. Output: sourced report text. | `openai` |
| `scout.py` | Orchestrator. Route question → fetch data/news → call `llm` → assemble report. | the above |
| `cli.py` | Commands: `scout ask "..."`, plus shortcuts (e.g. `scout driver <name>`). | `typer`, `scout.py` |

Each file should be understandable and testable on its own. If a file grows large or
starts doing two jobs, split it.

## 7. v1 question types (bounded scope)

v1 supports a focused set, each mapping to a known data fetch (so the data step is
deterministic and we avoid agent-loop complexity):

1. **Driver form** — "how is Norris doing this season?"
2. **Head-to-head** — "Leclerc vs Sainz this year"
3. **Race analysis** — "what decided the Monaco GP?"
4. **Season / standings summary**

A small router in `scout.py` maps the question to one of these intents and the data it
needs. (v2 removes this restriction — see §10.)

## 8. Error handling

- **Missing/invalid OpenAI key** → clear message naming the key and where to set it.
- **Unknown driver / race** → friendly "did you mean…?" rather than a crash.
- **Data not available yet** (e.g. a session that hasn't happened) → say so plainly.
- **OpenAI / network errors** → SDK retries; surface a clean message if it still fails.
- **FastF1 is slow to load** → enable FastF1's on-disk cache so repeat runs are fast.

## 9. Testing

- `f1_data.py` parsing → unit tests against small saved fixture responses (no live calls).
- `llm.py` and anything calling OpenAI → tested with the API **mocked** (fast, free).
- `scout.py` routing → unit tests mapping example questions to the right intent.

## 10. Build plan — one week

| Day | Goal |
|---|---|
| 1 | Setup: project + virtualenv, install deps, OpenAI key in `.env`; prove a "hello" OpenAI call **and** a first Ergast fetch work in isolation. |
| 2 | `f1_data.py`: clean adapter functions over Ergast (standings, results, a driver's season). |
| 3 | `llm.py` + `scout.py`: wire **one** question type (driver season summary) end-to-end. **Working Scout.** |
| 4 | Add FastF1 deeper data (race vs quali pace, tyres) + caching; add head-to-head + race-analysis. |
| 5 | `news.py` (simple RSS) + show sources in the report; polish CLI + error handling. |
| 6 | Tests (mock OpenAI, fixture data) + README. |
| 7 | Buffer / stretch: start v2 function-calling agent, polish, or sketch a 2nd-sport adapter. |

**Honest scope note:** a solid **v1 pipeline** is achievable in a week. The **v2 real
agent** (below) is a stretch for day 7 / the following week.

## 11. Growth path (post-v1)

- **v2 — real agent:** give the LLM the `f1_data` functions as *tools* (OpenAI
  function-calling) and let it decide which to call and reason in multiple steps.
  Removes the fixed question-type list. This is the headline "AI-native" upgrade.
- **Second sport:** add `baseball_data.py` (or NBA) behind the same interface to prove
  "one engine, many sports."
- **Web UI:** wrap the orchestrator in a small web app once the CLI is solid.

## 12. Setup the author still needs to do

- Create an OpenAI account, add ~$5 credit, generate an API key.
- Put the key in `.env` (never commit it; `.env` goes in `.gitignore`).
