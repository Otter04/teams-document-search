"""Elasticsearch search, chunk RRF, document/version grouping and source excerpts."""
import collections, copy, json, math, re, time, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from query import plan_rules, conditional_llm, apply_mode, es_filters, words, normal
from content import network_diagrams

CONFIG={'version':'search-1.3.1','llm_budget_seconds':2.5,'lexical_k':50,'vector_k':50,'num_candidates':200,
 'rrf_k':60,'rerank_k':100,'result_documents':5,'bm25_fields':['file_name^2','context^1.5','table_header^1.5','body'],
 'minimum_should_match':'50%','additional_chunk_weight':0.1,'max_additional_chunks':3,'support_pool_k':30,
 'r1_weights':{'rrf':0.45,'lexical_overlap':0.20,'cosine':0.20,'literal_phrase':0.05,'identifier':0.05,'metadata':0.05},
 'query_cache':False,'operating_query_logs':False,'exact_2a':False}

def http(base,path,body=None,timeout=15):
    req=urllib.request.Request(base+path,data=json.dumps(body,ensure_ascii=False).encode() if body is not None else None,
      headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=timeout) as r:return json.load(r)

def lexical(p):
    if not p['keywords'].strip():return {'match_all':{}}
    should=[{'multi_match':{'query':p['keywords'],'fields':CONFIG['bm25_fields'],
      'type':'most_fields','minimum_should_match':CONFIG['minimum_should_match']}}]
    # Keep the previously reviewed bilingual operations vocabulary.
    should.extend({'term':{'concepts':{'value':c,'boost':1.0}}} for c in p['concepts'])
    if p.get('lexical_expansions'):
        # All recognized concepts must occur; alternatives within each are OR-ed.
        # This gives English logs and diagram labels a route into the BM25 candidates.
        should.append({'bool':{'must':[{'bool':{'should':[
          {'multi_match':{'query':a,'fields':CONFIG['bm25_fields'],'type':'phrase'}}
          for a in expansion['alternatives']], 'minimum_should_match':1}}
          for expansion in p['lexical_expansions']]}})
    return {'bool':{'should':should,'minimum_should_match':1}}

def rrf(bm,vec):
    merged={}
    for name,hits in [('bm25',bm),('vector',vec)]:
        for rank,h in enumerate(hits,1):
            r=merged.setdefault(h['_id'],{'chunk_id':h['_id'],'source':h['_source'],'rrf_score':0,'branches':{}})
            r['rrf_score']+=1/(CONFIG['rrf_k']+rank)
            r['branches'][name]={'rank':rank,'score':h['_score']}
    return sorted(merged.values(),key=lambda r:(-r['rrf_score'],r['chunk_id']))

def condition_matches(metadata,key,value):
    actual=metadata.get(key)
    if actual is None:return False
    if not isinstance(value,dict):return actual==value
    # Calendar metadata is ISO formatted. File timestamps need timezone-aware comparisons.
    def canonical(v):
        if key!='file_modified_at':return v
        from datetime import datetime
        return datetime.fromisoformat(v.replace('Z','+00:00')).timestamp()
    a=canonical(actual)
    return all({'gte':a>=canonical(v),'lte':a<=canonical(v),'gt':a>canonical(v),'lt':a<canonical(v)}[op] for op,v in value.items())

def soft_score(p,s):
    values=[condition_matches(s['metadata'],k,v) for k,v in p['soft_conditions'].items()]
    if p['boost'].get('latest_version'):values.append(s['latest_version'])
    return sum(values)/len(values) if values else 0

def lexical_preferences(p):
    clauses=[]
    for key,value in p['soft_conditions'].items():
        condition={'range':{'metadata.'+key:value}} if isinstance(value,dict) else {'term':{'metadata.'+key:value}}
        clauses.append({'constant_score':{'filter':{'bool':{'filter':[
          {'term':{'metadata_statuses.'+key:'extracted'}},condition]}},'boost':1.0}})
    if p['boost'].get('latest_version'):clauses.append({'constant_score':{'filter':{'term':{'latest_version':True}},'boost':1.0}})
    return clauses

