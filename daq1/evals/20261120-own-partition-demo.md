# DAQ-1 demo — own standalone partition `nkarki_daq1` — 2026-11-20

Setup: partition generated with `pm_part_hlt.py -p nkarki_daq1`, started with
`setup_daq -ng` on the DAQ-1 VM `vm-onlsw-ai-is`, registered in a **private IPC**
(`TDAQ_IPC_INIT_REF=file:~/tdaq/ipc_root.ref`), read through a local Webis on port 8081.
Script: [`../vm/partition.sh`](../vm/partition.sh). Agent: `gpt-oss-20b` via CERN AI Gateway.

## 1. Transitions with `rc_sender`, observed with the DAQ-1 tool `get_run_state`

| `rc_sender` command | State seen by DAQ-1 | running | fault | last_transition |
|---|---|---|---|---|
| (after `setup_daq`) | `NONE` | false | false | `INIT_FSM` |
| `INITIALIZE` | `INITIAL` | false | false | `INITIALIZE` |
| `CONFIGURE` | `CONFIGURED` | false | false | `CONFIGURE` |
| `CONNECT` | `CONNECTED` | false | false | `CONNECT` |
| `START` | `RUNNING` | **true** | false | `START` |
| `STOP` | `CONNECTED` | false | false | `STOPARCHIVING` (six-step drain) |

## 2. The PDF's example interaction, on real IS data

**Q: "What is the current status of the nkarki_daq1 partition?"**

*While running* — tool: `get_partition_overview(partition="nkarki_daq1")`

> The **nkarki_daq1** partition is currently **RUNNING**.
> Run number 1795181140, run type Physics, recording disabled, start of run 20/11/26 14:25:40
> (local Webis time), end of run: ongoing; luminosity block 2 (started 2026-11-20T13:25:43 UTC);
> active time 20 s. No faults or errors are reported.

*After `STOP`* — same tool

> The **nkarki_daq1** partition is currently **CONNECTED but not running**.
> Run 1795181140 (Physics) started at 20/11/26 14:25:40 and ended at 20/11/26 14:26:22;
> active time 41 s. No faults are present.

**Verdict:** matches IS in both states; equivalent to the PDF's "The ATLAS partition is currently
not running", for a partition that exists in this setup. Minor: the second answer adds "simply in
a connected, idle state" (harmless interpretation).

## Observations

- The run number 1795181140 equals the Unix time of the start of run (13:25:40 UTC = 14:25:40 CET),
  apparently because a local partition has no central run-number service (inference).
- `end_of_run` was null while running and a real time after STOP — the epoch-0 placeholder was
  never reported as a date.
