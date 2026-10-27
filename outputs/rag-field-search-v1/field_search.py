#!/usr/bin/env python3
import argparse,copy,json,math,re,sys,unicodedata
from collections import Counter,defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parent/'rag-condition-search-v1'))
import condition_search as old
E=old.E
VERSION='field-search-1.0.1'
WEIGHTS={'job':4.,'role':4.,'identifier':3.,'title':.5,'system':.25,'client':.25}

def intent_tokens(text):
    text=unicodedata.normalize('NFC',text).casefold();out=[]
    bound=lambda x:re.search(r'(?<![a-z0-9가-힣])'+x+r'(?![a-z0-9가-힣])',text)
    if bound(r'cutover') or (bound(r'전환') and re.search(r'작업|로그|\blog\b',text)):out.append('intent:cutover')
    # Do not interpret arbitrary "automatic" tasks as elastic infrastructure.
    if re.search(r'오토\s*스케일(?:링)?|(?<![a-z0-9])auto[_ -]?scal(?:e|ing)(?![a-z0-9])',text) or re.search(r'자동(?:으로)?[^.!?\n]{0,18}(?:서버|인스턴스)[^.!?\n]{0,12}(?:늘리|확장|증설)',text):out.append('intent:autoscale')
    return out

def tokens(text,index,intents=False):
    ts=old.previous.tokens(text,index['clients'],index['rules'])
    return ts+(intent_tokens(text) if intents else [])

def feature_tokens(text,index,intents=False):return set(t for t in tokens(text,index,intents) if not t.startswith('k:'))

def query_feature_tokens(text,index,intents=False):
    # A technical identifier is an exact key, not a bag of implied concepts.
    normalized=unicodedata.normalize('NFC',text).casefold();identifiers=[]
    def mask(m):
        word=m[0]
        if any(c.isdigit() for c in word) and any(c in word for c in '-_./:'):
            identifiers.append('w:'+word);return ' '*len(word)
        return word
    remaining=re.sub(r'[a-z0-9]+(?:[._:/-][a-z0-9]+)*',mask,normalized)
    return feature_tokens(remaining,index,intents)|set(identifiers)

def prepare(index,parsed,metadata):
    assert set(index['documents'])==set(parsed)==set(metadata)
    features={};contexts={}
    for identity,doc in index['documents'].items():
        record=parsed[identity];m=metadata[identity]
        if old.base.enrich.check_output(m,record):raise ValueError('metadata input validation failed')
        f={key:[] for key in WEIGHTS}
        f['title'].append({'text':doc['source']['file_name'],'evidence':[{'kind':'source','field':'file_name','quote':doc['source']['file_name']}]})
        for key,fields in {'job':['작업명'],'identifier':['계약번호','견적번호','오류코드'],'system':['대상시스템'],'client':['거래처']}.items():
            for field in fields:
                value=m['fields'][field]
                if value['status']=='extracted':f[key].append({'text':value['value'],'evidence':value['evidence'],'metadata_field':field})
        for block in record['blocks']:
            if block['type']=='heading':f['title'].append({'text':block['text'],'evidence':[{'kind':'block','ref':block['block_id'],'quote':block['text'],'loc':block['loc']}]})
        # Only cells beneath literal named columns; no guessed inferred header list.
        for table in [b for b in record['blocks'] if b['type']=='table']:
            rows=sorted([b for b in record['blocks'] if b['parent_id']==table['block_id'] and b['type']=='table_row'],key=lambda b:b['order']);columns={}
            for row in rows:
                vals={cell['column']:re.sub(r'\s+','',cell['text']).casefold() for cell in row['cells'] if cell['text'].strip()}
                if len(vals)>=2 and all(v in old.base.HEADER_WORDS for v in vals.values()):
                    columns={col:'role' if name in ('역할','주요업무') else 'identifier' for col,name in vals.items() if name in ('역할','주요업무','호스트명','ip')};continue
                for cell in row['cells']:
                    if cell['column'] in columns and cell['text'].strip():f[columns[cell['column']]].append({'text':cell['text'],'evidence':[{'kind':'cell','ref':row['block_id'],'quote':cell['text'],'loc':cell['loc']}]})
        features[identity]=f
        if doc['metadata'].get('문서종류')=='실행 로그':
            selected=f['job']+f['system']
            for eid,entry in index['entries'].items():
                if entry['doc_id']==identity and entry['kind']=='native_chunk':contexts[eid]={'text':' | '.join(v['text'] for v in selected),'evidence':[e for v in selected for e in v['evidence']]}
    return {'features':features,'log_contexts':contexts,'weights':WEIGHTS,'version':VERSION,'model_called':False}

