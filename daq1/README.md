# DAQ-1 — MCP server for current ATLAS IS data

A read-only [FastMCP](https://gofastmcp.com) server that lets an AI assistant answer
questions about the **current** state of ATLAS TDAQ from the Information Service (IS),
read over HTTP through **Webis**. Scope: the ATLAS Run Status page
(`../ref/ATLAS.html`, `../ref/ATLAS.js`), plus discovery tools for anything else in IS.

```
question ─► agent.py (LangGraph, LLM on CERN AI Gateway)
              │ MCP over stdio
              ▼
            server.py (FastMCP, 12 read-only tools)
              │ HTTP
              ▼
            webis.py ─► webis_server (VM, :8080) ─► IS servers (TDAQ testbed)
```

## Design rules

1. **Read-only.** Every tool is annotated `readOnlyHint`; Webis runs without `-W`.
2. **Values come from IS unchanged.** No defaults, no interpolation. Interpretations are
   limited to rules taken from ATLAS.js (e.g. `running = state == "RUNNING"`,
   `recording_enabled = value == 1`, DQ colours) and are documented per tool.
3. **Missing data is explicit.** Any failure returns `available: false` with Webis's own
   reason (`invalid_partition`, `invalid_server`, `invalid_object`, `unreachable`,
   `missing_attribute`) and the `source` URL. Panels with several values report each one
   separately, so one missing object never hides the others.
4. **Traceable.** Every value carries `source` (Webis URL) and `is_updated` (IS publish time).
5. **Times are not converted.** IS time strings are returned as reported and labelled
   "local time of the Webis server" (the Webis API documents them as local time). The only
   exception is `lumiblock.started_utc`, which comes from an absolute nanosecond timestamp
   and is therefore real UTC.
6. **Current data only.** IS has no history; tools and agent say so and point to P-BEAST.

## Tools

| Tool | Run Status panel | IS objects | Live-tested on testbed |
|---|---|---|---|
| `get_run_state` | Header ("running?", Physics/StandBy mode) | `RunCtrl.RootController`, `RunParams.Ready4Physics` | ✅ (mode: offline only, not published) |
| `get_run_info` | Run number / type / recording | `RunParams.RunParams` | ✅ |
| `get_run_timing` | Run Timing | `RunParams.LumiBlock`, `RunParams.RunInfo`, `RunParams.RunParams` | ✅ |
| `get_partition_overview` | Header + run info + timing in one call | (the three above) | ✅ |
| `get_event_counters` | Counters | `DF.HLTSV.Events`, `DF.TopMIG-IS:HLT.info`, `DF.TopMIG-IS:HLT.Counters.Global` | ✅ (values 0: no events on testbed) |
| `get_trigger_config` | Trigger Configuration | `RunParams.TrigConf{SmKey,L1PsKey,HltPsKey,L1BgKey,Release}` | ⚠️ offline only (not published) |
| `get_data_quality` | Data Quality | `DQM.{ATLAS,IDBCM,LCD}` | ⚠️ offline only (DQM empty) |
| `get_beam_status` | Beam Status | `initial` / `LHC.{StableBeamsFlag,BeamEnergy}` | ⚠️ offline only (LHC empty) |
| `list_partitions` | — | `/info/current` | ✅ |
| `list_is_servers` | — | `/info/current/<p>/is` | ✅ |
| `list_is_objects` | — | `/info/current/<p>/is/<server>` | ✅ |
| `read_is_object` | — | any object (attributes + IS descriptions) | ✅ |

**Coverage:** all 23 IS values the Run Status page reads by element id (`ref/ATLAS.html`,
`ref/ATLAS.js`) are covered. Only the busy table, which ATLAS.js fetches separately, is not.

**Not covered on purpose:** the busy/deadtime panels (`L1CT.CTP.PerLumiBlock.BusyFractions`).
ATLAS.js reads them by XML position from nested structures; the object is not published on
the testbed, so its JSON shape could not be seen. Writing a parser for an unseen format
would mean guessing. The Trigger Rates tabs are P-BEAST/Grafana (DAQ-2).

## Setup

### On the VM (once)

```bash
source /cvmfs/atlas.cern.ch/repo/sw/tdaq/tools/cmake_tdaq/bin/cm_setup.sh tdaq-14-00-00
sudo dnf install -y glibc-devel kernel-headers        # ROOT/Cling needs them (webis_server)
# IS servers on the testbed call back into the VM; allow CERN-internal sources:
for net in 137.138.0.0/16 128.141.0.0/16 128.142.0.0/16 188.184.0.0/15 <testbed-private-range>; do
  sudo firewall-cmd --zone=trusted --add-source=$net; done
sudo firewall-cmd --runtime-to-permanent
nohup webis_server -p 8080 -a 127.0.0.1 > ~/webis.log 2>&1 &   # read-only, localhost only
```

Check: `is_ls -p <partition> -n RunCtrl` lists objects (if it prints
"Received nothing in the last 1000ms" for every server, the firewall is blocking).

### On the laptop (eduVPN on)

```bash
ssh -N -o ServerAliveInterval=30 -o ExitOnForwardFailure=yes \
    -L 8080:127.0.0.1:8080 <user>@vm-onlsw-ai-pbeast.cern.ch      # keep open
cd daq1
uv sync
echo "AIGW_API_KEY=..." > .env && chmod 600 .env                 # git-ignored
```

## Use

```bash
uv run pytest                                   # 34 offline tests (no network)
uv run python agent.py                          # chat; -v shows tool calls; -m <model>
uv run python agent.py -v -q "Is mytest running?"
uv run python eval_agent.py                     # live evaluation -> evals/<time>-<model>.md
uv run fastmcp list server.py                   # list the tools and their descriptions
uv run fastmcp call server.py get_run_state partition=mytest   # call one tool directly
uv run fastmcp dev inspector server.py          # MCP Inspector in the browser
```

### Use the server from any MCP client (Claude Desktop, Cursor, ...)

```json
{
  "mcpServers": {
    "atlas-is": {
      "command": "uv",
      "args": ["run", "--directory", "/ABSOLUTE/PATH/TO/daq1", "python", "server.py"],
      "env": { "WEBIS_URL": "http://127.0.0.1:8080" }
    }
  }
}
```

## Files

| File | Purpose |
|---|---|
| `webis.py` | Webis HTTP client: object/partition/server/object-list reads, `WebisError` codes |
| `server.py` | The MCP server and its 12 tools |
| `agent.py` | LangGraph agent + FastMCP→LangChain tool bridge + guarded `answer()` |
| `eval_agent.py` | 13 fixed shifter questions → Markdown transcript for review |
| `probe_llm.py` | One-off check of which gateway models do tool calling |
| `test_*.py` | Offline tests built from responses captured live on 2026-11-20 |

## Findings (2026-11-20, tdaq-14-00-00, testbed partition `mytest`)

- **Webis JSON format.** An object is an array `[name, type, "DD/MM/YY HH:MM:SS.us", {name,
  descr, type, range, value}, ...]`; errors are HTTP 404 with `{"error", "error_description"}`.
- **IS time strings are local time.** `LumiBlock.Time` (ns since epoch) = 10:45:40 UTC was
  shown by IS as `11:45:40`, i.e. UTC+1 (CET) on that date; an unset time appears as
  `1/1/70 01:00:00` (epoch 0 in CET). The Webis API spec (`doc/openapi.yaml`) confirms IS
  timestamps are "local time"; tools label them "local time of the Webis server".
- **Production access path.** The Webis API spec lists `https://atlasop.cern.ch` as the
  "ATLAS production server" (and `rhauser-c9s.cern.ch` as a TBED test server). The real
  `ATLAS` partition is only reachable there; `WEBIS_URL` plus authentication would point the
  same tools at it. Needs supervisor approval. The spec's `attr=` and `regex=` query options
  would reduce load on production.
- **Model choice.** On the CERN AI Gateway, 5/6 chat models handled tool calling;
  `gpt-oss-20b` was fastest (~2 s) and most literal; `hf-qwen3-32b-awq` added an unsupported
  claim; `gemma-4-12b` is not available to sandbox keys.
- **Failure modes found and fixed:**
  1. *Misattributed timestamp* — the agent presented the IS publish time as the time of the
     START transition. Fixed in the tool (field semantics + explicit
     `last_transition_time: null`) rather than only in the prompt.
  2. *Malformed tool call from the gateway* — `list_partitions<|channel|>commentary` with
     args `{""}` (harmony-format leak, seen for a zero-argument tool) ended the run silently.
     Fixed: no zero-argument tools; `answer()` retries and never returns an empty reply.
  3. *Fluent answer with no tool call* — "Give me an overview of mytest" produced an invented
     partition list (incl. a non-existent "ATLAS") in 4/4 runs. Fixed in code: answers with
     no tool call are retried and, if it persists, prefixed `[Unverified: no IS data was queried]`.
  4. *Servers taken for applications* — fixed via tool description.
  5. *Invented alternatives* — after `invalid_partition`, the model listed made-up
     partitions ("ATLAS-01 (example)") even though it had called a tool. Fixed in the tool:
     the error now includes the real `existing_partitions` (3/3 runs correct afterwards).
  6. *History questions* — IS cannot say when a run last happened; tool descriptions and
     the prompt now say so and point to P-BEAST.
  7. *Interpreting states* — "INITIAL" was explained as "ready for a new run" (wrong: it
     still needs CONFIGURE and CONNECT). Prompt now forbids unrequested interpretation.
- **`langchain-mcp-adapters`** requires `mcp<2` and cannot be used with FastMCP 4; a 15-line
  bridge in `agent.py` replaces it.
