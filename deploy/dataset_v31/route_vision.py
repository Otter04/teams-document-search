"""Explicit source-image review of ten raster candidates; no query information."""
from common import *
from PIL import Image
import shutil

def main():
 records=rows(OUT/'native-new.jsonl');alljobs=read(OUT/'vision-jobs-unreviewed.json')
 # Reviewed contact sheet plus source shapes: cover decoration, not operational diagrams.
 excluded={'D-165-vision-slide1-image11':'dark cover background; no source text or labelled diagram',
 'D-166-vision-slide1-image12':'cover hospital logo and decorative green bands',
 'D-182-vision-slide1-image3':'RAUM corporate cover logo and geometric background',
 'D-183-vision-slide1-image3':'university cover logo and decorative blue bands',
 'D-188-vision-slide1-image3':'unlabelled decorative network motif on cover',
 'D-189-vision-slide1-image3':'unlabelled decorative network motif on cover'}
 jobs=[j for j in alljobs if j['id'] not in excluded]
 for r in records:
  for u in r['coverage']['units']:
   jid=r['doc_id']+'-'+u['unit_id'].replace(':','-')
   if jid in excluded:u.update(status='excluded',required=False,reason='assistant source-image review: '+excluded[jid])
 lines(OUT/'native-new.jsonl',records);write(OUT/'visual-routing-review.json',{'excluded_decoration':excluded,'required':[j['id'] for j in jobs],'reviewer':'assistant source-image review; not independent human assessment'})
 unique={};aliases={}
 for j in jobs:
  if j['pixel_sha256'] in unique:aliases[j['id']]=unique[j['pixel_sha256']]['id']
  else:unique[j['pixel_sha256']]=j
 write(OUT/'vision-jobs.json',jobs);write(OUT/'vision-unique.json',list(unique.values()));write(OUT/'vision-aliases.json',aliases)
 shutil.copyfile(ROOT/'deploy/dataset_v31/vision_batch.py',OUT/'vision_batch.py')
 print('vision calls',len(unique))
if __name__=='__main__':main()
