"""Repeatable evaluation of the DAQ-1 agent against live IS data.

Asks a fixed set of shifter questions, records which tools were called and the
answer, and writes a Markdown transcript to evals/<timestamp>-<model>.md.
Judging correctness is left to a human reading the transcript next to the tool
results (also recorded).

Run:  uv run python eval_agent.py [-m MODEL]
"""

import argparse
import asyncio
import datetime as dt
import json
import pathlib

from fastmcp import Client
from langchain.agents import create_agent
from langchain_openai import ChatOpenAI

import agent

QUESTIONS = [
    # (category, question) -- categories map to the Run Status page and to failure modes
    ("header", "What is the current status of the mytest partition?"),
    ("header", "Give me an overview of mytest"),
    ("run info", "What run number is mytest on, and is data being recorded?"),
    ("timing", "Which lumiblock is mytest on and how long has the run been active?"),
    ("counters", "How many events have been recorded in mytest?"),
    ("unavailable", "What is the data quality status in mytest?"),
    ("unavailable", "What are the trigger keys of mytest?"),
    ("unavailable", "Are there stable beams?"),
    ("missing partition", "Is the ATLAS partition running?"),
    ("trap: timestamp", "When did the last transition in mytest happen?"),
    ("trap: unset value", "When did the current run in mytest end?"),
    ("discovery", "What partitions exist?"),
    ("discovery", "Which ROS applications publish data in mytest?"),
]


async def run(model: str, webis_url: str | None = None) -> pathlib.Path:
    llm = ChatOpenAI(model=model, base_url=agent.AIGW_URL, api_key=agent.load_key(),
                     temperature=0, timeout=120)
    calls: list[str] = []

    async with Client(agent.server_transport(webis_url)) as client:
        tools = await agent.mcp_tools(client, verbose=False)
        # wrap tools to record calls for the transcript
        for t in tools:
            orig = t.coroutine
            async def rec(_orig=orig, _name=t.name, **kw):
                out = await _orig(**kw)
                calls.append(f"`{_name}({json.dumps(kw)})` → `{out[:300]}`")
                return out
            t.coroutine = rec
        graph = create_agent(llm, tools, system_prompt=agent.SYSTEM_PROMPT)

        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        lines = [f"# DAQ-1 agent evaluation — {model} — {stamp}", ""]
        for i, (cat, q) in enumerate(QUESTIONS, 1):
            calls.clear()
            t0 = dt.datetime.now()
            a = await agent.answer(graph, q)
            secs = (dt.datetime.now() - t0).total_seconds()
            print(f"[{i}/{len(QUESTIONS)}] {cat}: {secs:.1f}s, {len(calls)} tool call(s)")
            lines += [f"## {i}. [{cat}] {q}", "", f"*{secs:.1f} s*", "", "**Tool calls**", ""]
            lines += [f"- {c}" for c in calls] or ["- (none)"]
            lines += ["", "**Answer**", "", a.strip(), "", "**Verdict:** _to fill in_", ""]

    out_dir = agent.HERE / "evals"
    out_dir.mkdir(exist_ok=True)
    path = out_dir / f"{stamp}-{model}.md"
    path.write_text("\n".join(lines))
    return path


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("-m", "--model", default="gpt-oss-20b")
    ap.add_argument("-w", "--webis", help="Webis URL (default: $WEBIS_URL or 127.0.0.1:8080)")
    a = ap.parse_args()
    print("transcript:", asyncio.run(run(a.model, a.webis)))
