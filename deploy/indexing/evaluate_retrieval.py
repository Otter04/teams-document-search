"""Offline document-retrieval regression. No answer generation or service endpoint."""
from collections import defaultdict
import copy,csv,json,math,sys,time
from pathlib import Path
import numpy as np
import faiss
from prepare import ROOT,read,lines,digest,write,save_lines
sys.path.insert(0,str(ROOT/'deploy/rag_app'))
from runtime import E,d

OUT=ROOT/'outputs/indexing-retrieval-eval-001'
INDEX=ROOT/'outputs/indexing-110-semantic-vector-001'

def prepare_view(folder):
    index=read(folder/'index.json')
    for doc in index['documents'].values():doc['native_chunk_count']=doc['indexed_chunk_count']
    parsed={r['doc_id']:r for r in lines(folder/'indexing-records.jsonl')}
    metadata={r['doc_id']:r for r in lines(folder/'enriched.jsonl')}
    for r in parsed.values():E.previous.APPROVED_RECORD_HASHES.add(E.record_hash(r))
    bundle=d.old.prepare(index,parsed,metadata)
    view=d.old.view(index,bundle,context=True,intents=True)
    return view,bundle,d.old.field_statistics(view,bundle,True)

def main():
    assert not (OUT/'summary.json').exists(),'Never overwrite a scored evaluation'
    frozen=read(OUT/'freeze.json');as_of=frozen['reference_date']
    for rel,h in frozen['index_artifact_hashes'].items():assert digest(INDEX/rel)==h,rel
    questions=lines(OUT/'query-inputs.jsonl')
    assert digest(OUT/'query-inputs.jsonl')==frozen['query_inputs_sha256']
    qmeta=read(OUT/'embedding-manifest.json');docmeta=read(INDEX/'embedding-manifest.json')
    assert qmeta['model_fingerprint']==docmeta['model_fingerprint']
    assert qmeta['pooling']==docmeta['pooling'] and qmeta['normalization']==docmeta['normalization']
    assert digest(OUT/'vectors.npy')==qmeta['vectors_sha256']
    query_vectors=np.load(OUT/'vectors.npy',allow_pickle=False);assert query_vectors.shape==(61,1024)
    assert np.isfinite(query_vectors).all() and np.allclose(np.linalg.norm(query_vectors,axis=1),1,atol=1e-5)
    mappings=lines(INDEX/'vector-map.jsonl');by_vector={r['vector_id']:r for r in mappings}
    vindex=faiss.read_index(str(INDEX/'vectors.faiss'));assert vindex.ntotal==1089
    new,bundle,stats=prepare_view(INDEX)
    pre,pbundle,pstats=prepare_view(ROOT/'outputs/indexing-110-bm25-001')
    # Preload lazy date parsers, then disallow file/network access while ranking.
    d.plan('2025년 수정된 문서',as_of,new['system_terms'],new['clients']);E.timestamp('2000-01-01 00:00:00')
    guard={'active':True,'attempts':0}
    def audit(event,args):
        if guard['active'] and event in ('open','socket.connect','socket.getaddrinfo','subprocess.Popen','os.system'):
            guard['attempts']+=1;raise RuntimeError('IO forbidden during retrieval: '+event)
    sys.addaudithook(audit)
    start=time.perf_counter()
    scores,ids=vindex.search(np.ascontiguousarray(query_vectors,dtype=np.float32),vindex.ntotal)
    assert scores.shape==(61,1089) and all(len(set(row.tolist()))==1089 for row in ids)
    results={k:[] for k in ['reviewed_vision_bm25','semantic_bm25','bge_m3','hybrid_rrf']}
    for i,q in enumerate(questions):
        lexical=d.search(new,bundle,q['query'],as_of,new['system_terms'],limit=100,statistics=stats)
        prelex=d.search(pre,pbundle,q['query'],as_of,pre['system_terms'],limit=100,statistics=pstats)
        def compact(result):return {'query_id':q['query_id'],'query':q['query'],'query_plan':result['query_plan'],'status':result['status'],'ranked':[{'doc_id':r['doc_id'],'score':r['score'],'evidence':[{k:e[k] for k in ['entry_id','score','source_refs']} for e in r['evidence']]} for r in result['results']]}
        results['semantic_bm25'].append(compact(lexical));results['reviewed_vision_bm25'].append(compact(prelex))
        plan=lexical['query_plan'];allowed,unknown=d.apply_filters(new,plan['filters'])
        if plan['requires_clarification']:allowed=set()
        if plan['sort']:
            allowed={did for did in allowed if new['documents'][did]['date_metadata']['fields']['파일최종수정일']['status']=='extracted'}
        bydoc=defaultdict(list)
        for value,vid in zip(scores[i],ids[i]):
            mapping=by_vector[int(vid)];did=mapping['doc_id']
            if did in allowed:bydoc[did].append({'entry_id':mapping['chunk_id'],'score':float(value),'source_refs':mapping['source_refs']})
        dense=[{'doc_id':did,'score':ev[0]['score'],'evidence':ev[:3]} for did,ev in bydoc.items()]
        def sort(ranking):
            if plan['sort']:
                direction=1 if plan['sort']['direction']=='asc' else -1
                ranking.sort(key=lambda r:(direction*d.ns_utc(new['documents'][r['doc_id']]['date_metadata']['fields']['파일최종수정일']['value']),-r['score'],r['doc_id']))
            else:ranking.sort(key=lambda r:(-r['score'],r['doc_id']))
            return ranking
        dense=sort(dense)
        lr={r['doc_id']:rank for rank,r in enumerate(lexical['results'],1)};dr={r['doc_id']:rank for rank,r in enumerate(dense,1)}
        densemap={r['doc_id']:r for r in dense}
        fused=[]
        for did in set(lr)|set(dr):
            score=sum(1/(frozen['settings']['rrf_k']+ranks[did]) for ranks in [lr,dr] if did in ranks)
            fused.append({'doc_id':did,'score':score,'bm25_rank':lr.get(did),'vector_rank':dr.get(did),'evidence':densemap.get(did,{}).get('evidence',[])})
        fused=sort(fused)
        for name,ranking in [('bge_m3',dense),('hybrid_rrf',fused)]:
            if plan.get('requested_limit'):ranking=ranking[:plan['requested_limit']]
            results[name].append({'query_id':q['query_id'],'query':q['query'],'query_plan':plan,'status':lexical['status'],'ranked':ranking,'unresolved_filter_documents':sorted(unknown)})
        for name in results:
            assert all(r['doc_id'] in allowed for r in results[name][-1]['ranked'])
    elapsed=time.perf_counter()-start;guard['active']=False
    # Freeze rankings on disk before reading answer labels.
    for name,rows in results.items():save_lines(OUT/f'{name}-rankings.jsonl',rows)
    ranking_hashes={name:digest(OUT/f'{name}-rankings.jsonl') for name in results}
    base=ROOT/frozen['baseline']
    for name,h in frozen['baseline_hashes'].items():assert digest(base/name)==h
    labels={r['query_id']:r for r in read(base/'query-results.json')}
    for path,h in frozen['source_gold_hashes'].items():
        assert digest(path)==h
        original_gold=lines(path)
    assert set(labels)=={q['query_id'] for q in questions}
    # Source-label identity verification is evaluation-only, after rankings are fixed.
    write(OUT/'source-gold-schema.json',{'count':len(original_gold),'first_record_keys':list(original_gold[0])})
    def metric(ids,answers):
        ids=ids[:10];positions=[i for i,did in enumerate(ids,1) if did in answers];first=min(positions,default=0)
        return {'hit_at_5':int(0<first<=5),'recall_at_5':len(set(ids[:5])&set(answers))/len(set(answers)),'rr_at_10':1/first if first else 0,'first_rank':first}
    def aggregate(rows):
        n=len(rows)
        return {'questions':n,'hits_at_5':sum(r['hit_at_5'] for r in rows),'hit_at_5':sum(r['hit_at_5'] for r in rows)/n,'mean_recall_at_5':sum(r['recall_at_5'] for r in rows)/n,'mrr_at_10':sum(r['rr_at_10'] for r in rows)/n,'all_gold_in_top5':sum(r['recall_at_5']==1 for r in rows),'top1':sum(r['first_rank']==1 for r in rows),'hit_goal_90pct':sum(r['hit_at_5'] for r in rows)/n>=.9,'recall_goal_90pct':sum(r['recall_at_5'] for r in rows)/n>=.9}
    scored={}
    for mode,rows in results.items():
        scored[mode]=[]
        for row in rows:
            label=labels[row['query_id']];ranking=[r['doc_id'] for r in row['ranked']];answers=label['answers']
            scored[mode].append({'query_id':row['query_id'],'query':row['query'],'answers':answers,'top5':ranking[:5],'top10':ranking[:10],**metric(ranking,answers),'answer_ranks':{a:ranking.index(a)+1 if a in ranking else None for a in answers}})
    old=[]
    for r in labels.values():old.append({**r,**metric(r['doc_ids'],r['answers'])})
    summary={'reference_date':as_of,'questions':61,'documents':110,'baseline':aggregate(old),'modes':{k:aggregate(v) for k,v in scored.items()},'retrieval_seconds':elapsed,'query_embedding_seconds':qmeta['elapsed_seconds'],'document_vectors_reused':1089,'new_query_vectors':61,'new_enrichment_or_answer_calls':0,'paid_api_calls':0,'development_set_not_independent':True,'ranking_parameters_tuned':False,'gold_labels_loaded_after_rankings_written':True,'io_guard_blocked_attempts':guard['attempts']}
    oldmap={r['query_id']:r for r in old};changes=[]
    for mode,rows in scored.items():
        for r in rows:
            prev=oldmap[r['query_id']]
            changes.append({'mode':mode,'query_id':r['query_id'],'query':r['query'],'answers':r['answers'],'previous_hit_at_5':prev['hit_at_5'],'hit_at_5':r['hit_at_5'],'previous_recall_at_5':prev['recall_at_5'],'recall_at_5':r['recall_at_5'],'previous_answer_ranks':prev['answer_ranks'],'answer_ranks':r['answer_ranks'],'top5':r['top5']})
    for mode,rows in scored.items():write(OUT/f'{mode}-scores.json',rows)
    write(OUT/'changes.json',changes);write(OUT/'summary.json',summary)
    with (OUT/'query-comparison.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(changes[0]));writer.writeheader();writer.writerows(changes)
    for rel,h in frozen['index_artifact_hashes'].items():assert digest(INDEX/rel)==h,rel
    write(OUT/'verification.json',{'index_artifacts_unchanged':True,'source_gold_unchanged':True,'ranking_hashes_before_scoring':ranking_hashes,'model_fingerprint_identical':True,'no_source_answers_in_query_embedding':True,'retrieval_io_guard':True,'blocked_io_attempts':guard['attempts'],'script_sha256':digest(Path(__file__)),'runtime_helpers':{str(p):digest(p) for p in [ROOT/'deploy/rag_app/runtime.py',ROOT/'outputs/rag-date-search-v2/date_search.py',ROOT/'outputs/rag-field-search-v1/field_search.py']},'production_search_or_answer_implemented':False})
    print(json.dumps(summary,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
