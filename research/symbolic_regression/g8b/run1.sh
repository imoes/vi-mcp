#!/bin/bash
# G8b-1: 33 tasks x 4 arms x seeds 0-9 in seed blocks, 12 in parallel, 3 h limit per run; resumable (finished runs skipped)
cd "$(dirname "$0")"
mkdir -p runs1
P=${PYTHON:-python3}
TASKS=$($P -c "import sys; sys.path.insert(0,'../../blind_tasks'); import blind_tasks as B; print(' '.join(B.TASKS))")
for s in 0 1 2 3 4 5 6 7 8 9; do
  for t in $TASKS; do for a in L XR XL Z; do
    [ -f runs1/${t}_${a}_${s}.json ] || echo "timeout 10800 $P arms2.py $t $a $s runs1 --budget 15000 > runs1/${t}_${a}_${s}.log 2>&1; echo exit=\$? >> runs1/${t}_${a}_${s}.log"
  done; done | xargs -P 12 -I{} sh -c '{}'
  echo "seed block $s done $(date -u +%FT%T)"
done
echo "ALL DONE $(date -u +%FT%T)"