def view(index,bundle,*,context=False,intents=False):
    if not context and not intents:return index
    ix=copy.deepcopy(index);postings=defaultdict(dict)
    for eid,entry in ix['entries'].items():
        text=' '.join([entry['context_header'],entry['table_header_text'],entry['text']])
        if context and eid in bundle['log_contexts']:
            entry['linked_log_context']=bundle['log_contexts'][eid];text+=' '+entry['linked_log_context']['text']
        ts=tokens(text,ix,intents);entry['length']=len(ts)
        for term,tf in Counter(ts).items():postings[term][eid]=tf
    ix['postings']=dict(postings);ix['average_length']=sum(e['length'] for e in ix['entries'].values())/len(ix['entries'])
    return ix

def field_statistics(index,bundle,intents):
    corpus={};df=Counter()
    for identity,fields in bundle['features'].items():
        corpus[identity]={field:set().union(*(feature_tokens(v['text'],index,intents) for v in values)) if values else set() for field,values in fields.items()}
        df.update(set().union(*corpus[identity].values()))
    return corpus,{term:math.log(1+(len(corpus)-count+.5)/(count+.5)) for term,count in df.items()}

def search(index,bundle,query,as_of,system_terms,*,weights=True,intents=False,limit=10,statistics=None):
    if not 1<=limit<=100:raise ValueError('invalid limit')
    plan=old.plan(query,as_of,system_terms);allowed,unknown=old.base.apply_filters(index,plan['filters'])
    uncertain={d for d in allowed if any(index['documents'][d]['metadata_statuses'].get(f['field'])!='extracted' for f in plan['filters'])};allowed-=uncertain;unknown|=uncertain
    scores=defaultdict(float);n=index['entry_count'];avg=index['average_length'] or 1;k1=index['config']['bm25_k1'];b=index['config']['bm25_b']
    for term in sorted(set(tokens(plan['lexical_query'],index,intents))):
        posting=index['postings'].get(term,{})
        if not posting:continue
        idf=math.log(1+(n-len(posting)+.5)/(len(posting)+.5))
        for eid,tf in posting.items():
            entry=index['entries'][eid]
            if entry['doc_id'] in allowed:scores[eid]+=idf*tf*(k1+1)/(tf+k1*(1-b+b*entry['length']/avg))
    bydoc=defaultdict(list)
    for eid,score in scores.items():bydoc[index['entries'][eid]['doc_id']].append((score,eid))
    corpus,idfs=statistics or field_statistics(index,bundle,intents);query_features=query_feature_tokens(plan['lexical_query'],index,intents)
    ranking=[]
    # Field evidence may be in a different block from the highest-scored chunk.
    for identity in sorted(allowed):
        hits=sorted(bydoc[identity],key=lambda h:(-h[0],h[1]));boosts=[]
        if weights:
            for field,w in WEIGHTS.items():
                matched=sorted(query_features&corpus[identity][field]);score=w*sum(idfs[t] for t in matched)
                if matched:boosts.append({'field':field,'weight':w,'matched_tokens':matched,'score':score,
                    'sources':[v for v in bundle['features'][identity][field] if feature_tokens(v['text'],index,intents)&set(matched)]})
        lexical=hits[0][0] if hits else 0.;bonus=sum(v['score'] for v in boosts)
        if lexical+bonus<=0:continue
        doc=index['documents'][identity]
        ranking.append({'doc_id':identity,'score':lexical+bonus,'lexical_score':lexical,'field_score':bonus,'field_matches':boosts,
            'evidence':[{'entry_id':eid,'score':score,**index['entries'][eid]} for score,eid in hits[:3]],'source':doc['source'],'metadata':doc['metadata'],
            'native_chunk_count':doc['native_chunk_count'],'pending_visual_units':doc['pending_visual_units'],'conditions_verified':False})
    ranking.sort(key=lambda r:(-r['score'],r['doc_id']))
    return {'results':[{'rank':i,**r} for i,r in enumerate(ranking[:limit],1)],'query_plan':plan,'unresolved_filter_documents':sorted(unknown),
        'eligible_documents':len(allowed),'intent_tokens':intent_tokens(query) if intents else [],'model_called':False,'conditions_verified':False}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--bundle',required=True);p.add_argument('--index',required=True);p.add_argument('--query',required=True);p.add_argument('--as-of',required=True)
    args=p.parse_args();ix=E.read_json(args.index);bundle=E.read_json(args.bundle);terms=E.read_json(ROOT.parent/'rag-enrichment-v1/reference-data.json')['system_terms']
    print(json.dumps(search(view(ix,bundle,context=True,intents=True),bundle,args.query,args.as_of,terms,intents=True),ensure_ascii=False,indent=2))
