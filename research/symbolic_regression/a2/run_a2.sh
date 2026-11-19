#!/bin/bash
# A2 runner (protocol PROTOCOL_A2.md): Popper arm first (3 reps), then GP arm (seeds 0-4); 8 parallel each, never both at once
A=$(cd "$(dirname "$0")" && pwd); EX=${POPPER_EXAMPLES:?set POPPER_EXAMPLES to Popper v5.0.1 examples/}; P=${PYTHON:-python3}
cd $A
tasks=$(grep ^OK list.txt | awk '{print $2}')
echo "popper start $(date -u +%FT%T)" >> run_a2.log
for t in $tasks; do for r in 0 1 2; do echo "$t $r"; done; done | \
  xargs -P 8 -L 1 bash -c 'docker run --rm -u $(id -u):$(id -g) -e HOME=/tmp -v '$A':/w -v '$EX':/ex:ro popper-g8b:5.0.1 /w/popper_one.sh $0 $1'
echo "popper done $(date -u +%FT%T)" >> run_a2.log
for t in $tasks; do for s in 0 1 2 3 4; do echo "$t $s"; done; done | \
  xargs -P 8 -L 1 bash -c '$0 '$A'/popper_bench.py '$EX' $1 $2 '$A'/gp_runs --seconds 600 > '$A'/gp_runs/$1__s$2.out 2>&1' $P
echo "ALL DONE $(date -u +%FT%T)" >> run_a2.log
