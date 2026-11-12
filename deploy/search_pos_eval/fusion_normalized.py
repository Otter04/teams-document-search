"""Offline frozen top50 comparison; gold is never used to compute scores."""
import csv
import math
from pathlib import Path
import fusion_fixed50 as F

ROOT=F.ROOT
OLD=F.OUT
OUT=ROOT/'outputs/search-fusion-normalized-001'
METHODS=('rrf','minmax','l2')

def save(name,obj):
    p=OUT/name;p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('x') as f:
        F.json.dump(obj,f,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n')

def normalize(scores,method):
    assert all(math.isfinite(s) and s>=0 for s in scores)
    if not scores:return [],'empty'
    if method=='minmax':
        lo,hi=min(scores),max(scores)
        if hi==lo:return [float(hi>0)]*len(scores),'constant_positive' if hi>0 else 'all_zero'
        return [(s-lo)/(hi-lo) for s in scores],None
    assert method=='l2'
    norm=math.sqrt(math.fsum(s*s for s in scores))
    return ([s/norm for s in scores],None) if norm else ([0.]*len(scores),'all_zero')

def fuse(keyword,semantic,method):
    assert method in METHODS
    rows={};exceptions={}
    for name,hits,w in [('keyword',keyword,1.0),('semantic',semantic,2.0)]:
        assert len(hits)<=50 and len({h['chunk_id'] for h in hits})==len(hits)
        scores=[h['score'] for h in hits]
        assert all(math.isfinite(s) and s>=0 for s in scores)
        if method=='rrf':values=[1/(60+i) for i in range(1,len(hits)+1)];event=None
        else:values,event=normalize(scores,method)
        if event:exceptions[name]=event
        for rank,(h,value) in enumerate(zip(hits,values),1):
            row=rows.setdefault(h['chunk_id'],dict(chunk_id=h['chunk_id'],doc_id=h['doc_id'],score=0.,branches={}))
            assert row['doc_id']==h['doc_id']
            # Preserve the original RRF floating-point operation for exact replay.
            contribution=w/(60+rank) if method=='rrf' else w*value
            row['score']+=contribution
            row['branches'][name]=dict(rank=rank,original_score=h['score'],normalized_score=value,contribution=contribution)
    return sorted(rows.values(),key=lambda h:(-h['score'],h['chunk_id'])),exceptions

def main():
    OUT.mkdir(exist_ok=True);assert not (OUT/'manifest.json').exists(),'Do not overwrite a run'
    oldmanifest=F.read(OLD/'manifest.json')
    frozen={str(p.relative_to(ROOT)):F.sha(p) for p in OLD.rglob('*') if p.is_file()}
    for rel,digest in oldmanifest['input_hashes'].items():
        if rel.startswith('outputs/'):
            assert F.sha(ROOT/rel)==digest,rel;frozen[rel]=digest
    for p in (Path(__file__),Path(F.__file__)):frozen[str(p.relative_to(ROOT))]=F.sha(p)
    labels={q['query_id']:q for q in F.read(F.SEMANTIC/'labels.json')}
    previous=F.read(OLD/'records.json');assert len(previous)==82
    save('manifest.json',dict(date='2026-11-04',methods=list(METHODS),weights=[1,2],rrf_constant=60,candidate_cap_per_branch=50,
        frozen_source=str(OLD.relative_to(ROOT)),keyword='m20-context_double-remove',semantic='search-openrouter-dual-semantic-001/schema',
        normalization='Per branch over returned top50, before union. Missing contribution=0; ties=chunk_id ascending.',
        minmax_degenerate='Constant positive scores => all1; all0 => all0; empty => no contribution',
        l2_degenerate='Zero norm => all0; empty => no contribution',
        input_hashes=frozen,new_model_calls=0,new_search_calls=0,service_changed=False))
    records=[];exceptions=[];rankmaps={};reproduced=0
    for old in previous:
        qid=old['query_id'];base=F.read(OLD/f'rankings/{qid}/weight-2.0.json')
        names={h['chunk_id']:h['file_name'] for h in base['hits']}
        metrics={k:old['metrics'][k] for k in ('keyword','semantic')}
        for method in METHODS:
            hits,events=fuse(base['keyword_hits'],base['semantic_hits'],method)
            for h in hits:h['file_name']=names[h['chunk_id']]
            assert {h['chunk_id'] for h in hits}==set(names)
            if method=='rrf':
                assert [(h['chunk_id'],h['score']) for h in hits]==[(h['chunk_id'],h['score']) for h in base['hits']]
                reproduced+=1
            if events:exceptions.append(dict(query_id=qid,method=method,events=events))
            save(f'rankings/{qid}/{method}.json',dict(query_id=qid,query=old['query'],method=method,hits=hits,exceptions=events))
            metrics[method]=F.measure(hits,labels[qid])
            rankmaps[qid,method]={h['chunk_id']:i+1 for i,h in enumerate(hits)}
        records.append(dict(query_id=qid,query=old['query'],blocked_in_service=old['blocked_in_service'],union_all_evidence=old['union_all_evidence'],metrics=metrics))
    summaries={key:{group:F.aggregate([r['metrics'][key] for r in records if group=='all82' or r['blocked_in_service']==(group=='blocked8')]) for group in ('all82','service74','blocked8')} for key in ('keyword','semantic')+METHODS}
    transitions={}
    for reference in ('rrf','semantic'):
        for method in ('minmax','l2'):
            transitions[reference+'->'+method]={}
            for cut in ('20','50'):
                transitions[reference+'->'+method][cut]={kind:[dict(query_id=r['query_id'],query=r['query'],blocked_in_service=r['blocked_in_service'],before=r['metrics'][reference]['complete_rank'],after=r['metrics'][method]['complete_rank']) for r in records if pred(r['metrics'][reference]['at'][cut],r['metrics'][method]['at'][cut])] for kind,pred in [('improved',lambda a,b:not a and b),('regressed',lambda a,b:a and not b)]}
    evidence=[]
    for e in F.read(OLD/'evidence-diagnostics.json'):
        e={k:v for k,v in e.items() if k not in ('ranks','examples')}
        e['ranks']={m:min((rankmaps[e['query_id'],m][cid] for cid in e['evidence_ids'] if cid in rankmaps[e['query_id'],m]),default=None) for m in METHODS}
        evidence.append(e)
    common=[r for r in records if all(r['metrics'][m]['found50'] for m in ('semantic',)+METHODS)]
    comparison=dict(summaries=summaries,transitions=transitions,exceptions=exceptions,
        union_all_evidence=sum(r['union_all_evidence'] for r in records),
        common_found50=dict(n=len(common),means={m:F.statistics.mean(r['metrics'][m]['complete_rank'] for r in common) for m in ('semantic',)+METHODS}),
        evidence_origin={origin:{m:{str(c):sum(e['origin']==origin and e['ranks'][m] is not None and e['ranks'][m]<=c for e in evidence) for c in (20,50)} for m in METHODS} for origin in ('keyword_only','semantic_only','both','neither')})
    save('records.json',records);save('comparison.json',comparison);save('evidence-diagnostics.json',evidence)
    with (OUT/'query-ranks.csv').open('x',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f);w.writerow(['query_id','query','blocked_in_service','keyword','semantic']+list(METHODS))
        for r in records:w.writerow([r['query_id'],r['query'],r['blocked_in_service']]+[r['metrics'][m]['complete_rank'] for m in ('keyword','semantic')+METHODS])
    assert all(F.sha(ROOT/p)==h for p,h in frozen.items())
    save('complete.json',dict(questions=82,rankings=246,rrf_exact_reproductions=reproduced,inputs_preserved=True,new_model_calls=0,new_search_calls=0,service_changed=False))
    print(F.json.dumps(comparison,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
