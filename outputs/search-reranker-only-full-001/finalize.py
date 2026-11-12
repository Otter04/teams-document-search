"""Finalize completed results, including explicitly recorded transport retries."""
import run as E
import inspect,statistics,json,hashlib
E.qs,E.olds,E.labels=E.setup()
assert all((E.O/'queries'/q['query_id']/'result.json').exists() for q in E.qs),'responses incomplete'
# Same aggregation; include preserved third/fourth transport attempts as well.
source=inspect.getsource(E.report).replace('attempt[12].json','attempt[1234].json')
exec(compile(source,'report_with_all_recorded_attempts','exec'),E.__dict__)
E.report()
rows=[E.read(E.O/'queries'/q['query_id']/'result.json') for q in E.qs]
s=E.read(E.O/'summary.json');normal=[r for r in rows if not r.get('resumed_after_interruption')]
s['uninterrupted_timing']={'n':len(normal),'mean_total_seconds':statistics.mean(r['timings']['total'] for r in normal)}
s['resumed_questions']=[r['id'] for r in rows if r.get('resumed_after_interruption')]
(E.O/'summary.json').write_text(json.dumps(s,ensure_ascii=False,indent=2)+'\n')
E.save(E.O/'execution-final.json',{'initial_workers':3,'later_max_workers':5,'tail':E.read(E.O/'tail-execution.json'),'final_retry':{'query_id':'EX100-I033','attempt':4,'transport_timeout_seconds':300,'model_payload_unchanged':True},'requests':s['api_calls'],'resumed_questions':s['resumed_questions'],'all_model_endpoints_remote':True,'second_qwen_calls':0,'helpers_sha256':{p.name:E.H.sha(p) for p in [E.O/'finish_tail.py',E.O/'finish_last.py',E.O/'finalize.py']}})
