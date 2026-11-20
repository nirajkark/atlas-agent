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


# --- get_run_info: built from the live RunParams.RunParams of 'mytest' (2026-11-20) ---

def run_params(**override):
    attrs = {"run_number": 160902, "max_events": 0, "recording_enabled": 0, "trigger_type": 0,
             "run_type": "Physics", "det_mask": "00000000000000000000280000000001",
             "beam_type": 0, "beam_energy": 0, "filename_tag": "", "T0_project_tag": "",
             "timeSOR": "20/11/26 11:27:25", "timeEOR": "1/1/70 01:00:00", "totalTime": 0}
    attrs.update(override)
    return {"name": "RunParams.RunParams", "type": "RunParams",
            "updated": "20/11/26 11:27:25.742991", "source": URL, "attributes": attrs}


def test_run_info_live_shape(monkeypatch):
    monkeypatch.setattr(webis, "get_object", lambda *a: run_params())
    r = call("get_run_info", partition="mytest")
    assert r["available"] is True
    assert r["run_number"] == 160902 and r["run_type"] == "Physics"
    assert r["recording_enabled"] is False          # 0 -> Disabled, as in ATLAS.js
    assert r["start_of_run"] == "20/11/26 11:27:25"
    assert r["end_of_run"] is None                  # epoch-0 placeholder is not a date
    assert r["max_events"] == 0                     # raw, not interpreted as "unlimited"
    assert r["project_tag"] is None                 # empty string -> not set
    assert "totalTime" not in r and "total_time" not in r


def test_run_info_ended_run(monkeypatch):
    monkeypatch.setattr(webis, "get_object",
                        lambda *a: run_params(recording_enabled=1, timeEOR="20/11/26 12:00:00"))
    r = call("get_run_info", partition="mytest")
    assert r["recording_enabled"] is True
    assert r["end_of_run"] == "20/11/26 12:00:00"


def test_run_info_missing(monkeypatch):
    def missing(*a):
        raise webis.WebisError("invalid_object", "No such object: RunParams.RunParams", URL)
    monkeypatch.setattr(webis, "get_object", missing)
    r = call("get_run_info", partition="initial")
    assert r["available"] is False and "run_number" not in r
