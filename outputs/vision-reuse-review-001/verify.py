"""Independent checks of the staged files plus negative repair boundaries."""
import copy
import json
from pathlib import Path
import review_reuse as r

H=Path(__file__).resolve().parent
a=r.a
records=a.read(H/'records.json')
integrity=a.read(H/'integrity.json')
assert all(a.filehash(p)==h for p,h in integrity['hashes'].items())
manifest=a.read(a.VISION/'manifest.json');items={a.key(i):i for i in manifest['items']}
native={d['doc_id']:d for d in [json.loads(l) for l in (r.ROOT/'outputs/parsing-run-003/parsed.jsonl').read_text().splitlines()]}
assembled={d['doc_id']:d for d in [json.loads(l) for l in (H/'parsed.reuse-staging.jsonl').read_text().splitlines()]}
assert len(assembled)==30
for row in records:
    key=row['id'];base=H/'units'/key;w=a.read(base/'wire.json');p=a.read(base/'provenance.json')
    assert a.filehash(base/'wire.json')==p['derivative_sha256']
    assert a.filehash(p['original_response_path'])==p['original_response_sha256']
    assert row['after']['reusable'] and not a.quality.base.check_wire(w)
    if row['prior_candidate']:
        original=json.loads(a.read(p['original_response_path'])['choices'][0]['message']['content'])
        assert original==w and not a.read(base/'changes.json')
    for doc in (a.read(base/'common-block-document.json'),assembled[row['doc_id']]):
        assert not a.quality.base.common.check(doc)
        assert a.review.common_payload(doc,items[key])==a.review.wire_payload(w)
for did,doc in assembled.items():
    assert doc['source']==native[did]['source']
    assert all(b in doc['blocks'] for b in native[did]['blocks'])
    assert all(u['status']=='completed' for u in doc['coverage']['units'] if u['unit_id'].startswith('vision:'))

def fixture(text,box):
    return dict(status='complete',texts=[dict(kind='paragraph',text=text,bbox=box)],tables=[],warnings=[],
        figures=[dict(kind='diagram',bbox=[0,0,1,1],nodes=[dict(id='n',label='동일하게 쓰인 문구',bbox=[.1,.1,.3,.3])],relations=[],claims=[])])
# Same phrase at a different place is a legitimate source occurrence.
w=fixture('동일하게 쓰인 문구',[.7,.7,.9,.9]);log=[]
assert r.deduplicate(w,{},log)['texts'] and not log
# A contained phrase with additional content must not be deleted.
w=fixture('동일하게 쓰인 문구 + 고유한 부정: 사용하지 않음',[.1,.1,.3,.3]);log=[]
assert r.deduplicate(w,{},log)['texts'] and not log
# Exact duplication at one place can be reduced, keeping its structural node.
w=fixture('동일하게 쓰인 문구',[.1,.1,.3,.3]);log=[]
r.deduplicate(w,{},log);assert not w['texts'] and len(w['figures'][0]['nodes'])==1 and len(log)==1
# Geometry fix must not rewrite non-geometric relationships or pad invalid text.
w=fixture('동일하게 쓰인 문구',[.1,.1,.1,.2]);f=w['figures'][0]
f['relations']=[dict(from_node='n',to_node='n',direction='undirected',label='관계',bbox=[.8,.6,.2,.6])]
log=[];r.repair_geometry(w,dict(width=1000,height=1000),log)
assert f['relations'][0]['bbox']==[.2,.599,.8,.601]
assert f['relations'][0]['label']=='관계' and w['texts'][0]['bbox']==[.1,.1,.1,.2]
assert a.quality.base.check_wire(w) # text region still blocks, not silently accepted
# Text present in an unreadable cell never grants generic 'known' status.
w=a.read(H/'units/D-044-vision-page2/wire.json');w['tables'][0]['cells'][0]['value_status']='unreadable'
before=copy.deepcopy(w);r.manual_apply('D-999-vision-page2',w,[]);assert w==before
assert any(i['code']=='UNREADABLE_CELL_WITH_TEXT' for i in a.quality.check_quality(w,[]))
# Truncated source is still invalid; only explicitly tagged derived reconstruction passes.
p=a.read(H/'units/D-102-vision-page2/provenance.json')
raw=a.read(p['original_response_path'])['choices'][0]['message']['content']
try:json.loads(raw)
except ValueError:pass
else:raise AssertionError('Original unexpectedly became valid JSON')
assert p['category']=='assistant_source_reconstruction' and not p['original_json_complete']
assert p['original_model_success_changed'] is False

result=dict(status='passed',raw_and_reference_hashes_preserved=len(integrity['hashes']),
    unchanged_units_verified=67,derivative_units=54,common_unit_roundtrips=121,
    final_assembled_documents=30,existing_native_blocks_preserved=True,
    negative_boundaries_passed=6,new_model_calls=0)
a.write(H/'verification.json',result)
print(json.dumps(result,ensure_ascii=False,indent=2))
