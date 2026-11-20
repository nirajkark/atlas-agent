"""DAQ-1: read-only MCP server for current ATLAS TDAQ data in IS (via Webis).

Covers the ATLAS Run Status page (ref/ATLAS.html, ref/ATLAS.js) plus discovery tools.

Run (stdio, for MCP clients):   uv run python server.py
Webis address:                  WEBIS_URL env var (default http://127.0.0.1:8080)

Rules: every tool is read-only; values come from IS unchanged; anything missing is
reported as available=false with the reason from Webis, never filled in.
"""

from datetime import datetime, timezone

from fastmcp import FastMCP

import webis

mcp = FastMCP(
    "atlas-is",
    instructions=(
        "Read-only access to current ATLAS TDAQ operational data from the "
        "Information Service (IS). Answer only from tool results. If a tool "
        "returns available=false, say the data is not available and why; never guess. "
        "Use list_partitions / list_is_servers / list_is_objects / read_is_object "
        "for anything the dedicated tools do not cover."
    ),
)

READ_ONLY = {"readOnlyHint": True, "openWorldHint": True}
TZ_NOTE = "not specified by IS"
EPOCH_ZERO_PREFIX = "1/1/70"  # IS shows an unset time as the Unix epoch (e.g. "1/1/70 01:00:00")


# ---------------------------------------------------------------- helpers

def unavailable(partition: str, err: webis.WebisError) -> dict:
    """Uniform 'no data' answer: explicit reason, never a guessed value."""
    return {
        "partition": partition,
        "available": False,
        "reason": err.code,          # e.g. invalid_object, invalid_partition, unreachable
        "detail": err.description,
        "source": err.url,
    }


def missing_attribute(partition: str, obj: dict, attr: str) -> dict:
    return {"partition": partition, "available": False, "reason": "missing_attribute",
            "detail": f"{obj['name']} has no '{attr}'", "source": obj["source"]}


def is_time(value):
    """IS time as reported, or None if IS holds the 'unset' epoch-0 placeholder."""
    if not value or str(value).startswith(EPOCH_ZERO_PREFIX):
        return None
    return value


def hhmmss(seconds: int) -> str:
    """Same formatting as ATLAS.js setDurationValue()."""
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def read_value(partition: str, server: str, obj: str, attr: str) -> dict:
    """One attribute with its own availability, for tools combining several objects."""
    try:
        o = webis.get_object(partition, server, obj)
    except webis.WebisError as e:
        return {"available": False, "reason": e.code, "detail": e.description, "source": e.url}
    if attr not in o["attributes"]:
        r = missing_attribute(partition, o, attr)
        r.pop("partition")
        return r
    return {"available": True, "value": o["attributes"][attr],
            "is_updated": o["updated"], "source": o["source"]}


def combine(partition: str, items: dict, **extra) -> dict:
    """Wrap per-item results; available=true if at least one item is available."""
    return {"partition": partition,
            "available": any(v.get("available") for v in items.values()),
            **items, **extra, "is_updated_tz": TZ_NOTE}


# ---------------------------------------------------------------- run status page: header

@mcp.tool(annotations=READ_ONLY)
def get_run_state(partition: str) -> dict:
    """Current run-control state of a TDAQ partition (is it running?).

    Reads RunCtrl.RootController from IS. `running` is true only when the
    root controller state is exactly "RUNNING" (same rule as the ATLAS Run
    Status page). If `fault` is true, `bad_children` and `error_reasons` say why.

    `is_updated` is when IS last (re)published this object (DD/MM/YY, time
    zone not specified by IS). The controller republishes periodically, so it
    is NOT the time of the last transition or of the run start; for the run
    start time use get_run_info.start_of_run.
    """
    try:
        obj = webis.get_object(partition, "RunCtrl", "RootController")
    except webis.WebisError as e:
        return unavailable(partition, e)

    a = obj["attributes"]
    if not a.get("state"):
        # Object exists but has no state: report it, don't infer "not running".
        return missing_attribute(partition, obj, "state")

    return {
        "partition": partition,
        "available": True,
        "state": a["state"],
        "running": a["state"] == "RUNNING",
        "busy": a.get("busy"),
        "fault": a.get("fault"),
        "transitioning": a.get("transitioning"),
        "error_reasons": a.get("errorReasons"),
        "bad_children": a.get("badChildren"),
        "last_transition": a.get("lastTransitionName"),
        # RootController does not publish WHEN the last transition happened; say so
        # explicitly so the publish time below is not mistaken for it.
        "last_transition_time": None,
        "last_transition_time_note": "not published by IS; is_updated is NOT this time",
        "is_updated": obj["updated"],
        "is_updated_tz": TZ_NOTE,
        "source": obj["source"],
    }


