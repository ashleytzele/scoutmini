# ScoutMini — Tool Catalog Design (driver, team, live race)

**Date:** 2026-06-27
**Status:** Approved design, ready for implementation planning
**Builds on:** the v2 function-calling agent ([agent.py]) and the Jolpica adapter
([f1_data.py]); see the [original design spec](2026-06-27-scout-design.md).

---

## 1. Goal

Expand ScoutMini from four fixed question types into a richer set of **tools** the
v2 agent can call to *understand a driver, a team, and a live race*. Every tool
obeys the **golden rule**: it returns only data fetched from an API, with the
source URL(s) attached — never the model's memory.

This is a large capability, so it is split into three phases. **Phase 1
(driver/team stats) is built first**; Phases 2–3 are roadmap.

## 2. Decisions captured from brainstorming

- **Depth:** both a broad *stats* layer (Jolpica) and a deep *analysis* layer
  (FastF1).
- **History:** modern era, **2014+** for Jolpica stats; FastF1 deep data only
  exists from **2018+**.
- **Live race:** cover all of running order + gaps, pit stops + tyres, race
  control, and weather; delivered **both** as agent-answered questions **and** a
  `live --watch` dashboard.
- **Tool granularity:** **hybrid** — granular fetch tools plus a few curated
  "profile" tools, behind a tool registry.

## 3. Cross-cutting design (foundation, Phase 1)

### 3.1 Tool registry (`agent.py` refactor)
Today the agent hand-maintains a `TOOLS` schema list and a `run_tool` if/elif
dispatch. Going from 3 to ~20 tools, replace this with a registry: each tool is
one entry bundling `name`, `description`, JSON-schema `parameters`, a `dispatch`
callable `(args, *, season_default, fetch_json) -> (text, source_urls)`, and an
optional formatter. `TOOLS` (OpenAI schema) and dispatch are both derived from
the registry, so adding a tool is a single entry. This is a targeted refactor of
existing code, not a rewrite; the loop in `run_agent` is unchanged.

### 3.2 On-disk cache (`cache.py`)
A small JSON cache wrapping the Jolpica fetcher (`f1_data._default_fetch_json`):
- key = request URL; value = response JSON + fetch timestamp.
- **Past seasons** are immutable → cached indefinitely. "Past" = any season
  before the current calendar year (from the system clock).
- **Current season** (this calendar year) → short TTL (e.g. 1 hour).
- Stored under a git-ignored dir (e.g. `.jolpi_cache/`).
- Injected the same way `fetch_json` already is, so tests stay offline.

This makes career/history fan-out (one call per season) cheap and protects
against Jolpica rate limits.

### 3.3 Conventions
- Each new data getter returns a frozen dataclass carrying `source_urls`, mirrors
  the existing `f1_data` style, and has a pure parser tested against a saved
  fixture (no live calls in tests).
- Name resolution: add `match_constructor` (name → constructorId, e.g.
  "Red Bull" → `red_bull`) alongside the existing `match_driver`/`match_race`.

## 4. Phase 1 — Driver & Team stats (Jolpica, 2014+) — BUILD FIRST

Lives in a **new module `f1_stats.py`** (the existing `f1_data.py` is already
~434 lines and focused on the core fetchers; the stats layer is a distinct job).
It reuses `f1_data`'s dataclasses, `match_*`, and URL/parse helpers. Jolpica
endpoints are Ergast-compatible (`https://api.jolpi.ca/ergast/f1`).

### 4.1 Driver tools
| Tool | Params | Returns | Source endpoint(s) |
|---|---|---|---|
| `get_driver_career` | `driver, since=2014` | per-season rows + totals: races, wins, podiums, poles, points, titles, best finish, teams | per-season `/{yr}/drivers/{id}/results.json` + `/{yr}/drivers/{id}/driverStandings.json` (looped, cached) |
| `get_qualifying` | `season, race, driver?` | grid/quali order, Q1–Q3 times | `/{season}/{round}/qualifying.json` |
| `driver_head_to_head` | `a, b, season?` | race finishes, **qualifying** H2H, points, wins; per-season if no season given | reuses driver-season + qualifying |
| `get_driver_circuit_record` | `driver, circuit` | results at one circuit across seasons | per-season results filtered by circuit |
| `driver_profile` *(curated)* | `driver` | career totals + current season + notable circuit records, one call | composes the above |

