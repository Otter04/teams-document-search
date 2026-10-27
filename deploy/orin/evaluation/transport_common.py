"""Standalone transport helpers, usable on Orin without evaluation labels."""
import hashlib
import json
import os
from pathlib import Path

OUT=Path(os.environ.get('ORIN_EVAL_DIR',str(Path(__file__).resolve().parents[3]/'outputs/orin-evaluation-run-001')))
MODEL='qwen3.6-35b-a3b'
def read(path):return json.loads(Path(path).read_text())
def canonical(x):return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
def digest(x):return hashlib.sha256(canonical(x).encode()).hexdigest()
def write(path,x):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+'.tmp');tmp.write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False)+'\n');tmp.replace(path)
