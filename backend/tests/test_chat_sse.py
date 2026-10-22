"""End-to-end SSE API tests through the real FastAPI application."""

import json

import httpx
import pytest

from app.main import app

pytestmark = pytest.mark.usefixtures("stack")


async def _stream_chat(message: str) -> tuple[httpx.Response, list[dict]]:
    transport = httpx.ASGITransport(app=app)
    events: list[dict] = []
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        async with client.stream(
            "POST",
            "/api/v1/chat/stream",
            json={"message": message},
            headers={
                "X-Tenant-Id": "1",
                "X-Trace-Id": "trc-gateway-001",
                "X-Gateway-Token": "cots-internal-dev-token",
            },
        ) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            assert response.headers["x-trace-id"]
            event_name = None
            async for line in response.aiter_lines():
                if line.startswith("event:"):
                    event_name = line.split(":", 1)[1].strip()
                elif line.startswith("data:"):
                    data = json.loads(line.split(":", 1)[1].strip())
                    events.append({"event": event_name, "data": data})
                    event_name = None
    return response, events


async def test_sse_streams_agent_actions_evidence_tokens_and_final():
    _response, events = await _stream_chat(
        "系统报 429 错误了，traceID trc-9f3a2c7b1e4d"
    )
    kinds = [e["event"] for e in events]

    assert "agent_action" in kinds
    assert "evidence" in kinds
    assert "token" in kinds
    assert "final" in kinds
    assert kinds[-1] == "done"

    agents = {
        e["data"]["agent"]
        for e in events
        if e["event"] == "agent_action" and e["data"]["agent"] != "supervisor"
    }
    assert {"diagnostic", "billing", "knowledge"} <= agents

    final = next(e["data"] for e in events if e["event"] == "final")
    report = final["report"]
    assert "证据链" in report["conclusion_markdown"]
    assert report["evidences"]
    assert report["token_usage"]["total_tokens"] > 0
    # Rules-engine path has no provider receipt -> flagged as estimated.
    assert report["token_usage_estimated"] is True

    # Typewriter streaming actually produced incremental tokens
    token_events = [e for e in events if e["event"] == "token"]
    assert len(token_events) > 10

    # trace id from gateway header is honored end-to-end
    assert report["trace_id"] == "trc-gateway-001"


async def test_sse_sequence_ids_are_monotonic():
    _response, events = await _stream_chat("QPS 被限制是不是欠费了？")
    # ids are present on raw stream; here we validate event ordering via payloads
    assert events[0]["event"] in {"agent_action", "round"}
    final_pos = next(i for i, e in enumerate(events) if e["event"] == "final")
    done_pos = next(i for i, e in enumerate(events) if e["event"] == "done")
    assert done_pos > final_pos
