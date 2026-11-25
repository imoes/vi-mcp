#!/bin/bash
# G8c-0 runner: 30 dreams x 4 arms x seeds 0-2, 4 parallel, seed blocks first (all of seed 0, then 1, then 2)
cd "$(dirname "$0")"
P=${PYTHON:-python3}
export VI_MCP_REPO=${VI_MCP_REPO:-$(cd ../../.. && pwd)}
mkdir -p runs0
for s in 0 1 2; do for i in $(seq 0 29); do for a in U O P M; do
  [ -f runs0/d${i}_${a}_${s}.json ] || echo "$i $a $s"; done; done; done | \
  xargs -P 4 -L 1 bash -c 'timeout 7200 '$P' oracle0.py run dreams.json $0 $1 $2 runs0 > runs0/d$0_$1_$2.log 2>&1'
echo "ALL DONE $(date -u +%FT%T)" >> run0.log
