#!/bin/bash
# PREREG_R3r2: R3r (adapter, 0-shot) and base Qwen3-0.6B (2-shot) read the gold paragraphs of the 400 fresh3 questions
# (dev_fresh3_400.json: 100 per type, disjoint from fresh, fresh2 and the development 400; random.Random("q1-fresh3-2026-11-22"));
# q1_read_v2.py unchanged (sha 5c6e9c6d…). Starts after the sym-rag pool reads ("done" in ragread/run.log) and when no claude-ft-*
# container runs; llama-server stopped, restarted in the EXIT trap.
B=/data1/claude-wikt/q1fresh3
LOG=$B/run.log
until grep -q "^done " /data1/claude-wikt/ragread/run.log 2>/dev/null && ! docker ps --format '{{.Names}}' | grep -q '^claude-ft-'; do sleep 60; done
trap 'docker start llama-server >/dev/null 2>&1; echo "llama-server started $(date -u +%T)" >> $LOG' EXIT
echo "start $(date -u +%FT%TZ)" >> $LOG
cd $B && sha256sum -c expected.sha256 >> $LOG 2>&1 || { echo "HASH-MISMATCH" >> $LOG; exit 1; }
docker stop llama-server >/dev/null 2>&1; echo "llama-server stopped $(date -u +%T)" >> $LOG
docker run --rm --name claude-ft-q1fresh3-r3r --gpus all --shm-size 2g -e HF_HUB_OFFLINE=1 -e PYTHONUNBUFFERED=1 \
  -v /data1/claude-wikt/q1read:/q:ro -v /data1/claude-wikt/kitR3r/out/sft:/adapter:ro -v $B:/o \
  -v /data1/claude-ft-bench/hf:/root/.cache/huggingface -w /o claude-ft-bench:cuda-gcc \
  bash -c 'python /q/q1_read_v2.py /o/dev_fresh3_400.json /o/read_fresh3_r3r.jsonl --per-type 100 --seed 11 --adapter /adapter --shots 0' > $B/r3r.log 2>&1
echo "r3r exit=$? $(date -u +%T)" >> $LOG
docker run --rm --name claude-ft-q1fresh3-base --gpus all --shm-size 2g -e HF_HUB_OFFLINE=1 -e PYTHONUNBUFFERED=1 \
  -v /data1/claude-wikt/q1read:/q:ro -v $B:/o \
  -v /data1/claude-ft-bench/hf:/root/.cache/huggingface -w /o claude-ft-bench:cuda-gcc \
  bash -c 'python /q/q1_read_v2.py /o/dev_fresh3_400.json /o/read_fresh3_base2shot.jsonl --per-type 100 --seed 11 --shots 2' > $B/base.log 2>&1
echo "base exit=$? $(date -u +%T)" >> $LOG
echo "done $(date -u +%FT%TZ)" >> $LOG
