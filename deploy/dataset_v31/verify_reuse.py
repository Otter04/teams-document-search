"""Source geometry checks for reused vision; no model or gold."""
from common import *
from collections import Counter
from pypdf import PdfReader
from pptx import Presentation

def main():
 audit=[];paths=read(OUT/'source-paths.json')
 for r in read(OUT/'reuse-ledger.json'):
  if not r['source_changed']:continue
  did=r['doc_id'];new=Path(paths[did]);old=Path('/Users/kangdongkyoon/Downloads/RAG_예비데이터셋_v2/files')/new.relative_to(FILES)
  if new.suffix=='.pdf':
   checks=[]
   with P.pdfplumber.open(old) as a,P.pdfplumber.open(new) as b:
    for i,(pa,pb) in enumerate(zip(a.pages,b.pages)):
     oldpix={hashlib.sha256(x['stream'].get_data()).hexdigest() for x in pa.images if not (i==0 and x['x0']<=0 and x['top']<=0 and x['x1']>=pa.width*.99 and x['bottom']>=pa.height*.99)};newpix={hashlib.sha256(x['stream'].get_data()).hexdigest() for x in pb.images}
     assert oldpix<=newpix,(did,i,'image stream delta')
     checks.append({'page':i+1,'old_unique_image_streams_preserved':len(oldpix)})
     def sig(x):return (x['object_type'],*[round(x[k],3) for k in ['x0','top','x1','bottom']])
     ca=Counter(sig(x) for x in pa.lines+pa.rects+pa.curves if not (i==0 and x['x0']<=0 and x['top']<=0 and x['x1']>=pa.width*.99 and x['bottom']>=pa.height*.99));cb=Counter(sig(x) for x in pb.lines+pb.rects+pb.curves);assert not ca-cb,(did,i,'graphics geometry delta',list((ca-cb).items())[:10]);checks[i]['old_graphic_geometries_preserved']=sum(ca.values())
   audit.append({'doc_id':did,'pages':checks})
  else:
   aa=Presentation(old);bb=Presentation(new);checks=[]
   for i,(a,b) in enumerate(zip(aa.slides,bb.slides),1):
    shapes={s.shape_id:s for s,_ in P.native.walk_shapes(b.shapes)};n=0
    for s,_ in P.native.walk_shapes(a.shapes):
     if s.has_text_frame and s.text.strip():continue
     if s.shape_type==14 and not getattr(s,'text','').strip():continue
     if s.shape_type==1 and not s.text.strip() and s.left==0 and s.top==0 and s.width>=aa.slide_width*.99 and s.height>=aa.slide_height*.99:continue
     assert s.shape_id in shapes,(did,i,s.shape_id,str(s.shape_type),s.left,s.top,s.width,s.height)
     t=shapes[s.shape_id];assert s.shape_type==t.shape_type
     assert (s.left,s.top,s.width,s.height)==(t.left,t.top,t.width,t.height),(did,i,s.shape_id)
     if s.shape_type==13:assert s.image.blob==t.image.blob
     if s.has_table:assert [[c.text for c in row.cells] for row in s.table.rows]==[[c.text for c in row.cells] for row in t.table.rows]
     n+=1
    checks.append({'slide':i,'nontext_shape_geometry_preserved':n})
   audit.append({'doc_id':did,'slides':checks,'whole_slide_vision_coordinates_removed':True})
 write(OUT/'reuse-geometry-verification.json',audit);print('Verified changed source geometry',len(audit))
if __name__=='__main__':main()
