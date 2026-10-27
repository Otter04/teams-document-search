"""Materialize evidence spans and human-readable review; no automatic semantic approval."""
from prepare import *

def strict_json(text):
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise ValueError('Duplicate JSON key: '+key)
            result[key]=value
        return result
    return json.loads(text,object_pairs_hook=pairs)

def validate(packet,candidate):
    assert set(candidate)=={'fields','summary_sources'}
    assert set(candidate['fields'])==set(packet['fields'])
    ids={e['id'] for e in packet['excerpts']}
    for k,values in list(candidate['fields'].items())+[('summary_sources',candidate['summary_sources'])]:
        assert isinstance(values,list) and len(values)<=(4 if k=='summary_sources' else 3)
        assert all(type(i)==int and i in ids for i in values)
        assert len(values)==len(set(values)),k
    assert candidate['summary_sources'],'Missing summary'
    assert any(candidate['fields'].values()),'Missing semantic fields'

def main():
    out=[];manifest=read(OUT/'manifest.json')
    for j in manifest['jobs']:
        p=OUT/'responses'/f"{j['doc_id']}.json"
        if not p.exists():continue
        env=read(p);assert env['request_sha256']==j['request_sha256']
        response=env['response'];assert response['model']==manifest['model']
        choice=response['choices'][0];assert choice['finish_reason']=='stop'
        candidate=strict_json(choice['message']['content']);packet=read(OUT/j['input']);validate(packet,candidate)
        excerpts={e['id']:e for e in packet['excerpts']}
        out.append({'doc_id':j['doc_id'],'file_name':packet['file_name'],'response_sha256':digest(p),'input_sha256':digest(OUT/j['input']),'fields':{k:[excerpts[i] for i in ids] for k,ids in candidate['fields'].items()},'summary':[excerpts[i] for i in candidate['summary_sources']],'semantic_review':'pending'})
    write(OUT/'semantic-review-packet.json',out)
    print(json.dumps(out,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
