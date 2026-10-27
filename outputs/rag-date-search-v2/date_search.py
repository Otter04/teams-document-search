"""Source-backed file times and date-role search. No network/model/gold input."""
import argparse, copy, hashlib, json, math, re, sys, unicodedata
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parent/'rag-enrichment-v3'))
import enrich as E
sys.path.insert(0,str(ROOT.parent/'rag-field-search-v1'))
import field_search as old
assert old.old.base.enrich is E
VERSION='date-search-2.0.0'
TZ=ZoneInfo('Asia/Seoul'); UTC=timezone.utc
DATE_FIELDS={'표지일','작성일','파일최종수정일'}
ROLE_PATTERNS={
 '표지일':r'표지\s*(?:날짜|일자|일)',
 '작성일':r'(?:명시적(?:인)?\s*)?작성\s*(?:일자|일)|작성된',
 '파일최종수정일':r'(?:파일\s*)?(?:최종\s*|마지막(?:으로)?\s*)?수정\s*(?:일자|일시|날짜|시각|일|된|한)?'}
SORT_DESC=re.compile(r'(?:가장\s*)?최근(?:에)?\s*수정(?:된|한)?|최신\s*수정\s*순|(?:최종\s*)?수정일\s*(?:내림차순|최신순)|수정일이\s*가장\s*늦은|마지막(?:으로)?\s*수정된')
SORT_ASC=re.compile(r'(?:최종\s*)?수정일\s*(?:오름차순|오래된\s*순)')
RETURN_COUNT=re.compile(r'(?<![가-힣A-Za-z0-9])(?:상위|최대|첫)\s*(\d+)\s*(?:개|건)(?:만)?(?=$|[\s,?.])')
UNSUPPORTED=re.compile(r'이전|이후|이상|이하|제외|말고|아닌|않|부터|까지|~|또는|혹은|이거나|분기|상반기|하반기|월초|월말|초순|중순|하순|이내|["“”‘’]')

def utc_ns(value):
    sec,nano=divmod(int(value),1_000_000_000)
    return datetime.fromtimestamp(sec,UTC).strftime('%Y-%m-%dT%H:%M:%S')+f'.{nano:09d}Z'

def ns_utc(value):
    m=re.fullmatch(r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,9}))?Z',value)
    if not m:raise ValueError('UTC timestamp with Z required')
    dt=datetime.fromisoformat(m[1]).replace(tzinfo=UTC)-datetime(1970,1,1,tzinfo=UTC)
    return (dt.days*86400+dt.seconds)*1_000_000_000+int((m[2] or '').ljust(9,'0'))

def collect_files(records,files_root):
    root=Path(files_root).resolve(); mapping={}; collected=datetime.now(UTC).isoformat()
    for p in root.rglob('*'):
        if not p.is_file():continue
        relative=unicodedata.normalize('NFC',str(p.relative_to(root)))
        if relative in mapping:raise ValueError('duplicate normalized path')
        mapping[relative]=p
    result={}
    for did,r in records.items():
        relative=r['source']['relative_path'];p=mapping[unicodedata.normalize('NFC',relative)].resolve()
        if not p.is_relative_to(root):raise ValueError('source path escapes files root')
        before=p.stat();sha=hashlib.sha256(p.read_bytes()).hexdigest();after=p.stat()
        if (before.st_ino,before.st_size,before.st_mtime_ns)!=(after.st_ino,after.st_size,after.st_mtime_ns):raise ValueError('source changed during collection')
        if sha!=r['source']['sha256']:raise ValueError('source hash differs from parsed input: '+did)
        result[did]={'schema_version':'1.0.0','doc_id':did,'source_sha256':sha,'relative_path':relative,
          'modified_at_utc':utc_ns(after.st_mtime_ns),'modified_at_ns':str(after.st_mtime_ns),
          'collected_at_utc':collected,'origin':'local_filesystem_stat.st_mtime_ns',
          'semantics':'observed_file_modification_time','timezone_for_calendar_queries':'Asia/Seoul'}
    return result

