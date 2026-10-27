"""Merge reviewed semantic fields without overwriting rule facts or original chunks."""
from collections import Counter,defaultdict
from copy import deepcopy
import sys
from prepare import *
sys.path.insert(0,str(ROOT/'deploy/rag_app'))
from runtime import d

def main():
    manifest=read(OUT/'manifest.json')
    for name,h in manifest['base_hashes'].items():assert digest(BASE/name)==h,name
    reviews=read(OUT/'semantic-review.completed.json')
    assert len(reviews)==len(manifest['jobs'])==17
    packets={r['doc_id']:r for r in read(OUT/'semantic-review-packet.json')}
    originals={r['doc_id']:r for r in lines(BASE/'indexing-records.jsonl')}
    chunks=lines(BASE/'chunks.jsonl');docs=lines(BASE/'document-index.jsonl')
    semantic={};extras=[];changes=[]
    for review in reviews:
        did=review['doc_id'];packet=packets[did]
        assert review['response_sha256']==packet['response_sha256']==digest(OUT/'responses'/f'{did}.json')
        assert review['input_sha256']==packet['input_sha256']==digest(OUT/'inputs'/f'{did}.json')
        assert review['status']=='approved_after_source_review'
        source=read(OUT/'inputs'/f'{did}.json');byid={e['id']:e for e in source['excerpts']}
        blocks={b['block_id']:b for b in originals[did]['blocks']}
        def resolve(choice):
            if isinstance(choice,int):return byid[choice]
            # A PDF line wrap can divide one supported phrase across excerpts.
            parts=[byid[i] for i in choice]
            assert len({e['block_id'] for e in parts})==1
            block=blocks[parts[0]['block_id']]
            for a,b in zip(parts,parts[1:]):assert not block['text'][a['end']:b['start']].strip()
            ev=deepcopy(parts[0]);ev.update(end=parts[-1]['end'],text=block['text'][parts[0]['start']:parts[-1]['end']],joined_excerpt_ids=choice)
            return ev
        fields={k:[resolve(i) for i in ids] for k,ids in review['accepted_fields'].items()}
        assert set(fields)==set(packet['fields'])
        summary=[resolve(i) for i in review['accepted_summary']]
        for ev in [e for values in fields.values() for e in values]+summary:
            assert blocks[ev['block_id']]['text'][ev['start']:ev['end']]==ev['text']
        def value(ev):
            b=blocks[ev['block_id']]
            return {'value':ev['text'],'evidence':{k:ev[k] for k in ['block_id','start','end','loc']},'source_context':'quoted_previous_message' if '-----Original Message-----' in b['text'] else 'document_body'}
        semantic[did]={'doc_id':did,'fields':{k:{'status':'extracted' if v else 'not_found_in_selected_evidence','items':[value(e) for e in v],'exhaustive':False,'method':'Orin Qwen3.6 evidence selection + assistant source review'} for k,v in fields.items()},'summary':{'kind':'extractive','items':[value(e) for e in summary],'text':'\n'.join(e['text'] for e in summary),'exhaustive':False},'provenance':{'model':'qwen3.6-35b-a3b','provider':'Orin local vLLM','quantization':'AWQ-4bit','response_sha256':review['response_sha256'],'input_sha256':review['input_sha256'],'reviewer':'assistant; not independent human evaluation','notes':review['notes']}}
        # Labels are derived metadata; all values remain exact source spans.
        text='\n'.join(f'{k}: '+e['text'] for k,values in fields.items() for e in values)
        text+='\n핵심 요약(원문 발췌):\n'+'\n'.join(e['text'] for e in summary)
        refs=[]
        for e in [x for values in fields.values() for x in values]+summary:
            ref={k:e[k] for k in ['block_id','start','end','loc']}
            if ref not in refs:refs.append(ref)
        cid=did+'-SEM-'+hashlib.sha256(text.encode()).hexdigest()[:16]
        extras.append({'doc_id':did,'chunk_id':cid,'kind':'semantic_metadata_excerpt','text':text,'context_header':originals[did]['source']['file_name']+' | 검증된 의미 메타데이터·원문 발췌 요약','table_header_text':'','source_refs':refs,'context_refs':[],'derived_labels':True,'semantic_record_ref':did,'source_sha256':originals[did]['source']['sha256']})
        if review.get('corrections'):changes.append({'doc_id':did,'changes':review['corrections']})
    index=deepcopy(read(BASE/'index.json'))
    for ex in extras:index['entries'][ex['chunk_id']]={k:ex[k] for k in ['doc_id','kind','text','context_header','table_header_text','source_refs','context_refs']}
    postings=defaultdict(dict)
    for eid,entry in index['entries'].items():
        terms=d.old.old.previous.tokens(' '.join([entry['context_header'],entry['table_header_text'],entry['text']]),index['clients'],index['rules'])
        entry['length']=len(terms)
        for term,n in Counter(terms).items():postings[term][eid]=n
    index.update(postings=dict(postings),entry_count=len(index['entries']),average_length=sum(e['length'] for e in index['entries'].values())/len(index['entries']),scope='native_and_reviewed_vision_plus_reviewed_semantic_enrichment',embedding_status='pending_bge_m3',model_called=True,retrieval_and_answer_implementation=False)
    for doc in docs:
        did=doc['doc_id'];doc['semantic_metadata']=semantic.get(did)
        if did in semantic:
            doc['summary']=semantic[did]['summary']['text'];doc['summary_status']='source_reviewed_extractive'
            cid=next(e['chunk_id'] for e in extras if e['doc_id']==did);doc['chunk_ids'].append(cid)
        index['documents'][did]['semantic_metadata']=semantic.get(did)
        index['documents'][did]['summary']=doc['summary']
        index['documents'][did]['indexed_chunk_count']=len(doc['chunk_ids'])
        index['documents'][did]['embedding_status']='pending_bge_m3'
    # Reuse source and rule files byte for byte. Create no new rule decisions.
    import shutil
    for name in ['parsed.jsonl','indexing-records.jsonl','enriched.jsonl','chunks.jsonl','source-metadata.jsonl','date-metadata.jsonl']:
        shutil.copyfile(BASE/name,OUT/name);assert digest(BASE/name)==digest(OUT/name)
    save_lines(OUT/'semantic-enriched.jsonl',semantic.values());save_lines(OUT/'semantic-chunks.jsonl',extras)
    save_lines(OUT/'document-index.jsonl',docs);write(OUT/'index.json',index);write(OUT/'semantic-corrections.json',changes)
    rows=[]
    for group in chunks:
        for c in group['chunks']:
            rows.append({'doc_id':group['doc_id'],'chunk_id':c['chunk_id'],'kind':'source_chunk','text':'\n'.join(x for x in [c['context_header'],c['table_header_text'],c['text']] if x),'source_refs':c['source_refs'],'source_sha256':group['source']['sha256']})
    for c in extras:rows.append({'doc_id':c['doc_id'],'chunk_id':c['chunk_id'],'kind':c['kind'],'text':c['context_header']+'\n'+c['text'],'source_refs':c['source_refs'],'source_sha256':c['source_sha256']})
    for i,r in enumerate(rows):r.update(vector_id=i,embedding_text_sha256=hashlib.sha256(r['text'].encode()).hexdigest())
    assert len(rows)==1089 and len({r['chunk_id'] for r in rows})==1089
    save_lines(OUT/'embedding-inputs.jsonl',rows)
    write(OUT/'assembly-verification.json',{'documents':110,'source_chunks_reused':1072,'semantic_documents':17,'semantic_chunks':17,'vector_inputs':1089,'rule_fields_unchanged':True,'source_span_validation':'passed','search_queries':0,'independent_semantic_accuracy_score':None,'assembly_review':'explicit assistant review; no model quality percentage claimed'})
    print('Prepared',len(rows),'bge-m3 inputs')

if __name__=='__main__':main()
