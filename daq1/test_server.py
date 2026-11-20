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


# --- panel tools: fake IS keyed by (server, object) ---------------------------------
# Shapes: RunParams.* / DF.* from the live 'mytest' partition (2026-11-20);
# TrigConf*, DQM.*, LHC.* follow the attribute names used in ref/ATLAS.js
# (not published on the testbed, so not verified against live data).

def fake_is(objects):
    def get_object(partition, server, obj):
        key = (server, obj)
        if key not in objects:
            raise webis.WebisError("invalid_object", f"No such object: {server}.{obj}", URL)
        return {"name": f"{server}.{obj}", "type": "T", "updated": "20/11/26 11:45:40.750959",
                "source": URL, "attributes": objects[key], "descriptions": {}}
    return get_object


def test_run_timing_live_shape(monkeypatch):
    monkeypatch.setattr(webis, "get_object", fake_is({
        ("RunParams", "LumiBlock"): {"RunNumber": 160902, "LumiBlockNumber": 5,
                                     "Time": 1795171540750956625},
        ("RunParams", "RunInfo"): {"activeTime": 1110},
        ("RunParams", "RunParams"): {"timeSOR": "20/11/26 11:27:25"},
    }))
    r = call("get_run_timing", partition="mytest")
    assert r["lumiblock"]["lumiblock"] == 5
    # IS showed this moment as 11:45:40 -> IS strings are UTC+1 on that date
    assert r["lumiblock"]["started_utc"] == "2026-11-20T10:45:40+00:00"
    assert r["active_time"] == {**r["active_time"], "seconds": 1110, "hhmmss": "00:18:30"}
    assert r["start_of_run"]["time"] == "20/11/26 11:27:25"


def test_run_timing_before_first_run(monkeypatch):
    monkeypatch.setattr(webis, "get_object", fake_is({}))
    r = call("get_run_timing", partition="mytest")
    assert r["available"] is False
    assert all(r[k]["available"] is False for k in ("lumiblock", "active_time", "start_of_run"))


def test_event_counters_partial(monkeypatch):
    monkeypatch.setattr(webis, "get_object", fake_is({
        ("DF", "HLTSV.Events"): {"LVL1Events": 1234567},
    }))
    r = call("get_event_counters", partition="mytest")
    assert r["available"] is True
    assert r["l1_triggers"]["value"] == 1234567
    assert r["accepted_events"]["available"] is False   # no invented zero
    assert "value" not in r["recorded_events"]


def test_trigger_config_full(monkeypatch):
    monkeypatch.setattr(webis, "get_object", fake_is({
        ("RunParams", "TrigConfSmKey"): {"SuperMasterKey": 3500},
        ("RunParams", "TrigConfL1PsKey"): {"L1PrescaleKey": 42},
        ("RunParams", "TrigConfHltPsKey"): {"HltPrescaleKey": 77},
        ("RunParams", "TrigConfL1BgKey"): {"L1BunchGroupKey": 9},
        ("RunParams", "TrigConfRelease"): {"HLTReleaseVersion": "25.0.1"},
    }))
    r = call("get_trigger_config", partition="ATLAS")
    assert r["super_master_key"]["value"] == 3500
    assert r["triggertool_url"].endswith("/smk/3500/l1psk/42/hltpsk/77")


def test_trigger_config_no_url_when_key_missing(monkeypatch):
    monkeypatch.setattr(webis, "get_object", fake_is({
        ("RunParams", "TrigConfSmKey"): {"SuperMasterKey": 3500},
    }))
    assert call("get_trigger_config", partition="ATLAS")["triggertool_url"] is None


def test_data_quality_colours(monkeypatch):
    monkeypatch.setattr(webis, "get_object", fake_is({
        ("DQM", "ATLAS"): {"status": 3}, ("DQM", "IDBCM"): {"status": 1}, ("DQM", "LCD"): {"status": 7},
    }))
    r = call("get_data_quality", partition="ATLAS")
    assert r["ATLAS"]["colour"] == "green" and r["IDBCM"]["colour"] == "red"
    assert r["LCD"]["status"] == 7 and r["LCD"]["colour"] is None   # unknown code: not guessed


def test_beam_status(monkeypatch):
    monkeypatch.setattr(webis, "get_object", fake_is({
        ("LHC", "StableBeamsFlag"): {"value": 1}, ("LHC", "BeamEnergy"): {"value": 6800},
    }))
    r = call("get_beam_status")
    assert r["partition"] == "initial"
    assert r["stable_beams_flag"]["stable_beams"] is True
    assert r["beam_energy"]["value"] == 6800 and r["beam_energy"]["unit"] == "GeV"


# --- discovery tools ----------------------------------------------------------------

def test_list_is_objects_filter_and_limit(monkeypatch):
    objs = [{"name": f"DF.ROS.Ch{i}", "type": "X", "time": "t"} for i in range(5)] + \
           [{"name": "DF.HLTSV.Events", "type": "HLTSV", "time": "t"}]
    monkeypatch.setattr(webis, "list_objects", lambda p, s: objs)
    r = call("list_is_objects", partition="mytest", server="DF", name_contains="ros", limit=2)
    assert r["total"] == 5 and r["truncated"] is True and len(r["objects"]) == 2


