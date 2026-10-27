"""Admit exact source spans after explicit assistant review; no new model calls."""
from enrichment import *
from jsonschema import Draft202012Validator

def main():
 dest=OUT/'semantic';manifest=read(dest/'manifest.json');records={r['doc_id']:r for r in rows(OUT/'native-new.jsonl')};results=[];extras=[];reviews=[]
 for j in manifest['jobs']:
  did=j['doc_id'];packet=read(dest/j['input']);raw=read(dest/'responses'/f'{did}.json');request=read(dest/j['request'])
  assert sha(dest/j['input'])==j['input_sha256'] and sha(dest/j['request'])==j['request_sha256']==raw['request_sha256']
  assert raw['http_status']==200 and raw['response']['choices'][0]['finish_reason']=='stop'
  data=json.loads(raw['response']['choices'][0]['message']['content']);assert not list(Draft202012Validator(request['response_format']['json_schema']['schema']).iter_errors(data))
  assert packet['source_record_sha256']==E.record_hash(records[did]);by={e['id']:e for e in packet['excerpts']};blocks={b['block_id']:b for b in records[did]['blocks']};corrections=[]
  if did=='D-172':data['fields']['목표']=[];corrections.append('Remove duplicated bandwidth design excerpt from goal; retain under implementation scope and summary.')
  if did=='D-178':data['fields']['요청사항']=[4];data['fields']['조건및합의']=[5,6];corrections.append('Allowed migration hours and conditional alternative equipment belong under conditions; preserve directive and follow-up excerpts.')
  def value(i):
   ev=by[i];b=blocks[ev['block_id']];assert b['text'][ev['start']:ev['end']]==ev['text'] and ev['loc']==b['loc'] and not b['content_refs']
   return {'value':ev['text'],'evidence':{k:ev[k] for k in ['block_id','start','end','loc']},'source_context':'document_body'}
  fields={k:{'status':'extracted' if v else 'not_found_in_selected_evidence','items':[value(i) for i in dict.fromkeys(v)],'exhaustive':False,'method':'Orin Qwen3.6 evidence selection + assistant source review'} for k,v in data['fields'].items()}
  summary=[value(i) for i in dict.fromkeys(data['summary_sources'])]
  result={'doc_id':did,'fields':fields,'summary':{'kind':'extractive','items':summary,'text':'\n'.join(x['value'] for x in summary),'exhaustive':False},'provenance':{'model':'qwen3.6-35b-a3b','provider':'Orin local vLLM','quantization':'AWQ-4bit','response_sha256':sha(dest/'responses'/f'{did}.json'),'input_sha256':j['input_sha256'],'reviewer':'assistant; not independent human evaluation','notes':'All accepted values are verbatim source spans. Empty fields are not filled by guessing; selected summaries are non-exhaustive.'}}
  text='\n'.join(k+': '+x['value'] for k,f in fields.items() for x in f['items']);text+='\n핵심 요약(원문 발췌):\n'+result['summary']['text'];refs=[]
  for ev in [x['evidence'] for f in fields.values() for x in f['items']]+[x['evidence'] for x in summary]:
   if ev not in refs:refs.append(ev)
  extras.append({'doc_id':did,'chunk_id':did+'-SEM-'+hashlib.sha256(text.encode()).hexdigest()[:16],'kind':'semantic_metadata_excerpt','text':text,'context_header':records[did]['source']['file_name']+' | 검증된 의미 메타데이터·원문 발췌 요약','table_header_text':'','source_refs':refs,'context_refs':[],'derived_labels':True,'semantic_record_ref':did,'source_sha256':records[did]['source']['sha256']})
  results.append(result);reviews.append({'doc_id':did,'status':'approved_after_source_review','response_sha256':result['provenance']['response_sha256'],'input_sha256':j['input_sha256'],'corrections':corrections,'accepted':data,'independent_accuracy_score':None})
 lines(dest/'semantic-enriched.jsonl',results);lines(dest/'semantic-chunks.jsonl',extras);write(dest/'semantic-review.completed.json',reviews);print('Reviewed',len(results))
if __name__=='__main__':main()
