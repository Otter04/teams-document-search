"""Score stored Orin responses with existing frozen content/contract criteria."""
import copy
import statistics
from pathlib import Path
from adapter import *
from jsonschema import Draft202012Validator

def timing(rows):
    times=[r['elapsed_ms']/1000 for r in rows if isinstance(r.get('elapsed_ms'),(int,float))]
    return {'count':len(times),'median_seconds':statistics.median(times) if times else None,
            'total_seconds':sum(times),'max_seconds':max(times) if times else None,
            'output_tokens':sum((r.get('response',{}).get('usage') or {}).get('completion_tokens',0) or 0 for r in rows),
            'input_tokens':sum((r.get('response',{}).get('usage') or {}).get('prompt_tokens',0) or 0 for r in rows)}

def vision_row(response,item,reference,model,provider):
    assessment=assess_vision(response,item,model,provider)
    raw=((response.get('choices') or [{}])[0].get('message') or {}).get('content') or '{}'
    w,complete,closed=review.recover(raw)
    # Prefix metrics are diagnostics only, matching the old source review.
    if not isinstance(w,dict):w={}
    try:
        observed=review.text_items(w)
        cov=review.coverage(reference,observed)
        tables=review.table_scores(reference,w)
        graph=review.graph_scores(reference,w,True)
        dup=review.duplicates(reference,w)
    except (KeyError,TypeError,AttributeError):
        w={};cov=review.coverage(reference,[]);tables=review.table_scores(reference,w)
        graph=review.graph_scores(reference,w,True);dup=[]
    assessment.pop('data')
    return {'id':key(item),'doc_id':item['doc_id'],'reference_method':reference['method'],
            'json_complete':complete,'coverage':cov,'tables':tables,'graph':graph,'duplicates':dup,**assessment}

def sumprf(rows):
    result={k:sum(r[k] for r in rows) for k in ['correct','expected','observed']}
    result['recall']=result['correct']/result['expected'] if result['expected'] else None
    result['precision']=result['correct']/result['observed'] if result['observed'] else None
    return result

def vision_summary(rows):
    result={'images':len(rows),'json_complete':sum(r['json_complete'] for r in rows),
            'transferred':sum(r['transfer_allowed'] for r in rows),
            'warning_images':sum(r['decision']=='candidate_with_warnings' for r in rows),
            'duplicate_images':sum(bool(r['duplicates']) for r in rows)}
    for group in ['all','native','scan']:
        subset=[r for r in rows if group=='all' or (r['reference_method']=='assistant_visual_transcription')==(group=='scan')]
        cov={k:sum(r['coverage'][k] for r in subset) for k in ['total','strict','compatible']}
        cov['recall']=cov['compatible']/cov['total'] if cov['total'] else None
        result[group]=cov
    tables=[t for r in rows for t in r['tables']['tables']]
    for kind in ['content','structure']:
        score=sumprf([t[kind] for t in tables]);score['observed']+=sum(r['tables']['unmatched_output_cells'] for r in rows)
        score['precision']=score['correct']/score['observed'] if score['observed'] else None
        result['table_'+kind]=score
    result['graph_edges']=sumprf([r['graph']['edges'] for r in rows if r['graph']['nodes']['expected']])
    result['graph_nodes']=sumprf([r['graph']['nodes'] for r in rows if r['graph']['nodes']['expected']])
    return result

def vision():
    m=read(VISION/'manifest.json');refs=read(ROOT/'outputs/vision-source-review-001/source-references.json')
    native={d['doc_id']:d for src in m['inputs'] for d in vision_runner.lines(src['parsed'])}
    docs=copy.deepcopy(native);rows=[];baseline=[];local_env=[];old_env=[]
    for item in m['items']:
        name=key(item);p=OUT/'results/vision'/name/'envelope.json'
        if not p.exists():continue
        env=read(p);response=env['response'];local_env.append(env)
        olddir=VISION/MODEL/'units'/name;old=read(olddir/'response.json')
        oldtime=read(olddir/'timing.json')['elapsed_seconds']
        old_env.append({'response':old,'elapsed_ms':oldtime*1000})
        r=vision_row(response,item,refs[name],MODEL,'local-vllm')
        b=vision_row(old,item,refs[name],OLD_MODEL,'DeepInfra')
        if r['transfer_allowed']:
            doc,_=convert_vision(docs[item['doc_id']],item,response)
            docs[item['doc_id']]=doc;r['common_roundtrip_preserved']=True
        else:
            unit=next(u for u in docs[item['doc_id']]['coverage']['units'] if u['unit_id']==item['unit_id'])
            unit.update(status='pending',reason='Orin vision quality gate rejected; see sidecar',block_ids=[])
        r['elapsed_ms']=env['elapsed_ms'];r['baseline_elapsed_ms']=oldtime*1000
        rows.append(r);baseline.append(b)
    for did,d in docs.items():
        assert not quality.base.common.check(d),did
        assert d['source']==native[did]['source'] and all(b in d['blocks'] for b in native[did]['blocks'])
    for src in m['inputs']:
        corpus=src['corpus'];ids={d['doc_id'] for d in m['documents'] if d['corpus']==corpus}
        path=OUT/'vision-common-blocks'/corpus/'parsed.candidate.jsonl';path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(''.join(canonical(docs[did])+'\n' for did in sorted(ids)))
    result={'planned':132,'received':len(rows),'complete':len(rows)==132,
            'comparison_scope':'same completed inputs only; missing jobs excluded until complete, not silently passed',
            'orin':vision_summary(rows),'openrouter_same_inputs':vision_summary(baseline),
            'timing':{'orin':timing(local_env),'openrouter_same_inputs':timing(old_env)},'records':rows,'baseline_records':baseline}
    write(OUT/'vision-evaluation.json',result)
    return result

