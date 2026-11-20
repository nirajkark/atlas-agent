"""DAQ-1 agent: ask questions about ATLAS TDAQ in plain English.

    LangGraph agent (LLM on CERN AI Gateway) --MCP/stdio--> server.py --HTTP--> Webis --> IS

Run:
    uv run python agent.py                      # interactive
    uv run python agent.py -q "Is mytest running?"
    uv run python agent.py -m qwen3.8-27b-fp16 -v   # other model, show tool calls
Needs: AIGW_API_KEY in .env, Webis reachable at WEBIS_URL (default 127.0.0.1:8080).
"""

import argparse
import asyncio
import json
import pathlib

from fastmcp import Client
from langchain.agents import create_agent
from langchain_core.tools import StructuredTool
from langchain_openai import ChatOpenAI

HERE = pathlib.Path(__file__).parent
AIGW_URL = "https://aigw.cern.ch/"

SYSTEM_PROMPT = """You assist ATLAS TDAQ shifters with the current state of the online system.

Rules:
- Use the tools for every factual statement. Never guess or fill in values.
- If a tool returns available=false, say the data is not available and give the
  reason from the tool (e.g. "no such partition", "object not published",
  "Webis unreachable").
- If a partition is RUNNING but fault=true, say both clearly and list
  bad_children and error_reasons.
- Timestamps: quote them as IS reports them and say the time zone is not
  specified by IS. Do not convert them.
- Write for a shifter: lead with a one-sentence answer, then only the
  relevant details. Short and plain; no raw field dumps.
"""


def load_key() -> str:
    env = dict(l.split("=", 1) for l in (HERE / ".env").read_text().split() if "=" in l)
    return env["AIGW_API_KEY"]


async def mcp_tools(client: Client, verbose: bool) -> list[StructuredTool]:
    """Bridge: expose every tool of the MCP server as a LangChain tool."""
    tools = []
    for t in await client.list_tools():
        async def call(_name=t.name, **args):
            if verbose:
                print(f"   [tool] {_name}({args})")
            r = await client.call_tool(_name, args, raise_on_error=False)
            return json.dumps(r.structured_content or {"content": str(r.content)})
        tools.append(StructuredTool.from_function(
            coroutine=call, name=t.name, description=t.description or "",
            args_schema=t.input_schema))  # JSON schema straight from the MCP server
    return tools


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-q", "--question", help="ask one question and exit")
    ap.add_argument("-m", "--model", default="gpt-oss-20b")
    ap.add_argument("-v", "--verbose", action="store_true", help="show tool calls")
    args = ap.parse_args()

    llm = ChatOpenAI(model=args.model, base_url=AIGW_URL, api_key=load_key(),
                     temperature=0, timeout=120)

    # Start server.py as a separate process and talk MCP to it over stdio.
    async with Client(HERE / "server.py") as client:
        agent = create_agent(llm, await mcp_tools(client, args.verbose),
                             system_prompt=SYSTEM_PROMPT)

        async def ask(q: str) -> str:
            out = await agent.ainvoke({"messages": [{"role": "user", "content": q}]})
            return out["messages"][-1].content

        if args.question:
            print(await ask(args.question))
            return
        print(f"DAQ-1 agent ({args.model}). Ctrl-D to quit.")
        while True:
            try:
                q = input("\n> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if q:
                print(await ask(q))


if __name__ == "__main__":
    asyncio.run(main())
