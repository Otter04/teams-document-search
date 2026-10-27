"""Source-vocabulary query planning. This module never reads evaluation answers."""
import calendar, copy, json, re, time, unicodedata, urllib.request
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

FIELDS={'거래처':'client','문서종류':'document_type','문서일자':'document_date','상태':'status',
 '대상시스템':'target_system','실행결과':'execution_result','통화':'currency','VAT':'vat',
 '표지일':'cover_date','작성일':'written_date','파일최종수정일':'file_modified_at'}
LABELS={v:k for k,v in FIELDS.items()}
TYPES={'계약서':['계약서','계약'], '견적서':['견적서','견적'], '제안서':['제안서','제안'],
 '네트워크 구성도':['네트워크 구성도','네트워크 도면'], '서버 구성도':['서버 구성도','서버 배치도'],
 '실행 로그':['로그','log'], '기타':['통화 메모','메모','메일','이메일']}
NEGATION=re.compile(r'제외|말고|아닌|빼고|않은')
DATE_RX=re.compile(r'(?:20\d{2}\s*년|작년|올해|지난해|금년)(?:\s*\d{1,2}\s*월)?(?:\s*\d{1,2}\s*일)?')
IDENT_RX=re.compile(r'[A-Za-z0-9]+(?:[._:/-][A-Za-z0-9]+)+')
def normal(s):return unicodedata.normalize('NFC',s).casefold()
def matches(text, term):
    return bool(re.search(r'(?<![a-z0-9])'+re.escape(normal(term))+r'(?![a-z0-9])',normal(text)))
def identifiers(text):return sorted({normal(m[0]) for m in IDENT_RX.finditer(text) if any(x.isdigit() for x in m[0])})
def words(text):return sorted(set(re.findall(r'[가-힣a-z0-9][가-힣a-z0-9_.:/-]*',normal(text))))
def calendar_range(text, ref):
    yr=ref.year-1 if ('작년' in text or '지난해' in text) else ref.year
    m=re.search(r'(20\d{2})\s*년',text)
    if m:yr=int(m[1])
    m=re.search(r'(\d{1,2})\s*월',text);mo=int(m[1]) if m else None
    m=re.search(r'(\d{1,2})\s*일',text);day=int(m[1]) if m else None
    low=date(yr,mo or 1,day or 1)
    high=date(yr,mo or 12,day or (calendar.monthrange(yr,mo)[1] if mo else 31))
    return {'gte':low.isoformat(),'lte':high.isoformat()}