def enrichment_row(env,g,p):
    candidate=None;errors=[];strict=False;relaxed=False
    response=env['response'] if env else {};choices=response.get('choices') or []
    if env is None:errors.append('response_not_received')
    if response.get('error'):errors.append('api_error')
    if len(choices)!=1:errors.append('missing_or_multiple_choices')
    else:
        if choices[0].get('finish_reason')!='stop':errors.append('not_normal_stop')
        raw=choices[0].get('message',{}).get('content')
        try:candidate=ec.loads(raw);strict=True
        except (ValueError,TypeError):
            errors.append('invalid_json')
            try:candidate=json.loads(raw,strict=False,object_pairs_hook=ec.unique);relaxed=True
            except (ValueError,TypeError):pass
    shape=candidate is not None and not list(Draft202012Validator(ec.schema()).iter_errors(candidate))
    if candidate is not None:errors+=ec.validate(candidate,p)
    usable=candidate if isinstance(candidate,dict) and isinstance(candidate.get('fields'),dict) and all(isinstance(f,dict) for f in candidate['fields'].values()) else None
    fields=ec.score_fields(usable,g,p,valid=bool(strict and not errors))
    return {'doc_id':g['doc_id'],'strict_json':strict,'shape_valid':shape,'relaxed_diagnostic':relaxed,
            'delivery_valid':bool(strict and not errors),'delivery_errors':errors,'fields':fields,
            'value_matches':sum(f['value_match'] for f in fields),'needed':sum(f['expected_value_observable'] for f in fields),
            'filled':sum(f['filled_scorable'] for f in fields),'summary':candidate.get('summary',[]) if shape else [],
            'elapsed_ms':env.get('elapsed_ms') if env else None,'response_sha256':digest(env) if env else None}

def enrichment_summary(rows):
    fields=[f for r in rows for f in r['fields']];matches=sum(r['value_matches'] for r in rows)
    needed=sum(r['needed'] for r in rows);filled=sum(r['filled'] for r in rows)
    return {'documents':len(rows),'strict_json':sum(r['strict_json'] for r in rows),'delivery_valid':sum(r['delivery_valid'] for r in rows),
            'value_only':{'matches':matches,'needed':needed,'filled':filled,'recall':matches/needed if needed else None,'precision':matches/filled if filled else None},
            'frozen_contract_metrics':ec.metrics(fields)}

def enrichment():
    gold={g['doc_id']:g for g in read(PREP/'private/gold.json')};rows=[];baseline=[];local_env=[];old_env=[];template=[]
    for did,g in gold.items():
        path=OUT/'results/enrichment'/did/'envelope.json'
        if not path.exists():continue
        env=read(path);packet=read(PREP/'public/inputs'/f'{did}.json')
        old=read(BASE_ENRICH/'responses'/MODEL/f'{did}.json')
        r=enrichment_row(env,g,packet);b=enrichment_row(old,g,packet)
        rows.append(r);baseline.append(b);local_env.append(env);old_env.append(old)
        template.append({'doc_id':did,'response_sha256':digest(env),'status':'pending','reviewer_kind':None,
                         'summary':r['summary'],'gold_summary_facts':g['summary_facts']})
    result={'planned':20,'received':len(rows),'complete':len(rows)==20,
            'comparison_scope':'same completed inputs only; summary semantic review separate',
            'orin':enrichment_summary(rows),'openrouter_same_inputs':enrichment_summary(baseline),
            'timing':{'orin':timing(local_env),'openrouter_same_inputs':timing(old_env)},'records':rows,'baseline_records':baseline}
    write(OUT/'enrichment-evaluation.json',result);write(OUT/'semantic-review.template.json',template)
    return result

def integrity():
    before=read(OUT/'preserved-hashes.json');changed=[p for p,h in before.items() if filehash(p)!=h]
    result={'checked_files':len(before),'changed':changed};write(OUT/'integrity.json',result)
    assert not changed,changed
    return result

if __name__=='__main__':
    v=vision();e=enrichment()
    print(json.dumps({'vision':{k:v[k] for k in ['received','orin','openrouter_same_inputs','timing']},
                      'enrichment':{k:e[k] for k in ['received','orin','openrouter_same_inputs','timing']}},ensure_ascii=False,indent=2))
