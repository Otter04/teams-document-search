"""Exercise the real supplied workbook using explicitly synthetic outputs.

python tests/integration_check.py DATASET OUTPUT_DIR
OUTPUT_DIR must not already exist; all artifacts are synthetic tests.
"""
from argparse import Namespace
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import evaluate as ev


def dump(path, value, lines=False):
    path.write_text(("\n".join(json.dumps(x, ensure_ascii=False) for x in value) if lines
                     else json.dumps(value, ensure_ascii=False, indent=2)) + "\n", encoding="utf-8")


def main(dataset, output):
    output.mkdir(parents=True, exist_ok=False)
    docs, strings, queries = ev.load_gold(dataset)
    template = next(dataset.glob("*.xlsx"))
    before_hash = hashlib.sha256(template.read_bytes()).hexdigest()
    parsed, chunks, metadata = [], [], []
    by_doc = {d: [g["text"] for g in strings if g["doc_id"] == d] for d in docs}
    for identity, d in docs.items():
        # These strings and labels come from gold solely to test the EVALUATOR.
        texts = by_doc[identity]
        parsed.append({"doc_id": identity, "blocks": [{"type": "test", "text": "\n".join(texts), "loc": {}, "heading_path": []}]})
        chunks.append({"doc_id": identity, "chunks": [{"chunk_id": f"c{i}", "text": t, "context_header": "가상 검증 입력"} for i, t in enumerate(texts)]})
        metadata.append({k: d[k] for k in ev.COLS + ["family"]})
    ids = list(docs)
    qids = list(queries)
    ranks = [5, 6, 10, 11, 0]
    search = []
    expected_ranks = []
    for i, (identity, q) in enumerate(queries.items()):
        rank = ranks[i] if i < len(ranks) else 1
        false = [d for d in ids if d not in q["answers"]][:11]
        ranked = false[:]
        if rank:
            ranked.insert(rank-1, q["answers"][0])
        search.append({"query_id": identity, "doc_ids": ranked})
        expected_ranks.append(rank if rank <= 10 else 0)
    metadata[0]["거래처"] = "의도적으로 틀린 거래처"
    metadata[0]["오류코드"] = "=1+1"  # The workbook must store text, not execute it.
    inputs = output / "inputs"
    inputs.mkdir()
    info = {k: "N/A" for k in ev.INFO}
    info.update(run_id="SYNTHETIC-001", environment="evaluator-self-test", pipeline_version="synthetic-v1",
                measured_at="2026-10-14", run_kind="synthetic-test", query_reference_date="2026-10-14")
    dump(inputs/"run-info.json", info)
    for name, data in [("parsed", parsed), ("chunks", chunks), ("metadata", metadata), ("search", search)]:
        dump(inputs/f"{name}.jsonl", data, True)
    dump(inputs/"manual.json", {"parse_success_rate": {"value": 0.9, "evidence": "의도적인 가상 측정값"}})
    args = Namespace(dataset=str(dataset), template=None, output=str(output/"full"),
                     run_info=str(inputs/"run-info.json"), manual_metrics=str(inputs/"manual.json"),
                     **{k: str(inputs/f"{k}.jsonl") for k in ["parsed", "chunks", "metadata", "search"]})
    report = ev.run(args)
    assert [q["rank"] for q in report["query_results"]] == expected_ranks
    expected_hit = sum(1 <= r <= 5 for r in expected_ranks)/len(expected_ranks)
    assert report["metrics"]["search"]["hit_at_5"] == expected_hit
    assert report["metrics"]["strings"]["preservation"] == 1
    assert report["metrics"]["strings"]["cut_rate"] == 0
    assert report["metrics"]["fields"]["거래처"]["counts"]["불일치"] == 1
    assert report["metrics"]["fields"]["오류코드"]["counts"]["환각"] == 1
    assert report["metrics"]["family"]["precision"] == report["metrics"]["family"]["recall"] == 1
    assert report["search_verdict"] == "통과"
    # Overall hit rate passes; number/mixed subtypes intentionally fall below 90%.
    assert report["all_stages_verdict"] == "미달 항목 있음"
    original = ev.openpyxl.load_workbook(template)
    saved = ev.openpyxl.load_workbook(output/"full/evaluation.xlsx")
    assert ev.formula_map(original) == ev.formula_map(saved)
    assert saved["추출결과"]["Z2"].data_type == "s"
    assert saved["추출결과"]["Z2"].value == "=1+1"
    assert saved["추출결과"]["H2"].number_format == original["추출결과"]["H2"].number_format == "@"
    # Check every original cell for unauthorized changes and every cell style.
    def allowed(sheet, cell):
        r, c = cell.row, cell.column
        return ((sheet == "필수문자열" and r >= 2 and c in [7, 8])
                or (sheet == "검색어" and r >= 2 and c == 9)
                or (sheet == "추출결과" and r >= 2 and c <= 27)
                or (sheet == "실행기록" and r == 2)
                or (sheet == "통과기준" and ((c == 3 and 3 <= r <= 11)
                    or (c == 5 and r in set(ev.MANUAL.values()) | {26, 27}))))
    checked = 0
    for s in original:
        target = saved[s.title]
        assert str(s.merged_cells) == str(target.merged_cells)
        assert str(s.data_validations) == str(target.data_validations)
        assert s.freeze_panes == target.freeze_panes
        assert {k: dict(v) for k, v in s.column_dimensions.items()} == {k: dict(v) for k, v in target.column_dimensions.items()}
        for row in s:
            for cell in row:
                dst = target[cell.coordinate]
                assert cell._style == dst._style, (s.title, cell.coordinate, "style")
                if not allowed(s.title, cell):
                    assert cell.value == dst.value, (s.title, cell.coordinate, "value")
                checked += 1
    # A second run from the last workbook must preserve history and clear stale inputs.
    info["run_id"] = "SYNTHETIC-002"
    dump(inputs/"run-info-partial.json", info)
    dump(inputs/"search-partial.jsonl", [{"query_id": qids[0], "doc_ids": []}], True)
    partial = deepcopy(args)
    partial.template = str(output/"full/evaluation.xlsx")
    partial.output = str(output/"partial")
    partial.run_info = str(inputs/"run-info-partial.json")
    partial.parsed = partial.chunks = partial.metadata = None
    partial.manual_metrics = None
    partial.search = str(inputs/"search-partial.jsonl")
    r2 = ev.run(partial)
    assert r2["search_verdict"] == "미측정"
    w2 = ev.openpyxl.load_workbook(output/"partial/evaluation.xlsx")
    assert w2["실행기록"]["A2"].value == "SYNTHETIC-001"
    assert w2["실행기록"]["A3"].value == "SYNTHETIC-002"
    assert w2["추출결과"]["A2"].value is None
    assert w2["필수문자열"]["G2"].value is None
    assert w2["검색어"]["I2"].value == 0 and w2["검색어"]["I3"].value is None
    assert w2["통과기준"]["E26"].value is None
    assert w2["통과기준"]["E16"].value is None
    # Same run ID must be rejected with no partial output; source must not change.
    duplicate = deepcopy(partial)
    duplicate.output = str(output/"duplicate-rejected")
    duplicate.template = str(output/"partial/evaluation.xlsx")
    try:
        ev.run(duplicate)
        raise AssertionError("duplicate run accepted")
    except ev.InputError:
        pass
    assert not Path(duplicate.output).exists()
    assert before_hash == hashlib.sha256(template.read_bytes()).hexdigest()
    print(json.dumps({"integration": "PASS", "original_cells_checked": checked,
                      "formula_count_preserved": len(ev.formula_map(original)),
                      "synthetic_expected_hit_at_5": expected_hit, "source_sha256_unchanged": True}, indent=2))


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve())
