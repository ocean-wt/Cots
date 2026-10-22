"""Token accounting: provider usage receipt vs local estimation."""

import pytest

from app.agents.llm import LLMService


class _Chunk:
    def __init__(self, content="", usage_metadata=None):
        self.content = content
        self.usage_metadata = usage_metadata


class _FakeChat:
    """Streams 2 text chunks; optionally returns usage on the last chunk."""

    def __init__(self, with_usage: bool):
        self.with_usage = with_usage

    async def astream(self, _messages):
        yield _Chunk("你好")
        if self.with_usage:
            yield _Chunk(
                "世界",
                {"input_tokens": 11, "output_tokens": 7, "total_tokens": 18},
            )
        else:
            yield _Chunk("世界")
        return

    def bind(self, *_a, **_k):
        return self

    def with_structured_output(self, *_a, **_k):
        return self

    async def ainvoke(self, *_a, **_k):
        class _R:
            root_causes = []
            summary = "x"
            requests_ticket = False
            confidence = 0.5

        return _R()


@pytest.fixture
def service():
    return LLMService()


async def _collect(stream):
    texts, usage = [], None
    async for text, u in stream:
        if text:
            texts.append(text)
        usage = u
    return "".join(texts), usage


async def test_stream_usage_marked_exact_when_provider_reports(service):
    service._chat = _FakeChat(with_usage=True)
    service.provider, service.model, = "fake", "fake-1"
    text, usage = await _collect(service.stream_synthesis("sys", "usr"))
    assert text == "你好世界"
    assert usage["estimated"] is False
    assert usage["total_tokens"] == 18
    assert usage["prompt_tokens"] == 11
    assert usage["completion_tokens"] == 7


async def test_stream_usage_estimated_when_provider_silent(service):
    service._chat = _FakeChat(with_usage=False)
    service.provider, service.model = "fake", "fake-1"
    text, usage = await _collect(service.stream_synthesis("sys", "usr"))
    assert text == "你好世界"
    assert usage["estimated"] is True
    assert usage["completion_tokens"] > 0
    assert usage["total_tokens"] == usage["prompt_tokens"] + usage["completion_tokens"]


async def test_unavailable_service_yields_nothing(service):
    service._chat = None
    collected = [x async for x in service.stream_synthesis("s", "u")]
    assert collected == []
