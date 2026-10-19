#!/usr/bin/env python3
"""End-to-end SSE probe — simulates the browser through the Go gateway.

Verifies, with assertions:
  * SSE 200 + text/event-stream + X-Trace-Id round trip
  * CORS preflight (OPTIONS)
  * supervisor -> concurrent experts -> evidence -> typed final report -> done
  * multi-agent concurrency (every expert starts before any finishes)
  * evidence chain contains log + billing + knowledge kinds

Usage: python scripts/e2e_probe.py [gateway_url]
"""

import json
import sys
import urllib.request

GATEWAY = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8080"
PROMPT = "我收到了 429 错误，并且我的账单好像超支了，请帮我看看日志 trc-9f3a2c7b1e4d"


def parse_sse(raw: str):
    events = []
    for block in raw.replace("\r\n", "\n").split("\n\n"):
        event_name, event_id, data = None, None, None
        for line in block.split("\n"):
            if line.startswith("event:"):
                event_name = line[6:].strip()
            elif line.startswith("id:"):
                event_id = line[3:].strip()
            elif line.startswith("data:"):
                data = line[5:].strip()
        if event_name and data:
            events.append((int(event_id or 0), event_name, json.loads(data)))
    return events


def preflight():
    req = urllib.request.Request(
        f"{GATEWAY}/api/v1/chat/stream", method="OPTIONS", headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,last-event-id",
        })
    with urllib.request.urlopen(req, timeout=15) as resp:
        assert resp.status == 204, resp.status
        assert resp.headers.get("Access-Control-Allow-Origin") == "*"
        print(f"[ok] CORS preflight 204, Allow-Origin=*")


def main() -> int:
    preflight()

    body = json.dumps({"message": PROMPT}).encode()
    req = urllib.request.Request(
        f"{GATEWAY}/api/v1/chat/stream", data=body, method="POST", headers={
            "Content-Type": "application/json",
            "X-Trace-Id": "trc-e2e-probe-01",
            "Origin": "http://localhost:5173",
        })
    with urllib.request.urlopen(req, timeout=180) as resp:
        assert resp.status == 200, resp.status
        ctype = resp.headers.get("Content-Type", "")
        assert "text/event-stream" in ctype, ctype
        trace = resp.headers.get("X-Trace-Id")
        assert trace == "trc-e2e-probe-01", trace
        print(f"[ok] SSE 200 {ctype.strip()} X-Trace-Id={trace}")
        events = parse_sse(resp.read().decode())

    names = [e[1] for e in events]
    assert "agent_action" in names and "final" in names and "done" in names, names
    assert names[-1] == "done", names[-1]

    # sequence ids must be strictly monotonic (resume safety)
    ids = [e[0] for e in events if e[0] > 0]
    assert ids == sorted(set(ids)) and len(ids) > 20, "SSE ids not monotonic"

    actions = [d for n, d in ((e[1], e[2]) for e in events) if n == "agent_action"]
    expert_running, expert_done = [], []
    seen_agents = set()
    for idx, a in enumerate(actions):
        if a["agent"] == "supervisor":
            continue
        seen_agents.add(a["agent"])
        if a["status"] == "running":
            expert_running.append(idx)
        if a["status"] in ("done", "error", "timeout"):
            expert_done.append(idx)
    assert {"diagnostic", "billing", "knowledge"} <= seen_agents, seen_agents
    assert max(expert_running) < min(expert_done), \
        "experts did not run concurrently"
    print(f"[ok] concurrent experts: {sorted(seen_agents)} "
          f"(last start seq {max(expert_running)} < first finish {min(expert_done)})")

    evidences = [e[2] for e in events if e[1] == "evidence"]
    kinds = {e["kind"] for e in evidences}
    assert {"log", "billing", "knowledge"} <= kinds, kinds
    print(f"[ok] evidence kinds: {sorted(kinds)}")

    report = next(e[2]["report"] for e in events if e[1] == "final")
    assert report["trace_id"] == "trc-e2e-probe-01"
    assert "9f3a2c7b1e4d" in report["conclusion_markdown"]
    assert report["root_causes"], "no root causes"
    assert report["token_usage"]["total_tokens"] > 0
    assert "[E1]" in report["conclusion_markdown"]
    print(f"[ok] final report: intent={report['intent']} rounds={report['rounds']} "
          f"root_causes={len(report['root_causes'])} tokens="
          f"{report['token_usage']['total_tokens']}")
    print("\nE2E PROBE PASSED")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AssertionError as exc:
        print(f"\nE2E PROBE FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
