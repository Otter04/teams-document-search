"""Offline quality gate before common-block conversion.

No model/API/network access. Frozen v1 schema and converter remain unchanged.
Only native source context supplied by the caller is used, never gold labels.
Reject/review does not repair, delete, relocate, or guess model content.
"""
import importlib.util
import json
import math
import re
import unicodedata
from pathlib import Path

HERE=Path(__file__).resolve().parent
VERSION='vision-quality-2.0.0'
spec=importlib.util.spec_from_file_location('vision_contract_v1',HERE.parent/'rag-vision-v1/contract.py')
base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)

def norm(s):
    return re.sub(r'\s+','',unicodedata.normalize('NFC',str(s)).replace('㈜','(주)').replace('×','x'))

def same_region(a,b):
    """Conservative geometry check; equal degenerate boxes remain base failures."""
    if not isinstance(a,list) or not isinstance(b,list) or len(a)!=4 or len(b)!=4:return False
    if not all(isinstance(x,(int,float)) and math.isfinite(x) for x in a+b):return False
    if a==b:return True
    aa=max(0,a[2]-a[0])*max(0,a[3]-a[1]);ba=max(0,b[2]-b[0])*max(0,b[3]-b[1])
    if not aa or not ba:return False
    intersection=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
    return intersection/min(aa,ba)>=0.7

def literals(w):
    out=[]
    for i,t in enumerate(w.get('texts',[])):
        if isinstance(t,dict) and isinstance(t.get('text'),str):out.append(dict(path=f'texts[{i}]',text=t['text'],bbox=t.get('bbox'),kind='text'))
    for i,t in enumerate(w.get('tables',[])):
        for j,c in enumerate(t.get('cells',[])):
            if isinstance(c,dict) and isinstance(c.get('text'),str):out.append(dict(path=f'tables[{i}].cells[{j}]',text=c['text'],bbox=c.get('bbox'),kind='cell',table=i,slot=(c.get('row'),c.get('column'))))
    for i,f in enumerate(w.get('figures',[])):
        for j,n in enumerate(f.get('nodes',[])):
            if isinstance(n,dict) and isinstance(n.get('label'),str):out.append(dict(path=f'figures[{i}].nodes[{j}]',text=n['label'],bbox=n.get('bbox'),kind='node'))
    return out

def native_literals(context):
    """Exact full strings and lines of supplied native context, no references."""
    out={}
    for b in context or []:
        strings=[b.get('text','')]+[c.get('text','') for c in b.get('cells',[])]
        for s in strings:
            if not isinstance(s,str):continue
            for t in [s]+s.splitlines():
                if len(norm(t))>=6:out.setdefault(norm(t),dict(text=t,source_block_id=b.get('block_id')))
    return list(out.values())

