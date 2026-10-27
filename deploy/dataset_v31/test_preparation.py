"""Source integration checks before opening any evaluation results."""
import unittest,collections
from unittest.mock import patch
from common import *
import review
class Preparation(unittest.TestCase):
 def test_original_sources_and_previous_artifacts_preserved(self):
  for rel,h in read(OUT/'baseline-freeze.json').items():self.assertEqual(sha(ROOT/rel),h,rel)
  paths=read(OUT/'source-paths.json')
  for did,h in read(OUT/'source-freeze.json').items():self.assertEqual(sha(paths[did]),h,did)
 def test_native_new_formats_and_structure(self):
  rs={r['doc_id']:r for r in rows(OUT/'native-new.jsonl')};self.assertEqual(len(rs),40)
  for r in rs.values():self.assertFalse(check(r),r['doc_id'])
  for did in ['D-167','D-168','D-169','D-186','D-197']:self.assertTrue(any(b['type']=='table' for b in rs[did]['blocks']),did)
  for did in ['D-190','D-191','D-192','D-193']:self.assertTrue(any('structure_path' in b['loc'] for b in rs[did]['blocks']),did)
  r=copy.deepcopy(rs['D-197']);r['blocks'][0]['loc']['kind']='csv';self.assertIn('new format location mismatch',check(r))
 def test_legacy_source_text_preserved(self):
  import subprocess,re
  rs={r['doc_id']:r for r in rows(OUT/'native-new.jsonl')};paths=read(OUT/'source-paths.json');n=lambda s:re.sub(r'\s+','',s)
  for did in ['D-159','D-160','D-161','D-162']:
   native=subprocess.run(['/usr/bin/textutil','-convert','txt','-stdout',paths[did]],capture_output=True,check=True).stdout.decode()
   self.assertEqual(n(native),n(''.join(b['text'] for b in rs[did]['blocks'])),did)
 def test_vision_truncation_stays_blocked(self):
  j=read(OUT/'vision-unique.json')[0];env=read(OUT/'vision-responses'/j['id']/'response.json');env['response']['choices'][0]['finish_reason']='length'
  with patch.object(review,'read',return_value=env):self.assertIn('incomplete finish: length',review.response(j)[1])
 def test_vision_review_source_hash_required(self):
  j=read(OUT/'vision-unique.json')[0];real=review.read
  def tamper(p):
   r=real(p)
   if 'vision-review' in Path(p).parts:r['asset_sha256']='0'*64
   return r
  with patch.object(review,'read',side_effect=tamper),self.assertRaises(AssertionError):review.approved(j)
 def test_all_vision_jobs_reviewed(self):
  jobs=read(OUT/'vision-unique.json');self.assertEqual(len(jobs),4)
  for j in jobs:self.assertIsNotNone(review.approved(j))
 def test_answer_free_evaluation_requests(self):
  questions=rows(OUT/'evaluation/inputs.jsonl');self.assertEqual(len(questions),150)
  self.assertTrue(all(set(q)=={'query_id','query','base_date'} for q in questions))
if __name__=='__main__':unittest.main()
