"""DAQ-1 agent: ask questions about ATLAS TDAQ in plain English.

    LangGraph agent (LLM on CERN AI Gateway) --MCP/stdio--> server.py --HTTP--> Webis --> IS

Run:
    uv run python agent.py                      # interactive
    uv run python agent.py -q "Is mytest running?"
    uv run python agent.py -m qwen3.8-27b-fp16 -v   # other model, show tool calls
    uv run python agent.py -w http://127.0.0.1:8081 # another Webis (e.g. own partition)
Needs: AIGW_API_KEY in .env, Webis reachable at WEBIS_URL (default 127.0.0.1:8080).
"""

import argparse
import asyncio
import json
import os
import pathlib

from fastmcp import Client
from fastmcp.client.transports import PythonStdioTransport
from langchain.agents import create_agent
from langchain_core.tools import StructuredTool
from langchain_openai import ChatOpenAI

HERE = pathlib.Path(__file__).parent
AIGW_URL = "https://aigw.cern.ch/"
DEFAULT_WEBIS = "http://127.0.0.1:8080"


def server_transport(webis_url: str | None = None) -> PythonStdioTransport:
    """Start server.py as a child process, passing WEBIS_URL explicitly.

    MCP's stdio launcher does not forward the parent's environment, so without
    this the server always used the default Webis (seen live: a request meant for
    port 8081 went to 8080).
    """
    url = webis_url or os.environ.get("WEBIS_URL", DEFAULT_WEBIS)
    return PythonStdioTransport(HERE / "server.py", env={"WEBIS_URL": url})

SYSTEM_PROMPT = """You assist ATLAS TDAQ shifters with the current state of the online system.

Rules:
- Use the tools for every factual statement. Never guess or fill in values.
  Never write example, placeholder or illustrative names or values: if you
  mention partitions, use only names a tool returned (e.g. existing_partitions).
- If a tool returns available=false, say the data is not available and give the
  reason from the tool (e.g. "no such partition", "object not published",
  "Webis unreachable").
- If a partition is RUNNING but fault=true, say both clearly and list
  bad_children and error_reasons.
- If a tool result has a `conclusion`, lead your answer with it.
- If a tool returns running=false with a running_basis (partition not up in
  IS), answer that the partition is not running and give that basis. Only in
  that case; if running is absent, the state is unknown.
- Timestamps: quote them as IS reports them and say they are in the local
  time of the Webis server. Do not convert them. Exception: fields ending in
  `_utc` are real UTC times; label them UTC. Only attach a time to an event
  if a field names that event (e.g. start_of_run). `is_updated` is just when
  IS last refreshed the data; never present it as the time of a transition.
- If the partition is RUNNING and `mode` is set, say whether it runs in
  Physics or StandBy mode.
- Report states as they are; do not explain what a state implies (e.g. do
  not say INITIAL means "ready for a new run") unless the user asks.
- IS holds only CURRENT values, no history. For questions about the past
  ("when was X last running?", "what happened at 08:00?"), say that IS
  cannot answer this and that historical data is in P-BEAST; you may still
  report the current state.
- Write for a shifter: lead with a one-sentence answer, then only the
  relevant details. Short and plain; no raw field dumps.

Partitions and tools:
- If the user names no partition, use list_partitions and ask which one;
  do not pick one yourself. (The beam status lives in the `initial` partition.)
- For a general "status" or "overview" question, use get_partition_overview
  and summarise state (with any fault), run number/type and timing together.
  Use the panel tools (event counters, trigger config, data quality, beam)
  when asked about those topics.
- If a panel tool reports data as unavailable, you may use list_is_objects to
  confirm what the partition actually publishes, and say so.
- For anything else, explore with list_is_servers / list_is_objects and read
  the object with read_is_object; use the attribute descriptions to explain values.
- IS servers (DF, RunCtrl, PMG, ...) are data containers, not applications.
  Application names are inside object names (RunCtrl.<app>, DF.ROS.<ROS name>),
  so list objects before naming applications.
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


MAX_RETRIES = 2


async def answer(agent, question: str) -> str:
    """Run the agent; never return silently.

    gpt-oss on the gateway sometimes emits a malformed tool call (e.g. name
    'list_partitions<|channel|>commentary', args '{""}'), which ends the run
    with an empty reply. Drop that bad turn, tell the model what went wrong and
    retry; if it still fails, say so explicitly instead of printing nothing.
    """
    messages = [{"role": "user", "content": question}]
    problem, unverified = "empty reply", None
    for _ in range(1 + MAX_RETRIES):
        out = await agent.ainvoke({"messages": messages})
        last = out["messages"][-1]
        bad = getattr(last, "invalid_tool_calls", None) or []
        used_tools = any(getattr(m, "type", None) == "tool" for m in out["messages"])
        if last.content and not bad and used_tools:
            return last.content
        if last.content and not bad:
            # Fluent answer with no IS query behind it: the most dangerous case.
            unverified = last.content
            problem = "answered without calling any tool"
            hint = ("You answered without querying IS. Every fact must come from a tool: "
                    "call the appropriate tool now (a word in the question may be a partition "
                    "name; check with list_partitions), then answer.")
        else:
            problem = (f"malformed tool call {bad[0].get('name')!r} with args "
                       f"{bad[0].get('args')!r}" if bad else "empty reply")
            hint = "Use the exact tool names and valid JSON arguments, then answer."
        messages = out["messages"][:-1] + [{
            "role": "user",
            "content": f"(System note: your previous step failed: {problem}. {hint} "
                       f"Original question: {question})"}]
    if unverified:
        return f"[Unverified: no IS data was queried]\n{unverified}"
    return f"[No answer: the model failed {1 + MAX_RETRIES} times ({problem}). Please retry.]"


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-q", "--question", help="ask one question and exit")
    ap.add_argument("-m", "--model", default="gpt-oss-20b")
    ap.add_argument("-v", "--verbose", action="store_true", help="show tool calls")
    ap.add_argument("-w", "--webis", help="Webis URL (default: $WEBIS_URL or %s)" % DEFAULT_WEBIS)
    args = ap.parse_args()

    llm = ChatOpenAI(model=args.model, base_url=AIGW_URL, api_key=load_key(),
                     temperature=0, timeout=120)

    # Start server.py as a separate process and talk MCP to it over stdio.
    async with Client(server_transport(args.webis)) as client:
        agent = create_agent(llm, await mcp_tools(client, args.verbose),
                             system_prompt=SYSTEM_PROMPT)

        async def ask(q: str) -> str:
            return await answer(agent, q)

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