def check_quality(w,native_context=None):
    issues=[]
    def add(code,severity,paths,detail,**evidence):
        issues.append(dict(code=code,severity=severity,paths=paths,detail=detail,evidence=evidence))
    ls=literals(w);claims=[]
    # Repetition requires same location; equal values in separate cells allowed.
    for i,a in enumerate(ls):
        an=norm(a['text'])
        if len(an)<6:continue
        for b in ls[:i]:
            bn=norm(b['text'])
            if len(bn)<6:continue
            if a['kind']==b['kind']=='cell':continue # use grid/whole-table checks
            exact=an==bn
            cross=a['kind']!=b['kind'] and min(len(an),len(bn))>=8 and min(len(an),len(bn))/max(len(an),len(bn))>=0.6 and (an in bn or bn in an)
            if (exact or cross) and same_region(a['bbox'],b['bbox']):
                add('DUPLICATE_LITERAL','error',[b['path'],a['path']],'Same/contained literal in the same image region.',text=a['text'],other_text=b['text']);break
    signatures=[]
    for i,t in enumerate(w.get('tables',[])):
        seen={};sig=[]
        for j,c in enumerate(t.get('cells',[])):
            path=f'tables[{i}].cells[{j}]';slot=(c.get('row'),c.get('column'))
            if None not in slot and slot in seen:add('DUPLICATE_CELL_SLOT','error',[seen[slot],path],'A cell anchor is emitted more than once.',slot=slot)
            seen[slot]=path
            sig.append((c.get('row'),c.get('column'),c.get('row_span'),c.get('column_span'),norm(c.get('text',''))))
            status=c.get('value_status');text=c.get('text','')
            if status=='known' and not str(text).strip():add('KNOWN_CELL_EMPTY','error',[path],'known cell has no text; blank or unreadable must be explicit.')
            if status=='unreadable' and str(text).strip():
                add('UNREADABLE_CELL_WITH_TEXT','review',[path],'May be partially read; do not assume the existing text is correct or delete it.',text=text)
            if status=='unreadable' and w.get('status')=='complete':
                add('COMPLETE_WITH_UNREADABLE_CELL','error',['status',path],'Page reports complete while a cell reports unreadable.')
        signature=tuple(sorted(sig,key=repr))
        for j,other,region in signatures:
            if signature and signature==other and same_region(t.get('bbox'),region):
                add('DUPLICATE_TABLE','error',[f'tables[{j}]',f'tables[{i}]'],'Same cell grid and content repeated in the same region.');break
        signatures.append((i,signature,t.get('bbox')))
    relations=[]
    for i,f in enumerate(w.get('figures',[])):
        ids={n.get('id'):n for n in f.get('nodes',[])}
        for j,c in enumerate(f.get('claims',[])):
            if not isinstance(c.get('text'),str):continue
            current=dict(path=f'figures[{i}].claims[{j}]',text=c['text'],bbox=c.get('bbox'),status=c.get('status'))
            for old in claims:
                if len(norm(current['text']))>=6 and norm(current['text'])==norm(old['text']) and same_region(current['bbox'],old['bbox']):
                    add('DUPLICATE_CLAIM','error',[old['path'],current['path']],'Same explanatory claim repeated in the same region.',text=current['text']);break
            claims.append(current)
        for j,r in enumerate(f.get('relations',[])):
            a=ids.get(r.get('from_node'));b=ids.get(r.get('to_node'))
            if not a or not b or not a.get('label') or not b.get('label'):continue
            endpoints=[(norm(n['label']),tuple(n.get('bbox',[]))) for n in [a,b]]
            if r.get('direction') in ['undirected','bidirectional']:endpoints.sort(key=repr)
            sig=(tuple(endpoints),r.get('direction'),r.get('label'));path=f'figures[{i}].relations[{j}]'
            old=next((p for s,p,region in relations if s==sig and same_region(region,r.get('bbox'))),None)
            if old:add('DUPLICATE_RELATION','error',[old,path],'Same endpoints, direction and label repeated.')
            relations.append((sig,path,r.get('bbox')))
    # Claim -> literal matching is NOT automatic relocation or evidence of
    # hallucination. It places the response on review hold, with source IDs.
    for src in native_literals(native_context):
        sn=norm(src['text'])
        if any(sn in norm(l['text']) for l in ls):continue
        # Allow source paragraph split across adjacent output text fields.
        if sn in ''.join(norm(l['text']) for l in ls):continue
        matches=[c for c in claims if sn in norm(c['text'])]
        if matches:add('SOURCE_LITERAL_ONLY_IN_CLAIMS','review',[c['path'] for c in matches],
            'Supplied native source literal appears only in explanation fields, not literal fields.',**src)
    # Bad coordinates can hide repeated text. Native occurrence counts provide
    # a second signal. A layout-independent count is review-only, not deletion.
    native_units=[]
    for b in native_context or []:
        native_units.extend([norm(c.get('text','')) for c in b['cells']] if b.get('cells') else [norm(b.get('text',''))])
    for src in native_literals(native_context):
        sn=norm(src['text'])
        if len(sn)<8:continue
        expected=sum(s.count(sn) for s in native_units)
        matched=[l for l in ls if sn in norm(l['text'])]
        observed=sum(norm(l['text']).count(sn) for l in matched)
        if expected and observed>expected:
            add('DUPLICATE_SOURCE_LITERAL_REVIEW','review',[l['path'] for l in matched],
                'Literal repeats more often than in supplied native context; inspect location/segmentation before deduplication.',
                **src,source_occurrences=expected,output_occurrences=observed)
    if w.get('status')=='unreadable' and any(str(t.get('text','')).strip() for t in w.get('texts',[])):
        add('UNREADABLE_PAGE_WITH_TEXT','review',['status','texts'],'Page has readable text; consider partial after source review.')
    return issues

def validate_response(response,item,expected_model):
    """No admission of prefixes. Caller may separately inspect partial diagnostics."""
    errors=[];data=None
    if response.get('model')!=expected_model:errors.append('unexpected model')
    if response.get('provider')!='DeepInfra':errors.append('unexpected provider')
    if response.get('error'):errors.append('response contains error')
    reasoning=((response.get('usage') or {}).get('completion_tokens_details') or {}).get('reasoning_tokens')
    if expected_model=='qwen/qwen3.6-35b-a3b' and isinstance(reasoning,(int,float)) and reasoning>0:
        errors.append('reasoning tokens generated despite frozen disabled reasoning')
    choices=response.get('choices') or []
    if len(choices)!=1:errors.append('expected one choice')
    else:
        if choices[0].get('finish_reason')!='stop':errors.append('incomplete response (not stop)')
        content=choices[0].get('message',{}).get('content')
        try:
            def reject_constant(x):raise ValueError('non-finite JSON number')
            def pairs(ps):
                d={}
                for k,v in ps:
                    if k in d:raise ValueError('duplicate JSON object key: '+k)
                    d[k]=v
                return d
            data=json.loads(content,parse_constant=reject_constant,object_pairs_hook=pairs)
        except (ValueError,TypeError) as e:errors.append('invalid JSON: '+str(e)[:200])
    # Schema is checked first so quality rules can rely on typed containers.
    if data is None:errors.append('missing or null extraction object')
    schema_errors=list(base.VALIDATOR.iter_errors(data)) if data is not None else []
    if data is not None:
        errors+=base.check_wire(data)
    issues=check_quality(data,item.get('native_context',[])) if data is not None and not schema_errors else []
    decision='reject' if errors or any(i['severity']=='error' for i in issues) else 'review' if issues else 'candidate'
    return dict(validator_version=VERSION,decision=decision,baseline_errors=errors,issues=issues,
        meaning_accuracy_verified=False,native_context_available=bool(item.get('native_context')),data=data)

def convert_checked(record,item,response,model):
    """Only supported offline entrypoint to conversion under the new gate."""
    assessment=validate_response(response,item,model)
    if assessment['decision']!='candidate':raise ValueError('quality gate '+assessment['decision'])
    return base.convert(record,item,assessment['data'],model),assessment
