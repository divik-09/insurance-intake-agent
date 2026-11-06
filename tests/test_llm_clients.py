import json
from types import SimpleNamespace

import pytest

from app.llm import AnthropicClient, ExtractionError, OpenAIClient, build_llm


class FakeAnthropic:
    """Mimics anthropic.Anthropic().messages.create()."""

    def __init__(self, content=None, raises=None):
        self._content, self._raises = content, raises
        self.last_kwargs = None
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.last_kwargs = kwargs
        if self._raises:
            raise self._raises
        return SimpleNamespace(content=self._content)


def test_anthropic_returns_tool_input_and_forces_tool_use():
    payload = {"business_name": "Acme", "state": "OH"}
    fake = FakeAnthropic(content=[SimpleNamespace(type="text", text="hi"),
                                  SimpleNamespace(type="tool_use", input=payload)])
    out = AnthropicClient("some-model", client=fake).extract("email text", {"state": None})
    assert out == payload
    assert fake.last_kwargs["tool_choice"] == {"type": "tool", "name": "record_submission"}
    assert "email text" in fake.last_kwargs["messages"][0]["content"]
    assert "untrusted" in fake.last_kwargs["system"]  # prompt-injection guard is present


def test_anthropic_without_tool_block_raises():
    fake = FakeAnthropic(content=[SimpleNamespace(type="text", text="sorry")])
    with pytest.raises(ExtractionError):
        AnthropicClient("m", client=fake).extract("x", {})


def test_anthropic_api_failure_becomes_extraction_error():
    with pytest.raises(ExtractionError):
        AnthropicClient("m", client=FakeAnthropic(raises=TimeoutError("boom"))).extract("x", {})


def test_openai_parses_json_mode_response():
    body = json.dumps({"business_name": "Acme"})
    create = lambda **kw: SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=body))])  # noqa: E731
    fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    assert OpenAIClient("m", client=fake).extract("x", {}) == {"business_name": "Acme"}


def test_openai_bad_json_becomes_extraction_error():
    create = lambda **kw: SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="not json"))])  # noqa: E731
    fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    with pytest.raises(ExtractionError):
        OpenAIClient("m", client=fake).extract("x", {})


def test_build_llm_factory():
    assert build_llm("heuristic").name == "heuristic"
    with pytest.raises(ValueError):
        build_llm("skynet")
