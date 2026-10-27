#!/usr/bin/env python3
"""Structure-aware native chunks and local lexical search. No models or gold input."""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import unicodedata

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parent/'rag-enrichment-v1'))
import enrich
VERSION='native-search-0.1.1'
CONFIG={'body_char_limit':1200,'long_block_overlap_chars':120,'log_window_minutes':5,
        'token_budget_status':'pending_model_selection','tokenizer':'unicode_words_and_korean_bigrams',
        'bm25_k1':1.2,'bm25_b':0.75,'document_aggregation':'max_entry_score'}
HEADER_WORDS={'no','품목','규격','수량','단가','금액','갑','을','호스트명','역할','os','사양','ip','비고',
              '버전','일자','내용','작성자','단계','주요활동','산출물','등급','인원','주요업무','구분'}
DATE_FIELDS={'문서일자','계약시작일','계약종료일','견적유효기간','로그시작','로그종료'}

def now():return datetime.now(timezone.utc).isoformat()
def unique_records(path):
    rows=enrich.read_lines(path);result={r['doc_id']:r for r in rows}
    if len(result)!=len(rows):raise ValueError('duplicate doc_id')
    return result

def literals(record):
    return [b for b in sorted(record['blocks'],key=lambda b:b['order'])
            if b['type'] not in ('slide','table') and not b['content_refs'] and b['text'].strip()]

def slices(text,limit,overlap):
    if limit<32 or not 0<=overlap<limit//2:raise ValueError('invalid chunk size/overlap')
    start=0
    while start<len(text):
        end=min(start+limit,len(text))
        if end<len(text):
            breaks=[m.end() for m in re.finditer(r'\s+',text[start:end])]
            if breaks and breaks[-1]>=limit*.6:end=start+breaks[-1]
        yield start,end
        if end==len(text):break
        start=max(start+1,end-overlap)

def reference(block,start=0,end=None):
    return {'block_id':block['block_id'],'start':start,'end':len(block['text']) if end is None else end,'loc':block['loc']}

def header_rows(rows):
    found=[]
    for row in rows:
        values=[enrich.squash(c['text']).casefold() for c in row['cells'] if c['text'].strip()]
        if len(values)>=2 and all(v in HEADER_WORDS for v in values):found.append(row)
    return found

