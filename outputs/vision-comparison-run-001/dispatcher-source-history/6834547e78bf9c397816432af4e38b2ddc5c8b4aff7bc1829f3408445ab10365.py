"""Run an explicitly partitioned tail of a model queue, using frozen requests.
No summarization writes while another dispatcher is running. The original
runner's exclusive inflight creation prevents duplicate requests in a race.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
import argparse
from run import DEFAULT_RUN, MODELS, HERE, load, write, verify_manifest, read_key, process_item, task_id, digest, now, canonical

def main(model,start,workers):
    out=DEFAULT_RUN;manifest=load(out/'manifest.json');verify_manifest(manifest);key=read_key()
    items=manifest['items'][start:]
    write(out/('dispatch-tail-'+model.split('/')[1]+'.json'),dict(start_index=start,workers=workers,model=model,
        started_at=now(),code_sha256=digest(HERE/'dispatch_remaining.py'),request_conditions_unchanged=True))
    def task(item):
        base=out/model.split('/')[1]/'units'/task_id(item)
        if (base/'result.json').exists() or (base/'inflight.json').exists():return None
        try:return process_item(out,item,model,manifest,key)
        except FileExistsError:return None
    # Provider/transport errors stop the process; normal model validation errors remain measured outputs.
    with ThreadPoolExecutor(max_workers=workers) as pool:
        pending={};it=iter(items);stop=False
        def submit():
            try:item=next(it)
            except StopIteration:return
            pending[pool.submit(task,item)]=item
        for _ in range(workers):submit()
        while pending:
            from concurrent.futures import wait,FIRST_COMPLETED
            done,_=wait(pending,timeout=30,return_when=FIRST_COMPLETED)
            for f in done:
                item=pending.pop(f)
                try:
                    r=f.result()
                    if r:
                        print(canonical({'unit':task_id(item),'model':model,'status':r['status'],'cost_usd':r.get('cost_usd')}),flush=True)
                        if r['status']=='http_error':stop=True
                except Exception as e:
                    stop=True;print(canonical({'error':str(e),'unit':task_id(item)}),flush=True)
            if not stop:
                for _ in done:submit()
    print(canonical({'dispatch_complete':True,'stopped_on_transport_error':stop}),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--model',choices=MODELS,required=True)
    p.add_argument('--start-index',type=int,default=20);p.add_argument('--workers',type=int,default=4)
    a=p.parse_args()
    if a.workers<1 or a.workers>4 or a.start_index<0:raise SystemExit('Invalid bounds')
    main(a.model,a.start_index,a.workers)
