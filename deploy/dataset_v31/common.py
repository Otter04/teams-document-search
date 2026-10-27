"""Versioned source-only incremental ingestion. Frozen v1 artifacts stay immutable."""
import copy, hashlib, importlib.util, json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'outputs/indexing-v31-001'
BASE=ROOT/'outputs/indexing-v2-001/prepared'
AUDIT=ROOT/'outputs/dataset-v31-audit-001'
FILES=Path('/Users/kangdongkyoon/Downloads/RAG_예비데이터셋_v3.1/files')
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
# Add source locations for native structured files and independently converted Office copies.
NEW_FORMATS={'doc':'docx','ppt':'pptx','xls':'xlsx','yaml':'txt','json':'txt','xml':'txt','jmx':'txt','html':'txt','csv':'txt'}
SCHEMA['title']='Common blocks 1.2.0: original-format locations and conversion provenance'
SCHEMA['properties']['schema_version']['const']='1.2.0'
for fmt,base in NEW_FORMATS.items():
 SCHEMA['properties']['source']['properties']['format']['enum'].append(fmt)
 loc=copy.deepcopy(next(x for x in locs if x['properties']['kind'].get('const')==base));loc['properties']['kind']['const']=fmt
 for key in ['structure_path','conversion_artifact']:loc['properties'][key]={'type':'string'}
 if fmt=='csv':
  for key in ['row','column']:loc['properties'][key]={'type':'integer','minimum':1}
 locs.append(loc)
validator=Draft202012Validator(SCHEMA);P.validation.VALIDATOR=validator;C.common.VALIDATOR=validator
OLD_CHECK=check
def check(r):
 errors=OLD_CHECK(r)
 def walk(x):
  if isinstance(x,dict):
   if x.get('kind') in NEW_FORMATS and x['kind']!=r['source']['format']:errors.append('new format location mismatch')
   for v in x.values():walk(v)
  elif isinstance(x,list):
   for v in x:walk(v)
 walk(r);return errors
