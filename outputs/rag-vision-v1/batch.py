"""Bounded parallel dispatch using the unchanged frozen per-request runner.

One task per (model, image), no automatic retry. Keeps model-output validation
failures as measured failures; stops new dispatch on transport/auth/rate errors.
"""
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
import argparse
import time
from run import (DEFAULT_RUN, HERE, MODELS, canonical, digest, load, now, process_item,
                 read_key, summarize, task_id, verify_manifest, write)

def main(out,workers):
    manifest=load(out/'manifest.json');verify_manifest(manifest);key=read_key()
    jobs=[(item,model) for item in manifest['items'] for model in MODELS
          if not (out/model.split('/')[1]/'units'/task_id(item)/'result.json').exists()]
    for item,model in jobs:
        base=out/model.split('/')[1]/'units'/task_id(item)
        if (base/'inflight.json').exists() and not (base/'response.json').exists():
            raise RuntimeError('Unresolved previous request; inspect before resuming')
    write(out/'dispatch-info.json',dict(code_sha256=digest(HERE/'batch.py'),workers=workers,
        started_at=now(),new_jobs=len(jobs),request_conditions_unchanged=True,automatic_retries=0))
    write(out/'status.json',dict(state='running',started_at=now(),remaining_jobs=len(jobs)))
    iterator=iter(jobs);futures={};stopped=[];completed=0
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            def submit():
                try:item,model=next(iterator)
                except StopIteration:return False
                futures[pool.submit(process_item,out,item,model,manifest,key)]=(item,model)
                return True
            for _ in range(workers):submit()
            while futures:
                done,_=wait(futures,timeout=30,return_when=FIRST_COMPLETED)
                if not done:
                    print(canonical({'state':'waiting','active':len(futures),'finished_this_batch':completed}),flush=True)
                for f in done:
                    item,model=futures.pop(f)
                    try:
                        result=f.result();completed+=1
                        print(canonical({'finished_this_batch':completed,'model':model,'unit':task_id(item),
                            'status':result['status'],'cost_usd':result.get('cost_usd'),'errors':result.get('errors',[])}),flush=True)
                        if result['status']=='http_error':stopped.append('HTTP error')
                    except Exception as e:
                        stopped.append(type(e).__name__+': '+str(e))
                        print(canonical({'stopped_dispatch':stopped[-1],'model':model,'unit':task_id(item)}),flush=True)
                if not stopped:
                    for _ in done:submit()
    finally:
        summaries=summarize(out,manifest)
        all_returned=all(s['attempted_units']==s['target_units'] for s in summaries)
        all_valid=all(s['valid_units']==s['target_units'] for s in summaries)
        write(out/'status.json',dict(state='api_processing_finished' if all_valid else
             'api_processing_finished_with_validation_failures' if all_returned else 'incomplete',
             updated_at=now(),dispatch_stopped_reasons=stopped,quality_evaluation_complete=False))
        print(canonical({'summary':summaries}),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--workers',type=int,default=4)
    args=p.parse_args()
    if not 1<=args.workers<=4:raise SystemExit('workers must be 1..4')
    main(DEFAULT_RUN,args.workers)
