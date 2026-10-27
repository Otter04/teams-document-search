"""Replay saved responses through v2; no dispatch, retry, network, or key access."""
import collections
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from quality import VERSION,check_quality,validate_response,convert_checked,base

ROOT=Path(__file__).resolve().parents[2]
RUN=ROOT/'outputs/vision-comparison-run-001'
REVIEW=ROOT/'outputs/vision-source-review-001'
OUT=ROOT/'outputs/vision-validation-run-002'
MODELS=['qwen3.6-35b-a3b','qwen3-vl-30b-a3b-instruct']
spec=importlib.util.spec_from_file_location('source_review_helpers',REVIEW/'review.py')
helpers=importlib.util.module_from_spec(spec);spec.loader.exec_module(helpers)
def load(p):return json.loads(Path(p).read_text())
def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(p,data):p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
def uid(item):return item['doc_id']+'-'+item['unit_id'].replace(':','-')
def counts(issues):return dict(collections.Counter(i['code'] for i in issues))

def evaluate():
    manifest=load(RUN/'manifest.json')
    frozen=list(RUN.rglob('*.json'))+list(RUN.rglob('*.jsonl'))+list(REVIEW.glob('*.json'))+[ROOT/'outputs/rag-vision-v1'/n for n in ['contract.py','run.py']]+[Path(i['parsed']) for i in manifest['inputs']]+[Path(d['path']) for d in manifest['documents']]+[Path(i['image_path']) for i in manifest['items']]
    before={str(p):digest(p) for p in frozen}
    native={d['doc_id']:d for i in manifest['inputs'] for d in [json.loads(l) for l in Path(i['parsed']).read_text().splitlines()]}
    previous=load(REVIEW/'evaluation.json');references=load(REVIEW/'source-references.json');all_results=[];remediation=[]
    for model in MODELS:
        prev={r['key']:r for r in next(m for m in previous if m['summary']['model']==model)['records']};records=[];docs=copy.deepcopy(native)
        for item in manifest['items']:
            key=uid(item);response=load(RUN/model/'units'/key/'response.json');result=validate_response(response,item,'qwen/'+model);data=result.pop('data')
            diagnostic=[]
            if data is None:
                partial,_,_=helpers.recover(response['choices'][0]['message']['content'])
                diagnostic=check_quality(partial,item.get('native_context',[]))
            # Prefix findings never change admission: invalid JSON is rejected.
            issues=result['issues']+diagnostic;old=prev[key]
            if result['decision']=='candidate':
                if not old['common_json_valid']:raise AssertionError('v2 must not promote baseline failures')
                doc,_=convert_checked(docs[item['doc_id']],item,response,'qwen/'+model)
                docs[item['doc_id']]=doc
            else:
                unit=next(u for u in docs[item['doc_id']]['coverage']['units'] if u['unit_id']==item['unit_id'])
                unit.update(status='pending',reason=VERSION+': '+result['decision']+'; see validation sidecar',block_ids=[])
            rec=dict(key=key,doc_id=item['doc_id'],unit_id=item['unit_id'],previous_valid=old['common_json_valid'],**result,
                prefix_issues_diagnostic_only=diagnostic,issue_counts=counts(issues),response_sha256=digest(RUN/model/'units'/key/'response.json'),
                source_review_remaining_mismatches=[d for d in old['coverage']['details'] if not d['compatible']],
                source_review_duplicate_flag=bool(old['duplicate_source_phrases']))
            records.append(rec)
            if rec['source_review_remaining_mismatches']:
                reference=references[key]
                for d in rec['source_review_remaining_mismatches']:
                    if d['expected'] in old['source_items_only_in_claims']:
                        action='existing_response_field_review';reason='Source string exists in claims: review relocation using source evidence; no mandatory re-call.'
                    elif reference['method']!='assistant_visual_transcription':
                        action='native_source_recovery_review';reason='Native source exists. Missing literal may be recovered from native parser after provenance review; no mandatory re-call.'
                    else:
                        action='source_reinspection_or_model_recall';reason='Source string not preserved in literal fields or claims; validator cannot infer correction. Manual source-based correction or new extraction required.'
                    remediation.append(dict(model=model,key=key,action=action,reason=reason,expected=d['expected'],nearest=d['nearest'],similarity=d['similarity'],
                        kind='possible_misread_or_rewrite' if (d['similarity'] or 0)>=.7 else 'missing_or_unmatched',
                        reference_status='assistant_review_draft',image_path=reference['image_path'],new_gate_decision=result['decision']))
        summary=dict(model=model,images=len(records),previous_valid=sum(r['previous_valid'] for r in records),decisions=dict(collections.Counter(r['decision'] for r in records)),
            newly_held_from_previous_valid=sum(r['previous_valid'] and r['decision']!='candidate' for r in records),
            issues_by_image=dict(collections.Counter(code for r in records for code in r['issue_counts'])),
            issue_instances=counts([i for r in records for i in r['issues']+r['prefix_issues_diagnostic_only']]),
            new_holds=[dict(key=r['key'],decision=r['decision'],codes=list(r['issue_counts'])) for r in records if r['previous_valid'] and r['decision']!='candidate'],
            prior_duplicate_flagged_images=sum(r['source_review_duplicate_flag'] for r in records),
            prior_duplicate_flag_detected=sum(r['source_review_duplicate_flag'] and any(c.startswith('DUPLICATE_') for c in r['issue_counts']) for r in records),
            candidate_known_source_mismatch_images=[r['key'] for r in records if r['decision']=='candidate' and r['source_review_remaining_mismatches']],
            native_documents_preserved=sum(all(b in docs[k]['blocks'] for b in d['blocks']) and d['source']==docs[k]['source'] for k,d in native.items()))
        for corpus in ['original','additional']:
            ids=[d['doc_id'] for d in manifest['documents'] if d['corpus']==corpus];rows=[docs[k] for k in ids]
            errors={d['doc_id']:base.common.check(d) for d in rows if base.common.check(d)}
            if errors:raise AssertionError(errors)
            path=OUT/model/corpus/'parsed.quality-candidate.jsonl';path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text(''.join(json.dumps(d,ensure_ascii=False,separators=(',',':'))+'\n' for d in rows))
        all_results.append(dict(summary=summary,records=records))
    write(OUT/'evaluation.json',all_results);write(OUT/'remediation-queue.json',remediation)
    changed=[p for p,h in before.items() if digest(p)!=h]
    if changed:raise AssertionError(changed)
    write(OUT/'integrity.json',dict(files_checked=len(before),changed_files=changed,hashes=before,model_calls=0,paid_calls=0,
        validator_code_sha256=digest(Path(__file__).with_name('quality.py')),evaluator_sha256=digest(Path(__file__)),
        frozen_contract_matches=all(digest(ROOT/'outputs/rag-vision-v1'/n)==h for n,h in manifest['code_hashes'].items())))
    print(json.dumps([r['summary'] for r in all_results],ensure_ascii=False,indent=2))
    return all_results

if __name__=='__main__':evaluate()
