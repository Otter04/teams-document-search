"""Materialize manually authored source-review judgments; no model calls.

review-specs.json is authored by the assistant after inspecting each original
summary and source. This program only resolves source pointers and counts.
It never infers semantic support or fact coverage automatically.
"""
import copy
import json
from pathlib import Path
from review_tools import HERE, PREP, evaluator, export
from contract import evidence_errors, score_fields, validate, norm

def evidence(spec, packet):
    blocks=packet['document']['blocks'];out=[]
    for short in spec.split(','):
        if short=='*':
            out += [{'kind':'block','ref':b['block_id'],'quote':b['text']} for b in blocks if b.get('text','').strip()]
        elif short.startswith('@'):
            key=short[1:];out.append({'kind':'source','ref':key,'quote':packet['document']['source'][key]})
        elif short.startswith('$'):
            key=short[1:];out.append({'kind':'input_source_metadata','ref':key,'quote':packet['source_metadata'][key]})
        else:
            matched=[b for b in blocks if b['block_id'].endswith('-'+short)]
            assert len(matched)==1,(short,len(matched))
            b=matched[0];out.append({'kind':'block','ref':b['block_id'],'quote':b['text']})
    return out

def main():
    templates=export();specs=evaluator.read(HERE/'review-specs.json')
    reviews=[]
    for r in templates:
        if r['candidate_id'] not in specs:continue
        p=evaluator.read(PREP/'public/inputs'/f"{r['doc_id']}.json")
        authored=specs[r['candidate_id']]
        assert len(authored)==len(r['sentences']),r['candidate_id']
        r.update(reviewer_id='assistant-source-review-2026-10-19',reviewer_kind='assistant',status='completed')
        for s,atoms in zip(r['sentences'],authored):
            for a in atoms:
                text,refs,facts=a[:3]
                ev=evidence(refs,p)
                for e in ev:
                    if e['kind']!='input_source_metadata':assert not evidence_errors([e],p)
                verdict=a[3] if len(a)>3 else 'supported'
                s['atomic_claims'].append({'text':text,'verdict':verdict,
                    'reason':a[4] if len(a)>4 else '검수자가 아래 원문 블록과 대조해 해당 사실을 확인했다. 모델의 인용 누락이나 형식 오류는 별도로 보존한다.',
                    'evidence':ev,'covered_gold_fact_ids':[r['doc_id']+'-F'+n for n in facts.split(',') if n]})
        reviews.append(r)
    evaluator.write(HERE/'semantic-review.completed.json',reviews)
    assert set(specs)<=set(r['candidate_id'] for r in templates),'Review without response'
    print(json.dumps({'reviewed':len(reviews),'received_readable':len(templates),'unreviewed':[r['candidate_id'] for r in templates if r['candidate_id'] not in specs]}))

if __name__=='__main__':main()
