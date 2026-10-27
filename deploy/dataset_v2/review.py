"""Validate collected responses; source approval is a separate explicit artifact."""
from common import *
Q=load('v2_quality',ROOT/'outputs/rag-vision-v3/quality.py')

def response(job):
 p=OUT/'vision-responses'/job['id']/'response.json'
 if not p.exists():return None, ['response not collected']
 envelope=read(p);errors=[]
 if envelope['http_status']!=200:return None,['HTTP '+str(envelope['http_status'])]
 choices=envelope['response'].get('choices',[])
 if len(choices)!=1:return None,['expected one choice']
 if choices[0].get('finish_reason')!='stop':errors.append('incomplete finish: '+str(choices[0].get('finish_reason')))
 try:data=json.loads(choices[0]['message']['content'])
 except (KeyError,TypeError,ValueError):return None,errors+['invalid JSON content']
 errors+=C.check_wire(data)
 return data,errors

def approved(job):
 review_path=OUT/'vision-review'/f"{job['id']}.json"
 if not review_path.exists():return None
 data,errors=response(job)
 r=read(review_path);raw=OUT/'vision-responses'/job['id']/'response.json'
 if errors:
  # Only this explicitly reviewed table repair may cross the raw wire gate.
  # HTTP, incomplete output, invalid JSON and all other defects stay blocked.
  assert data is not None and set(errors)<= {'cell outside table','unrepresented table cells'},errors
  assert r.get('source_structure_repaired') is True and r.get('raw_validation_errors')==errors,errors
 assert r['response_sha256']==sha(raw) and r['asset_sha256']==sha(OUT/job['asset_path'])
 assert r['decision']=='approved_after_source_review'
 corrected=OUT/r['corrected_path'];assert sha(corrected)==r['corrected_sha256']
 data=read(corrected);assert not C.check_wire(data)
 assert not [i for i in Q.check_quality(data) if i['blocks_transfer']]
 return data

def main():
 report=[]
 for j in read(OUT/'vision-unique.json'):
  data,errors=response(j)
  quality=Q.check_quality(data) if data is not None and not errors else []
  report.append({'job_id':j['id'],'collected':data is not None,'baseline_errors':errors,'quality_issues':quality,
    'source_reviewed':approved(j) is not None,'self_report':data.get('status') if data else None})
 write(OUT/'vision-transfer-review.json',report)
 print(json.dumps({'planned':len(report),'collected':sum(r['collected'] for r in report),
  'approved_after_source_review':sum(r['source_reviewed'] for r in report)},ensure_ascii=False))
if __name__=='__main__':main()
