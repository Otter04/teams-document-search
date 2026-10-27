"""Read-only remote snapshot into the dedicated local evaluation output."""
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'outputs/orin-evaluation-run-001'
REMOTE='ubuntu@192.168.60.40:/media/sdcard/rag-runtime/evaluation-run-001/'
cmd=['rsync','-a','--exclude=*.tmp','--include=/results/***','--include=/history/***',
     '--include=/run-status.json','--include=/progress.json','--include=/progress.log',
     '--include=/server-models.json','--include=/dispatch-location.json',
     '--exclude=*','-e','ssh -S /Users/kangdongkyoon/.ssh/rag-orin.sock -o BatchMode=yes -o ConnectTimeout=10',REMOTE,str(OUT)+'/']
subprocess.run(cmd,check=True)
status=json.loads((OUT/'run-status.json').read_text())
print(json.dumps(status,ensure_ascii=False),flush=True)
(OUT/'last-sync.json').write_text(json.dumps({'synced_at':datetime.now(timezone.utc).isoformat(),'status':status},ensure_ascii=False,indent=2)+'\n')
