#!/usr/bin/env bash
# Run on the Orin host, not on the Mac or inside an existing container.
# Prepared 2026-10-19; launched and text/image smoke-tested 2026-10-20.
# See outputs/orin-serving-run-001. Do not rerun while rag-qwen36 exists.
# 2026-10-20: user approved 49,152 context for full comparison inputs.
# Cache allocation fix: explicit 8 GiB replaces automatic cache sizing from
# gpu-memory-utilization. The 0.80 value is retained but does not control cache
# allocation when kv-cache-memory-bytes is set. No dtype/context/output change.
# Disable mirrored image processor cache: /tokenize then generation otherwise
# desynchronizes the frontend and engine caches in this installed build.
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
  --max-model-len 49152 \
  --gpu-memory-utilization 0.80 \
  --kv-cache-memory-bytes 8589934592 \
  --max-num-seqs 1 \
  --max-num-batched-tokens 2048 \
  --limit-mm-per-prompt '{"image":1,"video":0}' \
  --mm-processor-cache-gb 0 \
  --skip-mm-profiling \
  --reasoning-parser qwen3 \
  --default-chat-template-kwargs '{"enable_thinking":false}' \
  --enforce-eager

# Jetson shares CPU/GPU RAM. Release only these model files' clean page cache
# after weights reach GPU; never drop global caches or modify model contents.
nohup python3 - > /media/sdcard/rag-runtime/startup-cache-release.log 2>&1 <<'PY' &
import json, os, subprocess, time
from datetime import datetime, timezone
from pathlib import Path
model_dir=Path('/media/sdcard/models/Qwen3.6-35B-A3B-AWQ-4bit')
def memory():
    return {line.split(':',1)[0]:line.split(':',1)[1].strip()
            for line in Path('/proc/meminfo').read_text().splitlines()
            if line.split(':',1)[0] in ('MemFree','MemAvailable','Cached')}
for _ in range(900):
    state=json.loads(subprocess.check_output(['docker','inspect','rag-qwen36']))[0]['State']
    if not state['Running']:raise RuntimeError('Server exited before weight-load cache release')
    log=subprocess.check_output(['docker','logs','rag-qwen36'],stderr=subprocess.STDOUT).decode(errors='replace')
    if 'Model loading took' in log:break
    time.sleep(2)
else:raise TimeoutError('Weight loading not observed')
before=memory();files=[]
for p in sorted(model_dir.glob('*.safetensors')):
    fd=os.open(p,os.O_RDONLY)
    try:os.posix_fadvise(fd,0,0,os.POSIX_FADV_DONTNEED)
    finally:os.close(fd)
    files.append(p.name)
result={'at':datetime.now(timezone.utc).isoformat(),'method':'read-only model-shard POSIX_FADV_DONTNEED',
        'files':files,'before':before,'after':memory()}
Path('/media/sdcard/rag-runtime/startup-cache-release.json').write_text(json.dumps(result,indent=2))
print(json.dumps(result,indent=2),flush=True)
PY
