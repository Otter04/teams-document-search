"""Image-only ruled-table detection. No templates, IDs, references or OCR words."""
import cv2
import numpy as np


def bands(indices, gap=12):
    groups=[]
    for i in indices:
        if not groups or i-groups[-1][-1]>gap: groups.append([int(i)])
        else: groups[-1].append(int(i))
    return [int(round(sum(g)/len(g))) for g in groups]


def detect_tables(image):
    """Return conservative rectangular grids in original image pixel coordinates.

    Only connected, repeatedly ruled grids are accepted. Isolated boxes and
    flowchart connectors are excluded; borderless tables are unsupported.
    """
    gray=np.asarray(image.convert('L'))
    h,w=gray.shape
    ink=cv2.adaptiveThreshold(gray,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C,cv2.THRESH_BINARY_INV,31,12)
    horizontal=cv2.morphologyEx(cv2.dilate(ink,np.ones((max(3,h//700),1),np.uint8)),cv2.MORPH_OPEN,np.ones((1,max(20,w//30)),np.uint8))
    vertical=cv2.morphologyEx(cv2.dilate(ink,np.ones((1,max(3,w//700)),np.uint8)),cv2.MORPH_OPEN,np.ones((max(12,h//80),1),np.uint8))
    horizontal=cv2.morphologyEx(horizontal,cv2.MORPH_CLOSE,np.ones((3,max(5,w//100)),np.uint8))
    vertical=cv2.morphologyEx(vertical,cv2.MORPH_CLOSE,np.ones((max(5,h//150),3),np.uint8))
    grid=cv2.dilate(horizontal|vertical,np.ones((3,3),np.uint8))
    count,labels,stats,_=cv2.connectedComponentsWithStats(grid)
    tables=[]
    for label in range(1,count):
        x,y,ww,hh,area=map(int,stats[label])
        if ww < w*.15 or hh < h*.025:continue
        hm=horizontal[y:y+hh,x:x+ww]>0;vm=vertical[y:y+hh,x:x+ww]>0
        ys=[v+y for v in bands(np.flatnonzero(hm.sum(axis=1)>ww*.6))]
        xs=[v+x for v in bands(np.flatnonzero(vm.sum(axis=0)>hh*.65))]
        if len(xs)<3 or len(ys)<3:continue
        # Require continuous outer border; interior breaks may indicate merges.
        def hcov(yy,x0,x1):return (horizontal[max(0,yy-4):min(h,yy+5),x0:x1]>0).any(axis=0).mean()
        def vcov(xx,y0,y1):return (vertical[y0:y1,max(0,xx-4):min(w,xx+5)]>0).any(axis=1).mean()
        borders=[hcov(ys[0],xs[0],xs[-1]),hcov(ys[-1],xs[0],xs[-1]),vcov(xs[0],ys[0],ys[-1]),vcov(xs[-1],ys[0],ys[-1])]
        if min(borders)<.85:continue
        nr,nc=len(ys)-1,len(xs)-1
        parent=list(range(nr*nc))
        def find(i):
            while parent[i]!=i:i=parent[i]
            return i
        def union(a,b):parent[find(a)]=find(b)
        for r in range(nr):
            for c in range(nc):
                if c+1<nc and vcov(xs[c+1],ys[r]+4,ys[r+1]-4)<.25:union(r*nc+c,r*nc+c+1)
                if r+1<nr and hcov(ys[r+1],xs[c]+4,xs[c+1]-4)<.25:union(r*nc+c,(r+1)*nc+c)
        groups={}
        for r in range(nr):
            for c in range(nc):groups.setdefault(find(r*nc+c),[]).append((r,c))
        cells=[];valid=True
        for group in groups.values():
            r0=min(r for r,c in group);r1=max(r for r,c in group)+1
            c0=min(c for r,c in group);c1=max(c for r,c in group)+1
            if len(group)!=(r1-r0)*(c1-c0):valid=False;break
            cells.append({'row':r0+1,'column':c0+1,'row_span':r1-r0,'col_span':c1-c0,
                          'bbox_pixels':[xs[c0],ys[r0],xs[c1],ys[r1]]})
        if valid:
            tables.append({'bbox_pixels':[xs[0],ys[0],xs[-1],ys[-1]],'row_count':nr,'column_count':nc,
                           'cells':sorted(cells,key=lambda c:(c['row'],c['column'])),
                           'method':'image_ruled_grid','border_coverage':round(float(min(borders)),4)})
    return sorted(tables,key=lambda t:(t['bbox_pixels'][1],t['bbox_pixels'][0]))
