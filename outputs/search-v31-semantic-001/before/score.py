"""Offline scoring: answers are read here, never by the deployed search process."""
import argparse,collections,hashlib,json,math,re,sys
from pathlib import Path
from query import FIELDS,calendar_range
from engine import condition_matches
from datetime import date

ROOT=Path(__file__).resolve().parents[2];OUT=ROOT/'outputs/search-service-001'
def read(p):return json.loads(Path(p).read_text())
def lines(p):return [json.loads(s) for s in Path(p).read_text().splitlines() if s]
def write(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def pct95(values):return sorted(values)[math.ceil(len(values)*.95)-1] if values else None
def expected_filters(text):
    result={}
    for piece in text.split(';'):
        if '=' not in piece:continue
        k,v=map(str.strip,piece.split('=',1));v=v.split(' (')[0]
        result[FIELDS.get(k,k)]=v
    return result
def analysis_filters(p):
    result={}
    for k,v in p['conditions'].items():
        if isinstance(v,dict):
            start=v['gte'][:10];end=v.get('lte','')[:10]
            if start.endswith('01-01') and end.endswith('12-31'):result['기간']=start[:4]
            elif start.endswith('-01') and end[:7]==start[:7]:result['기간']=start[:7]
            else:result['기간']=v
        else:result[k]=v
    return result
def main():
    ap=argparse.ArgumentParser();ap.add_argument('run');args=ap.parse_args();folder=OUT/'evaluation'/args.run
    assert (folder/'complete.json').exists(),'Score only complete runs'
    goldroot=next(Path('/Users/kangdongkyoon/Downloads').glob('RAG_*/gold/queries.jsonl')).parent
    gold={r['query_id']:r for r in lines(goldroot/'queries.jsonl')};gold_docs={r['doc_id']:r for r in lines(goldroot/'documents.jsonl')}
    docs=read(OUT/'documents.json');blocks=read(OUT/'blocks.json');byvariant=collections.defaultdict(list)
    for r in lines(folder/'responses.jsonl'):byvariant[r['variant']].append(r)
    totals={};allscored={}
    for variant,rows in byvariant.items():
        scores=[];timing={'rules':[],'llm_attempted':[]};llm=collections.Counter();checks={'excerpt_count':0,'literal_errors':0,'missing_locations':0,'cards_without_literal_excerpts':0}
        for row in rows:
            q=gold[row['query_id']];o=row.get('response',{});p=o.get('query_plan',{});cards=o.get('results',[]);ids=[r['doc_id'] for r in cards];answers=q['answers'];found=[ids.index(a)+1 for a in answers if a in ids]
            expected=expected_filters(q['filters']);parsed=analysis_filters(p) if p else {};di=o.get('diagnostics',{})
            branches={k:list(dict.fromkeys(r['doc_id'] for r in di.get(k,[]))) for k in ['bm25','vector']}
            cut=[]
            for did in answers:
                if any(not condition_matches(docs[did]['metadata'],k,v) for k,v in p.get('filters',{}).items()):cut.append(did)
            families=[gold_docs[d]['family'] for d in ids];duplicates=len(families)!=len(set(families))
            goldgroups=collections.defaultdict(list)
            for did in answers:goldgroups[gold_docs[did]['family']].append(did)
            representatives=[]
            for family,members in goldgroups.items():
                if len(members)<2:continue
                latest=[d for d in members if gold_docs[d]['최신본']=='Y']
                # Original gold has latest flags, not independently adjudicated per-query representative labels.
                shown=[d for d in ids if gold_docs[d]['family']==family]
                representatives.append({'family':family,'expected_latest_from_original_gold':latest,'shown':shown,
                   'matches_original_latest':bool(set(latest)&set(shown)),'status':'provisional_latest_flag_check'})
            for c in cards:
                if not c['excerpts']:checks['cards_without_literal_excerpts']+=1
                for e in c['excerpts']:
                    checks['excerpt_count']+=1;b=blocks[c['doc_id']].get(e['block_id'],{})
                    if e['text']!=b.get('text','')[e['start']:e['end']] or len(e['text'])>100:checks['literal_errors']+=1
                    if not e.get('loc'):checks['missing_locations']+=1
            model=p.get('llm',{});attempted=model.get('attempted',False);llm[model.get('status','not_called')]+=1
            if 'timings' in o:timing['llm_attempted' if attempted else 'rules'].append(o['timings']['total_seconds'])
            scores.append({'query_id':q['query_id'],'query':q['query'],'type':q['type'],'answers':answers,'top5':ids,
              'hit':bool(found),'mrr_at_5':1/min(found) if found else 0,'individual_answer_recall':len(set(ids)&set(answers))/len(answers),
              'candidate_hit':bool(set(answers)&(set(branches['bm25'])|set(branches['vector']))),
              'branch_hits':{k:bool(set(answers)&set(v[:5])) for k,v in branches.items()},
              'expected_filters':expected,'extracted_conditions':parsed,'filter_exact_raw':expected==parsed,
              'gold_excluded_by_hard_filters':cut,'all_gold_excluded':len(cut)==len(answers),'family_duplicate':duplicates,
              'representatives':representatives,'status':o.get('status',row.get('error')),'llm':model,
              'relaxed':o.get('relaxed_conditions',[])})
        n=len(scores);filtered=[s for s in scores if s['expected_filters']]
        items={}
        for key in ['client','document_type','기간']:
            relevant=[s for s in scores if key in s['expected_filters']]
            items[key]={'correct':sum(s['extracted_conditions'].get(key)==s['expected_filters'][key] for s in relevant),'total':len(relevant)}
        groups=[s for s in scores if s['representatives']]
        totals[variant]={'questions':n,'hits_at_5':sum(s['hit'] for s in scores),'hit_at_5':sum(s['hit'] for s in scores)/n,
         'mrr_at_5':sum(s['mrr_at_5'] for s in scores)/n,'individual_answer_recall_mean':sum(s['individual_answer_recall'] for s in scores)/n,
         'candidate_hits':sum(s['candidate_hit'] for s in scores),'branch_hits':{k:sum(s['branch_hits'][k] for s in scores) for k in ['bm25','vector']},
         'by_type':{t:{'hits':sum(s['hit'] for s in scores if s['type']==t),'total':sum(s['type']==t for s in scores)} for t in sorted({s['type'] for s in scores})},
         'filter_exact_raw':{'correct':sum(s['filter_exact_raw'] for s in filtered),'total':len(filtered)},'filter_items':items,
         'hard_filter_excluded_any_gold_questions':sum(bool(s['gold_excluded_by_hard_filters']) for s in scores),
         'hard_filter_excluded_all_gold_questions':sum(s['all_gold_excluded'] for s in scores),
         'family_duplicate_questions':sum(s['family_duplicate'] for s in scores),
         'representative_latest_provisional':{'correct':sum(all(r['matches_original_latest'] for r in s['representatives']) for s in groups),'total':len(groups),
           'not_final_G5_2':'Missing per-query independently reviewed representative gold; oldest-evidence exception requires review.'},
         'empty_results':sum(not s['top5'] for s in scores),'errors':sum('error' in r for r in rows),'llm':dict(llm),
         'timing':{k:{'n':len(v),'p95_seconds':pct95(v),'mean_seconds':sum(v)/len(v) if v else None} for k,v in timing.items()},
         'literal_evidence_checks':checks,'failed_questions':[s['query_id'] for s in scores if not s['hit']]}
        allscored[variant]=scores
    write(folder/'scores.json',allscored);write(folder/'summary.json',{'variants':totals,
      'gold_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [goldroot/'queries.jsonl',goldroot/'documents.jsonl']},
      'development_only':True,'metric_note':'Design Recall@5 counts questions with any answer; named Hit@5 here. Individual-answer recall separately reported. Family folding makes all-version recall lower by design.',
      'label_notes':'Raw original filters are not corrected. Extra correct system conditions and latest-as-boost can cause exact-schema disagreement. Hard exclusions require source review before classifying as erroneous.'})
    print(json.dumps(totals,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
