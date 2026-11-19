#!/bin/bash
cd "$(dirname "$0")"
for s in 0 1 2 3 4 5 6 7 8 9; do for t in release_gate dependency_cycle sensor_state trusted_reading lineage_root bipartisan; do
  [ -f runs0/${t}_${s}.json ] || echo "timeout 2400 ${PYTHON:-python3} gp.py $t $s runs0 --budget 20000 > runs0/${t}_${s}.log 2>&1"
done; done | xargs -P 12 -I{} sh -c '{}'
echo "ALL DONE $(date -u +%T)"
