import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import evaluate as ev


def gold_doc(identity, family="F1"):
    d = {k: "N/A" for k in ev.COLS}
    d.update(doc_id=identity, family=family, 파일명=f"{identity}.txt", 경로="/sites/test", 형식="txt",
             문서종류="계약서", 거래처="테스트회사", 문서일자="2025-01-01", 금액="1000", 최신본="Y")
    return d


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.docs = {i: gold_doc(i) for i in ["D-1", "D-2"]}
        self.strings = [{"doc_id": "D-1", "text": "현장 도착", "kind": "조항", "loc": "1쪽"}]
        self.queries = {"Q-1": {"query_id": "Q-1", "answers": ["D-1"], "type": "의미형"},
                        "Q-2": {"query_id": "Q-2", "answers": ["D-2"], "type": "번호형"}}

    def calculate(self, **inputs):
        flags = {k: k in inputs for k in ["parsed", "chunks", "metadata", "search"]}
        kw = {k: inputs.get(k, {}) for k in flags}
        return ev.calculate(self.docs, self.strings, self.queries, **kw, supplied=flags)

    def block(self, text):
        return {"doc_id": "D-1", "blocks": [{"type": "paragraph", "text": text, "loc": {"page": 1}, "heading_path": []}]}

    def chunks(self, *texts, header="현장 도착"):
        return {"doc_id": "D-1", "chunks": [{"chunk_id": f"c{i}", "text": t, "context_header": header} for i, t in enumerate(texts)]}

    def test_whitespace_and_header_exclusion(self):
        r = self.calculate(parsed={"D-1": self.block("현장 도\n착")}, chunks={"D-1": self.chunks("현장", "도착")})
        self.assertEqual((r[2][0]["included"], r[2][0]["cut"]), ("Y", "Y"))
        r = self.calculate(parsed={"D-1": self.block("현장 도착")}, chunks={"D-1": self.chunks("현장\t도 착")})
        self.assertEqual(r[2][0]["cut"], "N")

    def test_missing_parse_does_not_mean_failure(self):
        r = self.calculate(parsed={})
        self.assertIsNone(r[2][0]["included"])
        self.assertIsNone(r[0]["strings"]["preservation"])
        self.assertEqual(r[1]["parsed"]["status"], "일부 평가")

    def test_empty_parse_is_measured_failure(self):
        r = self.calculate(parsed={"D-1": {"doc_id": "D-1", "blocks": []}})
        self.assertEqual(r[2][0]["included"], "N")
        self.assertIsNone(r[2][0]["cut"])

    def test_missing_chunks_vs_empty_chunks(self):
        r = self.calculate(parsed={"D-1": self.block("현장 도착")})
        self.assertIsNone(r[2][0]["cut"])
        r = self.calculate(parsed={"D-1": self.block("현장 도착")}, chunks={"D-1": self.chunks()})
        self.assertEqual(r[2][0]["cut"], "Y")

    def test_missing_header_rejected(self):
        with self.assertRaises(ev.InputError):
            self.calculate(chunks={"D-1": {"doc_id": "D-1", "chunks": [{"chunk_id": "c", "text": "현장"}]}})

    def test_search_missing_vs_empty_and_duplicates(self):
        r = self.calculate(search={"Q-1": {"doc_ids": []}})
        self.assertEqual(r[3][0]["rank"], 0)
        self.assertIsNone(r[3][1]["rank"])
        r = self.calculate(search={"Q-1": {"doc_ids": ["D-2", "D-2", "D-1"]}})
        self.assertEqual(r[3][0]["rank"], 2)
        self.assertEqual(len(r[5]), 1)

    def test_search_rank_boundaries(self):
        self.docs = {f"D-{i}": gold_doc(f"D-{i}") for i in range(1, 13)}
        for rank, hit, rr in [(5, 1, 1/5), (6, 0, 1/6), (10, 0, 1/10), (11, 0, 0)]:
            ranked = [f"D-{i}" for i in range(2, 13)]
            ranked.insert(rank-1, "D-1")
            r = self.calculate(search={"Q-1": {"doc_ids": ranked}})
            self.assertEqual(r[3][0]["hit_at_5"], hit)
            self.assertEqual(r[3][0]["rr"], rr)

    def test_unknown_search_doc_rejected(self):
        with self.assertRaises(ev.InputError):
            self.calculate(search={"Q-1": {"doc_ids": ["outside"]}})

    def test_metadata_cases(self):
        self.assertEqual(ev.score_field("N/A", "surprise"), "환각")
        self.assertEqual(ev.score_field("N/A", None), "정상공란")
        self.assertEqual(ev.score_field("a", None), "불일치")
        self.assertEqual(ev.score_field("", "anything"), "제외")
        self.assertEqual(ev.score_field("a", None, False), "미추출")
        self.assertEqual(ev.score_field(" ABC  def ", "abc def"), "일치")

    def test_metadata_no_gold_leakage(self):
        pred = {k: "N/A" for k in ev.FIELDS}
        r = self.calculate(metadata={"D-1": pred})
        self.assertEqual(r[4]["D-1"]["거래처"], "N/A")
        self.assertEqual(r[4]["D-1"]["파일명"], "D-1.txt")
        self.assertNotIn("family", r[4]["D-1"])
        self.assertEqual(r[0]["fields"]["거래처"]["counts"], {"불일치": 1, "미추출": 1})

    def test_missing_metadata_fields_rejected(self):
        with self.assertRaises(ev.InputError):
            self.calculate(metadata={"D-1": {"거래처": "테스트회사"}})

    def test_date_and_number_normalization(self):
        self.assertEqual(ev.normalize("금액", "1,234.0"), "1234")
        self.assertEqual(ev.normalize("금액", 0), "0")
        self.assertEqual(ev.normalize("로그시작", "2025-01-01T02:03:59"), "2025-01-01 02:03")
        self.assertEqual(ev.normalize("상태", None), "N/A")
        for field, value in [("금액", "1,23"), ("금액", "1.1"), ("금액", True),
                             ("문서일자", "2025-02-30"), ("문서일자", "01/02/2025"),
                             ("로그시작", "2025-01-01T00:00:00Z")]:
            with self.assertRaises(ValueError):
                ev.normalize(field, value)

    def test_pair_precision_recall_with_renamed_clusters(self):
        self.docs["D-3"] = gold_doc("D-3", "F2")
        r = ev.pair_scores(self.docs, {"D-1": "x", "D-2": "x", "D-3": "x"})
        self.assertEqual(r["precision"], 1/3)
        self.assertEqual(r["recall"], 1)
        r = ev.pair_scores(self.docs, {"D-1": "x", "D-2": "y", "D-3": "z"})
        self.assertIsNone(r["precision"])
        self.assertEqual(r["recall"], 0)

    def test_partial_evaluation_never_passes(self):
        self.assertEqual(ev.grade(1, .9, complete=False), "미측정")
        self.assertEqual(ev.grade(.9, .9), "통과")
        self.assertEqual(ev.grade(.899, .9), "미달")

    def test_unrun_family_recall_is_unmeasured(self):
        result = self.calculate(parsed={"D-1": self.block("현장 도착")})
        self.assertIsNone(result[0]["family"]["recall"])
        self.assertIsNone(result[0]["family"]["precision"])

    def test_duplicate_and_unknown_ids(self):
        for rows in [[{"doc_id": "D-1"}, {"doc_id": "D-1"}], [{"doc_id": "bad"}]]:
            with self.assertRaises(ev.InputError):
                ev.keyed(rows, "doc_id", self.docs)

    def test_duplicate_json_keys_and_nan(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/"input.json"
            for content in ['{"a":1,"a":2}', '{"a":NaN}']:
                p.write_text(content)
                with self.assertRaises(ev.InputError):
                    ev.read_json(p)

    def test_formula_injection_and_formula_guard(self):
        wb = ev.openpyxl.Workbook()
        c = wb.active["A1"]
        ev.set_literal(c, '=HYPERLINK("https://example.invalid","test")')
        self.assertEqual(c.data_type, "s")
        wb.active["B1"] = "=1+1"
        with self.assertRaises(ev.InputError):
            ev.set_literal(wb.active["B1"], 2)


if __name__ == "__main__":
    unittest.main()
