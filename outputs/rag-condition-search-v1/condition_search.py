#!/usr/bin/env python3
"""Explicit document-kind and target-system filters over a frozen lexical index."""
import argparse
from collections import defaultdict
import copy
import json
import math
from pathlib import Path
import re
import sys
import unicodedata
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parent/'rag-rule-search-v1'))
import search as previous
base=previous.base
E=base.enrich
VERSION='condition-search-1.0.0'
KIND_ALIASES=[
 (['네트워크 구성도'],['네트워크 구성도','망 구성도']),
 (['서버 구성도'],['서버 구성도']),
 (['네트워크 구성도','서버 구성도'],['구성도']),
 (['실행 로그'],['실행 로그','작업 로그','배치 로그','운영 로그','로그','log','logs']),
 (['계약서'],['계약서','계약']), (['견적서'],['견적서','견적']),
 (['제안서'],['제안서','제안']), (['기타'],['통화 메모','메모','이메일','메일'])]
SUFFIX=r'(?:에서|으로|관련|에는|은|는|이|가|을|를|의|에|도|로|와|과|만)?'

def match(text,term):
    pattern=re.escape(term.casefold()).replace(r'\ ',r'\s*')
    return list(re.finditer(r'(?<![a-z0-9가-힣_./-])'+pattern+SUFFIX+r'(?![a-z0-9가-힣_./-])',text))

def explicit_conditions(query,system_terms,*,kinds=True,systems=True):
    text=unicodedata.normalize('NFC',query).casefold();filters=[];recognized=[];warnings=[]
    # Quoted content, negation, or alternatives are not reliable direct filter requests.
    if re.search(r'아닌|아니고|말고|제외|않|빼고|외에|또는|혹은|이거나|["“”‘’]',text):
        return {'filters':[],'recognized':[],'warnings':['ambiguous_negation_alternative_or_quoted_scope']}
    if kinds:
        hits=[]
        for values,aliases in KIND_ALIASES:
            for alias in aliases:
                for m in match(text,alias):hits.append({'field':'문서종류','values':values,'text':m[0],'span':[m.start(),m.end()]})
        # Discard shorter overlapping generic words (e.g. 구성도 inside 서버 구성도).
        selected=[]
        for h in sorted(hits,key=lambda x:-(x['span'][1]-x['span'][0])):
            if not any(h['span'][0]<x['span'][1] and x['span'][0]<h['span'][1] for x in selected):selected.append(h)
        sets={tuple(h['values']) for h in selected}
        if len(sets)>1:warnings.append('multiple_document_kinds')
        elif sets:
            values=list(next(iter(sets)));filters.append({'field':'문서종류','op':'eq' if len(values)==1 else 'in','value':values[0] if len(values)==1 else values});recognized.extend(selected)
    if systems:
        found=[]
        for term in system_terms:
            for m in match(text,term):found.append({'field':'대상시스템','value':term,'text':m[0],'span':[m.start(),m.end()]})
        values={h['value'] for h in found}
        if len(values)>1:warnings.append('multiple_target_systems')
        elif values:
            filters.append({'field':'대상시스템','op':'eq','value':next(iter(values))});recognized.extend(found)
    return {'filters':filters,'recognized':recognized,'warnings':warnings}

def plan(query,as_of,system_terms,*,kinds=True,systems=True):
    p=previous.plan(query,as_of);extra=explicit_conditions(query,system_terms,kinds=kinds,systems=systems)
    # Do not remove the document words or system names: this isolates candidate filtering.
    for f in extra['filters']:
        same=[x for x in p['filters'] if x['field']==f['field']]
        if same and f not in same:raise ValueError('conflicting filter on '+f['field'])
        if f not in p['filters']:p['filters'].append(f)
    p['recognized']+=extra['recognized'];p['warnings']+=extra['warnings'];p['explicit_condition_rules']=extra
    return p

def search(index,query,as_of,system_terms,*,kinds=True,systems=True,limit=10):
    if not 1<=limit<=100:raise ValueError('limit must be 1..100')
    p=plan(query,as_of,system_terms,kinds=kinds,systems=systems)
    allowed,unknown=base.apply_filters(index,p['filters'])
    unresolved={identity for identity in allowed if any(index['documents'][identity]['metadata_statuses'].get(f['field'])!='extracted' for f in p['filters'])}
    allowed-=unresolved;unknown|=unresolved
    scores=defaultdict(float);n=index['entry_count'];avg=index['average_length'] or 1
    k1=index['config']['bm25_k1'];b=index['config']['bm25_b']
    for term in sorted(set(previous.tokens(p['lexical_query'],index['clients'],index['rules']))):
        posting=index['postings'].get(term,{})
        if not posting:continue
        idf=math.log(1+(n-len(posting)+.5)/(len(posting)+.5))
        for eid,tf in posting.items():
            entry=index['entries'][eid]
            if entry['doc_id'] in allowed:scores[eid]+=idf*tf*(k1+1)/(tf+k1*(1-b+b*entry['length']/avg))
    groups=defaultdict(list)
    for eid,score in scores.items():groups[index['entries'][eid]['doc_id']].append((score,eid))
    ranking=[]
    for identity,hits in groups.items():
        hits.sort(key=lambda h:(-h[0],h[1]));doc=index['documents'][identity]
        ranking.append({'doc_id':identity,'score':hits[0][0],
            'evidence':[{'entry_id':eid,'score':score,**index['entries'][eid]} for score,eid in hits[:3]],
            'source':doc['source'],'metadata':doc['metadata'],'native_chunk_count':doc['native_chunk_count'],
            'pending_visual_units':doc['pending_visual_units'],'conditions_verified':False,
            'metadata_conditions_checked':[{'condition':f,'actual_value':doc['metadata'][f['field']],'status':'extracted','matched':True} for f in p['filters']]})
    ranking.sort(key=lambda r:(-r['score'],r['doc_id']))
    return {'results':[{'rank':i,**r} for i,r in enumerate(ranking[:limit],1)],'query_plan':p,
        'concept_matches':previous.concepts(query,index['rules']),'unresolved_filter_documents':sorted(unknown),
        'eligible_documents':len(allowed),'conditions_verified':False,'model_called':False}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--index',required=True);p.add_argument('--query',required=True);p.add_argument('--as-of',required=True)
    p.add_argument('--reference',default=str(ROOT.parent/'rag-enrichment-v1/reference-data.json'));p.add_argument('--limit',type=int,default=5)
    args=p.parse_args();print(json.dumps(search(E.read_json(args.index),args.query,args.as_of,E.read_json(args.reference)['system_terms'],limit=args.limit),ensure_ascii=False,indent=2))
if __name__=='__main__':main()