def role_field(observations,role):
    matches=[copy.deepcopy(o) for o in observations if o['role']==role];values={o['value'] for o in matches}
    return {'value':next(iter(values)) if len(values)==1 else None,
      'status':'extracted' if len(values)==1 else 'needs_review' if values else 'not_observed_native',
      'role':role,'evidence':[e for o in matches for e in o['evidence']],'observations':matches}

def date_metadata(record,enriched,file_meta):
    if E.check_output(enriched,record):raise ValueError('invalid source enrichment')
    if file_meta['doc_id']!=record['doc_id'] or file_meta['source_sha256']!=record['source']['sha256'] or file_meta['relative_path']!=record['source']['relative_path']:raise ValueError('file metadata identity mismatch')
    if ns_utc(file_meta['modified_at_utc'])!=int(file_meta['modified_at_ns']):raise ValueError('file timestamp mismatch')
    obs=enriched['date_context']['observations']
    return {'schema_version':'1.0.0','doc_id':record['doc_id'],'source_sha256':record['source']['sha256'],
      'source_metadata':copy.deepcopy(file_meta),'visual_pending':bool(enriched['pending_visual_units']),
      'fields':{'표지일':role_field(obs,'cover_date'),'작성일':role_field(obs,'explicit_written_date'),
        '파일최종수정일':{'value':file_meta['modified_at_utc'],'status':'extracted','role':'file_modified_at',
          'evidence':[{'kind':'filesystem','origin':file_meta['origin'],'source_sha256':file_meta['source_sha256'],
                       'relative_path':file_meta['relative_path'],'modified_at_ns':file_meta['modified_at_ns']}],'observations':[]}}}

def attach_dates(index,dates):
    if set(index['documents'])!=set(dates):raise ValueError('date inventory mismatch')
    for did,doc in index['documents'].items():
        if dates[did]['doc_id']!=did or dates[did]['source_sha256']!=doc['source']['sha256']:raise ValueError('date source identity mismatch')
        doc['date_metadata']=copy.deepcopy(dates[did])
    index['date_search_version']=VERSION
    return index

