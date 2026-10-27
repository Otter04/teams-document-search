"""Versioned source-only incremental ingestion. Frozen v1 artifacts stay immutable."""
import copy, hashlib, importlib.util, json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'outputs/indexing-v2-001'
BASE=ROOT/'outputs/indexing-110-semantic-vector-001'
AUDIT=ROOT/'outputs/dataset-v2-content-audit-001'
FILES=Path('/Users/kangdongkyoon/Downloads/RAG_예비데이터셋_v2/files')
sys.path.insert(0,str(ROOT/'work/schema-deps'))
sys.path.insert(0,str(ROOT/'outputs/rag-parser-v3'))
def load(name,path):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m);return m
def read(p):return json.loads(Path(p).read_text())
def rows(p):return [json.loads(s) for s in Path(p).read_text().splitlines() if s.strip()]
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(p,x):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix(p.suffix+'.tmp');tmp.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n');tmp.replace(p)
def lines(p,x):Path(p).write_text(''.join(json.dumps(v,ensure_ascii=False)+'\n' for v in x))
P=load('v2_native_parser',ROOT/'outputs/rag-parser-v3/parse.py')
C=load('v2_vision_contract',ROOT/'outputs/rag-vision-v1/contract.py')
from jsonschema import Draft202012Validator
SCHEMA=copy.deepcopy(P.validation.SCHEMA)
SCHEMA['title']='Common blocks 1.1.0: added source formats and exact embedded-image frames'
SCHEMA['properties']['schema_version']['const']='1.1.0'
def extend_methods(x):
 if isinstance(x,dict):
  if 'enum' in x and 'native_parser' in x['enum']:x['enum'].append('reviewed_correction')
  for v in x.values():extend_methods(v)
 elif isinstance(x,list):
  for v in x:extend_methods(v)
extend_methods(SCHEMA)
SCHEMA['properties']['source']['properties']['format']['enum']+=['hwpx','ini','rtf','no_extension','jpg','png']
locs=SCHEMA['$defs']['loc']['oneOf']
for fmt in ['ini','rtf','no_extension']:
 loc=copy.deepcopy(next(x for x in locs if x['properties']['kind'].get('const')=='txt'));loc['properties']['kind']['const']=fmt;locs.append(loc)
loc=copy.deepcopy(next(x for x in locs if x['properties']['kind'].get('const')=='docx'));loc['properties']['kind']['const']='hwpx';loc['properties']['section']={'type':'string'};locs.append(loc)
for fmt in ['jpg','png']:
 locs.append({'type':'object','properties':{'kind':{'const':fmt},'bbox':{'$ref':'#/$defs/bbox'}},'required':['kind'],'additionalProperties':False})
validator=Draft202012Validator(SCHEMA)
P.validation.VALIDATOR=validator;C.common.VALIDATOR=validator
def check(r):
 errors=P.validation.check(r)
 def walk(x):
  if isinstance(x,dict):
   if x.get('kind') in ['hwpx','ini','rtf','no_extension','jpg','png'] and x['kind']!=r['source']['format']:errors.append('extended location format mismatch')
   if 'line_start' in x and x['line_start']>x['line_end']:errors.append('reversed extended line range')
   for v in x.values():walk(v)
  elif isinstance(x,list):
   for v in x:walk(v)
 walk(r);return errors
