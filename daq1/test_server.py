"""Tests for the MCP tool, called through a real in-memory MCP client.

webis.get_object is replaced by fakes built from responses captured on the testbed.
Run:  uv run pytest
"""

import asyncio

from fastmcp import Client

import server
import webis

URL = "http://127.0.0.1:8080/info/current/mytest/is/RunCtrl/RunCtrl.RootController"


def root_controller(state="INITIAL"):
    return {
        "name": "RunCtrl.RootController", "type": "RCStateInfo",
        "updated": "20/11/26 10:42:47.605131", "source": URL,
        "attributes": {"state": state, "busy": False, "fault": False, "transitioning": False,
                       "errorReasons": [], "badChildren": [], "lastTransitionName": "INITIALIZE"},
    }


def call(tool, **args):
    async def _run():
        async with Client(server.mcp) as c:
            return (await c.call_tool(tool, args)).data
    return asyncio.run(_run())


def test_tool_is_listed_and_read_only():
    async def _run():
        async with Client(server.mcp) as c:
            return await c.list_tools()
    tool = next(t for t in asyncio.run(_run()) if t.name == "get_run_state")
    assert tool.annotations.read_only_hint is True


def test_not_running(monkeypatch):
    # The real state of 'mytest' on 2026-11-20 (the PDF's example question)
    monkeypatch.setattr(webis, "get_object", lambda *a: root_controller("INITIAL"))
    r = call("get_run_state", partition="mytest")
    assert r["available"] is True
    assert r["state"] == "INITIAL"
    assert r["running"] is False
    assert r["is_updated"] == "20/11/26 10:42:47.605131"
    assert r["source"] == URL


def test_running(monkeypatch):
    monkeypatch.setattr(webis, "get_object", lambda *a: root_controller("RUNNING"))
    assert call("get_run_state", partition="mytest")["running"] is True


def test_missing_partition_is_not_reported_as_not_running(monkeypatch):
    def missing(*a):
        raise webis.WebisError("invalid_object", "No such object: RunCtrl.RootController", URL)
    monkeypatch.setattr(webis, "get_object", missing)
    r = call("get_run_state", partition="nope")
    assert r["available"] is False
    assert r["reason"] == "invalid_object"
    assert "running" not in r and "state" not in r   # no invented values


def test_webis_down(monkeypatch):
    def down(*a):
        raise webis.WebisError("unreachable", "Connection refused", URL)
    monkeypatch.setattr(webis, "get_object", down)
    r = call("get_run_state", partition="mytest")
    assert r == {"partition": "mytest", "available": False, "reason": "unreachable",
                 "detail": "Connection refused", "source": URL}