def test_read_is_object_trims_and_strips_prefix(monkeypatch):
    seen = {}
    def get_object(p, s, o):
        seen["obj"] = o
        return {"name": "RunCtrl.RootController", "type": "RCStateInfo", "updated": "u",
                "source": URL, "attributes": {"lastTransitionFull": "x" * 1000, "state": "RUNNING"},
                "descriptions": {"state": "Current state of the controller"}}
    monkeypatch.setattr(webis, "get_object", get_object)
    r = call("read_is_object", partition="mytest", server="RunCtrl",
             object_name="RunCtrl.RootController")
    assert seen["obj"] == "RootController"
    assert r["attributes"]["state"] == {"value": "RUNNING",
                                        "description": "Current state of the controller"}
    assert "truncated, 1000 chars" in r["attributes"]["lastTransitionFull"]["value"]


def test_list_partitions_unreachable(monkeypatch):
    def down():
        raise webis.WebisError("unreachable", "Connection refused", URL)
    monkeypatch.setattr(webis, "list_partitions", down)
    r = call("list_partitions")
    assert r["available"] is False and "partitions" not in r


def test_overview_combines_without_inventing(monkeypatch):
    monkeypatch.setattr(webis, "get_object", fake_is({
        ("RunCtrl", "RootController"): {"state": "RUNNING", "fault": True,
                                        "badChildren": ["HLT"], "errorReasons": ["HLT: wrong state"]},
        ("RunParams", "RunParams"): {"run_number": 160902, "run_type": "Physics",
                                     "timeSOR": "20/11/26 11:27:25", "timeEOR": "1/1/70 01:00:00"},
    }))
    r = call("get_partition_overview", partition="mytest")
    assert r["state"]["running"] is True and r["state"]["fault"] is True
    assert r["run_info"]["run_number"] == 160902
    assert r["timing"]["lumiblock"]["available"] is False    # not published -> says so


# --- header mode: RunParams.Ready4Physics (ATLAS.js printHeader) -----------------------
# Not published on the testbed; attribute name from ref/ATLAS.js.

def _rc(state):
    return {"state": state, "busy": False, "fault": False, "lastTransitionName": "START"}


def test_mode_physics_when_running(monkeypatch):
    monkeypatch.setattr(webis, "get_object", fake_is({
        ("RunCtrl", "RootController"): _rc("RUNNING"),
        ("RunParams", "Ready4Physics"): {"ready4physics": True}}))
    r = call("get_run_state", partition="ATLAS")
    assert r["mode"] == "Physics" and r["mode_note"] is None


def test_mode_standby_string_value(monkeypatch):
    # ATLAS.js compares with the string 'True' (XML); accept both forms
    monkeypatch.setattr(webis, "get_object", fake_is({
        ("RunCtrl", "RootController"): _rc("RUNNING"),
        ("RunParams", "Ready4Physics"): {"ready4physics": "False"}}))
    assert call("get_run_state", partition="ATLAS")["mode"] == "StandBy"


def test_mode_null_when_not_running(monkeypatch):
    monkeypatch.setattr(webis, "get_object", fake_is({
        ("RunCtrl", "RootController"): _rc("CONNECTED"),
        ("RunParams", "Ready4Physics"): {"ready4physics": True}}))
    r = call("get_run_state", partition="ATLAS")
    assert r["mode"] is None and "only shown while RUNNING" in r["mode_note"]


def test_mode_null_when_not_published(monkeypatch):
    # The real situation on the testbed partition 'mytest'
    monkeypatch.setattr(webis, "get_object", fake_is({
        ("RunCtrl", "RootController"): _rc("RUNNING")}))
    r = call("get_run_state", partition="mytest")
    assert r["running"] is True and r["mode"] is None
    assert "No such object: RunParams.Ready4Physics" in r["mode_note"]


def test_mode_unknown_value_not_guessed(monkeypatch):
    monkeypatch.setattr(webis, "get_object", fake_is({
        ("RunCtrl", "RootController"): _rc("RUNNING"),
        ("RunParams", "Ready4Physics"): {"ready4physics": "maybe"}}))
    r = call("get_run_state", partition="ATLAS")
    assert r["mode"] is None and "unrecognised" in r["mode_note"]


def test_unknown_partition_lists_real_ones(monkeypatch):
    # Seen live: without this the model invented "ATLAS-01 (example)" etc.
    def missing(*a):
        raise webis.WebisError("invalid_partition", "No such partition: ATLAS", URL)
    monkeypatch.setattr(webis, "get_object", missing)
    monkeypatch.setattr(webis, "list_partitions", lambda: ["initial", "mytest"])
    r = call("get_run_state", partition="ATLAS")
    assert r["available"] is False and r["reason"] == "invalid_partition"
    assert r["existing_partitions"] == ["initial", "mytest"]