def plan(query,as_of,system_terms,clients):
    roles=[f for f,pattern in ROLE_PATTERNS.items() if re.search(pattern,query)]
    desc=bool(SORT_DESC.search(query));asc=bool(SORT_ASC.search(query))
    p=old.old.plan(query,as_of,system_terms)
    p.update(date_role_search=False,sort=None,requires_clarification=False)
    if not roles:return p
    p['date_role_search']=True
    # Replace the old representative-date interpretation; retain kind/system conditions.
    p['filters']=[f for f in p['filters'] if f['field'] not in old.old.base.DATE_FIELDS]
    p['recognized']=[r for r in p['recognized'] if r.get('rule')!='calendar_period']
    p['warnings']=[w for w in p['warnings'] if w not in {'unsupported_or_yearless_date','unsupported_multiple_dates_comparison_or_negation','ambiguous_date_role'}]
    dates=list(old.old.previous.DATE_PATTERN.finditer(query))
    residual=SORT_DESC.sub(' ',SORT_ASC.sub(' ',query))
    remaining=old.old.previous.DATE_PATTERN.sub(' ',residual)
    bad=UNSUPPORTED.search(query) or re.search(r'\d+\s*(?:년|월|일)|최근|지난주|이번주|최신',remaining)
    if len(roles)!=1 or len(dates)>1 or bad or (desc and asc):
        p.update(requires_clarification=True);p['warnings'].append('unsupported_or_ambiguous_date_request');return p
    field=roles[0]
    if (desc or asc) and field!='파일최종수정일':
        p.update(requires_clarification=True);p['warnings'].append('sort_requires_file_modification_role');return p
    if desc or asc:p['sort']={'field':'파일최종수정일','direction':'asc' if asc else 'desc','tie_breakers':['score_desc','doc_id_asc']}
    if p['sort']:
        counts=list(RETURN_COUNT.finditer(residual))
        values={int(m[1]) for m in counts}
        if len(values)>1 or any(not 1<=v<=100 for v in values):
            p.update(requires_clarification=True);p['warnings'].append('invalid_or_conflicting_return_count');return p
        if counts:
            p['requested_limit']=next(iter(values))
            p['recognized'].append({'rule':'return_count','text':counts[0][0],'value':p['requested_limit']})
            residual=RETURN_COUNT.sub(' ',residual)
    if dates:
        try:start,end=old.old.previous.interval(dates[0][0],date.fromisoformat(as_of))
        except ValueError:
            p.update(requires_clarification=True);p['warnings'].append('invalid_calendar_date');return p
        if field=='파일최종수정일':
            low=datetime.combine(start,time.min,TZ).astimezone(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')
            high=datetime.combine(end+timedelta(days=1),time.min,TZ).astimezone(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')
            p['filters'] += [{'field':field,'op':'gte','value':low},{'field':field,'op':'lt','value':high}]
        else:p['filters'] += [{'field':field,'op':'gte','value':start.isoformat()},{'field':field,'op':'lte','value':end.isoformat()}]
        p['recognized'].append({'rule':'explicit_date_role','field':field,'text':dates[0][0]})
    elif not p['sort']:
        p.update(requires_clarification=True);p['warnings'].append('date_value_or_order_required');return p
    residual=old.old.previous.DATE_PATTERN.sub(' ',residual)
    for pattern in ROLE_PATTERNS.values():residual=re.sub(pattern,' ',residual)
    # Client names are explicit metadata conditions in the new date path.
    client_matches=[]
    for client in clients:
        if any(old.old.match(query,alias) for alias in set([client['name'],client['folder']]+client['aliases'])):client_matches.append(client)
    if len(client_matches)>1:
        p.update(requires_clarification=True);p['warnings'].append('multiple_clients');return p
    if client_matches:
        client=client_matches[0];p['filters'].append({'field':'거래처','op':'eq','value':client['name']})
        for alias in sorted(set([client['name'],client['folder']]+client['aliases']),key=len,reverse=True):
            for m in reversed(old.old.match(residual,alias)):residual=residual[:m.start()]+' '+residual[m.end():]
    content=residual
    for r in p['explicit_condition_rules']['recognized']:
        content=content.replace(r['text'],' ')
    content=re.sub(r'찾아\s*줘|찾아주세요|알려\s*줘|보여\s*줘|보여주세요|문서(?:를|가|는)?|파일(?:을|이|은)?|목록|정렬|순서|순으로|내림차순|오름차순',' ',content)
    content=re.sub(r'(?<!\S)(?:이|가|은|는|을|를|에|인|의|으로|순|날짜|명시적)(?!\S)',' ',content)
    p['lexical_query']=residual.strip();p['content_query']=' '.join(content.split())
    return p

def apply_filters(index,filters):
    legacy=[f for f in filters if f['field'] not in DATE_FIELDS]
    allowed,unknown=old.old.base.apply_filters(index,legacy)
    for f in legacy:
        uncertain={d for d in allowed if index['documents'][d]['metadata_statuses'].get(f['field'])!='extracted'}
        allowed-=uncertain;unknown|=uncertain
    for f in filters:
        if f['field'] not in DATE_FIELDS:continue
        if set(f)!={'field','op','value'} or f['op'] not in {'eq','gte','lte','lt'}:raise ValueError('invalid date filter')
        filetime=f['field']=='파일최종수정일'
        value=ns_utc(f['value']) if filetime else date.fromisoformat(f['value']).isoformat()
        if not filetime and value!=f['value']:raise ValueError('noncanonical date')
        kept=set()
        for did in allowed:
            item=index['documents'][did].get('date_metadata',{}).get('fields',{}).get(f['field'],{})
            if item.get('status')!='extracted' or item.get('value') is None:unknown.add(did);continue
            actual=ns_utc(item['value']) if filetime else item['value']
            if {'eq':actual==value,'gte':actual>=value,'lte':actual<=value,'lt':actual<value}[f['op']]:kept.add(did)
        allowed=kept
    return allowed,unknown

def search(index,bundle,query,as_of,system_terms,*,limit=10,statistics=None):
    if not isinstance(query,str) or not query.strip():raise ValueError('nonempty query required')
    if not isinstance(limit,int) or isinstance(limit,bool) or not 1<=limit<=100:raise ValueError('limit must be 1..100')
    p=plan(query,as_of,system_terms,index['clients'])
    limit=min(limit,p.get('requested_limit',limit))
    if p['requires_clarification']:
        return {'results':[],'query_plan':p,'unresolved_filter_documents':[],'eligible_documents':0,'status':'needs_clarification','model_called':False,'conditions_verified':False}
    allowed,unknown=apply_filters(index,p['filters'])
    if p['sort']:
        missing={d for d in allowed if index['documents'][d].get('date_metadata',{}).get('fields',{}).get('파일최종수정일',{}).get('status')!='extracted'}
        allowed-=missing;unknown|=missing
    # A substantive content request must match, even when a document-kind filter also matches.
    if p.get('content_query'):
        ts=set(old.tokens(p['content_query'],index,True));matched=set()
        for t in ts:
            matched.update(index['entries'][eid]['doc_id'] for eid in index['postings'].get(t,{}))
        allowed &= matched
    scores=defaultdict(float);n=index['entry_count'];avg=index['average_length'] or 1;k1=index['config']['bm25_k1'];b=index['config']['bm25_b']
    for term in sorted(set(old.tokens(p['lexical_query'],index,True))):
        posting=index['postings'].get(term,{})
        if not posting:continue
        idf=math.log(1+(n-len(posting)+.5)/(len(posting)+.5))
        for eid,tf in posting.items():
            entry=index['entries'][eid]
            if entry['doc_id'] in allowed:scores[eid]+=idf*tf*(k1+1)/(tf+k1*(1-b+b*entry['length']/avg))
    bydoc=defaultdict(list)
    for eid,score in scores.items():bydoc[index['entries'][eid]['doc_id']].append((score,eid))
    corpus,idfs=statistics or old.field_statistics(index,bundle,True);query_features=old.query_feature_tokens(p['lexical_query'],index,True);ranking=[]
    for did in sorted(allowed):
        hits=sorted(bydoc[did],key=lambda h:(-h[0],h[1]));boosts=[]
        for field,w in old.WEIGHTS.items():
            matched=sorted(query_features&corpus[did][field]);score=w*sum(idfs[t] for t in matched)
            if matched:boosts.append({'field':field,'weight':w,'matched_tokens':matched,'score':score,'sources':[v for v in bundle['features'][did][field] if old.feature_tokens(v['text'],index,True)&set(matched)]})
        lexical=hits[0][0] if hits else 0.;bonus=sum(v['score'] for v in boosts)
        if lexical+bonus<=0 and not (p['date_role_search'] and not p.get('content_query')):continue
        doc=index['documents'][did]
        ranking.append({'doc_id':did,'score':lexical+bonus,'lexical_score':lexical,'field_score':bonus,'field_matches':boosts,
          'evidence':[{'entry_id':eid,'score':score,**index['entries'][eid]} for score,eid in hits[:3]],'source':doc['source'],
          'metadata':doc['metadata'],'date_metadata':doc['date_metadata'],'native_chunk_count':doc['native_chunk_count'],
          'pending_visual_units':doc['pending_visual_units'],'metadata_conditions_checked':copy.deepcopy(p['filters']),
          'conditions_verified':False})
    if p['sort']:
        direction=1 if p['sort']['direction']=='asc' else -1
        ranking.sort(key=lambda r:(direction*ns_utc(r['date_metadata']['fields']['파일최종수정일']['value']),-r['score'],r['doc_id']))
    else:ranking.sort(key=lambda r:(-r['score'],r['doc_id']))
    return {'results':[{'rank':i,**r} for i,r in enumerate(ranking[:limit],1)],'query_plan':p,'unresolved_filter_documents':sorted(unknown),
      'eligible_documents':len(allowed),'ranked_documents_before_limit':len(ranking),'status':'ok','model_called':False,'conditions_verified':False}

if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('--run',required=True);a.add_argument('--query',required=True);a.add_argument('--as-of',required=True);a.add_argument('--limit',type=int,default=5);args=a.parse_args()
    folder=Path(args.run);ix=E.read_json(folder/'index.json');bundle=E.read_json(folder/'features.json')
    print(json.dumps(search(old.view(ix,bundle,context=True,intents=True),bundle,args.query,args.as_of,ix['system_terms'],limit=args.limit),ensure_ascii=False,indent=2))
