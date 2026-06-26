from types import SimpleNamespace

from scoutmini.llm import GOLDEN_RULE, analyze, build_messages


def test_build_messages_includes_golden_rule_and_payload():
    msgs = build_messages(
        question="How is Norris doing?",
        data_text="Norris: P2, 374 pts",
        sources="https://example/results",
    )

    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    assert msgs[0]["content"] == GOLDEN_RULE
    user = msgs[1]["content"]
    assert "How is Norris doing?" in user
    assert "Norris: P2, 374 pts" in user
    assert "https://example/results" in user


def test_golden_rule_states_the_anti_hallucination_constraint():
    lowered = GOLDEN_RULE.lower()
    assert "only" in lowered  # "analyze only the data provided"
    assert "cite" in lowered  # must cite the numbers used


class _FakeClient:
    """Minimal stand-in for openai.OpenAI capturing the create() call."""

    def __init__(self, content="  the report  "):
        self.captured = {}
        create = self._create

        class _Completions:
            def create(_self, **kwargs):
                return create(**kwargs)

        self.chat = SimpleNamespace(completions=_Completions())
        self._content = content

    def _create(self, **kwargs):
        self.captured.update(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self._content))]
        )


def test_analyze_calls_model_and_returns_trimmed_text():
    client = _FakeClient(content="  Norris is having a strong season.  ")

    out = analyze(
        question="How is Norris doing?",
        data_text="P2, 374 pts",
        sources="src",
        model="gpt-4o-mini",
        client=client,
    )

    assert out == "Norris is having a strong season."
    assert client.captured["model"] == "gpt-4o-mini"
    assert len(client.captured["messages"]) == 2
    assert client.captured["messages"][0]["content"] == GOLDEN_RULE
