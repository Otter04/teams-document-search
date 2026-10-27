"""Select source-backed semantic gaps only; use the existing evidence-selection prompt."""
from enrichment import *
import re,shutil
legacy=load('v31_semantic_prompt',ROOT/'deploy/indexing/prepare.py')
def main():
 dest=OUT/'semantic';dest.mkdir(exist_ok=True);assert not (dest/'manifest.json').exists()
 records=rows(OUT/'native-new.jsonl');metadata={r['doc_id']:r for r in rows(OUT/'metadata-preliminary.jsonl')};jobs=[];routing=[]
 for r in records:
  did=r['doc_id'];typ=metadata[did]['fields']['문서종류']['value'];name=r['source']['file_name']
  fields=['문제점','목표','추진범위'] if typ in ['제안서','설계서'] else ['요청사항','후속조치','조건및합의'] if typ in ['기타','제안요청서'] else []
  routing.append({'doc_id':did,'document_type':typ,'fields':fields,'route':'Orin evidence selection' if fields else 'rules and source blocks suffice for fixed metadata scope'})
  if not fields:continue
  excerpts=[]
  for b in r['blocks']:
   if b['type'] in ['slide','table','figure'] or b['content_refs']:continue
   offset=0
   for raw in b['text'].splitlines(keepends=True):
    text=raw.strip()
    if text:
     start=offset+raw.index(text);excerpts.append({'id':len(excerpts)+1,'text':text,'block_id':b['block_id'],'start':start,'end':start+len(text),'loc':b['loc'],'section':b['heading_path']})
    offset+=len(raw)
  assert excerpts and len(excerpts)<500,'Unbounded semantic packet requires review'
  ids=[e['id'] for e in excerpts];arr=lambda n:{'type':'array','items':{'type':'integer','enum':ids},'maxItems':n}
  schema={'type':'object','additionalProperties':False,'required':['fields','summary_sources'],'properties':{'fields':{'type':'object','additionalProperties':False,'required':fields,'properties':{k:arr(3) for k in fields}},'summary_sources':arr(4)}}
  packet={'doc_id':did,'file_name':name,'fields':fields,'excerpts':excerpts,'source_record_sha256':E.record_hash(r)};write(dest/'inputs'/f'{did}.json',packet)
  payload={'model':'qwen3.6-35b-a3b','messages':[{'role':'system','content':legacy.PROMPT},{'role':'user','content':json.dumps({'document_type':typ,'file_name':name,'fields':fields,'excerpts':[{'id':e['id'],'text':e['text'],'section':e['section']} for e in excerpts]},ensure_ascii=False)}],'temperature':0,'max_tokens':512,'stream':False,'chat_template_kwargs':{'enable_thinking':False},'response_format':{'type':'json_schema','json_schema':{'name':'semantic_evidence_selection','strict':True,'schema':schema}}}
  write(dest/'requests'/f'{did}.json',payload);jobs.append({'doc_id':did,'request':f'requests/{did}.json','request_sha256':sha(dest/'requests'/f'{did}.json'),'input':f'inputs/{did}.json','input_sha256':sha(dest/'inputs'/f'{did}.json')})
 write(dest/'routing.json',routing);write(dest/'manifest.json',{'jobs':jobs,'model':'qwen3.6-35b-a3b','scope':'new semantic gaps; preserve existing rule metadata; source excerpts only','gold_read':False})
 shutil.copyfile(ROOT/'deploy/indexing/run_semantic.py',dest/'run_semantic.py');(dest/'PROMPT.txt').write_text(legacy.PROMPT)
 print('semantic selected',len(jobs),[j['doc_id'] for j in jobs])
if __name__=='__main__':main()
