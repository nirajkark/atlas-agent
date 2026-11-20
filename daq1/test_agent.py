"""Offline tests for agent.answer(): malformed tool calls must never end in silence.

The malformed call below is the one gpt-oss-20b actually produced on the CERN AI
Gateway on 2026-11-20. Run:  uv run pytest
"""

import asyncio

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

import agent

BAD = AIMessage(content="", invalid_tool_calls=[{
    "type": "invalid_tool_call", "id": "x", "name": "list_partitions<|channel|>commentary",
    "args": '{""}', "error": "not valid JSON"}])


TOOL_MSG = ToolMessage(content='{"available": false}', tool_call_id="t1")


class FakeAgent:
    def __init__(self, replies):
        self.replies, self.seen = list(replies), []

    async def ainvoke(self, state):
        self.seen.append(state["messages"])
        reply = self.replies.pop(0)
        if isinstance(reply, tuple):            # ("no-tool", msg): answer without any tool call
            return {"messages": [HumanMessage("q"), reply[1]]}
        return {"messages": [HumanMessage("q"), TOOL_MSG, reply]}


def test_retry_after_malformed_call():
    fake = FakeAgent([BAD, AIMessage(content="No such partition: ATLAS.")])
    assert asyncio.run(agent.answer(fake, "Is ATLAS running?")) == "No such partition: ATLAS."
    note = fake.seen[1][-1]
    assert "malformed tool call" in note["content"]
    assert BAD not in fake.seen[1]          # the broken turn is dropped, not resent


def test_gives_up_explicitly():
    fake = FakeAgent([BAD] * 3)
    r = asyncio.run(agent.answer(fake, "Is ATLAS running?"))
    assert r.startswith("[No answer") and "list_partitions<|channel|>commentary" in r


def test_empty_reply_is_not_returned():
    fake = FakeAgent([AIMessage(content=""), AIMessage(content="ok")])
    assert asyncio.run(agent.answer(fake, "q")) == "ok"


INVENTED = AIMessage(content="Partitions known to IS: ATLAS, mytest, initial")  # seen live, no tool call


def test_answer_without_tool_is_retried():
    fake = FakeAgent([("no-tool", INVENTED), AIMessage(content="mytest is RUNNING.")])
    assert asyncio.run(agent.answer(fake, "Give me an overview of mytest")) == "mytest is RUNNING."
    assert "without querying IS" in fake.seen[1][-1]["content"]


def test_answer_without_tool_is_flagged_if_it_persists():
    fake = FakeAgent([("no-tool", INVENTED)] * 3)
    r = asyncio.run(agent.answer(fake, "Give me an overview of mytest"))
    assert r.startswith("[Unverified: no IS data was queried]")
