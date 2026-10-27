import copy, hashlib, os, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import date_search as d

class Dates(unittest.TestCase):
    def test_nanosecond_roundtrip_and_offset_rejection(self):
        for n in [0,-1,1736843340000000000,1736843340123456789]:self.assertEqual(d.ns_utc(d.utc_ns(n)),n)
        with self.assertRaises(ValueError):d.ns_utc('2025-01-14T17:29:00+09:00')
    def test_collect_and_detect_content_change(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)/'a.txt';p.write_text('example');ns=1736843340123456789;os.utime(p,ns=(ns,ns))
            r={'doc_id':'A','source':{'relative_path':'a.txt','sha256':hashlib.sha256(p.read_bytes()).hexdigest()}}
            m=d.collect_files({'A':r},root)['A'];self.assertEqual(m['modified_at_ns'],str(p.stat().st_mtime_ns))
            p.write_text('changed')
            with self.assertRaises(ValueError):d.collect_files({'A':r},root)
    def test_symlink_escape(self):
        with tempfile.TemporaryDirectory() as root,tempfile.TemporaryDirectory() as other:
            p=Path(other)/'outside.txt';p.write_text('test');(Path(root)/'a.txt').symlink_to(p)
            r={'source':{'relative_path':'a.txt','sha256':hashlib.sha256(p.read_bytes()).hexdigest()}}
            with self.assertRaises(ValueError):d.collect_files({'A':r},root)
    def test_cover_is_not_written(self):
        obs=[{'role':'cover_date','value':'2025-01-13','evidence':[{'ref':'A'}]}]
        self.assertEqual(d.role_field(obs,'explicit_written_date')['status'],'not_observed_native')
        self.assertEqual(d.role_field(obs,'cover_date')['value'],'2025-01-13')
    def test_conflicting_role(self):
        obs=[{'role':'explicit_written_date','value':v,'evidence':[{'ref':'A'}]} for v in ['2025-01-13','2025-01-14']]
        self.assertEqual(d.role_field(obs,'explicit_written_date')['status'],'needs_review')
    def test_seoul_calendar_boundaries(self):
        p=d.plan('2025년 1월 14일 수정된 문서','2026-10-17',[],[])
        self.assertEqual(p['filters'],[{'field':'파일최종수정일','op':'gte','value':'2025-01-13T15:00:00Z'},{'field':'파일최종수정일','op':'lt','value':'2025-01-14T15:00:00Z'}])
        index={'documents':{}}
        for k,v in [('before','2025-01-13T14:59:59.999999999Z'),('start','2025-01-13T15:00:00Z'),('end','2025-01-14T14:59:59.999999999Z'),('after','2025-01-14T15:00:00Z')]:
            index['documents'][k]={'metadata':{},'metadata_statuses':{},'date_metadata':{'fields':{'파일최종수정일':{'value':v,'status':'extracted'}}}}
        self.assertEqual(d.apply_filters(index,p['filters'])[0],{'start','end'})
    def test_written_plan_does_not_target_representative_date(self):
        p=d.plan('작성일 2025년 1월 13일 문서','2026-10-17',[],[])
        self.assertEqual({f['field'] for f in p['filters']},{'작성일'})
    def test_ambiguous_requests_fail_closed(self):
        for q in ['작성일 2025년 수정일 2025년 문서','최근 3일 수정된 문서','2025년 이전 수정된 문서','작성일 2025년 2월 30일 문서','수정일 문서']:
            with self.subTest(q=q):self.assertTrue(d.plan(q,'2026-10-17',[],[])['requires_clarification'])
    def test_latest_version_is_not_implicitly_modified_sort(self):
        self.assertIsNone(d.plan('최신 제안서','2026-10-17',[],[])['sort'])
    def synthetic_index(self,n=150):
        ix={'documents':{},'entries':{},'postings':{},'entry_count':n,'average_length':1,'config':{'bm25_k1':1.2,'bm25_b':.75},'clients':[],'rules':{'concepts':[]}}
        bundle={'features':{}}
        for i in range(n):
            did=f'D{i:03d}';stamp=d.utc_ns(i*1_000_000_000)
            ix['documents'][did]={'source':{},'metadata':{},'metadata_statuses':{},'native_chunk_count':0,'pending_visual_units':[],
               'date_metadata':{'fields':{'파일최종수정일':{'value':stamp,'status':'extracted'}}}}
            bundle['features'][did]={f:[] for f in d.old.WEIGHTS}
        return ix,bundle
    def test_global_sort_before_limit_and_missing_exclusion(self):
        ix,b=self.synthetic_index();r=d.search(ix,b,'가장 최근 수정된 문서','2026-10-17',[],limit=2)
        self.assertEqual([x['doc_id'] for x in r['results']],['D149','D148']);self.assertEqual(r['ranked_documents_before_limit'],150)
        ix['documents']['D149']['date_metadata']['fields']['파일최종수정일']['status']='unavailable'
        r=d.search(ix,b,'가장 최근 수정된 문서','2026-10-17',[],limit=1)
        self.assertEqual(r['results'][0]['doc_id'],'D148');self.assertIn('D149',r['unresolved_filter_documents'])
    def test_tie_break_and_ascending(self):
        ix,b=self.synthetic_index(3)
        ix['documents']['D001']['date_metadata']['fields']['파일최종수정일']['value']=d.utc_ns(0)
        r=d.search(ix,b,'수정일 오름차순 문서','2026-10-17',[],limit=3)
        self.assertEqual([x['doc_id'] for x in r['results']],['D000','D001','D002'])
    def test_nonmatching_content_not_ignored_by_sort(self):
        ix,b=self.synthetic_index(2)
        self.assertEqual(d.search(ix,b,'가장 최근 수정된 unicornxyz 문서','2026-10-17',[])['results'],[])

if __name__=='__main__':unittest.main()
