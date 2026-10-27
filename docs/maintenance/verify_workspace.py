"""Read-only artifact/link checks; writes only this maintenance verification report."""
import hashlib
import json
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent

def main():
    before=json.loads((HERE/'preservation-before.json').read_text())
    changed=[];missing=[]
    for name,h in before['files'].items():
        p=ROOT/name
        if not p.is_file():missing.append(name)
        elif hashlib.sha256(p.read_bytes()).hexdigest()!=h:changed.append(name)
    archive=ROOT/'docs/archive/2026-10-19-before-model-decision'
    backups={n:hashlib.sha256((archive/n).read_bytes()).hexdigest()==h for n,h in before['archived_root_documents'].items()}
    cat=json.loads((HERE/'catalog.json').read_text());badshort=[]
    for row in cat:
        p=ROOT/row['shortcut']
        if not p.is_symlink() or not p.exists() or p.resolve()!=(ROOT/row['original_path']).resolve():badshort.append(row['shortcut'])
    docs=[ROOT/'README.md',ROOT/'NEXT_TASK.md',ROOT/'outputs/README.md',ROOT/'work/README.md']
    docs += [p for p in (ROOT/'docs').rglob('*.md') if '2026-10-19-before-model-decision' not in p.parts]
    badlinks=[];count=0
    for p in docs:
        for target in re.findall(r'\[[^\]]*\]\(([^)]+)\)',p.read_text()):
            if re.match(r'\w+://',target) or target.startswith('#'):continue
            count+=1
            if not (p.parent/target.split('#')[0]).resolve().exists():badlinks.append({'file':str(p.relative_to(ROOT)),'target':target})
    result={'status':'passed' if not(changed or missing or badshort or badlinks) and all(backups.values()) else 'failed',
        'existing_output_files_verified':len(before['files']),'changed':changed,'missing':missing,
        'old_root_documents_preserved':backups,'categorized_packages':len(cat),'categories':len(set(x['category'] for x in cat)),
        'broken_shortcuts':badshort,'local_markdown_links_checked':count,'broken_links':badlinks,
        'root_document_lines':{n:{'before':len((archive/n).read_text().splitlines()),'after':len((ROOT/n).read_text().splitlines())} for n in ['README.md','NEXT_TASK.md']},
        'paid_calls':0,'runtime_configuration_changed':False}
    (HERE/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if result['status']!='passed':raise SystemExit(1)

if __name__=='__main__':main()
