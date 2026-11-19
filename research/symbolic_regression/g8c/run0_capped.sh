#!/bin/bash
# G8c-0 runner after the hal incident (19.11.2026): 2 parallel, each process capped at 4 GB (killed alone if it exceeds it),
# finished runs (runs0/*.json) skipped. Same order as run0.sh (seed blocks).
cd "$(dirname "$0")"
P=${PYTHON:-python3}
export VI_MCP_REPO=${VI_MCP_REPO:-$(cd ../../.. && pwd)}
for s in 0 1 2; do for i in $(seq 0 29); do for a in U O P M; do
  [ -f runs0/d${i}_${a}_${s}.json ] || echo "$i $a $s"; done; done; done | \
  xargs -P 1 -L 1 bash -c 'systemd-run --user --scope -q -p MemoryMax=4G -p MemorySwapMax=0 timeout 7200 '$P' oracle0.py run dreams.json $0 $1 $2 runs0 > runs0/d$0_$1_$2.log 2>&1; echo "d$0_$1_$2 exit $?" >> run0_capped.exits'
echo "ALL DONE $(date -u +%FT%T)" >> run0.log