@mcp.tool(annotations=READ_ONLY)
def get_run_info(partition: str) -> dict:
    """Run parameters of the current or most recent run of a partition:
    run number, run type, recording, start/end time, max events, beam, detector mask.

    Reads RunParams.RunParams from IS. These values persist after a run stops,
    so they may describe the LAST run: use get_run_state to know whether a run
    is active. `end_of_run` is null while the run has not ended. Times are as
    reported by IS (time zone not specified). `is_updated` is when IS last
    published this object, not an event time. `max_events`, `beam_type`,
    `trigger_type` and `detector_mask` are raw IS values, not interpreted.
    """
    try:
        obj = webis.get_object(partition, "RunParams", "RunParams")
    except webis.WebisError as e:
        return unavailable(partition, e)

    a = obj["attributes"]
    if "run_number" not in a:
        return missing_attribute(partition, obj, "run_number")

    rec = a.get("recording_enabled")
    return {
        "partition": partition,
        "available": True,
        "run_number": a["run_number"],
        "run_type": a.get("run_type"),
        "recording_enabled": None if rec is None else rec == 1,  # ATLAS.js: 1 -> Enabled
        "start_of_run": is_time(a.get("timeSOR")),
        "end_of_run": is_time(a.get("timeEOR")),
        "max_events": a.get("max_events"),
        "project_tag": a.get("T0_project_tag") or None,
        "filename_tag": a.get("filename_tag") or None,
        "trigger_type": a.get("trigger_type"),
        "beam_type": a.get("beam_type"),
        "beam_energy": a.get("beam_energy"),
        "detector_mask": a.get("det_mask"),
        "is_updated": obj["updated"],
        "is_updated_tz": TZ_NOTE,
        "source": obj["source"],
    }


@mcp.tool(annotations=READ_ONLY)
def get_partition_overview(partition: str) -> dict:
    """One-call status overview of a partition: run state (incl. faults), run
    parameters and run timing. Use this for general "what is the status of X?"
    questions; it returns exactly what get_run_state, get_run_info and
    get_run_timing return, under the keys `state`, `run_info` and `timing`.
    """
    state = get_run_state(partition)
    return {"partition": partition,
            "available": state.get("available", False),
            "state": state,
            "run_info": get_run_info(partition),
            "timing": get_run_timing(partition)}


# ---------------------------------------------------------------- run status page: panels

@mcp.tool(annotations=READ_ONLY)
def get_run_timing(partition: str) -> dict:
    """Run Timing panel: current luminosity block, active time of the run, start time.

    - lumiblock: RunParams.LumiBlock (run number + lumi block number). Its
      `started_utc` is converted from IS's absolute nanosecond timestamp, so it
      IS a real UTC time.
    - active_time: RunParams.RunInfo.activeTime in seconds, plus HH:MM:SS
      (formatted like the Run Status page).
    - start_of_run: RunParams.RunParams.timeSOR as reported by IS (time zone
      not specified).
    Each part has its own `available` flag; these objects exist only once a run
    has been started in the partition.
    """
    try:
        o = webis.get_object(partition, "RunParams", "LumiBlock")
        if "LumiBlockNumber" not in o["attributes"]:
            lb = missing_attribute(partition, o, "LumiBlockNumber")
            lb.pop("partition")
        else:
            ns = o["attributes"].get("Time")  # absolute time, ns since Unix epoch
            lb = {"available": True,
                  "run_number": o["attributes"].get("RunNumber"),
                  "lumiblock": o["attributes"]["LumiBlockNumber"],
                  "started_utc": (datetime.fromtimestamp(ns / 1e9, timezone.utc)
                                  .isoformat(timespec="seconds") if ns else None),
                  "is_updated": o["updated"], "source": o["source"]}
    except webis.WebisError as e:
        lb = {"available": False, "reason": e.code, "detail": e.description, "source": e.url}

    act = read_value(partition, "RunParams", "RunInfo", "activeTime")
    if act["available"]:
        act = {"available": True, "seconds": act["value"], "hhmmss": hhmmss(int(act["value"])),
               "is_updated": act["is_updated"], "source": act["source"]}

    sor = read_value(partition, "RunParams", "RunParams", "timeSOR")
    if sor["available"]:
        sor = {"available": True, "time": is_time(sor["value"]),
               "is_updated": sor["is_updated"], "source": sor["source"]}

    return combine(partition, {"lumiblock": lb, "active_time": act, "start_of_run": sor})


