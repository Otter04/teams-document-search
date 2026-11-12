"""Pure semantic score mixing and source-evidence metrics."""
import math, re

def unit(vector):
    if len(vector)!=1024 or not all(type(x) in (int,float) and math.isfinite(x) for x in vector):
        raise ValueError('invalid_vector')
    norm=math.sqrt(math.fsum(x*x for x in vector))
    if norm<=0:raise ValueError('zero_vector')
    return [x/norm for x in vector]

def mix(vectors,weights):
    if len(vectors)!=len(weights) or any(w<0 for w in weights) or abs(sum(weights)-1)>1e-9:
        raise ValueError('invalid_weights')
    vs=[unit(v) for v in vectors]
    # Normalizing this weighted query scales every document score equally.
    # For normalized document vectors its order is the weighted cosine order.
    return unit([math.fsum(w*v[i] for v,w in zip(vs,weights)) for i in range(1024)])

def validate_expression(original,text):
    if not isinstance(text,str) or not text.strip() or len(text)>1500:raise ValueError('invalid_text')
    if set(re.findall(r'\d+(?:[.,]\d+)*',original))!=set(re.findall(r'\d+(?:[.,]\d+)*',text)):
        raise ValueError('numbers_changed')
    for token in re.findall(r'[A-Za-z][A-Za-z0-9_.:/-]*',original):
        if token.lower() not in text.lower():raise ValueError('identifier_missing')
    return text.strip()

def measure(hits,label):
    ranks={h['chunk_id']:i+1 for i,h in enumerate(hits)}
    anchors=[min((ranks[c] for c in group if c in ranks),default=None)
             for card in label['cards'] for group in card['anchor_groups']]
    if not anchors:raise ValueError('empty_gold')
    last=max(anchors) if all(a is not None for a in anchors) else None
    first=min((a for a in anchors if a is not None),default=None)
    return {'complete_rank':last,'first_rank':first,'anchor_ranks':anchors,
            'at':{str(k):last is not None and last<=k for k in (1,5,10,20,30,50)}}

def summarize(rows):
    n=len(rows);found=[r['complete_rank'] for r in rows if r['complete_rank'] is not None]
    return {'n':n,'at':{str(k):sum(r['at'][str(k)] for r in rows) for k in (1,5,10,20,30,50)},
            'mean_rank_missing_as_51':sum(r['complete_rank'] or 51 for r in rows)/n,
            'found':len(found)}

def gate(base,candidate,split,stage):
    new=[q for q in base if not base[q]['at']['20'] and candidate[q]['at']['20']]
    lost=[q for q in base if base[q]['at']['20'] and not candidate[q]['at']['20']]
    sums={}
    for part in ('selection','check'):
        ids=[q for q in base if split[q]==part]
        sums[part]=sum(candidate[q]['at']['20']-base[q]['at']['20'] for q in ids)
    checks={'selection_improves':sums['selection']>=1,'check_no_net_loss':sums['check']>=0,
            'regressions_at_most_one':len(lost)<=1,
            'top50_preserved':sum(x['at']['50'] for x in candidate.values())>=sum(x['at']['50'] for x in base.values()),
            'net_gain':len(new)-len(lost)>=(2 if stage==3 else 1)}
    return {'pass':all(checks.values()),'checks':checks,'new_successes':new,'new_failures':lost,'split_net_gain':sums}