def rerank(rows,p,mode,query_vector=None):
    selected=copy.deepcopy(rows[:CONFIG['rerank_k']]);maximum=selected[0]['rrf_score'] if selected else 1
    terms=words(p['keywords'])
    for rank,r in enumerate(selected,1):
        # Wider recall must not also widen the multi-chunk bonus pool: otherwise
        # long documents gain merely from more weak supporting chunks being admitted.
        # Every candidate can still compete as its document's highest-scoring chunk.
        r['support_eligible']=rank<=CONFIG['support_pool_k']
        s=r['source'];title=normal(s['file_name']);body=normal(s['body'])
        overlap=sum((2 if w in title else 1 if w in body else 0) for w in terms)/(2*max(len(terms),1))
        if query_vector is not None:
            if len(query_vector)!=len(s['embedding']):raise ValueError('embedding dimension mismatch')
            cosine=max(0,min(1,math.fsum(a*b for a,b in zip(query_vector,s['embedding']))))
        else:cosine=max(0,min(1,(r['branches'].get('vector',{}).get('score',0)*2-1)))
        literal=float(normal(p['keywords']) in body or normal(p['keywords']) in title)
        exact=float(any(i in normal(s.get('identifier_text','')+' '+s['file_name']+' '+s['body']) for i in p['identifiers']))
        meta=soft_score(p,s)
        features={'rrf':r['rrf_score']/maximum,'lexical_overlap':overlap,'cosine':cosine,
                  'literal_phrase':literal,'identifier':exact,'metadata':meta}
        r['rerank_features']=features
        # Small metadata preference is part of R0 as well; R1 is an independent fixed experiment.
        r['score']=r['rrf_score']*(1+0.10*meta) if mode=='R0' else sum(features[k]*w for k,w in CONFIG['r1_weights'].items())
    return sorted(selected,key=lambda r:(-r['score'],r['chunk_id']))

def location_label(loc):
    kind=loc.get('kind','');parts=[]
    for key,label in [('page','페이지'),('slide','슬라이드'),('sheet','시트'),('cell_range','셀'),('paragraph','문단'),('paragraph_index','문단'),('table_index','표'),('row_index','행'),('cell_index','셀'),('line_start','시작 줄'),('line_end','끝 줄')]:
        if key in loc:parts.append(str(loc[key])+' '+label)
    return ' · '.join(parts) or kind or '위치 미확인'

