"""Offline integrity and admission tests using actual prepared corpus evidence."""
import unittest
import numpy as np
from unittest.mock import patch
from common import *
import review
class Preparation(unittest.TestCase):
 def test_source_reviewed_table_repair_requires_explicit_matching_record(self):
  job=next(j for j in read(OUT/'vision-unique.json') if j['id']=='D-120-vision-page3')
  self.assertIsNotNone(review.approved(job))
  real=review.read
  def tampered(path):
   r=real(path)
   if 'vision-review' in Path(path).parts:r['source_structure_repaired']=False
   return r
  with patch.object(review,'read',side_effect=tampered),self.assertRaises(AssertionError):review.approved(job)
 def test_table_repair_never_allows_truncated_response(self):
  job=next(j for j in read(OUT/'vision-unique.json') if j['id']=='D-120-vision-page3')
  data,errors=review.response(job)
  with patch.object(review,'response',return_value=(data,errors+['incomplete finish: length'])),self.assertRaises(AssertionError):review.approved(job)
 def test_previous_artifacts_and_source_bytes_preserved(self):
  for rel,h in read(OUT/'baseline-freeze.json').items():self.assertEqual(sha(ROOT/rel),h,rel)
  paths=read(OUT/'source-paths.json')
  for did,h in read(OUT/'source-freeze.json').items():self.assertEqual(sha(paths[did]),h,did)
 def test_old_metadata_changes_only_explicit_new_contract_field(self):
  changes=read(OUT/'prepared-partial/old-metadata-changes.json')
  self.assertEqual(len(changes),26)
  for r in changes:
   self.assertEqual(r['field'],'계약유형');self.assertIsNone(r['before']['value']);self.assertEqual(r['after']['status'],'extracted')
 def test_truncated_response_cannot_pass_transport_gate(self):
  job=read(OUT/'vision-unique.json')[0];response=read(OUT/'vision-responses'/job['id']/'response.json')
  response['response']['choices'][0]['finish_reason']='length'
  with patch.object(review,'read',return_value=response):
   data,errors=review.response(job)
  self.assertTrue(data);self.assertIn('incomplete finish: length',errors)
 def test_source_review_tied_to_response_and_image_hash(self):
  job=read(OUT/'vision-unique.json')[0]
  real=review.read
  def tampered(path):
   r=real(path)
   if 'vision-review' in Path(path).parts:r['asset_sha256']='0'*64
   return r
  with patch.object(review,'read',side_effect=tampered),self.assertRaises(AssertionError):review.approved(job)
 def test_vector_cache_identical_to_previous_vectors(self):
  base=np.load(BASE/'vectors.npy',allow_pickle=False);stage=OUT/'prepared-partial'
  reuse=read(stage/'vector-reuse.json');self.assertGreater(len(reuse),1000)
  for r in reuse:self.assertTrue(np.array_equal(np.load(stage/'embedding-cache'/(r['cache_key']+'.npy'),allow_pickle=False),base[r['prior_vector_id']]))
 def test_evaluation_request_contains_no_answers(self):
  values=rows(OUT/'evaluation/inputs.jsonl');self.assertEqual(len(values),125)
  self.assertTrue(all(set(q)=={'query_id','query','base_date'} for q in values))
 def test_unknown_new_source_location_is_rejected(self):
  r=copy.deepcopy(rows(OUT/'native-new.jsonl')[0]);r['blocks'][0]['loc']={'kind':'ini','line_start':2,'line_end':1}
  errors=check(r);self.assertIn('extended location format mismatch',errors);self.assertIn('reversed extended line range',errors)
if __name__=='__main__':unittest.main()
