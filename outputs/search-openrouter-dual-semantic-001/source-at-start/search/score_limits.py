"""Score frozen paired results locally; all gold stays outside model requests."""
import collections,copy,csv,hashlib,json,math,statistics,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];OUT=ROOT/'outputs/search-openrouter-rerank40-001'
sys.path.insert(0,str(ROOT/'deploy/search_reranker'))
from scoring_reference import score_one,summarize,members

def read(p):return json.loads(p.read_text())
def rows(p):return [json.loads(x) for x in p.read_text().splitlines() if x]
def write(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')
def distribution(xs):
    if not xs:return {'n':0}
    xs=sorted(xs);return {'n':len(xs),'mean':statistics.mean(xs),'median':statistics.median(xs),'p95':xs[math.ceil(.95*len(xs))-1],'max':max(xs)}
def main():
    done=read(OUT/'complete.json');assert done['completed']==166
    freeze=read(OUT/'freeze.json')
    for f,h in freeze['labels_hashes'].items():assert hashlib.sha256((ROOT/f).read_bytes()).hexdigest()==h
    for f,h in freeze['source_hashes'].items():assert hashlib.sha256((ROOT/f).read_bytes()).hexdigest()==h
    pairs=rows(OUT/'pairs.jsonl');assert len(pairs)==166 and len({x['query_id'] for x in pairs})==166
    gold=rows(ROOT/'outputs/indexing-v31-001/evaluation/gold-v31.jsonl');originals={g['query_id']:g for g in gold}
    for c in read(ROOT/'outputs/search-v31-paraphrase-001/cases.json'):
        if c['category']=='원문 대조':continue
        g=copy.deepcopy(originals[c['query_id'].split('-P')[0]])
        g.update(query_id=c['query_id'],query=c['query'],origin='표현변형',test_focus=c['category'])
        g['expected_cards']=[x for x in g['expected_cards'] if x['representative']==c['expected_doc_id']]
        g['answer_doc_ids']=[c['expected_doc_id']];gold.append(g)
    gm={g['query_id']:g for g in gold};docs=read(ROOT/'outputs/search-token-nori-reranker-001/data/documents.json')
    blocks=read(ROOT/'outputs/search-token-nori-reranker-001/data/blocks.json')
    branches=['baseline100','candidate40'];by={k:{} for k in branches};scores={};summary={};metrics={};invariants=[];literal_errors=[];literal_count=0;score_deltas=[]
    for pair in pairs:
        for name in branches:
            row={k:pair[k] for k in ['query_id','query','base_date']}
            if 'error' in pair:row.update(error=pair['error'],client_seconds=pair['client_pair_seconds'])
            else:
                r=pair['response'][name];row.update(response=r,client_seconds=r['timings']['equivalent_total_seconds'],timing_basis='common measured stages + own rerank/group')
            by[name][pair['query_id']]=row
        if 'response' not in pair:continue
        a=pair['response']['baseline100'];b=pair['response']['candidate40'];ad=a.get('diagnostics',{});bd=b.get('diagnostics',{})
        if a['query_plan']!=b['query_plan']:invariants.append([pair['query_id'],'query_plan'])
        for key in ['bm25','vector','candidate_fingerprint','filter_clauses']:
            if ad.get(key)!=bd.get(key):invariants.append([pair['query_id'],key])
        if not pair['response']['reranker_cap_not_applicable'] and ad['rerank_candidates'][:40]!=bd['rerank_candidates']:invariants.append([pair['query_id'],'top40'])
        ar={x['chunk_id']:x['score'] for x in ad.get('ranked_all',[])}
        for x in bd.get('ranked_all',[]):
            if x['chunk_id'] in ar:score_deltas.append(abs(ar[x['chunk_id']]-x['score']))
        for r in [a,b]:
            d=r.get('diagnostics',{}).get('reranking',{})
            if d.get('r1_executed') or d.get('truncated_pairs') or d.get('fallback'):invariants.append([pair['query_id'],'model_policy'])
            for c in r.get('results',[]):
                for ex in c.get('excerpts',[]):
                    literal_count+=1;source=blocks[c['doc_id']][ex['block_id']]
                    if source['text'][ex['start']:ex['end']]!=ex['text'] or source['loc']!=ex['loc']:literal_errors.append([pair['query_id'],c['doc_id'],ex['block_id']])
    for name in branches:
        rs=list(by[name].values());scores[name]=[score_one(g,by[name][g['query_id']],docs) for g in gold]
        summary[name]={label:summarize(scores[name][a:b]) for label,a,b in [('all166',0,166),('original150',0,150),('variants16',150,166),('old125',0,125),('new25',125,150)]}
        applied=[r for r in rs if r.get('response',{}).get('diagnostics',{}).get('reranking',{}).get('status')=='applied']
        metrics[name]={'equivalent_total':distribution([r['client_seconds'] for r in rs if 'response' in r]),
          'rerank_applied':distribution([r['response']['timings']['rerank_seconds'] for r in applied]),
          'actual_pairs':distribution([r['response']['diagnostics']['reranking']['pairs'] for r in applied]),
          'common':distribution([r['response']['timings']['common_seconds'] for r in rs if 'response' in r]),
          'applied_requests':len(applied),'total_model_pairs':sum(r['response']['diagnostics']['reranking']['pairs'] for r in applied)}
        eligible=[];found=0;total=0;allfound=0
        for row in applied:
            q=row['query_id'];req=[c for c in gm[q]['expected_cards'] if c['priority']=='필수'];ids={c['doc_id'] for c in row['response']['diagnostics']['rerank_candidates']}
            hit=sum(c['representative'] in ids for c in req);found+=hit;total+=len(req);allfound+=hit==len(req)
            eligible.append(q)
        metrics[name]['required_candidates']={'queries':len(eligible),'all_required_present':allfound,'required_documents':total,'present':found,'recall':found/total if total else None}
        counts=[collections.Counter(c['doc_id'] for c in r['response']['diagnostics']['rerank_candidates']) for r in applied]
        metrics[name]['unique_candidate_documents']=distribution([len(c) for c in counts])
        metrics[name]['largest_document_chunk_share']=distribution([max(c.values())/sum(c.values()) for c in counts if c])
        folder=OUT/name;folder.mkdir(exist_ok=True)
        (folder/'responses.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rs))
        write(folder/'scores.json',scores[name]);write(folder/'complete.json',{'completed':166});write(folder/'summary.json',summary[name])
    a={s['query_id']:s for s in scores['baseline100']};b={s['query_id']:s for s in scores['candidate40']}
    success=lambda s:s['all_required_representatives_found']
    improved=[q for q in a if not success(a[q]) and success(b[q])];regressed=[q for q in a if success(a[q]) and not success(b[q])]
    details=[]
    for pair in pairs:
        q=pair['query_id'];r=pair.get('response',{});base=r.get('baseline100',{});cand=r.get('candidate40',{})
        req=[x['representative'] for x in gm[q]['expected_cards'] if x['priority']=='필수'];bc=base.get('diagnostics',{}).get('rerank_candidates',[]);cc=cand.get('diagnostics',{}).get('rerank_candidates',[])
        detail={'query_id':q,'query':pair['query'],'rewritten':base.get('query_plan',{}).get('semantic'),'llm_status':base.get('query_plan',{}).get('llm',{}).get('status'),
          'baseline_success':success(a[q]),'candidate_success':success(b[q]),'lost_required_candidates':[d for d in req if d in {x['doc_id'] for x in bc} and d not in {x['doc_id'] for x in cc}],
          'required':[{ 'doc_id':d,'title':docs[d]['file_name'],
            'rrf_rank':next((i+1 for i,c in enumerate(bc) if c['doc_id']==d),None),
            'final100_rank':next((i+1 for i,c in enumerate(base.get('results',[])) if c['doc_id']==d),None),
            'final40_rank':next((i+1 for i,c in enumerate(cand.get('results',[])) if c['doc_id']==d),None)} for d in req],
          'top100':[x['doc_id'] for x in base.get('results',[])],'top40':[x['doc_id'] for x in cand.get('results',[])],
          'rerank100_seconds':base.get('timings',{}).get('rerank_seconds'),'rerank40_seconds':cand.get('timings',{}).get('rerank_seconds'),
          'total100_seconds':base.get('timings',{}).get('equivalent_total_seconds'),'total40_seconds':cand.get('timings',{}).get('equivalent_total_seconds')}
        details.append(detail)
    llms=[p['response']['baseline100']['query_plan']['llm'] for p in pairs if 'response' in p]
    result={'summary':summary,'metrics':metrics,'improvements':improved,'regressions':regressed,'errors':[p['query_id'] for p in pairs if 'error' in p],
      'invariant_violations':invariants,'literal_checks':literal_count,'literal_errors':literal_errors,'common_score_absolute_delta':distribution(score_deltas),
      'question_analysis':{'statuses':dict(collections.Counter(l['status'] for l in llms)),
        'errors':dict(collections.Counter(l.get('error') for l in llms if l.get('error'))),
        'providers':dict(collections.Counter(l.get('provider','unknown') for l in llms)),
        'seconds':distribution([l['elapsed_seconds'] for l in llms]),
        'api_reported_cost_usd':sum(l.get('usage',{}).get('cost') or 0 for l in llms),'missing_cost_records':sum(l.get('usage',{}).get('cost') is None for l in llms),
        'prompt_tokens':sum(l.get('usage',{}).get('prompt_tokens',0) for l in llms),'completion_tokens':sum(l.get('usage',{}).get('completion_tokens',0) for l in llms)},
      'changed_top5_questions':sum(d['top100']!=d['top40'] for d in details),
      'cap_affected_questions':sum(len(p.get('response',{}).get('baseline100',{}).get('diagnostics',{}).get('rerank_candidates',[]))>40 and not p.get('response',{}).get('reranker_cap_not_applicable',True) for p in pairs),
      'details':details,'paired_request_wall':distribution([p['client_pair_seconds'] for p in pairs])}
    for name in branches:
        accepted=[s for s in scores[name] if s['query_plan'].get('llm',{}).get('status')=='rewritten']
        fallback=[s for s in scores[name] if s['query_plan'].get('llm',{}).get('status')=='rewrite_fallback']
        result['summary'][name]['rewritten_only']=summarize(accepted) if accepted else None
        result['summary'][name]['fallback_only']=summarize(fallback) if fallback else None
    write(OUT/'comparison.json',result)
    with (OUT/'question-comparison.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f);w.writerow(['질문ID','원문','재작성','Qwen 상태','100 성공','40 성공','100 최종문서','40 최종문서','탈락 정답 후보','100 리랭킹 초','40 리랭킹 초','100 단계합 초','40 단계합 초'])
        for d in details:w.writerow([d[k] if not isinstance(d[k],list) else ', '.join(d[k]) for k in ['query_id','query','rewritten','llm_status','baseline_success','candidate_success','top100','top40','lost_required_candidates','rerank100_seconds','rerank40_seconds','total100_seconds','total40_seconds']])
    print(json.dumps({k:result[k] for k in ['summary','metrics','improvements','regressions','errors','question_analysis','cap_affected_questions']},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
