"""Resumable serial Orin-only image extraction. Never retries ambiguous attempts."""
import base64,fcntl,hashlib,json,sys,time,urllib.request,urllib.error
from datetime import datetime,timezone
from pathlib import Path
OUT=Path(sys.argv[1]);MODEL='qwen3.6-35b-a3b'
def read(p):return json.loads(p.read_text())
def write(p,x):
 p.parent.mkdir(exist_ok=True,parents=True);t=p.with_suffix('.tmp');t.write_text(json.dumps(x,ensure_ascii=False,indent=2));t.replace(p)
def main():
 lock=(OUT/'vision.lock').open('w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 jobs=read(OUT/'vision-unique.json');schema=read(OUT/'vision-schema.json');prompt=(OUT/'vision-prompt.txt').read_text();start=time.monotonic()
 def state(status,**kw):write(OUT/'vision-progress.json',{'status':status,'planned':len(jobs),'saved':len(list((OUT/'vision-responses').glob('*/response.json'))),'elapsed_seconds':time.monotonic()-start,**kw})
 for j in jobs:
  folder=OUT/'vision-responses'/j['id'];dest=folder/'response.json'
  if dest.exists():continue
  if (folder/'attempt.json').exists():raise RuntimeError('Unresolved attempt; inspect before retry '+j['id'])
  payload={'model':MODEL,'messages':[{'role':'system','content':prompt},{'role':'user','content':[{'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode((OUT/j['asset_path']).read_bytes()).decode()}},{'type':'text','text':'이 이미지 전체의 보이는 내용과 구조를 추출하세요. 외부 문맥은 제공하지 않습니다.'}]}],
   'temperature':0,'max_tokens':8192,'stream':False,'chat_template_kwargs':{'enable_thinking':False},
   'response_format':{'type':'json_schema','json_schema':{'name':'vision_extraction','strict':True,'schema':schema}}}
  digest=hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
  write(folder/'attempt.json',{'request_sha256':digest,'started_at':datetime.now(timezone.utc).isoformat(),'model':MODEL,'prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest(),'asset_sha256':hashlib.sha256((OUT/j['asset_path']).read_bytes()).hexdigest(),'max_tokens':8192,'provider':'Orin local vLLM','automatic_retry':False})
  state('generating',current=j['id']);print('START',j['id'],flush=True);t=time.monotonic()
  req=urllib.request.Request('http://127.0.0.1:8001/v1/chat/completions',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
  try:
   with urllib.request.urlopen(req,timeout=3600) as r:response=json.load(r);status=r.status
  except urllib.error.HTTPError as e:response={'error':e.read().decode()};status=e.code
  elapsed=time.monotonic()-t;write(dest,{'response':response,'http_status':status,'elapsed_seconds':elapsed,'request_sha256':digest,'job_id':j['id']})
  print('DONE',j['id'],status,round(elapsed,2),flush=True)
  if status>=500:raise RuntimeError('server error; preserve results and stop')
 state('responses_collected')
if __name__=='__main__':
 try:main()
 except Exception as e:write(OUT/'vision-error.json',{'error':str(e)});raise
