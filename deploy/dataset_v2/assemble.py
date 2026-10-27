"""Assemble v2 source artifacts, with explicit source review and vector reuse gates."""
import argparse,collections,time
import numpy as np
from enrichment import *
from reuse import replace_refs
from review import approved
from finalize_bm25 import projection

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--partial',action='store_true');args=ap.parse_args()
 dest=OUT/('prepared-partial' if args.partial else 'prepared')
 assert args.partial or not (dest/'assembly.json').exists(),'Preserve completed assembly'
 dest.mkdir(exist_ok=True);start=time.perf_counter()
 for rel,h in read(OUT/'baseline-freeze.json').items():assert sha(ROOT/rel)==h,rel
 paths=read(OUT/'source-paths.json')
 for did,h in read(OUT/'source-freeze.json').items():assert sha(paths[did])==h,did
 reference=read(ROOT/'outputs/rag-enrichment-v1/reference-data.json')
 rules=read(ROOT/'outputs/rag-rule-search-v1/rules.json')
 originals=rows(OUT/'reused-records.jsonl');new={r['doc_id']:r for r in rows(OUT/'native-new.jsonl')}
 jobs=read(OUT/'vision-jobs.json');byjob={j['id']:j for j in jobs};aliases=read(OUT/'vision-aliases.json')
 admitted=[];pending=[]
 for j in jobs:
  source=byjob[aliases.get(j['id'],j['id'])];wire=approved(source)
  if wire is None:pending.append(j['id']);continue
  assert j['pixel_sha256']==source['pixel_sha256']
  r=C.convert(new[j['doc_id']],j,wire,'qwen3.6-35b-a3b',provider='Orin local vLLM',quantization='AWQ-4bit')
  unit=next(u for u in r['coverage']['units'] if u['unit_id']==j['unit_id'])
  unit.update(status='completed',reason='assistant source-image review; raw response and review preserved separately')
  run=r['runs'][-1];run['prompt_version']='vision-prompt-proposal-001';run['implementation']='source-reviewed-vision-v2-ingestion'
  corrected=bool(read(OUT/'vision-review'/f"{source['id']}.json")['changes'])
  if corrected:run['method']='reviewed_correction'
  for b in r['blocks']:
   if b['run_ref']==run['run_id']:b['warnings']=[w for w in b['warnings'] if w!='model_output_needs_source_review']
  assert not check(r),check(r);new[j['doc_id']]=r
  admitted.append({'job_id':j['id'],'response_job_id':source['id'],'exact_pixel_reuse':j['id']!=source['id'],'review':str((OUT/'vision-review'/f"{source['id']}.json").relative_to(ROOT))})
 assert args.partial or not pending,('Unreviewed vision prevents final assembly',pending)
 # Existing records are already projected; project only newly parsed sources.
 records={r['doc_id']:r for r in originals};projection_audit={}
 for did,r in new.items():records[did],projection_audit[did]=projection(r)
 source_meta=d.collect_files(records,FILES);metadata={};dates={};chunks=[]
 for did,r in records.items():
  assert not check(r),(did,check(r))
  m=extract(r,reference);metadata[did]=m;dates[did]=d.date_metadata(r,m,source_meta[did])
  c=d.old.old.base.make_chunks(r,m)
  assert not d.old.old.base.validate_chunks(c,r,m),(did,d.old.old.base.validate_chunks(c,r,m))
  chunks.append(c)
 # Retain the 17 explicitly reviewed semantic outputs, remapping source identifiers only.
 idmaps=read(OUT/'source-id-map.json');semantics={};semantic_chunks=[]
 for old in rows(BASE/'semantic-enriched.jsonl'):
  did=old['doc_id'];m=replace_refs(old,idmaps[did]);blocks={b['block_id']:b for b in records[did]['blocks']}
  for item in [x for f in m['fields'].values() for x in f['items']]+m['summary']['items']:
   ev=item['evidence'];assert blocks[ev['block_id']]['text'][ev['start']:ev['end']]==item['value'],(did,item)
  m['reuse_provenance']={'source_record':str(BASE/'semantic-enriched.jsonl'),'v2_source_sha256':records[did]['source']['sha256'],'source_spans_reverified':True,'new_llm_call':False}
  semantics[did]=m
 for old in rows(BASE/'semantic-chunks.jsonl'):
  c=replace_refs(old,idmaps[old['doc_id']]);did=c['doc_id'];c['source_sha256']=records[did]['source']['sha256']
  blocks={b['block_id']:b for b in records[did]['blocks']}
  for ref in c['source_refs']:assert ref['block_id'] in blocks and 0<=ref['start']<ref['end']<=len(blocks[ref['block_id']]['text'])
  semantic_chunks.append(c)
 index=d.old.old.previous.build_index(d.old.old.base.build_index(chunks,reference['clients']),rules)
 d.attach_dates(index,dates);index['system_terms']=reference['system_terms']
 docs=[];bychunk={c['doc_id']:c for c in chunks}
 for did,r in records.items():
  doc={'doc_id':did,'source':r['source'],'metadata':metadata[did]['fields'],'date_metadata':dates[did]['fields'],
   'summary':semantics.get(did,{}).get('summary',{}).get('text'),'summary_status':'source_reviewed_extractive' if did in semantics else 'optional_not_requested',
   'semantic_metadata':semantics.get(did),'chunk_ids':[c['chunk_id'] for c in bychunk[did]['chunks']]+[c['chunk_id'] for c in semantic_chunks if c['doc_id']==did],
   'source_content_sha256':E.record_hash(r)}
  index['documents'][did].update(summary=doc['summary'],semantic_metadata=doc['semantic_metadata'],indexed_chunk_count=len(doc['chunk_ids']))
  docs.append(doc)
 # This legacy feature bundle is staging data only. Serving remains Elasticsearch/Nori.
 for c in semantic_chunks:index['entries'][c['chunk_id']]={k:c[k] for k in ['doc_id','kind','text','context_header','table_header_text','source_refs','context_refs']}
 inputs=[]
 for group in chunks:
  for c in group['chunks']:inputs.append({'doc_id':group['doc_id'],'chunk_id':c['chunk_id'],'kind':'source_chunk','text':'\n'.join(x for x in [c['context_header'],c['table_header_text'],c['text']] if x),'source_refs':c['source_refs'],'source_sha256':group['source']['sha256']})
 for c in semantic_chunks:inputs.append({'doc_id':c['doc_id'],'chunk_id':c['chunk_id'],'kind':c['kind'],'text':c['context_header']+'\n'+c['text'],'source_refs':c['source_refs'],'source_sha256':c['source_sha256']})
 for i,r in enumerate(inputs):r.update(vector_id=i,embedding_text_sha256=hashlib.sha256(r['text'].encode()).hexdigest())
 assert len({r['chunk_id'] for r in inputs})==len(inputs)
 identity=read(BASE/'embedding-manifest.json');vectors=np.load(BASE/'vectors.npy',allow_pickle=False)
 assert sha(BASE/'vectors.npy')==identity['vectors_sha256'] and sha(BASE/'embedding-inputs.jsonl')==identity['input_sha256']
 oldinputs=rows(BASE/'embedding-inputs.jsonl');assert vectors.shape==(len(oldinputs),1024)
 oldmap={r['embedding_text_sha256']:r for r in oldinputs};cache=dest/'embedding-cache';cache.mkdir(exist_ok=True);reuse=[]
 for r in inputs:
  prior=oldmap.get(r['embedding_text_sha256'])
  if prior:
   assert prior['text']==r['text'];vec=vectors[prior['vector_id']]
   assert np.isfinite(vec).all() and abs(np.linalg.norm(vec)-1)<1e-5
   key=hashlib.sha256((identity['model_fingerprint']+'\ncls-l2-fp16-v1\n'+r['text']).encode()).hexdigest()
   np.save(cache/(key+'.npy'),vec,allow_pickle=False)
   reuse.append({'chunk_id':r['chunk_id'],'prior_chunk_id':prior['chunk_id'],'prior_vector_id':prior['vector_id'],'embedding_text_sha256':r['embedding_text_sha256'],'cache_key':key})
 current_reuse=[];stable=OUT/'embedding-stable-001'
 if (stable/'embedding-manifest.json').exists():
  sm=read(stable/'embedding-manifest.json');assert sm['model_fingerprint']==identity['model_fingerprint']
  assert sha(stable/'embedding-inputs.jsonl')==sm['input_sha256'] and sha(stable/'vectors.npy')==sm['vectors_sha256']
  sv=np.load(stable/'vectors.npy',allow_pickle=False);si=rows(stable/'embedding-inputs.jsonl');assert sv.shape==(len(si),1024)
  sx={r['embedding_text_sha256']:(i,r) for i,r in enumerate(si)}
  for r in inputs:
   if r['embedding_text_sha256'] in oldmap or r['embedding_text_sha256'] not in sx:continue
   i,prior=sx[r['embedding_text_sha256']];assert r['text']==prior['text']
   vec=sv[i];assert np.isfinite(vec).all() and abs(np.linalg.norm(vec)-1)<1e-5
   key=hashlib.sha256((identity['model_fingerprint']+'\ncls-l2-fp16-v1\n'+r['text']).encode()).hexdigest();np.save(cache/(key+'.npy'),vec,allow_pickle=False)
   current_reuse.append({'chunk_id':r['chunk_id'],'prior_chunk_id':prior['chunk_id'],'stable_vector_id':i,'cache_key':key})
 for name,data in [('indexing-records.jsonl',records.values()),('parsed.jsonl',list(originals)+list(new.values())),('enriched.jsonl',metadata.values()),('date-metadata.jsonl',dates.values()),('source-metadata.jsonl',source_meta.values()),('chunks.jsonl',chunks),('semantic-enriched.jsonl',semantics.values()),('semantic-chunks.jsonl',semantic_chunks),('document-index.jsonl',docs),('embedding-inputs.jsonl',inputs)]:lines(dest/name,data)
 write(dest/'index.json',index);write(dest/'projection-audit.json',projection_audit);write(dest/'vision-admission.json',admitted);write(dest/'vector-reuse.json',reuse)
 oldmeta={r['doc_id']:r for r in rows(BASE/'enriched.jsonl')};changes=[]
 for did,old in oldmeta.items():
  for field,v in old['fields'].items():
   n=metadata[did]['fields'][field]
   if (v['value'],v['status'])!=(n['value'],n['status']):changes.append({'doc_id':did,'field':field,'before':v,'after':n})
 write(dest/'old-metadata-changes.json',changes)
 write(dest/'current-run-vector-reuse.json',current_reuse)
 report={'state':'partial_not_deployable' if pending else 'assembled_pending_embedding_and_index_load','documents':len(records),'vision_units_admitted':len(admitted),'vision_units_pending':pending,'semantic_outputs_reused':len(semantics),'source_chunks':sum(len(c['chunks']) for c in chunks),'embedding_inputs':len(inputs),'vectors_reusable':len(reuse),'current_run_vectors_cached':len(current_reuse),'vectors_to_generate':len(inputs)-len(reuse)-len(current_reuse),'metadata_changes_existing':len(changes),'old_source_artifacts_preserved':True,'gold_used':False,'new_semantic_calls':0,'elapsed_seconds':time.perf_counter()-start}
 for rel,h in read(OUT/'baseline-freeze.json').items():assert sha(ROOT/rel)==h,rel
 write(dest/'assembly.json',report);print(json.dumps(report,ensure_ascii=False))
if __name__=='__main__':main()
