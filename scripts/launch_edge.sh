#!/usr/bin/env bash
# Start Edge with a CDP port while keeping the real profile (and its login cookies).
#
# Edge 136+ ignores --remote-debugging-port when --user-data-dir is the default
# profile, so we point it at an NTFS junction of that same directory instead.
#
# usage: ./launch_edge.sh [port]
set -u

PORT="${1:-${ZHS_PORT:-9222}}"
WORKSPACE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
JUNCTION="$WORKSPACE/.edge-junction"
REAL_PROFILE="${EDGE_PROFILE:-C:/Users/$USERNAME/AppData/Local/Microsoft/Edge/User Data}"
EDGE="${EDGE_BIN:-/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe}"

if [ ! -e "$JUNCTION" ]; then
  echo "creating junction $JUNCTION -> $REAL_PROFILE"
  powershell.exe -NoProfile -Command \
    "New-Item -ItemType Junction -Path '$(cygpath -w "$JUNCTION")' -Target '$REAL_PROFILE'" >/dev/null
fi

if curl -s --max-time 3 "http://127.0.0.1:$PORT/json/version" >/dev/null 2>&1; then
  echo "port $PORT already serving CDP - reusing it"
  exit 0
fi

echo "launching Edge on port $PORT"
nohup "$EDGE" --remote-debugging-port="$PORT" \
  --user-data-dir="$(cygpath -w "$JUNCTION")" \
  --no-first-run --no-default-browser-check --restore-last-session \
  >/dev/null 2>&1 &

for _ in $(seq 1 20); do
  sleep 1
  if curl -s --max-time 2 "http://127.0.0.1:$PORT/json/version" >/dev/null 2>&1; then
    echo "CDP is up on $PORT"
    echo "now log in to zhihuishu by hand if the course page asks you to."
    exit 0
  fi
done

echo "FAILED: no CDP on $PORT after 20s."
echo "If Edge was already running without the flag, close it first - a running"
echo "instance ignores the new launch arguments."
exit 1
