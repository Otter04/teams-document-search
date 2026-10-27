#!/usr/bin/env bash
set -euo pipefail
# Run on Orin from /media/sdcard/rag-runtime/search-service-001.
search_root="$(cd "$(dirname "$0")" && pwd)"
test -f "$search_root/data/index-verification.json"
docker image inspect ghcr.io/nvidia-ai-iot/vllm:latest-jetson-orin >/dev/null
if docker container inspect rag-search >/dev/null 2>&1; then
  docker start rag-search
else
  docker run -d --name rag-search --runtime nvidia --network host \
    --memory 10g --cpus 4 --restart unless-stopped \
    -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 -e TOKENIZERS_PARALLELISM=false \
    -v "$search_root:/app:ro" -v /media/sdcard/models/bge-m3:/models/bge-m3:ro \
    -w /app ghcr.io/nvidia-ai-iot/vllm:latest-jetson-orin python3 service.py
fi
