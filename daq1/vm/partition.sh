#!/usr/bin/env bash
# Own standalone TDAQ partition on the DAQ-1 VM (vm-onlsw-ai-is), isolated from the
# shared testbed by a PRIVATE IPC ("initial" partition) in ~/tdaq.
#
# Run ON THE VM:
#   ./partition.sh up            # private IPC + generate + start partition + local Webis on :8081
#   ./partition.sh run           # INITIALIZE -> CONFIGURE -> CONNECT -> START
#   ./partition.sh cmd STOP      # any rc_sender command (STOP, START, UNCONFIGURE, SHUTDOWN ...)
#   ./partition.sh state         # state of the RootController
#   ./partition.sh down          # stop everything started by 'up'
#
# Verified with tdaq-14-00-00 on 2026-11-20.
PART=${PART:-nkarki_daq1}
WORK=${WORK:-$HOME/tdaq}
LOCAL_WEBIS_PORT=${LOCAL_WEBIS_PORT:-8081}

# cm_setup.sh uses unset variables, so load it BEFORE enabling strict mode.
source /cvmfs/atlas.cern.ch/repo/sw/tdaq/tools/cmake_tdaq/bin/cm_setup.sh tdaq-14-00-00 >/dev/null 2>&1
set -euo pipefail
export TDAQ_IPC_INIT_REF=file:$WORK/ipc_root.ref     # private IPC, not the testbed's
mkdir -p "$WORK"
cd "$WORK"

rc() { rc_sender -p "$PART" -n RootController -c "$1" -t 180000; }

state() {
  curl -s -m 10 "http://127.0.0.1:$LOCAL_WEBIS_PORT/info/current/$PART/is/RunCtrl/RunCtrl.RootController?format=json" \
    | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d if isinstance(d,dict) else {a["name"]:a["value"] for a in d[3:] if a["name"] in ("state","fault","lastTransitionName")})'
}

case "${1:-}" in
  up)
    pgrep -u "$USER" -x ipc_server >/dev/null || { nohup ipc_server > ipc_server.log 2>&1 & sleep 4; }
    [ -f "$PART.data.xml" ] || pm_part_hlt.py -p "$PART" > pm_part_hlt.log 2>&1
    setup_daq -d "$PART.data.xml" -p "$PART" -ng -ne -nc > setup_daq.log 2>&1
    pgrep -u "$USER" -f "webis_server.server -p $LOCAL_WEBIS_PORT" >/dev/null || \
      { nohup webis_server -p "$LOCAL_WEBIS_PORT" -a 127.0.0.1 > webis_local.log 2>&1 & }
    for _ in $(seq 10); do sleep 3; curl -s -m 5 "http://127.0.0.1:$LOCAL_WEBIS_PORT/info/current?format=json" && break; done; echo
    ipc_ls -P ;;
  run)   for c in INITIALIZE CONFIGURE CONNECT START; do echo "-> $c"; rc "$c"; done; state ;;
  cmd)   rc "${2:?rc_sender command, e.g. STOP}"; state ;;
  state) state ;;
  down)
    rc STOP 2>/dev/null || true; rc UNCONFIGURE 2>/dev/null || true; rc SHUTDOWN 2>/dev/null || true
    pkill -u "$USER" -f "webis_server.server -p $LOCAL_WEBIS_PORT" || true
    echo "Partition processes are managed by PMG; if anything is left: pmg_kill_partition -p $PART"
    echo "Private IPC server left running (stop with: pkill -u $USER -x ipc_server)" ;;
  *) sed -n '2,13p' "$0"; exit 1 ;;
esac
