"""Supplemental content diagnostics; never substitutes for frozen delivery gate."""
import collections
import json
from pathlib import Path
from review_tools import HERE,PREP,evaluator
from contract import norm,unique,score_fields,evidence_errors,validate,metrics
from jsonschema import Draft202012Validator
from contract import schema

def main():
    entries=evaluator.load_responses(HERE/'responses')
    gold={g['doc_id']:g for g in evaluator.read(PREP/'private/gold.json')}
    reviews={r['candidate_id']:r for r in evaluator.read(HERE/'semantic-review.completed.json')}
    official=evaluator.read(HERE/'evaluation-final/evaluation.json')
    results=[]
    for model in evaluator.manifest()['models']:
        rows=[];allfields=[];cost=0;refcounts=collections.Counter();schemaok=0;jsonok=0
        for did,g in gold.items():
            e=entries.get((model,did));p=evaluator.read(PREP/'public/inputs'/f'{did}.json')
            c=e['candidate'] if e else None
            relaxed=False
            if e and c is not None:jsonok+=1
            elif e:
                try:
                    c=json.loads(evaluator.read(Path(e['file']))['response']['choices'][0]['message']['content'],strict=False,object_pairs_hook=unique)
                    relaxed=True
                except (ValueError,TypeError,KeyError):pass
            if c is not None and not list(Draft202012Validator(schema()).iter_errors(c)):schemaok+=1
            fs=score_fields(c,g,p,False);allfields+=fs
            wrong=[{'field':f['field'],'predicted':f['predicted_value'],'expected':f['expected_value'],
                'category':'representation_only' if (f['field'] in ['로그시작','로그종료'] and f['predicted_value']==str(f['expected_value'])+':00') or (f['field']=='실행결과' and {'SUCCESS':'성공','FAILED':'실패'}.get(f['predicted_value'])==f['expected_value']) else 'meaning_or_field_policy'}
                for f in fs if f['predicted_value'] is not None and not f['value_match']]
            rv=reviews.get(evaluator.blind_id(model,did));atoms=[a for s in rv['sentences'] for a in s['atomic_claims']] if rv else []
            covered=sorted({f for a in atoms if a['verdict']=='supported' for f in a['covered_gold_fact_ids']})
            errors=(e['errors']+validate(c,p)) if e and c is not None else (e['errors'] if e else ['missing'])
            for error in errors:refcounts[error.split(':')[1] if ':' in error else error]+=1
            row={'doc_id':did,'strict_json':bool(e and e['candidate'] is not None),'diagnostic_relaxed_control_characters':relaxed,
                'value_matches':sum(f['value_match'] for f in fs),'needed':sum(f['expected_value_observable'] for f in fs),
                'filled_scorable':sum(f['filled_scorable'] for f in fs),'wrong_values':wrong,
                'missing_needed':[f['field'] for f in fs if f['expected_value_observable'] and f['predicted_value'] is None],
                'delivery_errors':errors,'summary_reviewed':rv is not None,'summary_claims':len(atoms),
                'summary_supported':sum(a['verdict']=='supported' for a in atoms),
                'summary_unsupported':sum(a['verdict']=='unsupported' for a in atoms),
                'summary_uncertain':sum(a['verdict']=='uncertain' for a in atoms),
                'core_facts_covered':covered,'core_facts_expected':[f['fact_id'] for f in g['summary_facts']],
                'summary_issues':[a for a in atoms if a['verdict']!='supported']}
            rows.append(row)
        total=lambda key:sum(r[key] for r in rows)
        frozen=next(x for x in official['models'] if x['model']==model)
        results.append({'model':model,'strict_json_documents':jsonok,'shape_schema_documents_including_diagnostic_decode':schemaok,
            'frozen_valid_documents':frozen['valid_documents'],'frozen_metadata_gate_pass':frozen['metadata_gate_pass'],
            'value_only':{'matches':total('value_matches'),'needed':190,'filled_scorable':total('filled_scorable'),
                'recall':total('value_matches')/190,'precision':total('value_matches')/total('filled_scorable')},
            'summary_content_diagnostic':{'reviewed_documents':total('summary_reviewed'),'claims':total('summary_claims'),
                'supported':total('summary_supported'),'unsupported':total('summary_unsupported'),'uncertain':total('summary_uncertain'),
                'supported_fraction':total('summary_supported')/total('summary_claims') if total('summary_claims') else None,
                'covered':sum(len(r['core_facts_covered']) for r in rows),'expected':61,
                'core_fact_recall':sum(len(r['core_facts_covered']) for r in rows)/61},
            'usage':frozen['usage'],'error_counts':dict(refcounts),'documents':rows})
    evaluator.write(HERE/'diagnostics.json',{'meaning':'Post-hoc diagnostic content comparison including rejected responses. Does not repair responses, alter frozen gold, or confer delivery success. Literal control characters may be read for content only and are marked. AI source review, not independent human evaluation.', 'models':results})
    print(json.dumps([{k:v for k,v in m.items() if k not in ['documents','error_counts']} for m in results],ensure_ascii=False,indent=2))

if __name__=='__main__':main()
