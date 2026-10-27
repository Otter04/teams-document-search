#!/usr/bin/env bash
set -euo pipefail
# Run only after source review, embedding, and v002 index verification.
candidate_root="$(cd "$(dirname "$0")" && pwd)"
test -f "$candidate_root/data/index-verification.json"
test -f "$candidate_root/service.py"
if docker container inspect rag-search-v31-validation >/dev/null 2>&1; then
  echo 'Candidate container exists; inspect its mount/port/index settings before resuming.'
  exit 1
fi
docker run -d --name rag-search-v31-validation --runtime nvidia --network host \
  --memory 10g --cpus 4 --restart unless-stopped \
  -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 -e TOKENIZERS_PARALLELISM=false \
  -e RAG_PORT=8022 -e RAG_CHUNK_INDEX=rag-search-chunks-v003 -e RAG_DOCUMENT_INDEX=rag-search-documents-v003 \
  -v "$candidate_root:/app:ro" -v /media/sdcard/models/bge-m3:/models/bge-m3:ro \
  -w /app ghcr.io/nvidia-ai-iot/vllm:latest-jetson-orin python3 service.py
