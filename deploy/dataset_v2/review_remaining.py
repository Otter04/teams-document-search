"""Source-specific corrections after visual comparison on 2026-10-24.
No model calls, no gold access, raw responses are immutable.
"""
from review import *
from datetime import datetime,timezone

def text(s,box,kind='paragraph'):return {'kind':kind,'text':s,'bbox':box}
def claim(s,box):return {'text':s,'status':'observed','bbox':box}
def ui(d,app,title,fields,buttons,scan=False):
 # Screenshots use the same visible UI geometry. Scans embed that screenshot.
 def box(b):
  if not scan:return b
  return [round(.057+b[0]*.761,4),round(.132+b[1]*.318,4),round(.057+b[2]*.761,4),round(.132+b[3]*.318,4)]
 outer=[t for t in d['texts'] if t['bbox'][1]<.13 or t['bbox'][1]>.45] if scan else []
 ts=[text(app,box([.012,.008,.8,.049]),'heading'),text(title,box([.2,.084,.95,.13]),'heading')]
 for i,s in enumerate(['개요','구성','디렉터리','정책','모니터링','설정']):ts.append(text(s,box([.018,.092+i*.053,.17,.125+i*.053])))
 for i,s in enumerate(buttons):ts.append(text(s,box([.79+i*.062,.9,.85+i*.062,.965])))
 cells=[]
 for i,(k,v) in enumerate(fields):
  for col,s in enumerate([k,v]):cells.append({'row':i+1,'column':col+1,'row_span':1,'column_span':1,'text':s,'value_status':'known','role':'header' if col==0 else 'data','bbox':box([.205 if col==0 else .407,.172+i*.076,.4 if col==0 else .942,.223+i*.076])})
 d.update(texts=outer+ts,tables=[{'bbox':box([.2,.17,.95,.23+(len(fields)-1)*.076]),'row_count':len(fields),'column_count':2,'header_rows':[],'header_status':'none','cells':cells}],figures=[])

forms={
 'D-120-vision-page1':('Setup','연결 서버',[('서버 이름','cs01.lab.local'),('인스턴스','표준')]),
 'D-120-vision-page2':('Admin Console','풀 추가',[('풀 ID','POOL-DEV-W11'),('유형','자동 / 인스턴트 클론'),('최대 데스크톱 수','40')]),
 'D-120-vision-page3':('Admin Console','권한',[('그룹','LAB\\G_Dev'),('풀','POOL-DEV-W11')]),
 'D-121-vision-page1':('Admin Console','이미지 푸시',[('골든 이미지','W11-GOLD-2502'),('스냅샷','snap-0224')]),
 'D-122-vision-page1':('Installer','관리 네트워크',[('호스트 이름','esx-lab01'),('IP','192.168.50.11')]),
 'D-122-vision-page2':('vSphere Client','클러스터 만들기',[('클러스터 이름','CL-LAB-01'),('HA','사용'),('DRS','완전 자동')]),
 'D-150-vision-image':('vSphere Client','데이터스토어 — 용량',[('DS-HAKSA-01','사용 82% / 여유 18%'),('DS-HAKSA-02','사용 47% / 여유 53%')]),
 'D-151-vision-image':('Backup Console','작업 목록 — EMR_RMAN_LEVEL0',[('상태','실패'),('시작','2025-08-24 01:40'),('오류','LTO9-02 드라이브 응답 없음'),('미디어','EMR0824')])}
