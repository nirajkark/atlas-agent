"""DAQ-1: read-only MCP server for current ATLAS TDAQ data in IS (via Webis).

Run (stdio, for MCP clients):   uv run python server.py
Webis address:                  WEBIS_URL env var (default http://127.0.0.1:8080)
"""

from fastmcp import FastMCP

import webis

mcp = FastMCP(
    "atlas-is",
    instructions=(
        "Read-only access to current ATLAS TDAQ operational data from the "
        "Information Service (IS). Answer only from tool results. If a tool "
        "returns available=false, say the data is not available and why; never guess."
    ),
)

READ_ONLY = {"readOnlyHint": True, "openWorldHint": True}


def unavailable(partition: str, err: webis.WebisError) -> dict:
    """Uniform 'no data' answer: explicit reason, never a guessed value."""
    return {
        "partition": partition,
        "available": False,
        "reason": err.code,          # e.g. invalid_object, unreachable
        "detail": err.description,
        "source": err.url,
    }


@mcp.tool(annotations=READ_ONLY)
def get_run_state(partition: str) -> dict:
    """Current run-control state of a TDAQ partition (is it running?).

    Reads RunCtrl.RootController from IS. `running` is true only when the
    root controller state is exactly "RUNNING" (same rule as the ATLAS Run
    Status page).

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
    state = a.get("state")
    if not state:
        # Object exists but has no state: report it, don't infer "not running".
        return {"partition": partition, "available": False,
                "reason": "missing_attribute", "detail": "RootController has no 'state'",
                "source": obj["source"]}

    return {
        "partition": partition,
        "available": True,
        "state": state,
        "running": state == "RUNNING",
        "busy": a.get("busy"),
        "fault": a.get("fault"),
        "transitioning": a.get("transitioning"),
        "error_reasons": a.get("errorReasons"),
        "bad_children": a.get("badChildren"),
        "last_transition": a.get("lastTransitionName"),
        "is_updated": obj["updated"],
        "is_updated_tz": "not specified by IS",
        "source": obj["source"],
    }


EPOCH_ZERO_PREFIX = "1/1/70"  # IS shows an unset time as the Unix epoch (e.g. "1/1/70 01:00:00")


def is_time(value):
    """IS time as reported, or None if IS holds the 'unset' epoch-0 placeholder."""
    if not value or str(value).startswith(EPOCH_ZERO_PREFIX):
        return None
    return value


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
        return {"partition": partition, "available": False,
                "reason": "missing_attribute", "detail": "RunParams has no 'run_number'",
                "source": obj["source"]}

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
        "is_updated_tz": "not specified by IS",
        "source": obj["source"],
    }


if __name__ == "__main__":
    import logging
    logging.getLogger("fastmcp").setLevel(logging.WARNING)  # keep stdio clients' terminals quiet
    mcp.run(show_banner=False)
