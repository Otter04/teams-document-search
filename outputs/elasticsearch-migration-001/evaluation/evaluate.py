"""Offline migration regression only; no user-facing search or answer service."""
import collections,hashlib,json,sys,time,urllib.request,urllib.error
from pathlib import Path
from export import ROOT,SRC,OUT,FIELDS,read,lines,sha,write,concepts,identifiers,d
import numpy as np
BASE='http://127.0.0.1:19200'
OLD=ROOT/'outputs/indexing-retrieval-eval-001'
RESULT=OUT/'evaluation'
SETTINGS={'bm25_fields':['body','context^0.3','table_header','metadata_text^0.3','title^0.5','job^4','role^4','identifier_text^3','system^0.25','client^0.25'],
 'multi_match_type':'most_fields','concept_boost':2,'identifier_boost':3,
 'document_aggregation':'maximum_scored_chunk','vector':'exact float32 flat, cosine',
 'reference_date':'2026-10-17','top_k':5,'source':'preexisting query and rule vocabulary; no gold-based tuning'}
def api(path,body):
    req=urllib.request.Request(BASE+path,data=json.dumps(body,ensure_ascii=False).encode(),headers={'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(req,timeout=120) as r:return json.load(r)
    except urllib.error.HTTPError as e:raise RuntimeError(e.read().decode()) from e
def filters(plan):
    result=[]
    for f in plan['filters']:
        key=FIELDS[f['field']];field='metadata.'+key
        result.append({'term':{'metadata_statuses.'+key:'extracted'}})
        if f['op']=='eq':result.append({'term':{field:f['value']}})
        elif f['op']=='in':result.append({'terms':{field:f['value']}})
        elif f['op'] in ['gte','lte','gt','lt']:result.append({'range':{field:{f['op']:f['value']}}})
        else:raise ValueError('Unsupported filter '+str(f))
    if plan.get('sort'):result.append({'exists':{'field':'metadata.file_modified_at'}})
    return result
def lexical(text,index):
    should=[{'multi_match':{'query':text,'fields':SETTINGS['bm25_fields'],'type':SETTINGS['multi_match_type']}}]
    should.extend({'term':{'concepts':{'value':c,'boost':SETTINGS['concept_boost']}}} for c in concepts(text,index))
    should.extend({'term':{'identifiers':{'value':c,'boost':SETTINGS['identifier_boost']}}} for c in identifiers(text))
    return {'bool':{'should':should,'minimum_should_match':1}}
def main():
    assert not (RESULT/'summary.json').exists(),'Do not overwrite a scored run'
    RESULT.mkdir(exist_ok=True)
    questions=lines(OLD/'query-inputs.jsonl');index=read(SRC/'index.json')
    qvectors=np.load(OLD/'vectors.npy',allow_pickle=False);assert qvectors.shape==(61,1024)
    assert read(OLD/'embedding-manifest.json')['model_fingerprint']==read(SRC/'embedding-manifest.json')['model_fingerprint']
    migration=read(OUT/'manifest.json')
    for rel,h in migration['source_hashes'].items():assert sha(SRC/rel)==h
    freeze={'settings':SETTINGS,'script_sha256':sha(Path(__file__)),
      'query_inputs_sha256':sha(OLD/'query-inputs.jsonl'),'query_vectors_sha256':sha(OLD/'vectors.npy'),
      'source_manifest_sha256':sha(OUT/'manifest.json'),'new_model_calls':0}
    write(RESULT/'freeze.json',freeze)
    rankings={'nori_bm25':[],'elasticsearch_vector':[]};requests=[];filterchecks=[];start=time.perf_counter()
    for i,q in enumerate(questions):
        plan=d.plan(q['query'],SETTINGS['reference_date'],index['system_terms'],index['clients'])
        fs=filters(plan)
        # Verify translated ES filters against the old metadata policy independently of labels.
        filter_response=api('/rag-documents/_search',{'size':110,'_source':['doc_id'],'query':{'bool':{'filter':fs}}})
        got={h['_id'] for h in filter_response['hits']['hits']}
        expected,_=d.apply_filters(index,plan['filters'])
        if plan.get('sort'):expected={did for did in expected if index['documents'][did]['date_metadata']['fields']['파일최종수정일']['status']=='extracted'}
        assert got==expected,(q['query_id'],got^expected)
        filterchecks.append({'query_id':q['query_id'],'eligible_docs':len(got),'matches_old_metadata_policy':True})
        if plan['requires_clarification']:
            for mode in rankings:rankings[mode].append({'query_id':q['query_id'],'query_plan':plan,'ranked':[]})
            continue
        must=[] if (plan['date_role_search'] and not plan.get('content_query')) else [lexical(plan['lexical_query'],index)]
        if plan.get('content_query'):must.append(lexical(plan['content_query'],index))
        sort=[{'_score':'desc'},{'doc_id':'asc'}]
        if plan.get('sort'):sort.insert(0,{'metadata.file_modified_at':plan['sort']['direction']})
        query={'size':110,'track_total_hits':True,'_source':['doc_id','chunk_id','source_refs'],
          'query':{'bool':{'must':must,'filter':fs}},'collapse':{'field':'doc_id'},'sort':sort}
        requests.append({'query_id':q['query_id'],'plan':plan,'request':query})
        t=time.perf_counter();res=api('/rag-chunks/_search',query);lexsec=time.perf_counter()-t
        ranks=[{'doc_id':h['_source']['doc_id'],'chunk_id':h['_source']['chunk_id'],'score':h['_score']} for h in res['hits']['hits']]
        if plan.get('requested_limit'):ranks=ranks[:plan['requested_limit']]
        rankings['nori_bm25'].append({'query_id':q['query_id'],'query_plan':plan,'ranked':ranks,'request_seconds':lexsec,'es_took_ms':res['took']})
        denseq={'size':1089,'_source':['doc_id','chunk_id'],'knn':{'field':'embedding',
          'query_vector':qvectors[i].tolist(),'k':1089,'num_candidates':1100,'filter':{'bool':{'filter':fs}}}}
        t=time.perf_counter();dense=api('/rag-chunks/_search',denseq);dense_sec=time.perf_counter()-t
        best={}
        for h in dense['hits']['hits']:
            did=h['_source']['doc_id']
            if did not in best:best[did]={'doc_id':did,'chunk_id':h['_source']['chunk_id'],'score':h['_score']*2-1}
        dense_ranks=sorted(best.values(),key=lambda r:(-r['score'],r['doc_id']))
        if plan.get('sort'):
            direction=1 if plan['sort']['direction']=='asc' else -1
            dense_ranks.sort(key=lambda r:(direction*d.ns_utc(index['documents'][r['doc_id']]['date_metadata']['fields']['파일최종수정일']['value']),-r['score'],r['doc_id']))
        if plan.get('requested_limit'):dense_ranks=dense_ranks[:plan['requested_limit']]
        rankings['elasticsearch_vector'].append({'query_id':q['query_id'],'query_plan':plan,'ranked':dense_ranks,'request_seconds':dense_sec,'es_took_ms':dense['took']})
    elapsed=time.perf_counter()-start
    for mode,rows in rankings.items():write(RESULT/f'{mode}-rankings.json',rows)
    write(RESULT/'requests.json',requests);write(RESULT/'filter-checks.json',filterchecks)
    # Only after immutable rankings are saved, load answer labels and prior scores.
    labels={r['query_id']:r for r in read(OLD/'semantic_bm25-scores.json')}
    old_dense={r['query_id']:r for r in lines(OLD/'bge_m3-rankings.jsonl')}
    vec_checks=[];scored={}
    for mode,rows in rankings.items():
        scores=[]
        for row in rows:
            ids=[r['doc_id'] for r in row['ranked']];gold=labels[row['query_id']]['answers']
            found=set(ids[:5])&set(gold);positions=[ids.index(g)+1 for g in gold if g in ids]
            first=min(positions,default=None)
            scores.append({'query_id':row['query_id'],'query':labels[row['query_id']]['query'],'answers':gold,
              'top5':ids[:5],'answer_ranks':{g:ids.index(g)+1 if g in ids else None for g in gold},
              'hit_at_5':bool(found),'recall_at_5':len(found)/len(gold),'top1':first==1,
              'previous_bm25_recall_at_5':labels[row['query_id']]['recall_at_5']})
            if mode=='elasticsearch_vector':
                old=old_dense[row['query_id']]['ranked'];previous={r['doc_id']:r['score'] for r in old}
                current={r['doc_id']:r['score'] for r in row['ranked']}
                assert set(current)==set(previous)
                err=max([abs(current[k]-previous[k]) for k in current] or [0])
                assert err<1e-5,(row['query_id'],err)
                vec_checks.append({'query_id':row['query_id'],'max_cosine_error':err,
                  'top5_same_as_prior_faiss':[r['doc_id'] for r in old[:5]]==ids[:5]})
        scored[mode]=scores;write(RESULT/f'{mode}-scores.json',scores)
    def aggregate(rows):
        return {'questions':len(rows),'hits_at_5':sum(r['hit_at_5'] for r in rows),
          'hit_at_5':sum(r['hit_at_5'] for r in rows)/len(rows),
          'mean_recall_at_5':sum(r['recall_at_5'] for r in rows)/len(rows),
          'all_gold_in_top5':sum(r['recall_at_5']==1 for r in rows),'top1':sum(r['top1'] for r in rows)}
    write(RESULT/'vector-equivalence.json',vec_checks)
    summary={'modes':{k:aggregate(v) for k,v in scored.items()},'previous_local_bm25':read(OLD/'summary.json')['modes']['semantic_bm25'],
      'elapsed_seconds':elapsed,'model_calls':0,'development_set_not_independent':True,
      'labels_loaded_after_rankings_saved':True,'metadata_filter_checks':len(filterchecks),
      'vector_score_max_error':max(r['max_cosine_error'] for r in vec_checks),
      'vector_top5_identical_questions':sum(r['top5_same_as_prior_faiss'] for r in vec_checks),
      'timing_note':'HTTP round trips through SSH included; previous in-process timings not directly comparable',
      'request_seconds':{k:sum(r.get('request_seconds',0) for r in v) for k,v in rankings.items()},
      'es_took_ms':{k:sum(r.get('es_took_ms',0) for r in v) for k,v in rankings.items()}}
    for rel,h in migration['source_hashes'].items():assert sha(SRC/rel)==h
    write(RESULT/'summary.json',summary);print(json.dumps(summary,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
