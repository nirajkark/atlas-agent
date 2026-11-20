"""Multi-turn evaluation: one continuous conversation, a key question placed in the middle.

Tests whether earlier answers in the context bias a later answer (e.g. after five
questions about a RUNNING partition, does "is ATLAS running?" still get checked
against IS?). Writes a Markdown transcript to evals/.

Run:  uv run python eval_conversation.py [-w WEBIS_URL] [-m MODEL]
"""

import argparse
import asyncio
import datetime as dt
import json

from fastmcp import Client
from langchain.agents import create_agent
from langchain_openai import ChatOpenAI

import agent

QUESTIONS = [
    "Which partitions exist right now?",
    "Is nkarki_daq1 running?",
    "What run number and run type does it have?",
    "Which lumiblock is it on, and how long has the run been active?",
    "Is data being recorded, and are there any faults?",
    "What is the current status of the ATLAS partition?",      # <- the PDF question, mid-conversation
    "How many events have been recorded in nkarki_daq1?",
    "Are there stable beams?",
    "When did the current run in nkarki_daq1 start?",
    "So, to summarise: which partitions are running and which are not?",
]


async def run(model: str, webis_url: str | None):
    llm = ChatOpenAI(model=model, base_url=agent.AIGW_URL, api_key=agent.load_key(),
                     temperature=0, timeout=120)
    history: list = []
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    lines = [f"# DAQ-1 multi-turn evaluation — {model} — {stamp}", "",
             f"One conversation, {len(QUESTIONS)} questions; Webis: `{webis_url or 'default'}`.", ""]
    async with Client(agent.server_transport(webis_url)) as client:
        graph = create_agent(llm, await agent.mcp_tools(client, verbose=False),
                             system_prompt=agent.SYSTEM_PROMPT)
        for i, q in enumerate(QUESTIONS, 1):
            t0 = dt.datetime.now()
            out = await graph.ainvoke({"messages": history + [{"role": "user", "content": q}]})
            new = out["messages"][len(history):]
            calls = [f"`{c['name']}({json.dumps(c['args'])})`"
                     for m in new for c in (getattr(m, "tool_calls", None) or [])]
            answer = (new[-1].content or "").strip() or "[empty reply]"
            history = out["messages"]
            secs = (dt.datetime.now() - t0).total_seconds()
            mark = "  <-- PDF question" if "ATLAS" in q else ""
            print(f"[{i:2}] {secs:5.1f}s  tools: {', '.join(calls) or '(none)'}{mark}")
            print(f"     Q: {q}\n     A: {answer[:260].replace(chr(10), ' ')}\n")
            lines += [f"## {i}. {q}{' (PDF question)' if mark else ''}", "", f"*{secs:.1f} s*", "",
                      "**Tool calls:** " + (", ".join(calls) or "(none)"), "", answer, "",
                      "**Verdict:** _to fill in_", ""]
    path = agent.HERE / "evals" / f"{stamp}-conversation-{model}.md"
    path.write_text("\n".join(lines))
    print("transcript:", path)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("-m", "--model", default="gpt-oss-20b")
    ap.add_argument("-w", "--webis")
    a = ap.parse_args()
    asyncio.run(run(a.model, a.webis))
