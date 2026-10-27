"""Import a read-only remote tar snapshot without overwriting saved responses."""
import argparse,tarfile
from common import *
def main():
 ap=argparse.ArgumentParser();ap.add_argument('snapshot',type=Path);a=ap.parse_args()
 ids={j['id'] for j in read(OUT/'vision-unique.json')};added=0
 with tarfile.open(a.snapshot) as t:
  for entry in t.getmembers():
   if not entry.isfile():continue
   parts=Path(entry.name).parts
   if len(parts)!=3 or parts[0]!='vision-responses' or parts[1] not in ids or parts[2] not in ['response.json','attempt.json']:continue
   payload=t.extractfile(entry).read();json.loads(payload);dest=OUT/entry.name;dest.parent.mkdir(parents=True,exist_ok=True)
   if dest.exists():assert dest.read_bytes()==payload,'Remote response changed: '+entry.name
   else:dest.write_bytes(payload);added+=1
  progress=t.extractfile('vision-progress.json').read();write(OUT/'remote-progress.json',json.loads(progress))
 print('Imported',added,'immutable files')
if __name__=='__main__':main()
