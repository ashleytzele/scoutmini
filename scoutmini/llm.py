"""OpenAI wrapper. Turns (question + fetched data + sources) into a sourced report.

The whole point of ScoutMini lives in :data:`GOLDEN_RULE`: the model is told to
analyse *only* the data we pass in and to cite the numbers it used. Network access
is injected via ``client`` so this is testable without a live key.
"""

from __future__ import annotations

from typing import List, Optional

from .config import Config

GOLDEN_RULE = (
    "You are ScoutMini, a Formula 1 analyst. Analyze ONLY the data provided in the "
    "user's message. Do NOT use any outside knowledge or memory about drivers, races, "
    "or results. If the answer is not in the provided data, say so plainly. "
    "Cite the specific numbers (positions, points, laps, dates) you used. "
    "Be concise: a few short paragraphs, no preamble."
)


def build_messages(question: str, data_text: str, sources: str) -> List[dict]:
    user = (
        f"Question: {question}\n\n"
        f"DATA (the only facts you may use):\n{data_text}\n\n"
        f"SOURCES:\n{sources}"
    )
    return [
        {"role": "system", "content": GOLDEN_RULE},
        {"role": "user", "content": user},
    ]


def make_client(config: Config):
    """Build a real OpenAI client. Imported lazily so tests never need the SDK."""
    from openai import OpenAI

    return OpenAI(api_key=config.openai_api_key)


def analyze(
    question: str,
    data_text: str,
    sources: str,
    *,
    model: str,
    client,
    temperature: float = 0.2,
) -> str:
    messages = build_messages(question, data_text, sources)
    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
    )
    return (resp.choices[0].message.content or "").strip()
