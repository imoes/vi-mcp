#!/bin/bash
# inside the container: popper_one.sh TASK REP  (examples mounted read-only at /ex, results at /w/popper_runs)
t=$1; r=$2; out=/w/popper_runs/${t}__r${r}.log
flag=""; case $t in noisy-*) flag="--noisy";; esac
s=$(date +%s.%N)
timeout 660 /opt/venv/bin/python /opt/Popper/popper.py /ex/$t --timeout 600 $flag > $out 2>&1
rc=$?; e=$(date +%s.%N)
echo "popper_exit=$rc popper_seconds=$(python3 -c "print(round($e - $s, 2))") flag=$flag" >> $out
