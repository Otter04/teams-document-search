"""Hash-bound content equivalence; no fuzzy names, score sums or answer IDs."""
import json,re
from pathlib import Path
POLICY='highest-scoring-equivalent-format-1.0'
REGISTRY=Path(__file__).with_name('content_equivalence.json')
FORMATS={'pdf','ppt','pptx','doc','docx','xls','xlsx','csv','txt','yaml','json'}
def requested_formats(query):
    return {x.lower() for x in re.findall(r'(?<![A-Za-z0-9])(?:pdf|pptx?|docx?|xlsx?|csv|txt|yaml|json)(?![A-Za-z0-9])',query,re.I)}
class ContentEquivalence:
    def __init__(self,docs,registry=None):
        self.docs=docs;self.groups={};self.proof={}
        data=registry if registry is not None else json.loads(REGISTRY.read_text())
        for group in data['groups']:
            if group['status']!='verified_same_content':continue
            ids={d for d in group['members'] if d in docs and docs[d]['source_sha256']==group['source_hashes'][d]}
            if len(ids)<2:continue
            for did in ids:
                if did in self.groups:raise ValueError('Overlapping equivalence registry')
                self.groups[did]=ids;self.proof[did]=group['id']
    def same(self,a,b):
        if a==b:return True
        if a not in self.docs or b not in self.docs:return False
        # Binary duplicates only within the already established family.
        x,y=self.docs[a],self.docs[b]
        return b in self.groups.get(a,set()) or (x['family_id']==y['family_id'] and x['source_sha256']==y['source_sha256'])
    def accepted(self,did,query='',plan=None):
        p=plan or {};formats=requested_formats(query)
        ids={d for d in self.docs if self.same(did,d)}
        if formats:ids={d for d in ids if self.docs[d]['format'].lower() in formats}
        # Explicit version/status/date requirements cannot be softened by equivalence.
        ref=self.docs[did]
        if p.get('requested_version'):ids={d for d in ids if self.docs[d].get('version_label')==ref.get('version_label')}
        if p.get('conditions',{}).get('status'):
            ids={d for d in ids if self.docs[d]['metadata'].get('status')==ref['metadata'].get('status')}
        date_fields=set(p.get('required_dates',{}))
        if p.get('sort'):date_fields.add(p['sort']['field'])
        if date_fields:ids={d for d in ids if all(self.docs[d]['metadata'].get(k)==ref['metadata'].get(k) for k in date_fields)}
        return ids
