"""Synchronize and score saved responses while the durable Orin job runs."""
import json, os, subprocess, sys, time
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
OUT=ROOT/'outputs/orin-evaluation-run-001'
env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONPATH=str(ROOT/'work/schema-deps'))
previous=None
while True:
    sync=subprocess.run([sys.executable,str(HERE/'sync_results.py')],cwd=ROOT,env=env,capture_output=True,text=True)
    if sync.returncode:
        print('Sync failed; remote batch is not stopped: '+sync.stderr,flush=True)
        sys.exit(sync.returncode)
    status=json.loads((OUT/'run-status.json').read_text())
    key=(status['status'],status['saved'])
    if key!=previous:
        subprocess.run([sys.executable,str(HERE/'report.py')],cwd=ROOT,env=env,check=True)
        print(json.dumps(status,ensure_ascii=False),flush=True)
        previous=key
    if status['status'].startswith('blocked') or status['status'] in ('responses_collected','limited_run_finished'):
        break
    time.sleep(50)
