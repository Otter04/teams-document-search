"""Explicit assistant source-image corrections; raw envelopes stay immutable."""
from review import *
def save(jid,edit,notes):
 j=next(j for j in read(OUT/'vision-unique.json') if j['id']==jid);raw,errors=response(j);assert raw is not None and not errors,errors
 corrected=copy.deepcopy(raw);changes=edit(corrected);assert not C.check_wire(corrected),C.check_wire(corrected)
 blocking=[x for x in Q.check_quality(corrected) if x['blocks_transfer']];assert not blocking,blocking
 dest=OUT/'vision-reviewed-wire'/f'{jid}.json';write(dest,corrected)
 write(OUT/'vision-review'/f'{jid}.json',{'decision':'approved_after_source_review','response_sha256':sha(OUT/'vision-responses'/jid/'response.json'),'asset_sha256':sha(OUT/j['asset_path']),'corrected_path':str(dest.relative_to(OUT)),'corrected_sha256':sha(dest),'changes':changes,'notes':notes,'reviewer':'assistant source image inspection; no independent accuracy claim'})
def order(w):
 t=w['tables'][0];xs=[.134,.275,.416,.558,.699,.842];ys=[.216,.236,.268,.286];t['bbox']=[xs[0],ys[0],xs[-1],ys[-1]]
 for c in t['cells']:r=c['row'];col=c['column'];c['bbox']=[xs[col-1],ys[r-1],xs[col],ys[r]]
 return ['Adjusted approximate cell boxes to the visible unequal column boundaries and row boundaries; text and amounts preserved.']
def stamp(w):
 for f in w['figures']:f['kind']='other'
 return ['Classified printed stamp placeholder as other, not a technical diagram. No assertion of actual legal signature.']
if __name__=='__main__':
 save('D-180-vision-page1',order,'Compared all 15 cells and six text blocks against source. N9K-C93180YC, FortiGate 400F, quantities, four amounts, delivery deadline and acceptance condition all match.')
 for did in ['D-182','D-183']:save(did+'-vision-slide4-image4',stamp,'Visible name and printed (인) circle match source. It is a printed signature field, not proof of an executed signature.')
def chart(w):
 f=w['figures'][0]
 f['claims']=[f['claims'][0],{'text':'그래프 후반부에 일시적인 응답 지연 구간이 표시되어 있다.','status':'observed','bbox':f['bbox']}]
 return ['Removed unsupported typical 1-2 second range and causal interpretation. Retained axis labels, directly printed values and visible temporary peak. Original plotted scale and printed peak annotation are not forced into numeric agreement.']
if __name__=='__main__':save('D-185-vision-page1',chart,'Compared source native text, chart caption, axes and printed red labels. No interpolation or reconstructed numeric series. Native/vision duplicate prose is handled by the existing projection.')
