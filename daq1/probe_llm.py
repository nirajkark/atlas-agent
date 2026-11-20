"""Probe the CERN AI Gateway: which chat models handle our tool-calling flow?

Reads AIGW_API_KEY from daq1/.env (never printed). Run:  uv run python probe_llm.py
"""

import json
import pathlib
import time

import httpx

BASE = "https://aigw.cern.ch"
ENV = pathlib.Path(__file__).with_name(".env")
KEY = dict(l.split("=", 1) for l in ENV.read_text().split() if "=" in l)["AIGW_API_KEY"]
H = {"Authorization": f"Bearer {KEY}"}

# Chat models from ml.docs.cern.ch/aigw/models (vertex previews retire 2026-11-20).
# Extras keep reasoning low so the probe is fast; values from the same docs page.
CANDIDATES = {
    "gpt-oss-20b": {"reasoning_effort": "low"},
    "glm-5.3-flash-int4": {"reasoning_effort": "low"},
    "qwen3.8-flash-next-int4": {"reasoning_effort": "low"},
    "qwen3.8-27b-fp16": {"chat_template_kwargs": {"enable_thinking": False}},
    "hf-qwen3-32b-awq": {},
    "gemma-4-12b-it-qat-w4a16-ct": {},
}

TOOL = {"type": "function", "function": {
    "name": "get_run_state",
    "description": "Current run-control state of a TDAQ partition (is it running?).",
    "parameters": {"type": "object", "properties": {"partition": {"type": "string"}},
                   "required": ["partition"]}}}
SYSTEM = ("Answer only from tool results. If a tool returns available=false, "
          "say the data is not available; never guess.")
QUESTION = "Is the mytest partition running?"
# Real result shape from server.get_run_state for 'mytest' (2026-11-20)
TOOL_RESULT = {"partition": "mytest", "available": True, "state": "INITIAL", "running": False,
               "busy": False, "fault": False, "last_transition": "INITIALIZE",
               "is_updated": "20/11/26 10:42:47.605131", "is_updated_tz": "local time of the Webis server (not converted)"}


def chat(model, messages, extra):
    r = httpx.post(f"{BASE}/chat/completions", headers=H, timeout=120, json={
        "model": model, "messages": messages, "tools": [TOOL], **extra})
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
    return r.json()["choices"][0]["message"]


def probe(model, extra):
    t0 = time.time()
    msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": QUESTION}]
    m1 = chat(model, msgs, extra)
    calls = m1.get("tool_calls") or []
    if not calls:
        return f"NO TOOL CALL  (replied: {(m1.get('content') or '')[:80]!r})", time.time() - t0
    c = calls[0]
    args = json.loads(c["function"]["arguments"] or "{}")
    ok_call = c["function"]["name"] == "get_run_state" and args.get("partition") == "mytest"
    msgs += [{"role": "assistant", "content": m1.get("content"), "tool_calls": calls},
             {"role": "tool", "tool_call_id": c["id"], "content": json.dumps(TOOL_RESULT)}]
    answer = (chat(model, msgs, extra).get("content") or "").strip()
    grounded = "not running" in answer.lower() or "initial" in answer.lower()
    verdict = ("OK" if ok_call and grounded else "CHECK") + f"  call={c['function']['name']}{args}"
    return f"{verdict}\n      answer: {answer[:200]!r}", time.time() - t0


if __name__ == "__main__":
    r = httpx.get(f"{BASE}/v1/models", headers=H, timeout=30)
    print("models endpoint:", r.status_code)
    served = {m["id"] for m in r.json().get("data", [])} if r.status_code == 200 else set()
    print("served:", ", ".join(sorted(served)) or "(could not list)")
    print()
    for model, extra in CANDIDATES.items():
        if served and model not in served:
            print(f"{model:30s} SKIP (not served to this key)")
            continue
        try:
            result, dt = probe(model, extra)
            print(f"{model:30s} {dt:5.1f}s  {result}")
        except Exception as e:
            print(f"{model:30s} ERROR {e}")
