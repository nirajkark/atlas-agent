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
    Status page). `is_updated` is the IS timestamp as reported (DD/MM/YY,
    time zone not specified by IS).
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


if __name__ == "__main__":
    import logging
    logging.getLogger("fastmcp").setLevel(logging.WARNING)  # keep stdio clients' terminals quiet
    mcp.run(show_banner=False)
