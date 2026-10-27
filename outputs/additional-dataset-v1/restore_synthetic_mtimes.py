"""Restore declared synthetic timestamps after copying this evaluation corpus.

Reads source-files.jsonl, never evaluation answer labels. No network or model calls.
"""
import argparse,hashlib,json,os
from pathlib import Path

def restore(root,apply=False):
    root=Path(root).resolve();files=(root/'files').resolve();changes=[]
    for line in (root/'source-files.jsonl').read_text().splitlines():
        r=json.loads(line);p=(files/r['relative_path']).resolve()
        if not p.is_relative_to(files) or not p.is_file():raise ValueError('Invalid source path')
        if hashlib.sha256(p.read_bytes()).hexdigest()!=r['sha256']:raise ValueError('Source hash changed: '+r['doc_id'])
        if r['timestamp_origin']!='synthetic_assigned_by_author':raise ValueError('Only synthetic timestamps may be restored')
        ns=int(r['modified_at_ns']);changes.append({'doc_id':r['doc_id'],'different':p.stat().st_mtime_ns!=ns,'expected_ns':str(ns)})
    # All paths and hashes are checked before any mutation.
    if apply:
        for line in(root/'source-files.jsonl').read_text().splitlines():
            r=json.loads(line);p=files/r['relative_path'];os.utime(p,ns=(p.stat().st_atime_ns,int(r['modified_at_ns'])))
    return {'applied':apply,'documents':len(changes),'different_before':sum(c['different']for c in changes)}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--apply',action='store_true');a=p.parse_args()
    print(json.dumps(restore(Path(__file__).parent,a.apply)))
