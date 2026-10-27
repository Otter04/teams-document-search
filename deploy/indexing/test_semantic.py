"""Reject invalid references/duplicate JSON without making model requests."""
from copy import deepcopy
import unittest
from inspect_semantic import validate,strict_json

class EvidenceValidationTests(unittest.TestCase):
    def setUp(self):
        self.packet={'fields':['목표'],'excerpts':[{'id':1},{'id':2}]}
        self.good={'fields':{'목표':[1]},'summary_sources':[1]}
    def test_valid(self):validate(self.packet,self.good)
    def test_unknown_evidence(self):
        bad=deepcopy(self.good);bad['fields']['목표']=[99]
        with self.assertRaises(AssertionError):validate(self.packet,bad)
    def test_bool_is_not_integer_reference(self):
        bad=deepcopy(self.good);bad['fields']['목표']=[True]
        with self.assertRaises(AssertionError):validate(self.packet,bad)
    def test_duplicate_reference(self):
        bad=deepcopy(self.good);bad['summary_sources']=[1,1]
        with self.assertRaises(AssertionError):validate(self.packet,bad)
    def test_unapproved_field(self):
        bad=deepcopy(self.good);bad['fields']['작성일']=[2]
        with self.assertRaises(AssertionError):validate(self.packet,bad)
    def test_duplicate_json_key(self):
        with self.assertRaises(ValueError):strict_json('{"fields":{},"fields":{}}')

if __name__=='__main__':unittest.main()