def plan_rules(query, reference, ref_date=None):
    query=unicodedata.normalize('NFC',query).strip()
    ref=date.fromisoformat(ref_date) if ref_date else datetime.now(ZoneInfo('Asia/Seoul')).date()
    p={'query':query,'semantic':query,'keywords':query,'conditions':{},'condition_evidence':{},
       'boost':{},'exact':[],'identifiers':identifiers(query),'concepts':[],'relaxable':[],
       'reference_date':ref.isoformat(),'used_llm':False,'llm':{'attempted':False},
       'warnings':[],'requires_clarification':False,'sort':None,'requested_version':None}
    def add(k,v,e):p['conditions'][k]=v;p['condition_evidence'][k]=e
    clients=[c for c in reference['clients'] if any(matches(query,a) for a in [c['name'],c['folder']]+c['aliases'])]
    p['client_candidates']=[c['name'] for c in clients]
    if len(clients)==1:
        c=clients[0];alias=max((a for a in [c['name'],c['folder']]+c['aliases'] if matches(query,a)),key=len)
        add('client',c['name'],alias)
        if normal(c['name']) not in normal(query):p['keywords']+=' '+c['name']
    elif len(clients)>1:p['warnings'].append('multiple_clients');p['requires_clarification']=True
    found=[(k,a) for k,aliases in TYPES.items() for a in aliases if matches(query,a)]
    kinds={k for k,a in found}
    if len(kinds)==1:add('document_type',next(iter(kinds)),max((a for k,a in found),key=len))
    elif len(kinds)>1:p['warnings'].append('multiple_document_types')
    for s in reference['system_terms']:
        if matches(query,s):
            if 'target_system' in p['conditions']:p['conditions'].pop('target_system');p['warnings'].append('multiple_systems');break
            add('target_system',s,s)
    for word,value in [('서명본','서명본'),('초안','초안')]:
        if word in query:add('status',value,word)
    if re.search(r'최신|최종본|최종\s*견적',query):p['boost']['latest_version']=True
    for word,value in [('실패','실패'),('성공','성공'),('경고','경고')]:
        if word in query and p['conditions'].get('document_type')=='실행 로그':add('execution_result',value,word)
    if re.search(r'달러|\bUSD\b',query,re.I):add('currency','USD','달러' if '달러' in query else 'USD')
    if re.search(r'부가세\s*포함|VAT\s*포함',query,re.I):add('vat','포함',re.search(r'부가세\s*포함|VAT\s*포함',query,re.I)[0])
    role='document_date'
    if re.search(r'표지\s*(날짜|일자|일)',query):role='cover_date'
    elif re.search(r'작성\s*(일자|일)|작성된',query):role='written_date'
    elif '수정' in query:role='file_modified_at'
    elif p['conditions'].get('document_type')=='실행 로그':role='log_start'
    if '수정' in query and re.search(r'최근|최신|마지막|내림차순|오름차순|오래된',query):
        p['sort']={'field':'file_modified_at','direction':'asc' if re.search(r'오름차순|오래된',query) else 'desc'}
    dm=list(DATE_RX.finditer(query))
    if len(dm)==1:
        try:
            bounds=calendar_range(dm[0][0],ref)
            if role=='file_modified_at':
                lo=date.fromisoformat(bounds['gte']);hi=date.fromisoformat(bounds['lte'])+timedelta(days=1)
                bounds={'gte':lo.isoformat()+'T00:00:00+09:00','lt':hi.isoformat()+'T00:00:00+09:00'}
            add(role,bounds,dm[0][0])
        except ValueError:p['warnings'].append('invalid_calendar_date');p['requires_clarification']=True
    elif len(dm)>1:p['warnings'].append('multiple_date_ranges');p['requires_clarification']=True
    p['unresolved_date']=bool(re.search(r'여름|겨울|가을|봄쯤|분기|월말|월초|최근\s*\d|지난달|이번달',query))
    if p['unresolved_date']:p['requires_clarification']=True
    if NEGATION.search(query):p['warnings'].append('unsupported_negation');p['requires_clarification']=True
    v=re.search(r'(?<![a-z0-9])(?:v|rev)(\d+(?:\.\d+)*)',query,re.I)
    if v:p['requested_version']='v'+v[1]
    for concept in reference['rules']['concepts']:
        terms=concept['aliases']+[a['text'] for a in concept.get('abbreviations',[]) if any(matches(query,w) for w in a['requires_any'])]
        if any(matches(query,a) for a in terms):p['concepts'].append('concept:'+concept['id'])
    p['relaxable']=[k for k in [role,'document_type','status'] if k in p['conditions']]
    content=DATE_RX.sub(' ',p['keywords'])
    content=re.sub(r'(?:가장\s*)?(?:최근|최신|마지막으로)\s*수정(?:된|한)?|수정일\s*(?:내림차순|오름차순)|표지\s*(?:날짜|일자|일)|작성일|파일\s*최종\s*수정일',' ',content)
    content=re.sub(r'찾아\s*줘|찾아주세요|알려\s*줘|보여\s*줘|보여주세요|문서(?:를|가|는)?|파일(?:을|이|은)?|목록|최신순|오래된\s*순',' ',content)
    p['keywords']=' '.join(content.split())
    return p

def apply_mode(p, mode):
    p=copy.deepcopy(p);p['filter_mode']=mode
    if mode not in ['A','B']:raise ValueError('filter_mode must be A or B')
    # B softens all non-client conditions. A keeps explicit extracted conditions.
    hard_a={'client','document_type','document_date','cover_date','written_date','file_modified_at','log_start','status'}
    p['filters']={k:v for k,v in p['conditions'].items() if (mode=='A' and k in hard_a) or k=='client'}
    p['soft_conditions']={k:v for k,v in p['conditions'].items() if k not in p['filters']}
    return p