def make_chunks(record,metadata,config=None):
    config=dict(CONFIG if config is None else config)
    errors=enrich.input_errors(record)+enrich.check_output(metadata,record)
    if errors:raise ValueError('; '.join(errors[:5]))
    limit=config['body_char_limit'];overlap=config['long_block_overlap_chars']
    source_blocks={b['block_id']:b for b in record['blocks']}
    filters={f:v['value'] for f,v in metadata['fields'].items() if v['status']=='extracted'}
    field_statuses={f:v['status'] for f,v in metadata['fields'].items()}
    chunks=[];table_audit=[]
    def emit(parts,kind,section,table=None,headers=(),warnings=()):
        text='\n'.join(source_blocks[p['block_id']]['text'][p['start']:p['end']] for p in parts)
        if not text.strip():return
        loc=parts[0]['loc']
        position=' '.join(f'{k}={loc[k]}' for k in ('page','slide','sheet','line_start') if k in loc)
        context=' | '.join([record['source']['file_name']]+[f'{f}={filters[f]}' for f in ('거래처','문서종류','문서일자') if f in filters]+[v for v in (section,position) if v])
        repeated=[reference(h) for h in headers if h['block_id'] not in {p['block_id'] for p in parts}]
        payload={'kind':kind,'text':text,'context_header':context,'source_refs':parts,'context_refs':repeated,
            'table_header_text':'\n'.join(h['text'] for h in headers),'table_id':table['block_id'] if table else None,
            'table_header_status':'rule_identified' if headers else 'unknown' if table else 'not_applicable',
            'heading_path':[section] if section else [],'filter_metadata':filters,'metadata_statuses':field_statuses,
            'body_chars':len(text),'token_count':None,'token_budget_status':'pending_model_selection','warnings':list(warnings)}
        payload['chunk_id']=record['doc_id']+'-C-'+enrich.record_hash({'source':record['source']['sha256'],'config':config,'payload':payload})[:16]
        chunks.append(payload)
    def pack(blocks,kind,section,table=None,headers=()):
        parts=[];size=0
        for block in blocks:
            if not block['text'].strip():continue
            long=len(block['text'])>limit
            spans=list(slices(block['text'],limit,overlap))
            for start,end in spans:
                n=end-start
                if parts and size+n+1>limit:emit(parts,kind,section,table,headers);parts=[];size=0
                if long:
                    if parts:emit(parts,kind,section,table,headers);parts=[];size=0
                    emit([reference(block,start,end)],kind,section,table,headers,
                         ['table_row_split' if table else 'long_block_split'])
                else:parts.append(reference(block,start,end));size+=n+(1 if len(parts)>1 else 0)
        if parts:emit(parts,kind,section,table,headers)
    pending=[];key=None;section='';last_window=None;consumed=set()
    def flush():
        nonlocal pending
        if pending:pack(pending,'log_window' if record['source']['format']=='log' else 'text',section)
        pending=[]
    for block in sorted(record['blocks'],key=lambda b:b['order']):
        if block['block_id'] in consumed:continue
        if block['type']=='table':
            flush();rows=[b for b in record['blocks'] if b['parent_id']==block['block_id'] and b['type']=='table_row']
            rows.sort(key=lambda b:b['order']);consumed.update(b['block_id'] for b in rows)
            headers=header_rows(rows);first=headers[0]['order'] if headers else None
            pre=[r for r in rows if first is not None and r['order']<first]
            body=[r for r in rows if first is None or r['order']>=first]
            title=' / '.join(block['heading_path']) or section
            if pre:pack(pre,'table_preamble',title)
            pack(body,'table_rows',title,block,headers)
            table_audit.append({'table_id':block['block_id'],'native_header_rows':block['table']['header_rows'],
                'header_block_ids':[h['block_id'] for h in headers],'status':'rule_identified' if headers else 'unknown',
                'header_semantics_independently_validated':False})
            key=None;continue
        if block['type'] in ('slide','table') or block['content_refs'] or not block['text'].strip():continue
        loc=block['loc'];frame=tuple((k,loc.get(k)) for k in ('kind','page','slide','sheet'))
        is_heading=block['type']=='heading' or bool(re.fullmatch(r'제\s*\d+\s*조\s*\([^\n]+\)',block['text'].strip()))
        if is_heading:
            flush();section=block['text'].strip()
        if record['source']['format']=='log':
            match=re.search(r'\[?(\d{4}-\d{2}-\d{2})[ T](\d{2}):(\d{2}):\d{2}',block['text'])
            if match:
                last_window=(match[1],int(match[2]),int(match[3])//config['log_window_minutes'])
            newkey=(frame,last_window)
        else:newkey=(frame,section)
        if key is not None and key!=newkey:flush()
        key=newkey;pending.append(block)
    flush()
    return {'schema_version':'1.0.0','record_kind':'native_chunks','doc_id':record['doc_id'],'source':record['source'],
        'input_record_sha256':enrich.record_hash(record),'metadata_record_sha256':enrich.record_hash(metadata),
        'scope':'native_only','model_called':False,'config':config,'chunks':chunks,'table_audit':table_audit,
        'filter_metadata':filters,'metadata_statuses':field_statuses,'pending_visual_units':metadata['pending_visual_units'],
        'deferred':['vision','embedding','model_token_budget','semantic_summary','family_and_latest_version']}

def validate_chunks(output,record,metadata):
    errors=[];blocks={b['block_id']:b for b in literals(record)};covered=defaultdict(list)
    if output['doc_id']!=record['doc_id'] or output['source']!=record['source']:errors.append('source mismatch')
    if output['input_record_sha256']!=enrich.record_hash(record) or output['metadata_record_sha256']!=enrich.record_hash(metadata):errors.append('input hash mismatch')
    expected={f:v['value'] for f,v in metadata['fields'].items() if v['status']=='extracted'}
    if output['filter_metadata']!=expected:errors.append('unresolved or altered document metadata')
    if output['pending_visual_units']!=metadata['pending_visual_units']:errors.append('pending vision queue changed')
    ids=[c['chunk_id'] for c in output['chunks']]
    if len(ids)!=len(set(ids)):errors.append('duplicate chunk IDs')
    audit={a['table_id']:a for a in output['table_audit']}
    for chunk in output['chunks']:
        if chunk['filter_metadata']!=expected:errors.append('unresolved or altered chunk metadata')
        if not chunk['context_header']:errors.append('missing context header')
        if len(chunk['text'])!=chunk['body_chars'] or len(chunk['text'])>output['config']['body_char_limit']:errors.append('body length violation')
        parts=[]
        for ref in chunk['source_refs']+chunk['context_refs']:
            b=blocks.get(ref['block_id'])
            if b is None or not 0<=ref['start']<ref['end']<=len(b['text']) or ref['loc']!=b['loc']:
                errors.append('invalid source reference');continue
        for ref in chunk['source_refs']:
            if ref['block_id'] not in blocks:continue
            b=blocks[ref['block_id']];parts.append(b['text'][ref['start']:ref['end']]);covered[ref['block_id']].append((ref['start'],ref['end']))
        if chunk['text']!='\n'.join(parts):errors.append('body differs from cited source')
        if chunk['table_id']:
            a=audit[chunk['table_id']];headers=a['header_block_ids']
            expected_header='\n'.join(blocks[h]['text'] for h in headers)
            if chunk['table_header_text']!=expected_header:errors.append('missing or altered table header')
            present={r['block_id'] for r in chunk['source_refs']+chunk['context_refs']}
            if not set(headers)<=present:errors.append('header reference missing')
    for bid,b in blocks.items():
        end=0
        for start,stop in sorted(covered[bid]):
            if start>end:errors.append('source character gap');break
            end=max(end,stop)
        if end<len(b['text']):errors.append('source block incomplete')
    return errors

def tokens(text,clients=()):
    text=unicodedata.normalize('NFC',text).casefold()
    additions=[]
    for client in clients:
        aliases=[client['name'],client['folder']]+client['aliases']
        if any(re.search(r'(?<![a-z0-9가-힣])'+re.escape(alias.casefold())+r'(?![a-z0-9가-힣])',text) for alias in aliases):additions.append(client['name'])
    result=[]
    for word in re.findall(r'[a-z0-9]+(?:[._:/-][a-z0-9]+)*|[가-힣]+',text+' '+' '.join(additions)):
        if re.fullmatch(r'[가-힣]+',word):
            result.append('w:'+word)
            if len(word)>1:result.extend('k:'+word[i:i+2] for i in range(len(word)-1))
        else:result.append('w:'+word)
    return result

def build_index(records,clients):
    entries={};documents={};postings=defaultdict(dict)
    for record in records:
        identity=record['doc_id'];documents[identity]={'source':record['source'],'metadata':record['filter_metadata'],
            'metadata_statuses':record['metadata_statuses'],'pending_visual_units':record['pending_visual_units'],
            'native_chunk_count':len(record['chunks']),'summary':None,'embedding_status':'pending_model_selection'}
        text=' '.join([record['source']['file_name'],record['source']['relative_path']]+[f'{k} {v}' for k,v in record['filter_metadata'].items()])
        entries[identity+'-document']={'doc_id':identity,'kind':'document_metadata','text':text,'source_refs':[],
                                      'context_header':'','table_header_text':'','context_refs':[]}
        for c in record['chunks']:
            entries[c['chunk_id']]={'doc_id':identity,'kind':'native_chunk','text':c['text'],'context_header':c['context_header'],
                'table_header_text':c['table_header_text'],'source_refs':c['source_refs'],'context_refs':c['context_refs']}
    for eid,entry in entries.items():
        terms=tokens(' '.join([entry['context_header'],entry['table_header_text'],entry['text']]),clients)
        entry['length']=len(terms)
        for term,tf in Counter(terms).items():postings[term][eid]=tf
    return {'schema_version':'1.0.0','engine':'python_local_bm25','config':CONFIG,'clients':clients,'documents':documents,
        'entries':entries,'postings':dict(postings),'entry_count':len(entries),'average_length':sum(e['length'] for e in entries.values())/max(1,len(entries)),
        'model_called':False,'scope':'keyword_only_development_baseline'}

def apply_filters(index,filters):
    if not isinstance(filters,(list,tuple)):raise ValueError('filters must be a list')
    allowed=set(index['documents']);unknown=set()
    for condition in filters:
        if not isinstance(condition,dict):raise ValueError('filter must be an object')
        if set(condition)!={'field','op','value'}:raise ValueError('filter requires field/op/value only')
        field,op,value=condition['field'],condition['op'],condition['value']
        if field not in enrich.ALL_FIELDS or op not in ('eq','in','gte','lte'):raise ValueError('unsupported filter')
        if op=='in':
            if not isinstance(value,list) or not value or not all(isinstance(v,str) and v.strip() for v in value):raise ValueError('in filter requires nonempty strings')
        elif not isinstance(value,str) or not value.strip():raise ValueError('filter value must be a nonempty string')
        if op in ('gte','lte') and field not in DATE_FIELDS|{'금액'}:raise ValueError('range only supported for dates/times/amount')
        if field=='금액' and op in ('gte','lte') and not value.isdigit():raise ValueError('invalid numeric filter')
        if field in DATE_FIELDS:
            fmt='%Y-%m-%d %H:%M' if field in {'로그시작','로그종료'} else '%Y-%m-%d'
            for date_value in value if op=='in' else [value]:
                try:
                    if datetime.strptime(date_value,fmt).strftime(fmt)!=date_value:raise ValueError()
                except ValueError:raise ValueError('date filter requires canonical '+fmt)
        next_allowed=set()
        for identity in allowed:
            actual=index['documents'][identity]['metadata'].get(field)
            if actual is None:unknown.add(identity);continue
            a=actual.casefold();v=value if op=='in' else value.casefold()
            if op=='eq':match=a==v
            elif op=='in':match=a in {x.casefold() for x in v}
            else:
                a,v=(int(a),int(v)) if field=='금액' else (a,v)
                match=a>=v if op=='gte' else a<=v
            if match:next_allowed.add(identity)
        allowed=next_allowed
    return allowed,unknown

def search(index,query,filters=(),limit=10):
    if not isinstance(query,str) or not query.strip():return {'results':[],'unresolved_filter_documents':[],'conditions_verified':False}
    if not 1<=limit<=100:raise ValueError('limit must be 1..100')
    allowed,unknown=apply_filters(index,filters);scores=defaultdict(float)
    n=index['entry_count'];avg=index['average_length'] or 1;k1=index['config']['bm25_k1'];b=index['config']['bm25_b']
    for term in sorted(set(tokens(query,index['clients']))):
        postings=index['postings'].get(term,{})
        if not postings:continue
        idf=math.log(1+(n-len(postings)+.5)/(len(postings)+.5))
        for eid,tf in postings.items():
            entry=index['entries'][eid]
            if entry['doc_id'] not in allowed:continue
            scores[eid]+=idf*tf*(k1+1)/(tf+k1*(1-b+b*entry['length']/avg))
    bydoc=defaultdict(list)
    for eid,score in scores.items():bydoc[index['entries'][eid]['doc_id']].append((score,eid))
    ranking=[]
    for identity,hits in bydoc.items():
        hits.sort(key=lambda h:(-h[0],h[1]));doc=index['documents'][identity]
        evidence=[{'entry_id':eid,'score':score,**index['entries'][eid]} for score,eid in hits[:3]]
        ranking.append({'doc_id':identity,'score':hits[0][0],'evidence':evidence,'source':doc['source'],
            'metadata':doc['metadata'],'native_chunk_count':doc['native_chunk_count'],
            'pending_visual_units':doc['pending_visual_units'],'conditions_verified':False})
    ranking.sort(key=lambda r:(-r['score'],r['doc_id']))
    return {'results':[{'rank':i,**r} for i,r in enumerate(ranking[:limit],1)],
            'unresolved_filter_documents':sorted(unknown),'conditions_verified':False}

def build(args):
    out=Path(args.output)
    if out.exists():raise ValueError('output directory must be new')
    source=unique_records(args.parsed);meta=unique_records(args.metadata)
    if source.keys()!=meta.keys():raise ValueError('input document inventory mismatch')
    outputs=[]
    for identity,r in source.items():
        result=make_chunks(r,meta[identity]);errors=validate_chunks(result,r,meta[identity])
        if errors:raise ValueError(identity+': '+'; '.join(errors))
        outputs.append(result)
    clients=enrich.read_json(args.reference)['clients'];index=build_index(outputs,clients)
    out.mkdir(parents=True);enrich.save_lines(out/'chunks.jsonl',outputs);enrich.dump(out/'index.json',index)
    enrich.dump(out/'provenance.json',{'created_at_utc':now(),'implementation':VERSION,'model_called':False,'network_calls':0,
        'inputs':{str(Path(p).resolve()):enrich.digest(p) for p in [args.parsed,args.metadata,args.reference]},
        'code_sha256':enrich.digest(__file__),'contract_sha256':enrich.digest(ROOT/'CONTRACT.md'),
        'config':CONFIG,'documents':len(outputs),'chunks':sum(len(r['chunks']) for r in outputs),'index_entries':len(index['entries']),
        'gold_read_by_builder':False,'outputs':{name:enrich.digest(out/name) for name in ('chunks.jsonl','index.json')}})
    print(json.dumps({'documents':len(outputs),'chunks':sum(len(r['chunks']) for r in outputs),'index_entries':len(index['entries'])}))

def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    b=sub.add_parser('build')
    for name in ('parsed','metadata','reference','output'):b.add_argument('--'+name,required=True)
    s=sub.add_parser('search');s.add_argument('--index',required=True);s.add_argument('--query',required=True)
    s.add_argument('--filters',default='[]');s.add_argument('--limit',type=int,default=5)
    args=p.parse_args()
    if args.command=='build':build(args)
    else:print(json.dumps(search(enrich.read_json(args.index),args.query,json.loads(args.filters),args.limit),ensure_ascii=False,indent=2))

if __name__=='__main__':main()
