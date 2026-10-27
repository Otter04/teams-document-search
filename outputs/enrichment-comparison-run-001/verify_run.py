"""Offline final audit of authorized call count, immutable requests and reviews."""
import hashlib
import json
from pathlib import Path
from review_tools import HERE,PREP,evaluator
from contract import digest,evidence_errors

def main():
    evaluator.assert_frozen();preflight=evaluator.preflight()
    reqs=evaluator.read(PREP/'requests/index.json')['requests']
    expected={(r['model'],r['doc_id']):r for r in reqs}
    entries=evaluator.load_responses(HERE/'responses')
    assert len(entries)==40 and set(entries)==set(expected)
    attempts=list((HERE/'attempts').rglob('*.json'))
    assert len(attempts)==40
    attempt_keys=[];ids=[]
    for p in attempts:
        a=evaluator.read(p);attempt_keys.append((a['model'],a['doc_id']))
    assert set(attempt_keys)==set(expected) and len(set(attempt_keys))==40
    for key,e in entries.items():
        env=evaluator.read(Path(e['file']));response=env['response'];ids.append(response['id'])
        assert response['model']==key[0] and response['provider']=='DeepInfra'
        assert not response.get('error')
        assert response['choices'][0]['finish_reason']=='stop'
        assert digest(evaluator.read(PREP/expected[key]['path']))==expected[key]['request_sha256']
        assert isinstance(response['usage']['cost'],(int,float))
        assert env['elapsed_ms']>0
    assert len(set(ids))==40
    reviews=evaluator.read(HERE/'semantic-review.completed.json')
    assert len(reviews)==40 and len({r['candidate_id'] for r in reviews})==40
    gold={g['doc_id']:g for g in evaluator.read(PREP/'private/gold.json')}
    for r in reviews:
        matches=[e for (m,d),e in entries.items() if evaluator.blind_id(m,d)==r['candidate_id']]
        assert len(matches)==1 and matches[0]['response_sha256']==r['response_sha256']
        assert r['reviewer_kind']=='assistant' and r['status']=='completed'
        p=evaluator.read(PREP/'public/inputs'/f"{r['doc_id']}.json")
        allowed={f['fact_id'] for f in gold[r['doc_id']]['summary_facts']}
        for s in r['sentences']:
            assert s['atomic_claims']
            for a in s['atomic_claims']:
                assert set(a['covered_gold_fact_ids'])<=allowed
                assert a['verdict']=='supported' or not a['covered_gold_fact_ids']
                for e in a['evidence']:
                    if e['kind']=='input_source_metadata':assert p['source_metadata'][e['ref']]==e['quote']
                    else:assert not evidence_errors([e],p)
    result={'status':'passed','paid_attempts':40,'unique_response_ids':40,'automatic_retries':0,
       'model_provider_checked':40,'response_costs_present':40,'source_reviews_completed':40,
       'frozen_preflight':preflight,'errors_saved':len(list((HERE/'errors').rglob('*.json'))),
       'notes':'Review support judgments are authored by an assistant; this audit checks completeness and references, not independent semantic truth. preflight paid_calls=0 describes the checker, not this completed run.'}
    evaluator.write(HERE/'verification.json',result)
    evaluator.write(HERE/'result-files.sha256.json',{str(p.relative_to(HERE)):hashlib.sha256(p.read_bytes()).hexdigest() for p in HERE.rglob('*') if p.is_file() and p.name!='result-files.sha256.json'})
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