def conditional_llm(p, reference, url, model, timeout=2.5, attempt=1):
    trigger=(not p['conditions'] and len(p['query'].split())>=4) or len(p['client_candidates'])>1 or p['unresolved_date']
    if not trigger or 'unsupported_negation' in p['warnings'] or 'invalid_calendar_date' in p['warnings']:return p
    original=copy.deepcopy(p);p=copy.deepcopy(p);start=time.perf_counter();p['llm']={'attempted':True,'status':'pending','timeout_seconds':timeout,'attempts':attempt}
    allowed={k:sorted(set(v)) for k,v in {'client':[c['name'] for c in reference['clients']],
      'document_type':list(TYPES),'target_system':reference['system_terms'],'status':['초안','서명본','최종']}.items()}
    schema={'type':'object','properties':{'conditions':{'type':'array','items':{'type':'object','properties':{
      'field':{'type':'string','enum':list(allowed)},'value':{'type':'string'},'evidence':{'type':'string'}},
      'required':['field','value','evidence'],'additionalProperties':False}},'keywords':{'type':'string'}},
      'required':['conditions','keywords'],'additionalProperties':False}
    prompt='검색 질문을 분석한다. 문서 내용에 답하지 않는다. 명시된 조건만 반환한다. evidence는 질문의 연속 원문이다. 추정하거나 모호한 날짜를 확정하지 않는다. keywords는 조건 외 검색 핵심어이다. 허용 값: '+json.dumps(allowed,ensure_ascii=False)
    body={'model':model,'temperature':0,'max_tokens':300,'chat_template_kwargs':{'enable_thinking':False},
      'messages':[{'role':'system','content':prompt},{'role':'user','content':p['query']}],
      'response_format':{'type':'json_schema','json_schema':{'name':'query_plan','strict':True,'schema':schema}}}
    try:
        req=urllib.request.Request(url+'/chat/completions',data=json.dumps(body).encode(),headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(req,timeout=timeout) as r:raw=json.load(r)
        choice=raw['choices'][0]
        if choice['finish_reason']!='stop':raise ValueError('truncated_response')
        out=json.loads(choice['message']['content'])
        if set(out)!={'conditions','keywords'} or not isinstance(out['keywords'],str) or not isinstance(out['conditions'],list):raise ValueError('invalid_schema')
        candidate=copy.deepcopy(p['conditions']);evidence=copy.deepcopy(p['condition_evidence'])
        for c in out['conditions']:
            if set(c)!={'field','value','evidence'}:raise ValueError('invalid_schema')
            k,v,e=c['field'],c['value'],c['evidence']
            if k not in allowed or v not in allowed[k] or not isinstance(e,str) or not e or e not in p['query']:raise ValueError('unsupported_value_or_evidence')
            # Do not let a well-formed model output turn an unrelated quote into a hard filter.
            if k=='client':
                cl=next(x for x in reference['clients'] if x['name']==v)
                supported=any(matches(e,a) for a in [cl['name'],cl['folder']]+cl['aliases'])
            elif k=='document_type':supported=any(matches(e,a) for a in TYPES[v])
            else:supported=matches(e,v)
            if not supported or (k in candidate and candidate[k]!=v):raise ValueError('contradictory_or_ungrounded_condition')
            if k=='client' and len(p['client_candidates'])>1:continue
            candidate[k]=v;evidence[k]=e
        # Keywords may be narrowed only to literal query words; no new entities.
        if any(w not in normal(p['query']) for w in words(out['keywords'])):raise ValueError('ungrounded_keywords')
        p['conditions']=candidate;p['condition_evidence']=evidence
        if out['keywords'].strip():p['keywords']=out['keywords'].strip()
        p['used_llm']=True;p['llm']['status']='accepted'
    except Exception as e:
        remaining=timeout-(time.perf_counter()-start)
        if isinstance(e,(ValueError,KeyError,TypeError)) and attempt==1 and remaining>0.1:
            retried=conditional_llm(original,reference,url,model,remaining,2)
            retried['llm']['first_error']=type(e).__name__+': '+str(e)[:160]
            retried['llm']['elapsed_seconds']=time.perf_counter()-start
            retried['llm']['timeout_seconds']=timeout
            return retried
        p['llm'].update(status='rules_fallback',error=type(e).__name__+': '+str(e)[:160])
    p['llm']['elapsed_seconds']=time.perf_counter()-start
    if p['unresolved_date']:
        p['requires_clarification']=True;p['warnings'].append('ambiguous_date_requires_explicit_range')
    return p

def es_filters(p):
    clauses=[]
    for key,value in p['filters'].items():
        clauses.append({'term':{'metadata_statuses.'+key:'extracted'}})
        clauses.append({'range':{'metadata.'+key:value}} if isinstance(value,dict) else {'term':{'metadata.'+key:value}})
    if p['sort']:clauses.append({'exists':{'field':'metadata.file_modified_at'}})
    return clauses
