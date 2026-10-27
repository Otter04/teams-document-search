"""Validate explicitly authored source reviews; never generates semantic verdicts."""
from adapter import *

_saved=sys.modules.get('contract')
sys.modules['contract']=ec
frozen_runner=module('orin_frozen_enrichment_runner',PREP/'run.py')
if _saved is None:del sys.modules['contract']
else:sys.modules['contract']=_saved

def score():
    path=OUT/'semantic-review.completed.json'
    if not path.exists():return None
    reviews=read(path);gold={g['doc_id']:g for g in read(PREP/'private/gold.json')}
    assert len({r['doc_id'] for r in reviews})==len(reviews)
    old=next(m for m in read(BASE_ENRICH/'diagnostics.json')['models'] if m['model']==OLD_MODEL)
    old_by_id={d['doc_id']:d for d in old['documents']}
    rows=[];base=[]
    for r in reviews:
        did=r['doc_id'];assert did in gold
        env=read(OUT/'results/enrichment'/did/'envelope.json')
        content=env['response']['choices'][0]['message']['content']
        candidate=ec.loads(content)
        packet=read(PREP/'public/inputs'/f'{did}.json')
        result=frozen_runner.check_review(r,{'response_sha256':digest(env)},gold[did],candidate,packet)
        assert result is not None,did
        rows.append({'doc_id':did,**result})
        b=old_by_id[did]
        base.append({'doc_id':did,'claims':b['summary_claims'],'supported':b['summary_supported'],
                     'unsupported':b['summary_unsupported'],'uncertain':b['summary_uncertain'],
                     'facts_covered':len(b['core_facts_covered']),'facts_expected':len(b['core_facts_expected'])})
    def aggregate(rs):
        d={k:sum(r[k] for r in rs) for k in ['claims','supported','unsupported','uncertain','facts_covered','facts_expected']}
        d['supported_fraction']=d['supported']/d['claims'] if d['claims'] else None
        d['core_fact_recall']=d['facts_covered']/d['facts_expected'] if d['facts_expected'] else None
        return d
    result={'reviewed_documents':len(rows),'planned':20,'complete':len(rows)==20,
            'method':'Explicit assistant source review, same frozen compound gold facts; not independent human evaluation. Semantic review is separate from JSON delivery gate.',
            'orin':aggregate(rows),'openrouter_same_inputs':aggregate(base),'records':rows,'baseline_records':base}
    write(OUT/'semantic-evaluation.json',result)
    return result

if __name__=='__main__':print(json.dumps(score(),ensure_ascii=False,indent=2))
