"""v2 — the function-calling agent.

Instead of v1's fixed router (one question -> one data fetch), here we hand the
F1 data functions to the model as *tools* and let it decide which to call, in
what order, across multiple turns. This removes the fixed question-type list:
the model can combine tools to answer open-ended questions.

The golden rule still holds: the model only ever sees data our tools return
(tool outputs), never its own memory. We accumulate the source URLs from every
tool it runs so the answer stays cited.

Network (``fetch_json``) and the OpenAI ``client`` are injected, so the whole
loop is testable with a scripted fake client and fixture data — no live calls.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import List, Tuple

from . import f1_data, llm
from .config import Config
from .scout import format_driver_season, format_race_analysis, format_standings

AGENT_SYSTEM = (
    "You are ScoutMini, a Formula 1 analyst. Answer the user's question using ONLY "
    "data returned by the provided tools — never your own memory or outside "
    "knowledge. Call whatever tools you need (you may call several, over multiple "
    "turns) to gather the facts, then give a concise answer that cites the specific "
    "numbers you used. If the tools don't contain the answer, say so plainly. "
    "When the user doesn't name a season, use the configured default season."
)

# OpenAI tool (function) specifications. Each maps to a function in run_tool().
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_driver_season",
            "description": (
                "A driver's full season: every race result (grid vs finish, points, "
                "status) plus their championship position, points, wins. Use for "
                "form, consistency, or single-driver questions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "driver": {"type": "string", "description": "Driver name, e.g. 'Norris'."},
                    "season": {"type": "integer", "description": "Season year, e.g. 2024."},
                },
                "required": ["driver"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_standings",
            "description": "The driver championship standings table (all drivers) for a season.",
            "parameters": {
                "type": "object",
                "properties": {
                    "season": {"type": "integer", "description": "Season year, e.g. 2024."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_race",
            "description": (
                "Full classification of a single race: winner, pole, every driver's "
                "grid vs finish, and who retired. Use for 'what happened at <race>'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "race": {"type": "string", "description": "Race name, e.g. 'Monaco'."},
                    "season": {"type": "integer", "description": "Season year, e.g. 2024."},
                },
                "required": ["race"],
            },
        },
    },
]


@dataclass
class AgentResult:
    answer: str
    sources: List[str] = field(default_factory=list)
    steps: int = 0
    tool_calls: List[str] = field(default_factory=list)


def run_tool(
    name: str,
    args: dict,
    *,
    season_default: int,
    fetch_json,
) -> Tuple[str, List[str]]:
    """Execute one tool call. Returns (text for the model, source URLs).

    The text reuses v1's formatters, so the model sees the same fact-dense blocks.
    """
    season = int(args.get("season") or season_default)

    if name == "get_driver_season":
        ds = f1_data.get_driver_season(args["driver"], season, fetch_json=fetch_json)
        return format_driver_season(ds), list(ds.source_urls)
    if name == "get_standings":
        st = f1_data.get_standings(season, fetch_json=fetch_json)
        return format_standings(st), list(st.source_urls)
    if name == "get_race":
        ra = f1_data.get_race(args["race"], season, fetch_json=fetch_json)
        return format_race_analysis(ra), list(ra.source_urls)

    raise ValueError(f"Unknown tool: {name}")


def _assistant_msg(msg) -> dict:
    """Rebuild the model's tool-call turn as a plain dict to append to history."""
    return {
        "role": "assistant",
        "content": msg.content or "",
        "tool_calls": [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments},
            }
            for tc in msg.tool_calls
        ],
    }


def _dedup(seq: List[str]) -> List[str]:
    return list(dict.fromkeys(seq))


def run_agent(
    question: str,
    config: Config,
    *,
    client=None,
    fetch_json=f1_data._default_fetch_json,
    max_steps: int = 6,
) -> AgentResult:
    """Run the tool-calling loop until the model gives a final answer.

    Each turn: ask the model (offering the tools); if it requests tool calls, run
    them and feed the results back; otherwise return its answer. A ``max_steps``
    guard prevents infinite loops — if hit, we ask once more without tools.
    """
    if client is None:
        client = llm.make_client(config)

    messages = [
        {"role": "system", "content": AGENT_SYSTEM},
        {"role": "user", "content": question},
    ]
    sources: List[str] = []
    called: List[str] = []

    for step in range(1, max_steps + 1):
        resp = client.chat.completions.create(
            model=config.model,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
            temperature=0.2,
        )
        msg = resp.choices[0].message
        tool_calls = msg.tool_calls or []

        if not tool_calls:
            return AgentResult((msg.content or "").strip(), _dedup(sources), step, called)

        messages.append(_assistant_msg(msg))
        for tc in tool_calls:
            name = tc.function.name
            called.append(name)
            try:
                args = json.loads(tc.function.arguments or "{}")
                text, src = run_tool(
                    name, args, season_default=config.season, fetch_json=fetch_json
                )
                sources.extend(src)
            except Exception as exc:  # feed the error back so the model can recover
                text = f"ERROR running {name}: {exc}"
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": text})

    # Ran out of steps — force a final answer using only what we've gathered.
    resp = client.chat.completions.create(
        model=config.model,
        messages=messages
        + [{"role": "user", "content": "Give your best answer now using only the data already gathered."}],
        temperature=0.2,
    )
    return AgentResult((resp.choices[0].message.content or "").strip(), _dedup(sources), max_steps, called)
