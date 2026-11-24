#!/usr/bin/env bash
# Demo helper for the presentation.
#   ./scripts/demo_load.sh http://<alb-dns>            # show load balancing
#   ./scripts/demo_load.sh http://<alb-dns> stress     # drive CPU up to trigger scale-out
set -euo pipefail
URL="${1:?Usage: demo_load.sh <portal-url> [stress]}"

if [ "${2:-}" = "stress" ]; then
  echo "Sending CPU load for ~10 minutes. Watch EC2 > Auto Scaling Groups > Activity."
  for round in $(seq 1 10); do
    for i in $(seq 1 8); do curl -s "$URL/stress?seconds=60" >/dev/null & done
    wait
    echo "round $round done"
  done
else
  for i in $(seq 1 10); do
    curl -s "$URL/health"; echo
  done
fi