class SearchEngine:
    def __init__(self,docs,blocks,reference,embed,es='http://127.0.0.1:9200',qwen='http://127.0.0.1:8001/v1',model=''):
        self.docs=docs;self.blocks=blocks;self.reference=reference;self.embed=embed;self.es=es;self.qwen=qwen;self.model=model
        self.pool=ThreadPoolExecutor(max_workers=4);self.index='rag-search-chunks-v001';self.docindex='rag-search-documents-v001'
        self.families=collections.defaultdict(list)
        self.network_diagrams=network_diagrams(blocks)
        for d in docs.values():self.families[d['family_id']].append(d)
    def trace_rows(self,rows,combined_ranks=None):
        """Public rank view: no vectors, scores, formulas or generated explanations."""
        out=[]
        for rank,r in enumerate(rows,1):
            s=r.get('source',r.get('_source'));cid=r.get('chunk_id',r.get('_id'))
            locations=list(dict.fromkeys(location_label(ref.get('loc',{})) for ref in s.get('source_refs',[])))
            out.append({'rank':rank,'chunk_id':cid,'doc_id':s['doc_id'],'title':self.docs[s['doc_id']]['file_name'],
              'locations':locations,'preview':s.get('body','')[:180],
              'branch_ranks':{name:v['rank'] for name,v in r.get('branches',{}).items()},
              'combined_rank':(combined_ranks or {}).get(cid)})
        return out
    def retrieve(self,p,vector,emit=None):
        fs=es_filters(p);source=['doc_id','chunk_id','body','file_name','context','table_header','metadata','identifiers',
          'identifier_text','source_refs','kind','family_id','copy_group','latest_version','version_label','embedding']
        b={'size':CONFIG['lexical_k'],'_source':source,'query':{'bool':{'must':[lexical(p)],'filter':fs,
           'should':lexical_preferences(p),'minimum_should_match':0}},
           'sort':[{'_score':'desc'},{'chunk_id':'asc'}]}
        v={'size':CONFIG['vector_k'],'_source':source,'knn':{'field':'embedding','query_vector':vector,
          'k':CONFIG['vector_k'],'num_candidates':CONFIG['num_candidates'],'filter':{'bool':{'filter':fs}}},
          'sort':[{'_score':'desc'},{'chunk_id':'asc'}]}
        fb=self.pool.submit(http,self.es,'/'+self.index+'/_search',b)
        fv=self.pool.submit(http,self.es,'/'+self.index+'/_search',v)
        completed={}
        for future in as_completed([fb,fv]):
            name='bm25' if future is fb else 'vector';completed[name]=future.result()
            if emit:emit(name,{'rows':self.trace_rows(completed[name]['hits']['hits'])})
        bm=completed['bm25'];dense=completed['vector']
        return bm['hits']['hits'],dense['hits']['hits'],{'bm25':bm['took'],'vector':dense['took']}
    def excerpts(self,did,rows,p):
        candidates=[];seen=set();terms=words(p['keywords'])
        for row in rows:
            for ref in row['source']['source_refs']:
                block=self.blocks.get(did,{}).get(ref.get('block_id'))
                if not block:continue
                # Visual structure serialization is useful to search but is not a literal quotation.
                text=block.get('text','')
                literal=block.get('run_ref')=='native' or any(e.get('kind')=='literal' and e.get('quote')==text for e in block.get('evidence',[]))
                if not literal or not text.strip():continue
                lo=ref.get('start',0);hi=ref.get('end',len(text))
                if not isinstance(lo,int) or not isinstance(hi,int) or not 0<=lo<hi<=len(text):continue
                segment=text[lo:hi];low=normal(segment)
                positions=[low.find(t) for t in terms if t in low]
                start=max(0,min(positions,default=0)-25);end=min(len(segment),start+100)
                quote=segment[start:end]
                if quote in seen:continue
                seen.add(quote);highlights=[]
                for term in terms:
                    highlights.extend([m.start(),m.end()] for m in re.finditer(re.escape(term),normal(quote)))
                score=sum(t in low for t in terms)
                candidates.append((score,row['score'],{'text':quote,'block_id':block['block_id'],'start':lo+start,
                  'end':lo+end,'loc':block['loc'],'location':location_label(block['loc']),
                  'highlight_spans':sorted(highlights),'literal_verified':True}))
        candidates.sort(key=lambda x:(-x[0],-x[1]))
        # For semantic-only matches show one leading literal excerpt, without artificial highlights.
        limit=3 if candidates and candidates[0][0]>0 else 1
        return [r[2] for r in candidates[:limit]]
    def group(self,rows,p):
        perdoc=collections.defaultdict(list)
        for r in rows:perdoc[r['source']['doc_id']].append(r)
        scored={did:rs[0]['score']+CONFIG['additional_chunk_weight']*sum(r['score'] for r in
          [r for r in rs[1:] if r.get('support_eligible',True)][:CONFIG['max_additional_chunks']]) for did,rs in perdoc.items()}
        families=collections.defaultdict(list)
        for did in scored:families[self.docs[did]['family_id']].append(did)
        results=[]
        for fid,ids in families.items():
            eligible=list(ids);reason='highest_score'
            if p['requested_version']:
                versionids=[d for d in ids if self.docs[d]['version_label']==p['requested_version']]
                if versionids:eligible=versionids;reason='requested_version'
            elif p['conditions'].get('status'):
                statusids=[d for d in ids if self.docs[d]['metadata'].get('status')==p['conditions']['status']]
                if statusids:eligible=statusids;reason='requested_status'
            elif p['identifiers']:
                exactids=[d for d in ids if any(i in normal(self.docs[d]['identifier_text']+' '+self.docs[d]['file_name']) for i in p['identifiers'])]
                if exactids:eligible=exactids;reason='identifier_evidence'
            if reason=='highest_score' and p.get('requested_version_order')=='earliest':
                def version(d):
                    m=re.fullmatch(r'(?:v|rev)(\d+(?:\.\d+)*)',self.docs[d]['version_label'],re.I)
                    return tuple(int(n) for n in m[1].split('.')) if m else None
                numbered={d:version(d) for d in ids if version(d) is not None}
                if numbered:
                    first=min(numbered.values());eligible=[d for d,v in numbered.items() if v==first]
                    reason='earliest_matching_version'
            if reason=='highest_score':
                if p['sort']:
                    field=p['sort']['field'];order=sorted(ids,key=lambda d:self.docs[d]['metadata'].get(field,''),reverse=p['sort']['direction']=='desc')
                    eligible=[d for d in order if self.docs[d]['metadata'].get(field)==self.docs[order[0]]['metadata'].get(field)]
                    reason='requested_date_order'
                else:
                    latest=[d for d in ids if self.docs[d]['latest_version']]
                    if latest:eligible=latest;reason='latest_matching_candidate'
                    else:reason='matching_older_version_latest_not_in_candidates'
            # Prefer the clean copy name only among identical hashes, without changing evidence version.
            rep=max(eligible,key=lambda d:(scored[d],d))
            copies=[d for d in eligible if self.docs[d]['source_sha256']==self.docs[rep]['source_sha256']]
            rep=min(copies,key=lambda d:(bool(re.search(r'\(\d+\)|copy|복사본',self.docs[d]['file_name'],re.I)),d))
            doc=self.docs[rep];ev=self.excerpts(rep,perdoc[rep],p)
            members=self.families[fid]
            card={'doc_id':rep,'title':doc['file_name'],'family_id':fid,'score':max(scored[d] for d in ids),
              'representative_reason':reason,'metadata':doc['metadata'],'url':doc['original']['source'].get('web_url'),
              'source_path':doc['source_path'],'excerpts':ev,'evidence_status':'literal_source' if ev else 'source_location_only',
              'matched_chunk_ids':[r['chunk_id'] for r in perdoc[rep]],
              'other_versions':[{'doc_id':d['doc_id'],'title':d['file_name'],'version':d['version_label'],
                'latest':d['latest_version'],'matched':d['doc_id'] in ids,'same_content':d['source_sha256']==doc['source_sha256'],
                'url':d['original']['source'].get('web_url')} for d in members if d['doc_id']!=rep],
              'latest_doc_ids':[d['doc_id'] for d in members if d['latest_version']]}
            if p.get('content_requirement'):
                card['content_evidence']=[dict(e,location=location_label(e['loc'])) for e in self.network_diagrams.get(rep,[])]
            results.append(card)
        results.sort(key=lambda r:(-r['score'],r['doc_id']))
        if p['sort']:
            # All matching documents are collected on the dedicated date-sort path before limiting.
            results.sort(key=lambda r:r['metadata'].get(p['sort']['field'],''),reverse=p['sort']['direction']=='desc')
        return results[:CONFIG['result_documents']]
    def date_candidates(self,p):
        # Walk all matching chunks before grouping or limiting documents. The source
        # index is immutable; search_after avoids a fixed top-N recency blind spot.
        scope=copy.deepcopy(p);scope['sort']=None
        datequery={'size':2000,'_source':True,'query':{'bool':{'must':[lexical(p)],'filter':es_filters(scope)}},
          'sort':[{'metadata.'+p['sort']['field']:{'order':p['sort']['direction'],'missing':'_last'}},{'chunk_id':'asc'}]}
        hits=[]
        while True:
            batch=http(self.es,'/'+self.index+'/_search',datequery)['hits']['hits'];hits.extend(batch)
            if len(batch)<datequery['size']:break
            datequery['search_after']=batch[-1]['sort']
        return [{'chunk_id':h['_id'],'source':h['_source'],'score':1/(1+i)} for i,h in enumerate(hits)]
    def search(self,query,mode='B',ranker='R0',reference_date=None,use_llm=True,emit=None):
        start=time.perf_counter()
        if ranker not in ['R0','R1']:raise ValueError('unknown reranker')
        p=plan_rules(query,self.reference,reference_date)
        if use_llm:p=conditional_llm(p,self.reference,self.qwen,self.model)
        p=apply_mode(p,mode);analysis=time.perf_counter()-start
        if p.get('content_requirement'):p['content_doc_ids']=sorted(self.network_diagrams)
        if emit:emit('analysis',{'query_plan':p})
        if p['requires_clarification']:
            return {'status':'needs_clarification','query_plan':p,'results':[],'timings':{'total_seconds':time.perf_counter()-start,'analysis_seconds':analysis}}
        t=time.perf_counter();vector=self.embed(query);embedding=time.perf_counter()-t
        def retrieve():
            if emit:
                emit('searching',{'filters':p['filters']})
                return self.retrieve(p,vector,emit)
            return self.retrieve(p,vector)
        t=time.perf_counter();bm,vec,took=retrieve();relaxed=[]
        while not bm and not vec:
            drop=next((k for k in p['relaxable'] if k in p['filters'] and k!='client'),None)
            if not drop:break
            value=p['filters'].pop(drop);relaxed.append({'field':drop,'previous_value':value})
            if emit:emit('relaxed',{'field':drop})
            bm,vec,took=retrieve()
        rows=rrf(bm,vec)
        if emit:emit('combined',{'rows':self.trace_rows(rows),'used_count':min(len(rows),CONFIG['rerank_k']),
                                'date_order_overrides':bool(p['sort'])})
        ranked=rerank(rows,p,ranker,vector)
        if emit and not p['sort']:
            emit('adjusted',{'rows':self.trace_rows(ranked,{r['chunk_id']:i for i,r in enumerate(rows,1)}),'ranker':ranker})
        # Date-order requests must not sort just an arbitrary top-50 candidate subset.
        date_coverage=None;undated_results=[]
        if p['sort']:
            allrows=self.date_candidates(p);field=p['sort']['field']
            def dated(r):
                s=r['source']
                return bool(s['metadata'].get(field)) and (field=='file_modified_at' or s.get('metadata_statuses',self.docs[s['doc_id']].get('metadata_statuses',{})).get(field)=='extracted')
            ranked=[r for r in allrows if dated(r)];unknown=[r for r in allrows if not dated(r)]
            scope=copy.deepcopy(p);scope['sort']=None
            undated_results=self.group(unknown,scope)
            date_coverage={'field':field,'dated_documents':len({r['source']['doc_id'] for r in ranked}),
              'undated_documents':len({r['source']['doc_id'] for r in unknown}),
              'undated_doc_ids':sorted({r['source']['doc_id'] for r in unknown}),
              'unknown_dates_in_latest_ranking':False,'fallback_to_other_date':False}
            if emit:emit('date_order',{'sort':p['sort'],'date_coverage':date_coverage,
                                     'rows':self.trace_rows(ranked),'basis':'all_matching_chunks'})
        results=self.group(ranked,p);retrieval=time.perf_counter()-t
        return {'status':'ok' if results or undated_results else 'no_results','query_plan':p,'results':results,'relaxed_conditions':relaxed,
          'date_coverage':date_coverage,'undated_results':undated_results,
          'reranker':ranker,'timings':{'total_seconds':time.perf_counter()-start,'analysis_seconds':analysis,
            'embedding_seconds':embedding,'retrieval_and_cards_seconds':retrieval,'es_took_ms':took},
          'diagnostics':{'bm25':[{k:h[k] for k in ['_id','_score']}|{'doc_id':h['_source']['doc_id']} for h in bm],
            'vector':[{k:h[k] for k in ['_id','_score']}|{'doc_id':h['_source']['doc_id']} for h in vec],
            'rrf_top30':[{'doc_id':r['source']['doc_id'],'chunk_id':r['chunk_id'],'score':r['rrf_score']} for r in rows[:30]],
            'rerank_candidates':[{'doc_id':r['source']['doc_id'],'chunk_id':r['chunk_id']} for r in rows[:CONFIG['rerank_k']]],
            'ranked_top30':[{'doc_id':r['source']['doc_id'],'chunk_id':r['chunk_id'],'score':r['score']} for r in ranked[:30]],
            'branch_filters_identical':True,'filter_clauses':es_filters(p)}}