### 4.2 Team / constructor tools
| Tool | Params | Returns | Source endpoint(s) |
|---|---|---|---|
| `get_constructor_standings` | `season` | constructor championship table | `/{season}/constructorStandings.json` |
| `get_constructor_season` | `team, season` | both drivers, points, wins, podiums | `/{season}/constructors/{id}/results.json` + standings |
| `get_constructor_history` | `team, since=2014` | titles, wins/points per season, driver lineups | looped per-season (cached) |
| `constructor_head_to_head` | `a, b, season?` | points, wins, finishing comparison | composes constructor-season |
| `team_profile` *(curated)* | `team` | history summary + current season + current drivers | composes the above |

### 4.3 Reference tools
- `get_schedule(season)` — calendar (round, circuit, date). (Schedule fetch
  already exists via `get_race_meta`; expose a season-calendar tool.)
- `get_circuit(name)` — circuit details + which rounds it has hosted.

### 4.4 Surfacing
All Phase 1 tools are registered with the agent. The high-value ones also get CLI
commands: `scoutmini career <driver>`, `scoutmini team <name>`, `scoutmini
qualifying <race> [--season]`. Existing `ask`/`agent`/`pace` are untouched.

### 4.5 Edge cases
- Unknown driver/team/circuit → friendly "did you mean…" (reuse the
  `match_*` + suggestion pattern).
- A season/round with no data yet → say so plainly (existing `DataNotAvailable`).
- Career fan-out: Ergast paginates results (30/page); aggregate **per season**
  (bounded, cache-friendly) rather than one huge paginated career call.

### 4.6 Testing
- Pure parsers (qualifying, constructor standings/results, career aggregation)
  → unit tests against small saved fixtures.
- `match_constructor` → unit tests.
- Cache → unit test hit/miss + TTL with an injected clock and temp dir.
- Registry → test that every entry has a valid schema and dispatch; agent loop
  unchanged (existing tests still pass).
- No live network in the suite.

## 5. Phase 2 — Deep analysis (FastF1, 2018+) — roadmap

Builds on the existing `fastf1_data.get_driver_pace`. Tools: promote
`get_driver_pace` to an agent tool; add `quali_vs_race_pace`, `get_tyre_strategy`,
`form_trend` (rolling results/points momentum), `compare_teammates` (intra-team
quali/race H2H — the purest skill signal), and `driver_strengths` (derived
circuit-type and quali-vs-race splits). Same pure-compute-on-a-DataFrame pattern
as today, cached via `.ff1_cache/`.

## 6. Phase 3 — Live race (OpenF1) + UX — roadmap

New adapter `openf1_data.py` over the **OpenF1 API** (openf1.org; free REST/JSON,
real-time during sessions + historical). Tools, all agent-registered:
`session_status` (gate: is a session live, and which), `live_positions`,
`live_intervals`, `live_pit`, `live_tyres`, `race_control` (flags, SC/VSC,
penalties, investigations), `live_weather`.

UX: `scoutmini live` (one-shot snapshot) and `scoutmini live --watch` (polls every
N seconds and redraws a compact board: order | gap | tyre | last race-control
message). Caveats: live fields only populate while a session runs (otherwise
last-known state); polling needs sensible intervals + light caching; a true live
demo must wait for an actual session. Citations include the OpenF1 endpoint +
timestamp.

## 7. Out of scope (for now)

- Narrative/explanatory encyclopedia (rules, controversies, history prose) — would
  need a citable text source (e.g. Wikipedia) to honour the golden rule; a
  separate decision.
- A second sport adapter.
- Web UI.

## 8. Build order

1. **Phase 1** foundation (cache + registry) → driver tools → team tools →
   reference tools → CLI commands → tests.
2. Phase 2 (FastF1 analysis).
3. Phase 3 (OpenF1 live + watch dashboard).

Each phase ships independently and keeps the suite green.
