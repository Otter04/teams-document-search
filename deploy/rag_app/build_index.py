"""Build a versioned searchable 110-document corpus from preserved/reviewed data."""
import copy
import json
import time
import unicodedata
from pathlib import Path
from runtime import ROOT,OUT,E,d,common,read,lines,write

REUSE=ROOT/'outputs/vision-reuse-review-001'
def norm(t):return ''.join(unicodedata.normalize('NFC',t).split())
def frame(loc):return tuple((k,loc.get(k)) for k in ('kind','page','slide','sheet'))

def searchable_record(original):
    record=copy.deepcopy(original);added=[]
    seen={(frame(b['loc']),norm(b['text'])) for b in record['blocks'] if b['text'].strip()}
    for fig in list(record['blocks']):
        if fig['type']!='figure':continue
        nodes={n['node_id']:n for n in fig['visual']['nodes']}
        def add(text,loc,evidence,label):
            if (frame(loc),norm(text)) in seen:return
            seen.add((frame(loc),norm(text)))
            bid=fig['block_id']+'-search-'+label
            b=dict(block_id=bid,parent_id=fig['block_id'],order=len(record['blocks'])+1,
                type='paragraph',text=text,loc=copy.deepcopy(loc),heading_path=fig['heading_path'],
                run_ref=fig['run_ref'],evidence=copy.deepcopy(evidence),claims=[],
                context_ids=[fig['block_id']],content_refs=[],
                warnings=['deterministic_serialization_of_reviewed_visual_structure'])
            record['blocks'].append(b)
            for unit in record['coverage']['units']:
                if fig['block_id'] in unit['block_ids']:unit['block_ids'].append(bid)
            added.append(dict(block_id=bid,source_figure=fig['block_id'],kind=label,text=text))
        for i,n in enumerate(nodes.values()):
            add(n['label'],n['loc'],[e for e in fig['evidence'] if e['evidence_id'] in n['evidence_ids']],f'node{i}')
        for i,edge in enumerate(fig['visual']['relations']):
            x=nodes[edge['from_node']]['label'].replace('\n',' / ')
            y=nodes[edge['to_node']]['label'].replace('\n',' / ')
            arrow={'undirected':'— (방향 표시 없음) —','forward':'→','bidirectional':'↔','unknown':'— (방향 미확인) —'}[edge['direction']]
            label='; 선 라벨: '+edge['label'] if edge['label'] else ''
            ev=[e for e in fig['evidence'] if e['evidence_id'] in edge['evidence_ids']]
            add(f'구성도 연결선: {x} {arrow} {y}{label}',ev[0]['loc'],ev,f'edge{i}')
    # Sort page order so signature/date/title rules see source reading order.
    record['blocks'].sort(key=lambda b:(b['loc'].get('page',b['loc'].get('slide',0)), b['order']))
    for i,b in enumerate(record['blocks'],1):b['order']=i
    assert not common.check(record),common.check(record)
    return record,added

def build():
    if (OUT/'index.json').exists():raise ValueError('Index already exists; preserve it and use a new version')
    started=time.perf_counter()
    parsed={r['doc_id']:r for r in lines(ROOT/'outputs/parsing-run-003/parsed.jsonl')}
    staged={r['doc_id']:r for r in lines(REUSE/'parsed.reuse-staging.jsonl')}
    check=read(REUSE/'verification.json');assert check['status']=='passed'
    for p,h in read(REUSE/'integrity.json')['hashes'].items():assert E.digest(p)==h,p
    for r in read(REUSE/'records.json'):
        assert r['after']['reusable'] and r['wire_common_roundtrip']
        p=read(r['provenance_path']);assert E.digest(p['derivative_path'])==p['derivative_sha256']
    original=copy.deepcopy(parsed);parsed.update(staged)
    assert len(parsed)==110 and len(staged)==30
    # The 103 free-form claims remain in original common blocks, not in text.
    projections={};added=[]
    for did,r in parsed.items():
        projections[did],extra=searchable_record(r);added.extend(extra)
        E.previous.APPROVED_RECORD_HASHES.add(E.record_hash(projections[did]))
    manifest=read(ROOT/'outputs/vision-comparison-run-001/manifest.json')
    sample=next(x for x in manifest['documents'] if x['doc_id']=='D-001')
    rel=original['D-001']['source']['relative_path']
    sourcepath=Path(sample['path']);files_root=sourcepath
    for _ in Path(rel).parts:files_root=files_root.parent
    files=d.collect_files(projections,files_root)
    ref=read(ROOT/'outputs/rag-enrichment-v1/reference-data.json');rules=read(ROOT/'outputs/rag-rule-search-v1/rules.json')
    metadata={};dates={};chunks=[]
    for did,r in projections.items():
        m=E.extract(r,ref);assert not E.check_output(m,r),(did,E.check_output(m,r))
        metadata[did]=m;dates[did]=d.date_metadata(r,m,files[did])
        c=d.old.old.base.make_chunks(r,m);assert not d.old.old.base.validate_chunks(c,r,m)
        c.update(scope='native_and_reviewed_vision',record_kind='reviewed_source_chunks',
            deferred=['embedding','semantic_summary','family_and_latest_version'])
        # Do not index duplicate chunks at the same source location twice.
        seen=set();kept=[]
        for chunk in c['chunks']:
            k=(norm(chunk['text']),tuple(frame(x['loc']) for x in chunk['source_refs']))
            if k not in seen:kept.append(chunk);seen.add(k)
        c['chunks']=kept;chunks.append(c)
    ix=d.old.old.previous.build_index(d.old.old.base.build_index(chunks,ref['clients']),rules)
    bundle=d.old.prepare(ix,projections,metadata);d.attach_dates(ix,dates)
    ix.update(system_terms=ref['system_terms'],scope='110_document_index_with_reviewed_vision',
              claims_indexed=False,embedding_status='not_implemented',answer_model='orin:qwen3.6-35b-a3b')
    for doc in ix['documents'].values():
        doc['searchable_chunk_count']=doc['native_chunk_count']
        doc['embedding_status']='not_implemented'
    OUT.mkdir(parents=True,exist_ok=True)
    for name,rows in [('parsed.jsonl',parsed.values()),('searchable-records.jsonl',projections.values()),
        ('enriched.jsonl',metadata.values()),('chunks.jsonl',chunks),('date-metadata.jsonl',dates.values()),('source-metadata.jsonl',files.values())]:
        E.save_lines(OUT/name,rows)
    write(OUT/'index.json',ix);write(OUT/'features.json',bundle);write(OUT/'visual-serialization.json',added)
    write(OUT/'source-paths.json',{did:str(files_root/Path(r['source']['relative_path'])) for did,r in projections.items()})
    summary=dict(documents=110,vision_documents=30,reused_vision_units=121,
        indexed_chunks=sum(len(c['chunks']) for c in chunks),serialized_visual_blocks=len(added),
        pending_visual_units=sum(len(m['pending_visual_units']) for m in metadata.values()),
        enrichment='rules over native plus reviewed vision literals; no new enrichment model call',
        claims_indexed=False,embedding_implemented=False,new_model_calls=0,
        elapsed_seconds=round(time.perf_counter()-started,3))
    write(OUT/'build-summary.json',summary)
    write(OUT/'build-provenance.json',dict(inputs={str(p):E.digest(p) for p in [REUSE/'parsed.reuse-staging.jsonl',REUSE/'ingestion-policy.json',Path(__file__)]},
        files={p.name:E.digest(p) for p in OUT.iterdir() if p.is_file()},gold_used=False))
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__':build()
