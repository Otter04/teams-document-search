#!/usr/bin/env bash
set -euo pipefail
cd /media/sdcard/rag-runtime/elasticsearch-001
if docker container inspect rag-elasticsearch >/dev/null 2>&1; then
  docker start rag-elasticsearch
  exit 0
fi
# Use runc explicitly: this CPU service must not use the host's NVIDIA default.
# Bind to loopback only. This is an isolated development index, not a public API.
docker build --network=host --tag rag-elasticsearch-nori:8.19.23 .
mkdir -p data
docker run --rm --runtime=runc --user 0 --entrypoint /bin/sh \
  -v "$PWD/data:/data" rag-elasticsearch-nori:8.19.23 -c 'chown 1000:0 /data'
docker run -d --name rag-elasticsearch --runtime=runc --restart unless-stopped \
  --memory=4g --cpus=4 --ulimit nofile=65536:65536 \
  -p 127.0.0.1:9200:9200 \
  -e discovery.type=single-node -e cluster.name=rag-orin -e node.name=rag-orin-01 \
  -e xpack.security.enabled=false -e xpack.ml.enabled=false \
  -e ingest.geoip.downloader.enabled=false -e node.store.allow_mmap=false \
  -e 'ES_JAVA_OPTS=-Xms2g -Xmx2g' \
  -v "$PWD/data:/usr/share/elasticsearch/data" \
  rag-elasticsearch-nori:8.19.23
