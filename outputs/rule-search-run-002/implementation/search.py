#!/usr/bin/env python3
"""Auditable bilingual lexical search and conservative calendar filters, no models."""
import argparse
from calendar import monthrange
from collections import Counter, defaultdict
import copy
from datetime import date, timedelta
import math
from pathlib import Path
import re
import sys
import unicodedata
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parent/'rag-native-search-v1'))
import pipeline as base
VERSION='rule-search-1.0.1'
PARTICLES=r'(?:에서|으로|부터|까지|에게|에는|에서의|에서만|은|는|이|가|을|를|의|에|도|로|와|과|만)?'

def matches(text,alias):
    alias=unicodedata.normalize('NFC',alias).casefold()
    pattern=re.escape(alias).replace(r'\ ',r'[\s_-]+')
    suffix=PARTICLES if re.search('[가-힣]$',alias) else ''
    return list(re.finditer(r'(?<![a-z0-9가-힣])'+pattern+suffix+r'(?![a-z0-9가-힣])',text))

def concepts(text,rules):
    text=unicodedata.normalize('NFC',text).casefold();hits=[]
    for concept in rules['concepts']:
        spans={}
        for alias in concept['aliases']:
            for m in matches(text,alias):spans[m.span()]={'alias':alias,'text':m[0],'start':m.start(),'end':m.end()}
        for item in concept.get('abbreviations',[]):
            if any(matches(text,context) for context in item['requires_any']):
                for m in matches(text,item['text']):spans[m.span()]={'alias':item['text'],'text':m[0],'start':m.start(),'end':m.end(),'context_guard':True}
        if spans:hits.append({'concept':concept['id'],'matches':list(spans.values())})
    return hits

def tokens(text,clients,rules):
    result=base.tokens(text,clients)
    for word in re.findall(r'[a-z0-9]+(?:[._:/-][a-z0-9]+)*',unicodedata.normalize('NFC',text).casefold()):
        if '_' in word:result.extend('w:'+part for part in word.split('_') if part)
    for hit in concepts(text,rules):result.extend(['concept:'+hit['concept']]*len(hit['matches']))
    return result

def build_index(baseline,rules):
    index=copy.deepcopy(baseline);postings=defaultdict(dict)
    for eid,entry in index['entries'].items():
        text=' '.join([entry['context_header'],entry['table_header_text'],entry['text']])
        ts=tokens(text,index['clients'],rules);entry['length']=len(ts)
        for term,tf in Counter(ts).items():postings[term][eid]=tf
    index.update(postings=dict(postings),average_length=sum(e['length'] for e in index['entries'].values())/len(index['entries']),rules=rules,
                 rule_search_version=VERSION,scope='bilingual_keyword_development_baseline')
    return index

DATE_PATTERN=re.compile(r'(?<!\d)(?:\d{4}년(?:\s*\d{1,2}월(?:\s*\d{1,2}일)?)?|\d{4}-\d{2}(?:-\d{2})?|(?:올해|금년|작년|지난해|재작년|내년)(?:\s*\d{1,2}월(?:\s*\d{1,2}일)?)?|이번\s*달|지난\s*달|다음\s*달|오늘|어제)(?!\d)')

def interval(expression,as_of):
    s=re.sub(r'\s+','',expression)
    if s in ('오늘','어제'):
        d=as_of-timedelta(days=int(s=='어제'));return d,d
    if s in ('이번달','지난달','다음달'):
        n=as_of.year*12+as_of.month-1+{'이번달':0,'지난달':-1,'다음달':1}[s];y,m=divmod(n,12);m+=1
        return date(y,m,1),date(y,m,monthrange(y,m)[1])
    for label,offset in [('재작년',-2),('지난해',-1),('작년',-1),('올해',0),('금년',0),('내년',1)]:
        if s.startswith(label):s=str(as_of.year+offset)+'년'+s[len(label):];break
    if '년' in s:
        m=re.fullmatch(r'(\d{4})년(?:(\d{1,2})월(?:(\d{1,2})일)?)?',s)
        if not m:raise ValueError('invalid date expression')
        y,month,day=m.groups()
    else:
        pieces=s.split('-');y=pieces[0];month=pieces[1] if len(pieces)>1 else None;day=pieces[2] if len(pieces)>2 else None
    y=int(y)
    if month is None:return date(y,1,1),date(y,12,31)
    month=int(month)
    if day is None:return date(y,month,1),date(y,month,monthrange(y,month)[1])
    d=date(y,month,int(day));return d,d

