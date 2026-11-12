"""Offline fusion of frozen keyword50 and OpenRouter-embedded semantic50.

Only weights 1:1.5 and 1:2, RRF constant60. No network/API/model dependencies.
Gold is used after fusion for evidence-level scoring, never in ranking.
"""
import copy
import csv
import hashlib
import json
import math
import statistics
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'outputs/search-fusion-fixed50-001'
KEYWORD=ROOT/'outputs/search-context-filename-001'
SEMANTIC=ROOT/'outputs/search-openrouter-dual-semantic-001'
DATA=ROOT/'outputs/search-token-nori-reranker-001/data'
WEIGHTS=(1.5,2.0)
CONSTANT=60

def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(name,obj):
    p=OUT/name;p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('x') as f:json.dump(obj,f,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n')
def unit(v):
    assert len(v)==1024 and all(math.isfinite(x) for x in v)
    norm=math.sqrt(math.fsum(x*x for x in v));assert norm>0
    return [x/norm for x in v]
def fuse(keyword,semantic,weight):
    assert weight in WEIGHTS
    merged={}
    for name,hits,w in [('keyword',keyword,1.0),('semantic',semantic,weight)]:
        assert len(hits)<=50 and len({h['chunk_id'] for h in hits})==len(hits)
        for rank,h in enumerate(hits,1):
            row=merged.setdefault(h['chunk_id'],dict(chunk_id=h['chunk_id'],doc_id=h['doc_id'],score=0.0,branches={}))
            assert row['doc_id']==h['doc_id']
            row['score']+=w/(CONSTANT+rank)
            row['branches'][name]=dict(rank=rank,original_score=h['score'])
    return sorted(merged.values(),key=lambda r:(-r['score'],r['chunk_id']))
def anchors(hits,label):
    ranks={h['chunk_id']:i+1 for i,h in enumerate(hits)}
    return [min((ranks[cid] for cid in ids if cid in ranks),default=None)
            for card in label['cards'] for ids in card['anchor_groups']]
def measure(hits,label):
    ar=anchors(hits,label)
    complete=max(ar) if ar and all(r is not None for r in ar) else None
    return dict(anchor_ranks=ar,complete_rank=complete,
        at={str(k):complete is not None and complete<=k for k in (10,20,40,50)},
        found50=complete is not None and complete<=50)
def aggregate(rows):
    found=[r['complete_rank'] for r in rows if r['found50']]
    return dict(n=len(rows),at={str(k):sum(r['at'][str(k)] for r in rows) for k in (10,20,40,50)},
        mean_found50=statistics.mean(found) if found else None,missing50=len(rows)-len(found),found50=len(found))

def main():
    OUT.mkdir(exist_ok=True)
    assert not (OUT/'manifest.json').exists(),'Preserve existing experiment; no automatic overwrite'
    qs=read(SEMANTIC/'inputs.json');previous=read(ROOT/'outputs/search-branch-eval-001/inputs.json')
    assert [(q['query_id'],q['query']) for q in qs]==[(q['query_id'],q['query']) for q in previous]
    labels=read(SEMANTIC/'labels.json');assert labels==read(ROOT/'outputs/search-branch-eval-001/labels.json')
    labels={q['query_id']:q for q in labels};assert len(qs)==82
    manifest=read(SEMANTIC/'manifest.json')
    assert read(SEMANTIC/'complete.json')['only_openrouter']
    assert manifest['embedding']['endpoint']=='https://openrouter.ai/api/v1/embeddings'
    assert manifest['embedding']['model']=='baai/bge-m3'
    assert manifest['weights']==[.5,.5] and manifest['retrieved_k']==50
    frozen={}
    for folder in (KEYWORD,SEMANTIC):
        for p in folder.rglob('*'):
            if p.is_file():frozen[str(p.relative_to(ROOT))]=sha(p)
    for folder in (ROOT/'deploy/search_openrouter',ROOT/'deploy/search_weighted_rrf'):
        for p in folder.glob('*.py'):frozen[str(p.relative_to(ROOT))]=sha(p)
    for p in (DATA/'chunks.ndjson',DATA/'documents.json',ROOT/'outputs/search-branch-eval-001/inputs.json',ROOT/'outputs/search-branch-eval-001/labels.json'):
        frozen[str(p.relative_to(ROOT))]=sha(p)
    assert sha(DATA/'chunks.ndjson')==manifest['sources'][str((DATA/'chunks.ndjson').relative_to(ROOT))]
    assert sha(DATA/'chunks.ndjson')==read(KEYWORD/'manifest.json')['input_hashes'][str((DATA/'chunks.ndjson').relative_to(ROOT))]
    chunks={}
    with (DATA/'chunks.ndjson').open() as f:
        for action in f:
            cid=json.loads(action)['create']['_id'];r=json.loads(next(f));chunks[cid]={k:r[k] for k in ('doc_id','file_name','context','body','source_refs')}
    assert len(chunks)==3022
    save('manifest.json',dict(date='2026-11-04',questions=82,weights=list(WEIGHTS),rrf_constant=CONSTANT,
        candidate_cap_per_branch=50,keyword_run=str(KEYWORD.relative_to(ROOT)),keyword_condition='m20-context_double-remove',
        semantic_run=str(SEMANTIC.relative_to(ROOT)),semantic_condition='schema',
        embedding_endpoint=manifest['embedding']['endpoint'],embedding_model=manifest['embedding']['model'],embedding_provider='DeepInfra',
        reuse='Saved OpenRouter Qwen + OpenRouter embeddings + semantic ranks; no new calls',
        criterion='all anchor groups of every required card in top20; found mean and missing use top50',
        scope='Full chunk-id union, no post-fusion document cap, no document grouping, no reranker',
        input_hashes=frozen))
    records=[];evidence=[];provenance=[];timings=[]
    for q in qs:
        qid=q['query_id'];label=labels[qid]
        k=read(KEYWORD/f'requests/{qid}/m20-context_double-remove.json')
        s=read(SEMANTIC/f'requests/{qid}/schema/result.json')
        e=read(SEMANTIC/f'requests/{qid}/schema/embedding.json')
        rw=read(SEMANTIC/f'requests/{qid}/schema/rewrite.json')
        assert q['query']==s['query']==k['query']
        assert k['request']['query']['bool']['filter'][:-1]==s['filters']
        assert e['endpoint']=='https://openrouter.ai/api/v1/embeddings' and e['http_status']==200 and not e.get('error')
        assert e['request']['model']=='baai/bge-m3' and e['request']['provider']==dict(order=['DeepInfra'],allow_fallbacks=False)
        assert e['response']['provider']=='DeepInfra' and e['request']['input']==s['rewrite']['texts']
        assert rw['endpoint']=='https://openrouter.ai/api/v1/chat/completions'
        assert rw['request']['response_format']['type']=='json_schema'
        vectors=[unit(d['embedding']) for d in sorted(e['response']['data'],key=lambda d:d['index'])]
        assert len(vectors)==2
        for v,key in zip(vectors,('A','B')):assert max(abs(a-b) for a,b in zip(v,s['vectors'][key]))<1e-12
        mixed=unit([.5*a+.5*b for a,b in zip(*vectors)])
        assert max(abs(a-b) for a,b in zip(mixed,s['vectors']['mixed']))<1e-12
        for h in k['hits']+s['hits']:assert chunks[h['chunk_id']]['doc_id']==h['doc_id']
        provenance.append(dict(query_id=qid,embedding_endpoint=e['endpoint'],provider=e['response']['provider'],
            request_vector_matches=True,filters_identical=True,source_rewrite_status=s['rewrite']['status']))
        fused={}
        for weight in WEIGHTS:
            t=time.perf_counter();hits=fuse(k['hits'],s['hits'],weight);timings.append(time.perf_counter()-t)
            for h in hits:h['file_name']=chunks[h['chunk_id']]['file_name']
            fused[str(weight)]=hits
            save(f'rankings/{qid}/weight-{weight}.json',dict(query_id=qid,query=q['query'],weight=weight,
                 keyword_hits=k['hits'],semantic_hits=s['hits'],hits=hits))
        union_ids={h['chunk_id'] for h in k['hits']+s['hits']}
        assert all(set(h['chunk_id'] for h in hits)==union_ids for hits in fused.values())
        metrics={'keyword':measure(k['hits'],label),'semantic':measure(s['hits'],label)}
        metrics.update({w:measure(hits,label) for w,hits in fused.items()})
        assert metrics['semantic']['complete_rank']==s['metric']['complete_rank']
        union_available=all(any(cid in union_ids for cid in ids) for card in label['cards'] for ids in card['anchor_groups'])
        records.append(dict(query_id=qid,query=q['query'],blocked_in_service=q['blocked_in_service'],union_count=len(union_ids),
            union_all_evidence=union_available,metrics=metrics))
        i=0
        for card_index,card in enumerate(label['cards']):
            for anchor_index,ids in enumerate(card['anchor_groups']):
                ranks={name:m['anchor_ranks'][i] for name,m in metrics.items()};i+=1
                source='both' if ranks['keyword'] and ranks['semantic'] else 'keyword_only' if ranks['keyword'] else 'semantic_only' if ranks['semantic'] else 'neither'
                examples=[dict(chunk_id=cid,**chunks[cid]) for cid in ids if cid in union_ids]
                evidence.append(dict(query_id=qid,query=q['query'],blocked_in_service=q['blocked_in_service'],card=card_index,anchor=anchor_index,
                    representative=card['representative'],evidence_ids=ids,origin=source,ranks=ranks,examples=examples))
    summaries={}
    for key in ('keyword','semantic','1.5','2.0'):
        summaries[key]={group:aggregate([r['metrics'][key] for r in records if group=='all82' or r['blocked_in_service']==(group=='blocked8')])
                        for group in ('all82','service74','blocked8')}
    assert summaries['keyword']['all82']['at']['20']==54 and summaries['keyword']['all82']['at']['50']==63
    assert summaries['semantic']['all82']['at']['20']==68 and summaries['semantic']['all82']['at']['50']==79
    diagnostics={}
    for origin in ('keyword_only','semantic_only','both','neither'):
        part=[e for e in evidence if e['origin']==origin]
        diagnostics[origin]=dict(anchor_groups=len(part),by_weight={})
        for w in ('1.5','2.0'):
            diagnostics[origin]['by_weight'][w]={str(cut):sum(e['ranks'][w] is not None and e['ranks'][w]<=cut for e in part) for cut in (20,40,50)}
        diagnostics[origin]['promoted_1_5_to_2']=[dict(query_id=e['query_id'],card=e['card'],anchor=e['anchor'],ranks=e['ranks']) for e in part if e['ranks']['1.5'] and e['ranks']['2.0']<e['ranks']['1.5']]
        diagnostics[origin]['demoted_1_5_to_2']=[dict(query_id=e['query_id'],card=e['card'],anchor=e['anchor'],ranks=e['ranks']) for e in part if e['ranks']['1.5'] and e['ranks']['2.0']>e['ranks']['1.5']]
    transitions={}
    for a,z in [('keyword','1.5'),('semantic','1.5'),('keyword','2.0'),('semantic','2.0'),('1.5','2.0')]:
        transitions[a+'->'+z]={kind:[dict(query_id=r['query_id'],query=r['query'],blocked_in_service=r['blocked_in_service'],before=r['metrics'][a]['complete_rank'],after=r['metrics'][z]['complete_rank']) for r in records if fn(r['metrics'][a]['at']['20'],r['metrics'][z]['at']['20'])]
            for kind,fn in [('improved',lambda x,y:not x and y),('regressed',lambda x,y:x and not y)]}
    save('records.json',records);save('evidence-diagnostics.json',evidence);save('api-provenance.json',provenance)
    save('comparison.json',dict(summaries=summaries,union_all_evidence=sum(r['union_all_evidence'] for r in records),
        union_missing=[r['query_id'] for r in records if not r['union_all_evidence']],diagnostics=diagnostics,transitions=transitions,
        fusion_compute_mean_ms=statistics.mean(timings)*1000,timing_scope='offline fusion only; not end-to-end search'))
    with (OUT/'query-ranks.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.writer(f);writer.writerow(['query_id','query','blocked_in_service','union_all_evidence','keyword_rank','semantic_rank','rrf_1_5_rank','rrf_2_rank','rrf_1_5_top20','rrf_2_top20'])
        for r in records:writer.writerow([r['query_id'],r['query'],r['blocked_in_service'],r['union_all_evidence']]+[r['metrics'][key]['complete_rank'] for key in ('keyword','semantic','1.5','2.0')]+[r['metrics'][w]['at']['20'] for w in ('1.5','2.0')])
    with (OUT/'evidence-movement.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.writer(f);writer.writerow(['query_id','card','anchor','origin','keyword_rank','semantic_rank','rrf_1_5_rank','rrf_2_rank','rrf_1_5_top20','rrf_2_top20'])
        for e in evidence:writer.writerow([e['query_id'],e['card'],e['anchor'],e['origin']]+[e['ranks'][k] for k in ('keyword','semantic','1.5','2.0')]+[e['ranks'][w] is not None and e['ranks'][w]<=20 for w in ('1.5','2.0')])
    assert all(sha(ROOT/p)==h for p,h in frozen.items())
    save('complete.json',dict(queries=82,fused_rankings=164,weights=list(WEIGHTS),new_model_calls=0,new_search_calls=0,
        reused_openrouter_query_embedding_batches=len(provenance),all_vectors_verified=True,all_filters_equal=True,
        frozen_inputs_preserved=True,service_changed=False))
    print(json.dumps(dict(summaries=summaries,union_all_evidence=sum(r['union_all_evidence'] for r in records),
        origin_counts={k:v['anchor_groups'] for k,v in diagnostics.items()},transitions=transitions['1.5->2.0']),ensure_ascii=False,indent=2))

if __name__=='__main__':main()
