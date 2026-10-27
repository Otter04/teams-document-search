"""Load the existing date/condition search with reviewed-literal enrichment."""
import importlib.util
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'outputs/rag-live-001'
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);sys.modules[name]=module
    spec.loader.exec_module(module);return module

E=load('enrich',ROOT/'outputs/rag-integrated-enrichment-v1/enrich.py')
sys.path.insert(0,str(ROOT/'outputs/rag-date-search-v2'))
import date_search as d
assert d.E is E and d.old.old.base.enrich is E
common=load('live_common_validator',ROOT/'outputs/common-block-design/validate_design.py')
read=lambda p:json.loads(Path(p).read_text())
def lines(p):return [json.loads(x) for x in Path(p).read_text().splitlines() if x.strip()]
def write(p,x):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')
