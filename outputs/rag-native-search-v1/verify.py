#!/usr/bin/env python3
"""Replay without network or gold access, then verify original file hashes."""
import argparse
import os
from pathlib import Path
import sys
import unicodedata
import pipeline as p

def run(args):
    out=Path(args.run);src=p.unique_records(args.parsed);meta=p.unique_records(args.metadata)
    stored=p.unique_records(out/'chunks.jsonl');ix=p.enrich.read_json(out/'index.json');prov=p.enrich.read_json(out/'provenance.json')
    queries=p.enrich.read_lines(out/'evaluation/query-inputs.jsonl')
    expected=p.enrich.read_lines(out/'evaluation/search-results.jsonl')
    assert all(set(q)=={'query_id','query'} for q in queries)
    assert all(p.enrich.digest(path)==sha for path,sha in prov['inputs'].items())
    assert p.enrich.digest(p.ROOT/'pipeline.py')==prov['code_sha256']
    guard={'active':True,'blocked_attempts':0}
    def audit(event,values):
        if not guard['active']:return
        blocked=event in ('socket.connect','socket.getaddrinfo','subprocess.Popen','os.system')
        if event=='open':
            path,mode,flags=values
            blocked=blocked or '/gold/' in str(path).replace('\\','/') or (isinstance(mode,str) and any(c in mode for c in 'wax+')) or bool(flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND))
        if blocked:
            guard['blocked_attempts']+=1
            raise RuntimeError('Replay attempted forbidden IO: '+event)
    sys.addaudithook(audit)
    rebuilt=[p.make_chunks(record,meta[identity]) for identity,record in src.items()]
    assert {r['doc_id']:r for r in rebuilt}==stored
    rebuilt_index=p.build_index(rebuilt,ix['clients']);assert rebuilt_index==ix
    results=[{'query_id':q['query_id'],'query':q['query'],**p.search(rebuilt_index,q['query'],limit=10)} for q in queries]
    assert results==expected
    guard['active']=False
    files=Path(args.dataset)/'files'
    lookup={unicodedata.normalize('NFC',str(path.relative_to(files))):path for path in files.rglob('*') if path.is_file()}
    checks=[]
    for identity,record in src.items():
        path=lookup[unicodedata.normalize('NFC',record['source']['relative_path'])]
        checks.append({'doc_id':identity,'source_sha256_match':p.enrich.digest(path)==record['source']['sha256']})
    assert all(c['source_sha256_match'] for c in checks)
    assert all(p.enrich.digest(out/name)==sha for name,sha in prov['outputs'].items())
    result={'documents_replayed':len(rebuilt),'chunks_exact_match':True,'index_exact_match':True,'queries_exact_match':len(results),
            'all_source_hashes_match':len(checks),'source_checks':checks,'inputs_and_output_hashes_unchanged':True,
            'replay_network_gold_and_write_guard_enabled':True,'forbidden_io_attempts':guard['blocked_attempts'],
            'source_original_files_read_only':True,'model_called':False,'implementation_sha256':p.enrich.digest(p.ROOT/'pipeline.py')}
    p.enrich.dump(out/'verification.json',result)
    print({k:v for k,v in result.items() if k!='source_checks'})

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for field in ('run','parsed','metadata','dataset'):parser.add_argument('--'+field,required=True)
    run(parser.parse_args())
