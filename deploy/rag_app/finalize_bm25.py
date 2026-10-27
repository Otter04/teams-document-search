"""Finalize BM25 indexing only. No queries, generation, embeddings, or API calls."""
import collections
import copy
import csv
import json
from pathlib import Path
import re
import sys
import time
import unicodedata
from runtime import ROOT,E,d,common,read,lines,write

SOURCE=ROOT/'outputs/rag-live-001'
OUT=ROOT/'outputs/indexing-110-bm25-001'
def norm(s):return re.sub(r'\s+','',unicodedata.normalize('NFC',s)).replace('㈜','(주)').replace('×','x')
def frame(b):return tuple(b['loc'].get(k) for k in ('kind','page','slide','sheet'))
def same_region(a,b):
    if frame(a)!=frame(b):return False
    a=a['loc'].get('bbox');b=b['loc'].get('bbox')
    if not a or not b:return False
    area=lambda x:max(0,x['x1']-x['x0'])*max(0,x['y1']-x['y0'])
    intersection=max(0,min(a['x1'],b['x1'])-max(a['x0'],b['x0']))*max(0,min(a['y1'],b['y1'])-max(a['y0'],b['y0']))
    return intersection/max(1e-12,min(area(a),area(b)))>=.5

def projection(source):
    r=copy.deepcopy(source);log=[];mapping={};runs={x['run_id']:x for x in r['runs']}
    native=[b for b in r['blocks'] if runs[b['run_ref']]['method']=='native_parser']
    native_ids={b['block_id'] for b in native}
    # Only duplicate extraction of one source region across native/vision paths.
    # Similar phrases, separate source regions and native repetitions are kept.
    for b in r['blocks']:
        if b['block_id'] in native_ids or b['type'] not in ('heading','paragraph','caption') or not b['text'].strip():continue
        matched=[n for n in native if n['type'] not in ('slide','table','figure') and norm(n['text'])==norm(b['text']) and same_region(n,b)]
        if not matched:continue
        n=matched[0];log.append(dict(kind='duplicate_literal_reference',old_id=b['block_id'],retained_id=n['block_id'],old_text=b['text'],retained_text=n['text']))
        b['text']='';b['content_refs']=[n['block_id']]
        b['warnings'].append('duplicate_extraction_indexes_native_literal_once')
    def rows(t):return sorted([b for b in r['blocks'] if b['parent_id']==t['block_id'] and b['type']=='table_row'],key=lambda b:b['cells'][0]['row'])
    def grid(t):return sorted((c['row'],c['column'],c['row_span'],c['column_span'],norm(c['text'])) for row in rows(t) for c in row['cells'])
    for t in [b for b in r['blocks'] if b['type']=='table' and b['block_id'] not in native_ids]:
        matches=[n for n in native if n['type']=='table' and same_region(n,t) and n['table']['row_count']==t['table']['row_count'] and n['table']['column_count']==t['table']['column_count'] and grid(n)==grid(t)]
        if not matches:continue
        n=matches[0];mapping[t['block_id']]=n['block_id']
        nr={x['cells'][0]['row']:x for x in rows(n)}
        for row in rows(t):
            target=nr[row['cells'][0]['row']]
            assert norm(row['text'])==norm(target['text'])
            mapping[row['block_id']]=target['block_id']
        if not n['table']['header_rows'] and t['table']['header_rows']:
            n['table'].update(header_rows=t['table']['header_rows'],header_status=t['table']['header_status'])
            n['warnings'].append('header_rows_from_reviewed_vision_table:'+t['block_id'])
        log.append(dict(kind='duplicate_table_alias',old_id=t['block_id'],retained_id=n['block_id'],cell_count=len(grid(t)),retained_vision_header=t['table']['header_rows']))
    r['blocks']=[b for b in r['blocks'] if b['block_id'] not in mapping]
    for b in r['blocks']:
        b['parent_id']=mapping.get(b['parent_id'],b['parent_id'])
        for field in ('context_ids','content_refs'):b[field]=list(dict.fromkeys(mapping.get(v,v) for v in b[field]))
    for u in r['coverage']['units']:u['block_ids']=list(dict.fromkeys(mapping.get(v,v) for v in u['block_ids']))
    # Serialize supported structure, never the model's free-form claims.
    for fig in list(r['blocks']):
        if fig['type']!='figure':continue
        nodes={n['node_id']:n for n in fig['visual']['nodes']}
        def add(text,loc,ev,kind):
            candidate={'loc':loc}
            existing=[b for b in r['blocks'] if b['text'].strip() and norm(b['text'])==norm(text) and same_region(b,candidate)]
            if existing:return
            bid=fig['block_id']+'-index-'+kind
            r['blocks'].append(dict(block_id=bid,parent_id=fig['block_id'],order=len(r['blocks'])+1,type='paragraph',text=text,loc=copy.deepcopy(loc),heading_path=fig['heading_path'],run_ref=fig['run_ref'],evidence=copy.deepcopy(ev),claims=[],context_ids=[fig['block_id']],content_refs=[],warnings=['deterministic_serialization_of_reviewed_visual_structure']))
            for u in r['coverage']['units']:
                if fig['block_id'] in u['block_ids']:u['block_ids'].append(bid)
            log.append(dict(kind='visual_structure_serialization',block_id=bid,source_figure=fig['block_id'],text=text))
        for i,n in enumerate(nodes.values()):add(n['label'],n['loc'],[e for e in fig['evidence'] if e['evidence_id'] in n['evidence_ids']],f'node{i}')
        for i,e in enumerate(fig['visual']['relations']):
            x=nodes[e['from_node']]['label'].replace('\n',' / ');y=nodes[e['to_node']]['label'].replace('\n',' / ')
            arrow={'undirected':'— (방향 표시 없음) —','forward':'→','bidirectional':'↔','unknown':'— (방향 미확인) —'}[e['direction']]
            ev=[v for v in fig['evidence'] if v['evidence_id'] in e['evidence_ids']]
            label='; 선 라벨: '+e['label'] if e['label'] else ''
            add(f'구성도 연결선: {x} {arrow} {y}{label}',ev[0]['loc'],ev,f'edge{i}')
    r['blocks'].sort(key=lambda b:(b['loc'].get('page',b['loc'].get('slide',0)),b['order']))
    for i,b in enumerate(r['blocks'],1):b['order']=i
    assert not common.check(r),common.check(r)
    # All original literals either remain verbatim or have an explicit alias.
    current={b['block_id']:b for b in r['blocks']}
    for old in source['blocks']:
        if not old['text'].strip():continue
        b=current.get(old['block_id']) or current[mapping[old['block_id']]]
        if b['content_refs']:b=current[b['content_refs'][0]]
        assert norm(b['text'])==norm(old['text']),old['block_id']
    return r,log