@mcp.tool(annotations=READ_ONLY)
def get_event_counters(partition: str) -> dict:
    """Counters panel of the Run Status page (cumulative event counts of the run):

    - l1_triggers:     DF.HLTSV.Events.LVL1Events
    - accepted_events: DF.TopMIG-IS:HLT.info.OutputDeliveredEvents
    - recorded_events: DF.TopMIG-IS:HLT.Counters.Global.WritingTotalEvents
    Raw integers from IS; each has its own `available` flag.
    """
    return combine(partition, {
        "l1_triggers": read_value(partition, "DF", "HLTSV.Events", "LVL1Events"),
        "accepted_events": read_value(partition, "DF", "TopMIG-IS:HLT.info", "OutputDeliveredEvents"),
        "recorded_events": read_value(partition, "DF", "TopMIG-IS:HLT.Counters.Global",
                                      "WritingTotalEvents"),
    })


@mcp.tool(annotations=READ_ONLY)
def get_trigger_config(partition: str = "ATLAS") -> dict:
    """Trigger Configuration panel: trigger database keys and HLT release.

    - super_master_key:  RunParams.TrigConfSmKey.SuperMasterKey
    - l1_prescale_key:   RunParams.TrigConfL1PsKey.L1PrescaleKey
    - hlt_prescale_key:  RunParams.TrigConfHltPsKey.HltPrescaleKey
    - bunch_group_key:   RunParams.TrigConfL1BgKey.L1BunchGroupKey
    - hlt_release:       RunParams.TrigConfRelease.HLTReleaseVersion
    `triggertool_url` is the link the Run Status page builds from the three
    keys; it is only given when all three are available.
    """
    items = {
        "super_master_key": read_value(partition, "RunParams", "TrigConfSmKey", "SuperMasterKey"),
        "l1_prescale_key": read_value(partition, "RunParams", "TrigConfL1PsKey", "L1PrescaleKey"),
        "hlt_prescale_key": read_value(partition, "RunParams", "TrigConfHltPsKey", "HltPrescaleKey"),
        "bunch_group_key": read_value(partition, "RunParams", "TrigConfL1BgKey", "L1BunchGroupKey"),
        "hlt_release": read_value(partition, "RunParams", "TrigConfRelease", "HLTReleaseVersion"),
    }
    keys = [items[k] for k in ("super_master_key", "l1_prescale_key", "hlt_prescale_key")]
    url = None
    if all(k["available"] for k in keys):
        smk, l1, hlt = (k["value"] for k in keys)
        url = f"https://atlas-triggertool.web.cern.ch/db/run3/comb/smk/{smk}/l1psk/{l1}/hltpsk/{hlt}"
    return combine(partition, items, triggertool_url=url)


DQ_SYSTEMS = ("ATLAS", "IDBCM", "LCD")           # the three buttons on the Run Status page
DQ_COLOURS = {0: "grey", 1: "red", 2: "yellow", 3: "green"}   # ATLAS.js getDataQualityColor()


@mcp.tool(annotations=READ_ONLY)
def get_data_quality(partition: str = "ATLAS") -> dict:
    """Data Quality panel: DQM status of ATLAS, IDBCM and LCD (DQM.<system>.status).

    `status` is the raw IS integer; `colour` is how the Run Status page shows
    it (0 grey, 1 red, 2 yellow, 3 green). Any other code gets colour=null.
    """
    items = {}
    for system in DQ_SYSTEMS:
        r = read_value(partition, "DQM", system, "status")
        if r["available"]:
            r = {"available": True, "status": r["value"], "colour": DQ_COLOURS.get(r["value"]),
                 "is_updated": r["is_updated"], "source": r["source"]}
        items[system] = r
    return combine(partition, items)