for j in read(OUT/'vision-unique.json'):
 rp=OUT/'vision-review'/f"{j['id']}.json"
 if rp.exists():continue
 original,errors=response(j);d=copy.deepcopy(original);changes=[];did=j['doc_id'];jid=j['id']
 if jid in forms:
  ui(d,*forms[jid],['CANCEL','NEXT'] if 'page' in jid else (['새로 고침'] if did=='D-150' else ['닫기','다시 실행']),scan='page' in jid)
  changes.append('원본 UI의 제목·메뉴·버튼과 키/값 입력란을 구분. 가짜 구성도/연결선·중복 전사를 제거하고 2열 필드로 복원. 디렉터리·풀 원문 및 근거 영역 보정.')
 if did=='D-121' and 'page2' in jid:
  d['figures'][0]['claims']=[claim('대부분 구간에서 약 8~15이며 18시 전후 구간에서 급증 후 감소한다. 표시된 최댓값은 37이다.',[.08,.16,.81,.41])]
  # Chart occupies the embedded screenshot, not the entire scan width.
  d['figures'][0]['bbox']=[.06,.13,.82,.45]
  for t in d['texts']:
   if t['text']=='세션 최대 37':t['bbox']=[.6,.15,.77,.21]
   if t['text'] in ['00:00','06:00','12:00','18:00','24:00']:
    x=.1+['00:00','06:00','12:00','18:00','24:00'].index(t['text'])*.177
    t['bbox']=[x-.02,.408,min(x+.025,.82),.435]
  changes.append('차트 설명의 과도한 시간/범위 단정을 실제 곡선 관찰로 정정하고 x축 근거 영역을 스캔 내 차트에 맞춤.')
 if 141<=int(did[2:])<=148:
  f=d['figures'][0];f['kind']='photo';f['relations']=[]
  # These are synthetic equipment/box illustrations, not topology diagrams.
  labels=[n['label'] for n in f['nodes']]
  d['texts']=[t for t in d['texts'] if not any(t['text'].replace('\n',' ') in s.replace('\n',' ') for s in labels)]
  if did=='D-144':
   for n in f['nodes']:n['label']=n['label'].replace('확장 셀프','확장 쉘프')
   changes.append('원본 라벨의 쉘프를 셀프로 오독한 부분 수정.')
  if did=='D-141':s='같은 라벨이 붙은 상자 3개가 가로로 배치된 이미지다.'
  elif did=='D-145':s='같은 AP-515 제품 라벨이 붙은 상자 3개가 가로로 배치된 이미지다.'
  else:s='장비 전면 3개가 세로로 배치된 이미지이며 일부 위치에 녹색 표시가 보인다. 표시만으로 실제 운영 상태를 확정하지 않는다.'
  if did=='D-143':s+=' 이미지에 보이는 전면은 3개이며 별도 라벨에는 FMS 서버 4대라고 적혀 있다.'
  f['claims']=[claim(s,f['bbox'])]
  changes.append('장비/상자 이미지 분류를 photo로 수정. 별도 물체의 반복 라벨은 유지하고 texts/nodes 이중 기록만 제거. 포트 번호·작동 상태 추정은 관찰 설명으로 대체.')
 if did in ['D-149','D-152']:
  title=d['texts'][0]['text'];peak='CPU 최대 91%' if did=='D-149' else '트래픽 최대 3.2Gbps'
  ys=['100%','75%','50%','25%','0%'] if did=='D-149' else ['4Gbps','3Gbps','2Gbps','1Gbps','0Gbps']
  d['texts']=[text(title,[.02,.03,.8,.08],'caption'),text(peak,[.61 if did=='D-149' else .72,.14 if did=='D-149' else .23,.9,.2 if did=='D-149' else .29],'caption')]
  for i,s in enumerate(ys):d['texts'].append(text(s,[.02,.116+i*.191,.055,.145+i*.191],'caption'))
  for i,s in enumerate(['00:00','06:00','12:00','18:00','24:00']):
   x=.069+i*.225;d['texts'].append(text(s,[x-.02,.914,min(x+.023,1),.947],'caption'))
  s=('약 14~15시 구간에 급증하고 감소하는 선 그래프다. 표시된 최댓값은 91%이며 나머지 구간은 대체로 약 18~35% 범위다.' if did=='D-149' else '약 17~18시 구간에 급증하고 감소하는 선 그래프다. 표시된 최댓값은 3.2Gbps이며 나머지 구간은 대체로 약 0.7~1.4Gbps 범위다.')
  d['figures']=[{'kind':'chart','bbox':[.07,.125,.97,.895],'nodes':[],'relations':[],'claims':[claim(s,[.07,.125,.97,.895])]}]
  changes.append('차트의 잘못된 좌표와 곡선 설명을 원본에 맞춰 수정; D-152의 누락된 차트 구조를 별도 검수 관찰로 기록. 정밀 시계열 수치 복원은 아님.')
 assert not C.check_wire(d),(jid,C.check_wire(d))
 blockers=[i for i in Q.check_quality(d) if i['blocks_transfer']];assert not blockers,(jid,blockers)
 dest=OUT/'vision-reviewed-wire'/f'{jid}.json';write(dest,d)
 r={'job_id':jid,'decision':'approved_after_source_review','reviewer':'assistant visual source comparison; not independent human review','reviewed_at':datetime.now(timezone.utc).isoformat(),'response_sha256':sha(OUT/'vision-responses'/jid/'response.json'),'asset_sha256':sha(OUT/j['asset_path']),'corrected_path':str(dest.relative_to(OUT)),'corrected_sha256':sha(dest),'changes':changes,'scope':'Compared source image labels, key values, UI fields and visible objects/curves. Coordinates approximate; no precise chart digitization or claims of operating state. Raw model quality is not equated with reviewed result quality.','raw_response_modified':False,'raw_validation_errors':errors,'source_structure_repaired':bool(errors)}
 write(rp,r);assert approved(j) is not None
 print(jid,'corrected' if changes else 'unchanged')
