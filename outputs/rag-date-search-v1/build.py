"""Collect source file metadata and rebuild native artifacts, without evaluation labels."""
import argparse, json, sys
from pathlib import Path
import date_search as d
E=d.E

def build(parsed_path,files_root,reference_path,rules_path,output):
    out=Path(output)
    if out.exists():raise ValueError('choose a new output directory')
    parsed={r['doc_id']:r for r in E.read_lines(parsed_path)}
    if len(parsed)!=len(E.read_lines(parsed_path)):raise ValueError('duplicate doc_id')
    ref=E.read_json(reference_path);rules=E.read_json(rules_path)
    files=d.collect_files(parsed,files_root)
    first=next(iter(parsed.values()));warm=E.extract(first,ref);assert not E.check_output(warm,first)
    E.timestamp('2000-01-01 00:00:00')
    guard={'active':True,'blocked_attempts':0}
    def audit(event,args):
        if guard['active'] and event in {'open','socket.connect','socket.getaddrinfo','subprocess.Popen','os.system'}:
            guard['blocked_attempts']+=1;raise RuntimeError('IO forbidden during enrichment/indexing: '+event)
    sys.addaudithook(audit)
    enriched={};dates={};chunks=[]
    for did,r in parsed.items():
        enriched[did]=E.extract(r,ref)
        errors=E.check_output(enriched[did],r)
        if errors:raise ValueError((did,errors))
        dates[did]=d.date_metadata(r,enriched[did],files[did])
        c=d.old.old.base.make_chunks(r,enriched[did]);errors=d.old.old.base.validate_chunks(c,r,enriched[did])
        if errors:raise ValueError((did,errors))
        chunks.append(c)
    index=d.old.old.previous.build_index(d.old.old.base.build_index(chunks,ref['clients']),rules)
    bundle=d.old.prepare(index,parsed,enriched)
    d.attach_dates(index,dates);index['system_terms']=ref['system_terms']
    guard['active']=False
    out.mkdir(parents=True)
    for name,rows in [('enriched.jsonl',enriched.values()),('chunks.jsonl',chunks),('source-metadata.jsonl',files.values()),('date-metadata.jsonl',dates.values())]:E.save_lines(out/name,rows)
    E.dump(out/'index.json',index);E.dump(out/'features.json',bundle)
    E.dump(out/'enrichment.schema.json',E.schema())
    E.dump(out/'date-metadata.schema.json',{
      '$schema':'https://json-schema.org/draft/2020-12/schema','type':'object','additionalProperties':False,
      'required':['schema_version','doc_id','source_sha256','source_metadata','visual_pending','fields'],
      'properties':{'schema_version':{'const':'1.0.0'},'doc_id':{'type':'string','minLength':1},'source_sha256':{'type':'string','pattern':'^[0-9a-f]{64}$'},
        'source_metadata':{'type':'object','required':['doc_id','source_sha256','relative_path','modified_at_utc','modified_at_ns','collected_at_utc','origin','semantics']},
        'visual_pending':{'type':'boolean'},'fields':{'type':'object','additionalProperties':False,'required':sorted(d.DATE_FIELDS),
          'properties':{}}}})
    # A compact schema is supplemented by source identity and semantic checks in date_metadata().
    schema=E.read_json(out/'date-metadata.schema.json')
    for field,role in [('표지일','cover_date'),('작성일','explicit_written_date'),('파일최종수정일','file_modified_at')]:
        schema['properties']['fields']['properties'][field]={'type':'object','additionalProperties':False,'required':['value','status','role','evidence','observations'],
          'properties':{'value':{'type':['string','null']},'status':{'enum':['extracted','not_observed_native','needs_review']},'role':{'const':role},'evidence':{'type':'array'},'observations':{'type':'array'}},
          'allOf':[{'if':{'properties':{'status':{'const':'extracted'}}},'then':{'properties':{'value':{'type':'string','minLength':1},'evidence':{'minItems':1}}},'else':{'properties':{'value':{'const':None}}}}]}
    E.dump(out/'date-metadata.schema.json',schema)
    from jsonschema import Draft202012Validator
    for dm in dates.values():Draft202012Validator(schema).validate(dm)
    code_paths=[Path(parsed_path),Path(reference_path),Path(rules_path),Path(__file__),d.ROOT/'date_search.py',d.ROOT/'CONTRACT.md',E.ROOT/'enrich.py',E.ROOT.parent/'rag-enrichment-v1/enrich.py',d.old.ROOT/'field_search.py',d.old.old.ROOT/'condition_search.py',d.old.old.previous.ROOT/'search.py',d.old.old.base.ROOT/'pipeline.py']
    E.dump(out/'provenance.json',{'version':d.VERSION,'model_called':False,'external_api_calls':0,'gold_read_during_build':False,
      'documents':len(parsed),'source_hashes_verified':len(files),'blocked_io_attempts':guard['blocked_attempts'],
      'inputs':{str(p.resolve()):E.digest(p) for p in code_paths},'outputs':{p.name:E.digest(p) for p in out.iterdir() if p.is_file()}})
    return {'documents':len(parsed),'modified_times':len(files),'native_chunks':sum(len(c['chunks']) for c in chunks),'output':str(out)}

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for n in ('parsed','files-root','reference','rules','output'):p.add_argument('--'+n,required=True)
    a=p.parse_args();print(json.dumps(build(a.parsed,a.files_root,a.reference,a.rules,a.output),ensure_ascii=False))