@mcp.tool(annotations=READ_ONLY)
def get_beam_status(partition: str = "initial") -> dict:
    """Beam Status panel: LHC stable-beams flag and beam energy.

    The Run Status page reads these from the `initial` partition:
    LHC.StableBeamsFlag.value (1 = stable beams) and LHC.BeamEnergy.value (GeV).
    """
    flag = read_value(partition, "LHC", "StableBeamsFlag", "value")
    if flag["available"]:
        flag = {**flag, "stable_beams": flag["value"] == 1}
    energy = read_value(partition, "LHC", "BeamEnergy", "value")
    if energy["available"]:
        energy = {**energy, "unit": "GeV"}
    return combine(partition, {"stable_beams_flag": flag, "beam_energy": energy})


# ---------------------------------------------------------------- discovery

@mcp.tool(annotations=READ_ONLY)
def list_partitions(name_contains: str = "") -> dict:
    """Names of all TDAQ partitions currently known to IS/IPC, optionally
    filtered by a case-insensitive substring (empty = all)."""
    try:
        names = webis.list_partitions()
        return {"available": True,
                "partitions": [n for n in names if name_contains.lower() in n.lower()]}
    except webis.WebisError as e:
        return {"available": False, "reason": e.code, "detail": e.description, "source": e.url}


@mcp.tool(annotations=READ_ONLY)
def list_is_servers(partition: str) -> dict:
    """IS servers in a partition (e.g. RunCtrl, RunParams, DF, DQM) and their hosts.

    IS servers are data containers, NOT applications. Application names appear
    inside object names: RunCtrl.<application> holds the run-control state of
    each controlled application, and e.g. DF.ROS.<ROS name> holds ROS data.
    To find applications, use list_is_objects on the relevant server.
    """
    try:
        servers = webis.list_servers(partition)
    except webis.WebisError as e:
        return unavailable(partition, e)
    return {"partition": partition, "available": True,
            "servers": [{"name": s.get("name"), "host": s.get("host")} for s in servers]}


@mcp.tool(annotations=READ_ONLY)
def list_is_objects(partition: str, server: str, name_contains: str = "", limit: int = 100) -> dict:
    """Objects published in one IS server, optionally filtered by a substring of the name.

    Returns at most `limit` objects (name, IS type, last update); `total` is the
    number of matches. An empty list means the server currently publishes nothing.
    """
    try:
        objs = webis.list_objects(partition, server)
    except webis.WebisError as e:
        return unavailable(partition, e)
    match = [o for o in objs if name_contains.lower() in o.get("name", "").lower()]
    return {"partition": partition, "server": server, "available": True,
            "total": len(match), "truncated": len(match) > limit,
            "objects": match[:limit], "is_updated_tz": TZ_NOTE}


MAX_STR, MAX_LIST = 300, 20


def _trim(v):
    if isinstance(v, str) and len(v) > MAX_STR:
        return v[:MAX_STR] + f"... [truncated, {len(v)} chars]"
    if isinstance(v, list) and len(v) > MAX_LIST:
        return v[:MAX_LIST] + [f"... [truncated, {len(v)} items]"]
    return v


@mcp.tool(annotations=READ_ONLY)
def read_is_object(partition: str, server: str, object_name: str) -> dict:
    """Read any IS object: all attributes with their IS descriptions.

    `object_name` may be given with or without the server prefix
    (e.g. "RootController" or "RunCtrl.RootController"). Long strings and lists
    are truncated. Values are raw IS values, not interpreted.
    """
    name = object_name.removeprefix(server + ".")
    try:
        o = webis.get_object(partition, server, name)
    except webis.WebisError as e:
        return unavailable(partition, e)
    return {"partition": partition, "available": True, "name": o["name"], "type": o["type"],
            "attributes": {k: {"value": _trim(v), "description": o["descriptions"].get(k, "")}
                           for k, v in o["attributes"].items()},
            "is_updated": o["updated"], "is_updated_tz": TZ_NOTE, "source": o["source"]}


if __name__ == "__main__":
    import logging
    logging.getLogger("fastmcp").setLevel(logging.WARNING)  # keep stdio clients' terminals quiet
    mcp.run(show_banner=False)
