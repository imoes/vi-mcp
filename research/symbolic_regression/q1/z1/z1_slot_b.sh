#!/bin/bash
# Z1 step 0b GPU slot on the 3070 host (PLAN_Z1_step0b.md), run with setsid nohup:
#   z1_slot_b.sh GIVE_UP_ISO STOP_READS_ISO HARD_END_ISO
# Starts only when ALL hold: af's CT-S1B wait.log has "smoke runner returned" or "GAVE UP at 20:15 UTC"; 7a's kit35_s43/run.log
# has a line ^(launcher exit|BUSY: |HASH-MISMATCH); no claude-* container; no GPU compute process except the vision llama-server;
# the vision server answers a real chat request. Gives up at GIVE_UP. Then: vision stopped, Qwen3-8B Q4 served on 127.0.0.1:18093,
# q1_read_teacher.py reads until done or STOP_READS (question boundary), hard timeout at HARD_END. The EXIT trap ALWAYS removes the 8B
# container, restarts the vision server (if this script stopped it) and probes it with a real chat request; all logged to $W/slot_b.log.
set -u
W=/data1/claude-wikt/z1probe; LOG=$W/slot_b.log
AF=/data1/claude-wikt/ct-s1b/runs/wait.log; Z4=/data1/claude-wikt/kit35_s43/run.log
GIVE_UP=$(date -u -d "$1" +%s); HARD_END=$(date -u -d "$3" +%s); STOP_READS="$2"
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
  docker rm -f claude-z1-teacher >/dev/null 2>&1 && log "8B container removed"
  if [ $stopped_vision = 1 ]; then
    docker start llama-server >/dev/null 2>&1 && log "vision llama-server started" || log "vision llama-server start FAILED"
    answer=""
    for i in $(seq 40); do answer=$(chat_probe); [ -n "$answer" ] && break; sleep 15; done
    if [ -n "$answer" ]; then log "vision chat probe OK: $answer"; else log "vision chat probe FAILED after 10 min"; fi
  fi
  log "z1_slot_b exit"
}
trap restore EXIT
log "waiting (give up $1, reads stop $2, hard end $3)"
while :; do
  [ $(date -u +%s) -ge $GIVE_UP ] && { log "GAVE UP: start conditions not met before $1; teacher NOT started"; exit 1; }
  af=$(grep -cE 'smoke runner returned|GAVE UP at 20:15 UTC' $AF 2>/dev/null); af=${af:-0}
  z4=$(grep -cE '^(launcher exit|BUSY: |HASH-MISMATCH)' $Z4 2>/dev/null); z4=${z4:-0}
  cc=$(docker ps --format '{{.Names}}' | grep -c '^claude-')
  vis=$(docker ps --format '{{.Names}}' | grep -c '^llama-server$')
  apps=$(nvidia-smi --query-compute-apps=pid --format=csv,noheader | wc -l)
  vpid=$(docker top llama-server -eo pid 2>/dev/null | tail -n +2 | tr '\n' '|'); other=0
  for p in $(nvidia-smi --query-compute-apps=pid --format=csv,noheader); do echo "|$vpid" | grep -q "|$p|" || other=$((other+1)); done
  probe=""; [ $af -ge 1 ] && [ $z4 -ge 1 ] && [ $cc = 0 ] && [ $vis = 1 ] && [ $other = 0 ] && probe=$(chat_probe)
  log "check: af_done=$af z4_done=$z4 claude_containers=$cc vision_running=$vis gpu_apps=$apps non_vision_gpu_apps=$other probe=${probe:-none}"
  [ -n "$probe" ] && break
  sleep 60
done
log "start conditions met; GPU before: $(nvidia-smi --query-gpu=memory.used,utilization.gpu --format=csv,noheader)"
cd $W && sha256sum -c expected_b.sha256 >> $LOG 2>&1 || { log "HASH-MISMATCH"; exit 1; }
docker stop llama-server >/dev/null && stopped_vision=1 && log "VISION STOPPED"
docker run -d --name claude-z1-teacher --user $(id -u):$(id -g) --gpus all -p 127.0.0.1:18093:8080 -v ~/vifacts/models:/m:ro \
  ghcr.io/ggml-org/llama.cpp:server-cuda -m /m/Qwen3-8B-Q4_K_M.gguf --host 0.0.0.0 --port 8080 --n-gpu-layers 99 \
  --ctx-size 8192 --parallel 1 --flash-attn on --jinja >/dev/null || { log "8B start failed"; exit 1; }
for i in $(seq 60); do curl -s -m 5 localhost:18093/health | grep -q ok && break; sleep 5; done
curl -s -m 5 localhost:18093/health | grep -q ok || { log "8B not healthy"; exit 1; }
log "8B ready; GPU: $(nvidia-smi --query-gpu=memory.used,utilization.gpu --format=csv,noheader)"
left=$(( HARD_END - $(date -u +%s) - 60 )); [ $left -le 60 ] && { log "no time left"; exit 1; }
timeout $left python3 -I q1_read_teacher.py dev_fresh4_400.json teacher_step0b.jsonl --ids ids_step0.json --url http://127.0.0.1:18093 \
  --shots 2 --stop-at "$STOP_READS" > $W/teacher.log 2>&1
rc=$?
log "reader exit=$rc; last line: $(tail -1 $W/teacher.log); questions read: $(wc -l < $W/teacher_step0b.jsonl 2>/dev/null || echo 0)"