def plan(query,as_of):
    today=date.fromisoformat(as_of)
    if today.isoformat()!=as_of:raise ValueError('as_of must be YYYY-MM-DD')
    filters=[];recognized=[];warnings=[];spans=[]
    dates=list(DATE_PATTERN.finditer(query));is_log=bool(re.search(r'로그|\blog\b',query,re.I))
    # Never convert an ambiguous role or unsupported comparison into a hard date filter.
    field=None
    if re.search(r'계약\s*(?:종료일|만료일)',query):field='계약종료일'
    elif re.search(r'계약\s*시작일',query):field='계약시작일'
    elif re.search(r'문서일자|작성일',query):field='문서일자'
    elif is_log:field='로그시작'
    unsupported=bool(re.search(r'이전|이후|이상|이하|제외|말고|아닌|않|부터|까지|~|또는|이나|혹은',query))
    if dates:
        if len(dates)!=1 or unsupported:warnings.append('unsupported_multiple_dates_comparison_or_negation')
        elif field is None:warnings.append('ambiguous_date_role')
        else:
            m=dates[0]
            try:start,end=interval(m[0],today)
            except ValueError:warnings.append('invalid_calendar_date')
            else:
                low=start.isoformat()+(' 00:00' if field=='로그시작' else '')
                high=end.isoformat()+(' 23:59' if field=='로그시작' else '')
                filters.extend([{'field':field,'op':'gte','value':low},{'field':field,'op':'lte','value':high}])
                if field=='로그시작':filters.append({'field':'문서종류','op':'eq','value':'실행 로그'})
                recognized.append({'rule':'calendar_period','text':m[0],'span':[m.start(),m.end()],'field':field,'start':low,'end':high})
                spans.append(m.span())
    elif re.search(r'\d+월|최근|지난주|이번주|분기|상반기|하반기',query):warnings.append('unsupported_or_yearless_date')
    status_matches=list(re.finditer(r'실패한|성공한|실패로\s*끝난|성공으로\s*끝난',query))
    if is_log and status_matches and not unsupported:
        values={'실패' if '실패' in m[0] else '성공' for m in status_matches}
        if len(values)==1:
            status=values.pop();filters.append({'field':'실행결과','op':'eq','value':status})
            for m in status_matches:
                recognized.append({'rule':'explicit_final_status','text':m[0],'span':[m.start(),m.end()],'value':status});spans.append(m.span())
        else:warnings.append('conflicting_final_status')
    residual=query
    for start,end in sorted(spans,reverse=True):residual=residual[:start]+' '+residual[end:]
    return {'reference_date':as_of,'timezone':'Asia/Seoul','filters':filters,'recognized':recognized,'warnings':warnings,
            'lexical_query':residual.strip(),'conditions_verified':False}

def search(index,query,as_of,*,terms=True,dates=True,limit=10):
    if not 1<=limit<=100:raise ValueError('limit must be 1..100')
    query_plan=plan(query,as_of) if dates else {'reference_date':as_of,'timezone':'Asia/Seoul','filters':[],'recognized':[],'warnings':[],'lexical_query':query,'conditions_verified':False}
    if not terms:
        result=base.search(index,query_plan['lexical_query'],query_plan['filters'],limit)
    else:
        allowed,unknown=base.apply_filters(index,query_plan['filters']);scores=defaultdict(float)
        n=index['entry_count'];avg=index['average_length'] or 1;k1=index['config']['bm25_k1'];b=index['config']['bm25_b']
        for term in sorted(set(tokens(query_plan['lexical_query'],index['clients'],index['rules']))):
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
            evidence=[{'entry_id':eid,'score':score,**index['entries'][eid]} for score,eid in hits[:3]]
            ranking.append({'doc_id':identity,'score':hits[0][0],'evidence':evidence,'source':doc['source'],'metadata':doc['metadata'],
                'native_chunk_count':doc['native_chunk_count'],'pending_visual_units':doc['pending_visual_units'],'conditions_verified':False})
        ranking.sort(key=lambda r:(-r['score'],r['doc_id']))
        result={'results':[{'rank':i,**r} for i,r in enumerate(ranking[:limit],1)],'unresolved_filter_documents':sorted(unknown),'conditions_verified':False}
    result.update(query_plan=query_plan,concept_matches=concepts(query,index['rules']) if terms else [],model_called=False)
    return result

def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    b=sub.add_parser('build');b.add_argument('--baseline',required=True);b.add_argument('--rules',default=str(ROOT/'rules.json'));b.add_argument('--output',required=True)
    s=sub.add_parser('search');s.add_argument('--index',required=True);s.add_argument('--query',required=True);s.add_argument('--as-of',required=True);s.add_argument('--limit',type=int,default=5)
    args=parser.parse_args()
    if args.command=='build':
        out=Path(args.output)
        if out.exists():raise ValueError('new output directory required')
        ix=build_index(base.enrich.read_json(args.baseline),base.enrich.read_json(args.rules));out.mkdir(parents=True)
        base.enrich.dump(out/'index.json',ix)
        base.enrich.dump(out/'provenance.json',{'version':VERSION,'model_called':False,'created_at_utc':base.now(),
            'inputs':{str(Path(p).resolve()):base.enrich.digest(p) for p in [args.baseline,args.rules,__file__,ROOT/'CONTRACT.md',base.ROOT/'pipeline.py']},
            'outputs':{'index.json':base.enrich.digest(out/'index.json')},'documents':len(ix['documents']),'entries':ix['entry_count']})
        print('Built',len(ix['documents']),'documents;',ix['entry_count'],'entries')
    else:
        import json
        print(json.dumps(search(base.enrich.read_json(args.index),args.query,args.as_of,limit=args.limit),ensure_ascii=False,indent=2))
if __name__=='__main__':main()
