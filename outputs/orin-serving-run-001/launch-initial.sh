#!/usr/bin/env bash
# Run on the Orin host, not on the Mac or inside an existing container.
# Prepared 2026-10-19. CLI options checked; model loading not yet tested.
set -euo pipefail

test -r /media/sdcard/models/Qwen3.6-35B-A3B-AWQ-4bit/config.json
test -r /media/sdcard/models/Qwen3.6-35B-A3B-AWQ-4bit/model.safetensors.index.json
docker image inspect ghcr.io/nvidia-ai-iot/vllm:latest-jetson-orin >/dev/null
mkdir -p /media/sdcard/rag-runtime/cache

docker run -d \
  --name rag-qwen36 \
  --pull never \
  --runtime nvidia \
  --ipc host \
  -p 127.0.0.1:8001:8000 \
  --mount type=bind,src=/media/sdcard/models/Qwen3.6-35B-A3B-AWQ-4bit,dst=/models/qwen36,readonly \
  --mount type=bind,src=/media/sdcard/rag-runtime/cache,dst=/root/.cache \
  -e HF_HUB_OFFLINE=1 \
  -e TRANSFORMERS_OFFLINE=1 \
  -e HF_HUB_DISABLE_TELEMETRY=1 \
  --entrypoint /opt/venv/bin/vllm \
  ghcr.io/nvidia-ai-iot/vllm:latest-jetson-orin \
  serve /models/qwen36 \
  --served-model-name qwen3.6-35b-a3b \
  --host 0.0.0.0 \
  --port 8000 \
  --dtype half \
  --max-model-len 16384 \
  --gpu-memory-utilization 0.80 \
  --max-num-seqs 1 \
  --max-num-batched-tokens 2048 \
  --limit-mm-per-prompt '{"image":1,"video":0}' \
  --reasoning-parser qwen3 \
  --default-chat-template-kwargs '{"enable_thinking":false}' \
  --enforce-eager
