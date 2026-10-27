"""One search execution, live NDJSON events, no query persistence."""
import copy,json,queue,threading

def stream_search(engine,query,mode,ranker,reference_date,use_llm):
    events=queue.Queue(maxsize=128);closed=threading.Event()
    def emit(stage,data):
        event={'stage':stage,'data':copy.deepcopy(data)}
        while not closed.is_set():
            try:events.put(event,timeout=.2);return
            except queue.Full:continue
        raise InterruptedError('stream closed')
    def work():
        try:
            emit('started',{})
            result=engine.search(query,mode,ranker,reference_date,use_llm,emit=emit)
            emit('complete',result)
        except InterruptedError:pass
        except Exception:
            if not closed.is_set():
                try:emit('error',{'message':'검색 처리 중 오류가 발생했습니다. 표시된 중간 순위는 최종 결과가 아닙니다.'})
                except InterruptedError:pass
    threading.Thread(target=work,daemon=True).start()
    try:
        while True:
            try:event=events.get(timeout=1)
            except queue.Empty:
                yield '\n';continue
            yield json.dumps(event,ensure_ascii=False)+'\n'
            if event['stage'] in ['complete','error']:break
    finally:closed.set()
