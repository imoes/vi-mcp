#!/bin/bash
# Z1 step 0 GPU slot on the 3070 host (PLAN_Z1_step0.md), run with setsid nohup:
#   z1_slot.sh START_AT_ISO START_BY_ISO READ_END_ISO [IGNORE comma list]
# Waits until START_AT; starts only if no claude-* container (minus IGNORE) and no z3q.py runs and the vision llama-server is up and
# answers a real chat request (until START_BY, else gives up). Then stops the vision server and runs q1_read_sample.py in a GPU
# container until it is done or READ_END. The EXIT trap ALWAYS removes the reader container, restarts the vision server (if this
# script stopped it) and probes it with a real chat request; everything is logged to $W/slot.log.
set -u
W=/data1/claude-wikt/z1probe; LOG=$W/slot.log
START_AT=$(date -u -d "$1" +%s); START_BY=$(date -u -d "$2" +%s); READ_END=$(date -u -d "$3" +%s)
IGNORE="${4:-}"; IGN_RE="^($(echo "$IGNORE" | sed 's/,/|/g'))\$"; [ -z "$IGNORE" ] && IGN_RE='^$'
log() { echo "$(date -u +%FT%TZ) $*" >> $LOG; }
chat_probe() {
  curl -s -m 120 localhost:8000/v1/chat/completions -H 'Content-Type: application/json' \
    -d '{"messages":[{"role":"user","content":"Reply with exactly: OK"}],"chat_template_kwargs":{"enable_thinking":false}}' \
    2>/dev/null | python3 -c "import json,sys
try:
    r = json.load(sys.stdin); print(repr(r['choices'][0]['message']['content']), r['choices'][0]['finish_reason'])
except Exception:
    pass"
}
stopped_vision=0
restore() {
  docker rm -f claude-z1-step0 >/dev/null 2>&1 && log "reader container removed"
  if [ $stopped_vision = 1 ]; then
    docker start llama-server >/dev/null 2>&1 && log "vision llama-server started" || log "vision llama-server start FAILED"
    answer=""
    for i in $(seq 40); do answer=$(chat_probe); [ -n "$answer" ] && break; sleep 15; done
    if [ -n "$answer" ]; then log "vision chat probe OK: $answer"; else log "vision chat probe FAILED after 10 min"; fi
  fi
  log "z1_slot exit"
}
trap restore EXIT
log "waiting for $1 (start by $2, reads end $3, ignore '${IGNORE}')"
while [ $(date -u +%s) -lt $START_AT ]; do sleep 20; done
while :; do
  [ $(date -u +%s) -ge $START_BY ] && { log "gave up: slot conditions not met before $2"; exit 1; }
  z3=$(pgrep -f '[z]3q\.py' | wc -l); cc=$(docker ps --format '{{.Names}}' | grep '^claude-' | grep -Evc "$IGN_RE")
  vis=$(docker ps --format '{{.Names}}' | grep -c '^llama-server$')
  probe=""; [ $z3 = 0 ] && [ $cc = 0 ] && [ $vis = 1 ] && probe=$(chat_probe)
  log "check: z3q=$z3 claude_containers=$cc vision_running=$vis probe=${probe:-none}"
  [ -n "$probe" ] && break
  sleep 60
done
log "slot conditions met; GPU before: $(nvidia-smi --query-gpu=memory.used,utilization.gpu --format=csv,noheader)"
docker stop llama-server >/dev/null && stopped_vision=1 && log "VISION STOPPED"
cd $W && sha256sum -c expected.sha256 >> $LOG 2>&1 || { log "HASH-MISMATCH"; exit 1; }
left=$(( READ_END - $(date -u +%s) )); [ $left -le 60 ] && { log "no time left"; exit 1; }
log "reader start, timeout ${left}s"
timeout $left docker run --rm --name claude-z1-step0 --gpus all --shm-size 2g -e HF_HUB_OFFLINE=1 -e PYTHONUNBUFFERED=1 \
  -v $W:/o -v /data1/claude-wikt/kitR3r/out/sft:/adapter:ro -v /data1/claude-ft-bench/hf:/root/.cache/huggingface -w /o \
  claude-ft-bench:cuda-gcc python q1_read_sample.py dev_fresh4_400.json samples_step0.jsonl --ids ids_step0.json --samples 8 \
  --temperature 0.7 --top-p 0.8 --top-k 20 --sample-seed 20261125 --adapter /adapter --shots 0 > $W/reader.log 2>&1
rc=$?
log "reader exit=$rc ($( [ $rc = 124 ] && echo 'READ_END reached' || echo done)); questions read: $(wc -l < $W/samples_step0.jsonl 2>/dev/null || echo 0); GPU: $(nvidia-smi --query-gpu=memory.used --format=csv,noheader)"
