"""Offline integrity check for a fully returned comparison; never calls APIs."""
from pathlib import Path
from run import DEFAULT_RUN, MODELS, INPUTS, HERE, digest, load, lines, verify_manifest, make_payload, object_hash, task_id, common, write, now

def main(out=DEFAULT_RUN):
    m=load(out/'manifest.json');verify_manifest(m)
    response_ids=[];count=0;native_count=0
    for model in MODELS:
        for item in m['items']:
            base=out/model.split('/')[1]/'units'/task_id(item)
            r=load(base/'result.json');response=load(base/'response.json')
            assert r['requested_model']==r['reported_model']==model
            assert r['provider']==response['provider']=='DeepInfra'
            assert r['request_sha256']==object_hash(make_payload(item,model,m))
            assert not (base/'inflight.json').exists()
            assert bool((base/'extraction.json').exists())==(r['status']=='valid')
            assert response['id']==r['response_id']
            response_ids.append(response['id']);count+=1
        for corpus,source in INPUTS:
            native={d['doc_id']:d for d in lines(source/'parsed.jsonl')}
            candidate=lines(out/model.split('/')[1]/corpus/'parsed.candidate.jsonl')
            assert set(native)=={d['doc_id'] for d in candidate}
            for d in candidate:
                assert not common.check(d)
                assert [b for b in d['blocks'] if b['run_ref']=='native']==native[d['doc_id']]['blocks']
                native_count+=1
    assert len(response_ids)==len(set(response_ids))
    report={'checked_at':now(),'passed':True,'original_source_hash_and_mtime_count':len(m['documents']),
        'frozen_image_count':len(m['items']),'response_count':count,'unique_response_ids':len(set(response_ids)),
        'candidate_documents_valid_with_native_blocks_preserved':native_count,
        'evaluation_code_sha256':{name:digest(HERE/name) for name in ['evaluate.py','audit_outputs.py','report.py','verify_final.py']},
        'frozen_request_code_and_schema_unchanged':True,'all_request_payload_hashes_match':True,
        'no_remaining_inflight_markers':True,'does_not_certify_visual_accuracy':True}
    write(out/'integrity-verification.json',report);print(report)

if __name__=='__main__':main()