def main():
    if OUT.exists():raise ValueError('Version already exists; do not overwrite final artifacts')
    start=time.perf_counter()
    inputs=[SOURCE/x for x in ('parsed.jsonl','enriched.jsonl','source-metadata.jsonl')]
    inputs += [ROOT/'outputs/parsing-run-003/parsed.jsonl',ROOT/'outputs/vision-reuse-review-001/records.json',Path(__file__)]
    hashes={str(p):E.digest(p) for p in inputs}
    src={r['doc_id']:r for r in lines(SOURCE/'parsed.jsonl')};prev={r['doc_id']:r for r in lines(SOURCE/'enriched.jsonl')}
    source_meta={r['doc_id']:r for r in lines(SOURCE/'source-metadata.jsonl')}
    baseline={r['doc_id']:r for r in lines(ROOT/'outputs/date-search-run-002/enriched.jsonl')}
    assert len(src)==110
    # Prohibit model requests or shell operations during finalization.
    def offline(event,args):
        if event in ('socket.connect','socket.getaddrinfo','subprocess.Popen','os.system'):raise RuntimeError('Indexing finalization is offline')
    sys.addaudithook(offline)
    records={};audits={};enriched={};dates={};chunks=[];changes=[];ledger=[]
    ref=read(ROOT/'outputs/rag-enrichment-v1/reference-data.json');rules=read(ROOT/'outputs/rag-rule-search-v1/rules.json')
    for did,s in src.items():
        r,log=projection(s);records[did]=r;audits[did]=log
        E.previous.APPROVED_RECORD_HASHES.add(E.record_hash(r))
        m=E.extract(r,ref);assert not E.check_output(m,r),(did,E.check_output(m,r));enriched[did]=m
        # Deduplication must never change a metadata value/status.
        assert all((v['value'],v['status'])==(prev[did]['fields'][k]['value'],prev[did]['fields'][k]['status']) for k,v in m['fields'].items()),did
        dates[did]=d.date_metadata(r,m,source_meta[did])
        c=d.old.old.base.make_chunks(r,m);assert not d.old.old.base.validate_chunks(c,r,m),did
        c.update(scope='native_and_reviewed_vision',record_kind='reviewed_source_chunks',deferred=['optional_semantic_summary'],model_called=False)
        c['config']['token_budget_status']='character_chunks_for_bm25_no_embedding'
        for ch in c['chunks']:ch['token_budget_status']='character_chunks_for_bm25_no_embedding'
        # Keep all source references; no post-validation chunk deletion.
        assert not d.old.old.base.validate_chunks(c,r,m)
        chunks.append(c)
        for field,v in m['fields'].items():
            old=baseline[did]['fields'][field]
            if (old['value'],old['status'].replace('not_found_native','not_found_text'))!=(v['value'],v['status']):
                changes.append(dict(doc_id=did,field=field,before=old['value'],after=v['value'],before_status=old['status'],after_status=v['status'],evidence=v['evidence']))
        ledger.append(dict(doc_id=did,file_name=r['source']['file_name'],format=r['source']['format'],
            vision_units=sum(u['unit_id'].startswith('vision:') for u in r['coverage']['units']),
            required_units_complete=all(u['status']=='completed' for u in r['coverage']['units'] if u['required']),
            metadata_rule_complete=True,metadata_values=sum(v['status']=='extracted' for v in m['fields'].values()),
            unresolved_fields=[k for k,v in m['fields'].items() if v['status']=='needs_review'],
            chunk_count=len(c['chunks']),bm25_indexed=True,
            llm_enrichment_full_result_reused=False,llm_summary='not_requested',
            vision_reused_from='OpenRouter Qwen3.6 + audited corrections' if any(u['unit_id'].startswith('vision:') for u in r['coverage']['units']) else None))
    ix=d.old.old.previous.build_index(d.old.old.base.build_index(chunks,ref['clients']),rules)
    d.attach_dates(ix,dates)
    ix.update(scope='bm25_indexing_only',system_terms=ref['system_terms'],claims_indexed=False,
        embedding_status='not_in_selected_scope',retrieval_and_answer_implementation=False)
    ix['config']['token_budget_status']='character_chunks_for_bm25_no_embedding'
    for doc in ix['documents'].values():
        doc['indexed_chunk_count']=doc.pop('native_chunk_count');doc['embedding_status']='not_in_selected_scope'
    # Verify serialized postings directly; this is not a retrieval benchmark.
    assert set(ix['documents'])==set(src)
    expected_ids={ch['chunk_id'] for c in chunks for ch in c['chunks']}
    assert expected_ids=={k for k,e in ix['entries'].items() if e['kind']=='native_chunk'}
    for eid,entry in ix['entries'].items():
        ts=d.old.old.previous.tokens(' '.join([entry['context_header'],entry['table_header_text'],entry['text']]),ix['clients'],ix['rules'])
        for token,n in collections.Counter(ts).items():assert ix['postings'][token][eid]==n,(eid,token)
    OUT.mkdir(parents=True)
    for name,rows in [('parsed.jsonl',src.values()),('indexing-records.jsonl',records.values()),('enriched.jsonl',enriched.values()),('chunks.jsonl',chunks),('date-metadata.jsonl',dates.values()),('source-metadata.jsonl',source_meta.values()),('document-status.jsonl',ledger)]:E.save_lines(OUT/name,rows)
    write(OUT/'index.json',ix);write(OUT/'deduplication-and-structure.json',audits);write(OUT/'metadata-changes.json',changes)
    docs=[dict(doc_id=did,source=r['source'],metadata=enriched[did]['fields'],date_metadata=dates[did]['fields'],summary=None,summary_status='optional_not_requested',chunk_ids=[c['chunk_id'] for x in chunks if x['doc_id']==did for c in x['chunks']],source_content_sha256=E.record_hash(r)) for did,r in records.items()]
    E.save_lines(OUT/'document-index.jsonl',docs)
    with (OUT/'document-status.csv').open('w',encoding='utf-8-sig',newline='') as f:
        wr=csv.DictWriter(f,fieldnames=list(ledger[0]));wr.writeheader();wr.writerows(ledger)
    counts=collections.Counter(x['kind'] for log in audits.values() for x in log)
    summary=dict(selected_scope='existing results -> reviewed literals/rule metadata/chunks/BM25, no retrieval/answer',
        documents=110,documents_with_body_chunks=sum(bool(c['chunks']) for c in chunks),vision_documents=sum(bool(r['vision_units']) for r in ledger),vision_units=sum(r['vision_units'] for r in ledger),
        rule_enriched_documents=110,llm_enriched_documents_adopted=0,llm_summaries_adopted=0,
        chunks=sum(len(c['chunks']) for c in chunks),bm25_documents=len(ix['documents']),
        metadata_values=sum(r['metadata_values'] for r in ledger),metadata_new_values=sum(x['before'] is None and x['after'] is not None for x in changes),metadata_pending_documents=sum(bool(r['unresolved_fields']) for r in ledger),
        deduplication=dict(counts),new_model_calls=0,embedding='not_in_selected_scope',
        completed_scope='BM25 indexing for 110 documents; optional semantic claims/summary are excluded',elapsed_seconds=round(time.perf_counter()-start,3))
    write(OUT/'summary.json',summary)
    assert all(E.digest(p)==h for p,h in hashes.items())
    write(OUT/'verification.json',dict(status='passed',document_inventory=110,
        common_block_validation=110,metadata_validation=110,chunk_coverage_validation=110,
        metadata_values_unchanged_by_dedup=True,original_literals_preserved_or_aliased=True,
        every_chunk_in_postings=True,postings_recomputed=True,new_model_calls=0,
        original_input_hashes=hashes,output_hashes={p.name:E.digest(p) for p in OUT.iterdir() if p.is_file()}))
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
