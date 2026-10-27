#!/usr/bin/env python3
"""Read pipeline outputs; evaluate against gold; fill a COPY of the workbook.

No model calls, indexing, OCR, or changes to the source dataset are performed.
See README.md for the JSONL contract and interpretation of partial runs.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import sys
import tempfile
import unicodedata

import openpyxl
from openpyxl.workbook.properties import CalcProperties

VERSION = "1.0.1"
COLS = ["doc_id", "파일명", "경로", "형식", "스캔", "문서종류", "거래처", "문서일자",
        "사업명", "대상시스템", "상태", "계약번호", "계약유형", "계약시작일", "계약종료일",
        "금액", "통화", "VAT", "견적번호", "견적유효기간", "사이트", "작업명", "로그시작",
        "로그종료", "실행결과", "오류코드"]
FIELDS = [k for k in COLS[5:] if k != "사업명"]
DATES = {"문서일자", "계약시작일", "계약종료일", "견적유효기간"}
TIMES = {"로그시작", "로그종료"}
EXACT = DATES | TIMES | {"계약번호", "견적번호", "금액", "오류코드"}
INFO = ["run_id", "environment", "llm_model", "quantization", "provider", "embedding_model",
        "prompt_version", "pipeline_version", "measured_at"]
MANUAL = {"collection_rate": 14, "sync_rate": 15, "parse_success_rate": 16,
          "table_cell_accuracy": 18, "ocr_cer": 19, "encoding_error_documents": 20,
          "schema_success_rate": 21, "oversize_chunks": 28, "missing_table_headers": 29,
          "missing_context_headers": 30, "throughput_docs_per_hour": 38}
COUNTS = {"encoding_error_documents", "oversize_chunks", "missing_table_headers", "missing_context_headers"}


class InputError(ValueError):
    pass


def need(condition, message):
    if not condition:
        raise InputError(message)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        need(key not in result, f"JSON 키 중복: {key}")
        result[key] = value
    return result


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"), object_pairs_hook=unique_object,
                      parse_constant=lambda v: (_ for _ in ()).throw(InputError(f"잘못된 숫자: {v}")))


def read_records(path):
    path = Path(path)
    if path.suffix.lower() == ".json":
        rows = read_json(path)
    else:
        rows = []
        for line_no, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
            if line.strip():
                try:
                    rows.append(json.loads(line, object_pairs_hook=unique_object,
                                           parse_constant=lambda v: (_ for _ in ()).throw(InputError(v))))
                except (ValueError, InputError) as exc:
                    raise InputError(f"{path.name}:{line_no}: {exc}") from exc
    need(isinstance(rows, list) and all(isinstance(r, dict) for r in rows), f"{path}: 객체 배열/JSONL 필요")
    return rows


def keyed(rows, key, allowed=None):
    out = {}
    for row in rows:
        identity = row.get(key)
        need(isinstance(identity, str) and identity.strip(), f"{key} 누락 또는 잘못된 형식")
        need(identity not in out, f"중복 {key}: {identity}")
        need(allowed is None or identity in allowed, f"알 수 없는 {key}: {identity}")
        out[identity] = row
    return out


def clean_text(text):
    # Match the handoff's whitespace-only rule, not fuzzy or semantic matching.
    return "".join(text.split())


def excel_text(value):
    # Excel TRIM also collapses repeated ASCII spaces; preserve tabs/NBSP.
    return re.sub(r" +", " ", str(value if value is not None else "").strip(" ")).casefold()


def normalize(field, value):
    need(value is None or isinstance(value, (str, int, float)) and not isinstance(value, bool),
         f"{field}: 문자열/숫자/null만 허용")
    s = str(value).strip() if value is not None else ""
    if not s or s.casefold() == "n/a":
        return "N/A"
    if field in DATES:
        need(bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", s)), f"{field}: YYYY-MM-DD 필요: {s}")
        date.fromisoformat(s)
    elif field in TIMES:
        need(bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2}(\.\d+)?)?", s)),
             f"{field}: 시간대 없는 ISO 시각 필요: {s}")
        s = datetime.fromisoformat(s).strftime("%Y-%m-%d %H:%M")
    elif field == "금액":
        need(bool(re.fullmatch(r"[+-]?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?", s)), f"금액 형식 오류: {s}")
        try:
            n = Decimal(s.replace(",", ""))
        except InvalidOperation as exc:
            raise InputError(f"금액 형식 오류: {s}") from exc
        need(n.is_finite() and n == n.to_integral_value(), f"금액은 정수여야 함: {s}")
        s = str(int(n))
    return s


def coverage(records, expected, supplied):
    return {"provided": supplied, "completed": len(records), "expected": len(expected),
            "missing_ids": sorted(set(expected) - set(records)),
            "status": "미실행" if not supplied else "완료" if len(records) == len(expected) else "일부 평가"}


def fraction(a, b):
    return a / b if b else None


def grade(value, threshold, direction="≥", complete=True):
    if not complete or value is None:
        return "미측정"
    if threshold is None:
        return "참고"
    return "통과" if (value >= threshold if direction == "≥" else value <= threshold) else "미달"


def score_field(gold, prediction, present=True):
    if not present:
        return "미추출"
    g, p = excel_text(gold), excel_text(prediction)
    if not g:
        return "제외"
    if g == "n/a":
        return "정상공란" if p in ("", "n/a") else "환각"
    return "일치" if p == g else "불일치"


def pair_scores(gold, predictions):
    # Count pairs in partitions; predicted family names need not match gold names.
    def pairs(n):
        return n * (n - 1) // 2
    actual = Counter(d["family"] for d in gold.values())
    predicted = Counter(predictions.values())
    overlaps = Counter((gold[d]["family"], family) for d, family in predictions.items())
    tp = sum(pairs(n) for n in overlaps.values())
    relevant = sum(pairs(n) for n in actual.values())
    retrieved = sum(pairs(n) for n in predicted.values())
    # No positive predictions => undefined precision, never a fabricated 100%.
    return {"true_positive_pairs": tp, "predicted_pairs": retrieved, "gold_pairs": relevant,
            "precision": fraction(tp, retrieved), "recall": fraction(tp, relevant)}


def fingerprint(path):
    return {"path": str(Path(path).resolve()), "sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest()}


def load_gold(dataset):
    docs = keyed(read_records(dataset / "gold/documents.jsonl"), "doc_id")
    strings = read_records(dataset / "gold/golden_strings.jsonl")
    queries = keyed(read_records(dataset / "gold/queries.jsonl"), "query_id")
    need(docs and strings and queries, "정답 세트가 비어 있음")
    for d in docs.values():
        need(all(k in d for k in COLS + ["family"]), f"정답 필드 누락: {d['doc_id']}")
    for s in strings:
        need(s.get("doc_id") in docs and isinstance(s.get("text"), str) and clean_text(s["text"]), "필수 문자열 정답 오류")
    for q in queries.values():
        need(isinstance(q.get("answers"), list) and 1 <= len(q["answers"]) <= 3, "검색 정답은 1~3개")
        need(all(a in docs for a in q["answers"]), f"검색 정답 ID 오류: {q['query_id']}")
        need(isinstance(q.get("type"), str) and q["type"], "검색어 유형 누락")
    # Only the known file mapping is used. No generator is executed.
    paths = {unicodedata.normalize("NFC", str(p.relative_to(dataset / "files")))
             for p in (dataset / "files").rglob("*") if p.is_file()}
    for d in docs.values():
        relative = d["경로"].lstrip("/") + "/" + d["파일명"]
        need(unicodedata.normalize("NFC", relative) in paths, f"원본 파일 없음: {d['doc_id']}")
    return docs, strings, queries


def validate_template(wb, docs, strings, queries):
    need(set(["통과기준", "문서정답", "필수문자열", "검색어", "추출결과", "실행기록", "보강채점", "용량계획"]) <= set(wb.sheetnames),
         "평가 엑셀 시트 누락")
    gold_rows = {r[0]: r for r in wb["문서정답"].iter_rows(min_row=2, values_only=True) if r[0]}
    need(set(gold_rows) == set(docs), "엑셀/JSON 문서 ID 불일치")
    for identity, d in docs.items():
        for i, key in enumerate(COLS + ["family", "최신본"]):
            need(str(gold_rows[identity][i] if gold_rows[identity][i] is not None else "") == str(d.get(key, "")),
                 f"엑셀/JSON 정답 불일치: {identity}/{key}")
    srows = [(r[0], r[2], r[3], r[4]) for r in wb["필수문자열"].iter_rows(min_row=2, values_only=True) if r[0]]
    need(srows == [(s["doc_id"], s["text"], s["kind"], s["loc"]) for s in strings], "엑셀/JSON 필수 문자열 순서·내용 불일치")
    qrows = [(r[0], r[1], r[2], [x for x in r[3:6] if x], r[6] or "")
             for r in wb["검색어"].iter_rows(min_row=2, values_only=True) if r[0]]
    need(qrows == [(q["query_id"], q["query"], q["type"], q["answers"], q.get("filters", "")) for q in queries.values()],
         "엑셀/JSON 검색 정답 순서·내용 불일치")
    need(len(docs) <= 300 and len(strings) <= 1000 and len(queries) <= 200, "엑셀 수식의 평가 범위 초과")


def calculate(docs, strings, queries, parsed, chunks, metadata, search, supplied):
    parsed_text, chunk_text, predictions, rankings, warnings = {}, {}, {}, {}, []
    for identity, r in parsed.items():
        need(isinstance(r.get("blocks"), list), f"{identity}: blocks 배열 필요")
        for b in r["blocks"]:
            need(isinstance(b, dict) and isinstance(b.get("text"), str), f"{identity}: block.text 문자열 필요")
            need(isinstance(b.get("type"), str) and isinstance(b.get("loc"), dict)
                 and isinstance(b.get("heading_path"), list), f"{identity}: type/loc/heading_path 필요")
        parsed_text[identity] = clean_text("\n".join(b["text"] for b in r["blocks"]))
    for identity, r in chunks.items():
        need(isinstance(r.get("chunks"), list), f"{identity}: chunks 배열 필요")
        seen = set()
        for c in r["chunks"]:
            need(isinstance(c, dict) and isinstance(c.get("text"), str), f"{identity}: chunk.text 필요")
            need(isinstance(c.get("chunk_id"), str) and c["chunk_id"] and c["chunk_id"] not in seen,
                 f"{identity}: chunk_id 누락/중복")
            need(c.get("doc_id", identity) == identity, f"{identity}: chunk.doc_id 불일치")
            need("context_header" in c and isinstance(c["context_header"], str),
                 f"{identity}: 문맥 머리말은 context_header 필드로 분리해야 함")
            seen.add(c["chunk_id"])
        chunk_text[identity] = [clean_text(c["text"]) for c in r["chunks"]]
    for identity, r in metadata.items():
        need(all(k in r for k in FIELDS), f"{identity}: 채점 필드 누락: {sorted(set(FIELDS)-set(r))}")
        predictions[identity] = {k: normalize(k, r.get(k)) for k in COLS[4:]}
        # Provenance only. NEVER copy gold labels, family or latest flags into a prediction.
        predictions[identity].update({k: docs[identity][k] for k in COLS[:4]})
        for k in COLS[1:4]:
            need(k not in r or r[k] == docs[identity][k], f"{identity}: 파일 식별 정보 불일치: {k}")
    for identity, r in search.items():
        need(isinstance(r.get("doc_ids"), list) and all(isinstance(x, str) for x in r["doc_ids"]),
             f"{identity}: doc_ids 배열 필요")
        need(all(x in docs for x in r["doc_ids"]), f"{identity}: 검색 결과에 평가 대상 밖 doc_id 포함")
        unique = list(dict.fromkeys(r["doc_ids"]))
        if len(unique) != len(r["doc_ids"]):
            warnings.append(f"{identity}: 중복 문서 제거 후 순위 계산")
        rankings[identity] = unique[:10]
    cov = {k: coverage(v, queries if k == "search" else docs, supplied[k])
           for k, v in [("parsed", parsed), ("chunks", chunks), ("metadata", metadata), ("search", search)]}
    string_results = []
    for s in strings:
        identity, needle = s["doc_id"], clean_text(s["text"])
        included = None if identity not in parsed_text else ("Y" if needle in parsed_text[identity] else "N")
        cut = None
        if included == "Y" and identity in chunk_text:
            cut = "N" if any(needle in c for c in chunk_text[identity]) else "Y"
        string_results.append({**s, "included": included, "cut": cut})
    included = Counter(s["included"] for s in string_results)
    cut = Counter(s["cut"] for s in string_results)
    field_counts = {k: Counter(score_field(d[k], predictions.get(identity, {}).get(k), identity in predictions)
                               for identity, d in docs.items()) for k in FIELDS}
    exact_counts = sum((field_counts[k] for k in FIELDS if k in EXACT), Counter())
    all_counts = sum(field_counts.values(), Counter())
    accuracy = lambda c: fraction(c["일치"], c["일치"] + c["불일치"])
    field_metrics = {k: {"accuracy": accuracy(c), "counts": dict(c)} for k, c in field_counts.items()}
    family_predictions = {}
    for identity, r in metadata.items():
        if "family" in r:
            need(isinstance(r["family"], str) and r["family"].strip() and r["family"].strip().casefold() != "n/a",
                 f"{identity}: family는 비어 있지 않은 군집 ID 필요 (단독 문서도 고유 ID 사용)")
            family_predictions[identity] = r["family"].strip()
    cov["family"] = coverage(family_predictions, docs, bool(family_predictions))
    family = pair_scores(docs, family_predictions)
    if not family_predictions:
        family["recall"] = None
    qresults = []
    for identity, q in queries.items():
        rank = None if identity not in rankings else next((i for i, d in enumerate(rankings[identity], 1) if d in q["answers"]), 0)
        qresults.append({"query_id": identity, "type": q["type"], "rank": rank,
                         "hit_at_5": None if rank is None else int(1 <= rank <= 5),
                         "rr": None if rank is None else (1 / rank if rank else 0),
                         "top_10": rankings.get(identity)})
    def qmetric(rows):
        measured = [r for r in rows if r["rank"] is not None]
        return {"measured": len(measured), "expected": len(rows),
                "hit_at_5": fraction(sum(r["hit_at_5"] for r in measured), len(measured)),
                "mrr_at_10": fraction(sum(r["rr"] for r in measured), len(measured))}
    metrics = {"strings": {"preservation": fraction(included["Y"], included["Y"] + included["N"]),
                            "measured": included["Y"] + included["N"], "expected": len(strings),
                            "cut_rate": fraction(cut["Y"], cut["Y"] + cut["N"]),
                            "cut_measured": cut["Y"] + cut["N"], "parse_present_strings": included["Y"]},
               "fields": field_metrics, "exact_accuracy": accuracy(exact_counts),
               "hallucination_rate": fraction(all_counts["환각"], all_counts["환각"] + all_counts["정상공란"]),
               "family": family, "search": qmetric(qresults),
               "search_by_type": {t: qmetric([r for r in qresults if r["type"] == t]) for t in sorted({q["type"] for q in queries.values()})}}
    return metrics, cov, string_results, qresults, predictions, warnings


def validate_info(info):
    need(isinstance(info, dict), "run-info는 JSON 객체여야 함")
    need(all(isinstance(info.get(k), str) and info[k].strip() for k in INFO), f"실행 정보 필수 키: {', '.join(INFO)}")
    need(info.get("run_kind") in ("evaluation", "synthetic-test"), "run_kind는 evaluation 또는 synthetic-test")
    date.fromisoformat(info["measured_at"])
    need(bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", info["measured_at"])), "measured_at는 YYYY-MM-DD")
    need(bool(re.fullmatch(r"[A-Za-z0-9_.-]+", info["run_id"])), "run_id는 영문/숫자/밑줄/점/하이픈만 허용")


def build_gates(wb, metrics, cov, manual):
    need(isinstance(manual, dict), "수동 측정은 JSON 객체 필요")
    need(set(manual) <= set(MANUAL), f"알 수 없는 수동 지표: {set(manual)-set(MANUAL)}")
    values = {}
    for name, measurement in manual.items():
        need(isinstance(measurement, dict) and isinstance(measurement.get("evidence"), str)
             and measurement["evidence"].strip(), f"{name}: 측정 근거 evidence 필요")
        v = measurement.get("value")
        need(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v >= 0, f"{name}: 유한한 0 이상 숫자 필요")
        if name in COUNTS:
            need(v == int(v), f"{name}: 정수 필요")
        elif name != "throughput_docs_per_hour":
            need(v <= 1, f"{name}: 비율은 0~1")
        values[MANUAL[name]] = v
    m = metrics
    values.update({17: m["strings"]["preservation"], 22: m["fields"]["문서종류"]["accuracy"],
                   23: m["fields"]["거래처"]["accuracy"], 24: m["exact_accuracy"], 25: m["hallucination_rate"],
                   26: m["family"]["precision"], 27: m["family"]["recall"], 31: m["strings"]["cut_rate"],
                   32: m["search"]["hit_at_5"], 37: m["search"]["mrr_at_10"]})
    for row, kind in [(33, "메타데이터형"), (34, "번호형"), (35, "의미형"), (36, "혼합")]:
        values[row] = m["search_by_type"].get(kind, {}).get("hit_at_5")
    complete = {17: cov["parsed"]["status"] == "완료", 31: cov["parsed"]["status"] == cov["chunks"]["status"] == "완료"}
    complete.update({r: cov["metadata"]["status"] == "완료" for r in range(22, 26)})
    complete.update({r: cov["family"]["status"] == "완료" for r in [26, 27]})
    complete.update({r: cov["search"]["status"] == "완료" for r in range(32, 38)})
    gates = []
    for r in range(14, 39):
        threshold = wb["통과기준"][f"D{r}"].value
        if r == 38 and isinstance(threshold, str) and threshold.startswith("="):
            need(threshold.replace("'", "") == "=용량계획!B22", "운영 기준 수식 변경: 직접 숫자로 지정 필요")
            need(wb["용량계획"]["B22"].value == "=B18/B19", "용량계획 필요 처리량 수식 변경")
            n, hours = wb["용량계획"]["B18"].value, wb["용량계획"]["B19"].value
            need(isinstance(n, (int, float)) and isinstance(hours, (int, float)) and n >= 0 and hours > 0,
                 "용량계획 B18/B19는 유효한 숫자 필요")
            threshold = n / hours
        need(threshold is None or isinstance(threshold, (int, float)) and math.isfinite(threshold), f"D{r}: 숫자 기준값 필요")
        direction = wb["통과기준"][f"C{r}"].value
        need(direction in ("≥", "≤"), f"C{r}: 비교 방향 오류")
        gates.append({"row": r, "metric": wb["통과기준"][f"B{r}"].value, "value": values.get(r),
                      "threshold": threshold, "direction": direction,
                      "status": grade(values.get(r), threshold, direction, complete.get(r, True))})
    final = next(g["status"] for g in gates if g["row"] == 32)
    statuses = {g["status"] for g in gates}
    overall = "미달 항목 있음" if "미달" in statuses else "측정 진행 중" if "미측정" in statuses else "전체 통과"
    return gates, final, overall


def formula_map(wb):
    return {(s.title, c.coordinate): c.value for s in wb for row in s for c in row if c.data_type == "f"}


def set_literal(cell, value):
    need(cell.data_type != "f", f"수식 칸 덮어쓰기 차단: {cell.parent.title}!{cell.coordinate}")
    cell.value = value
    if isinstance(value, str):
        # Pipeline text such as '=...' must never become an Excel formula.
        cell.data_type = "s"


def fill_workbook(wb, report, docs, predictions):
    before = formula_map(wb)
    info = report["run_info"]
    history = wb["실행기록"]
    need(not any(r[0] == info["run_id"] for r in history.iter_rows(min_row=2, values_only=True)), "동일 실행ID가 이미 실행기록에 있음")
    history_row = next((r for r in range(2, history.max_row + 1) if all(history.cell(r, c).value is None for c in range(1, 20))), None)
    need(history_row is not None, "실행기록 입력 공간 소진")
    for i, key in enumerate(INFO, 3):
        set_literal(wb["통과기준"][f"C{i}"], info[key])
    # Clear stale measured inputs when continuing from a previous output workbook.
    for r in set(MANUAL.values()) | {26, 27}:
        set_literal(wb["통과기준"][f"E{r}"], None)
    for gate in report["gates"]:
        if gate["row"] in set(MANUAL.values()) | {26, 27}:
            set_literal(wb["통과기준"][f"E{gate['row']}"], gate["value"] if gate["status"] != "미측정" else None)
    result_iter = iter(report["string_results"])
    for r in range(2, wb["필수문자열"].max_row + 1):
        s = next(result_iter) if wb["필수문자열"].cell(r, 1).value else None
        for c, key in [(7, "included"), (8, "cut")]:
            set_literal(wb["필수문자열"].cell(r, c), s[key] if s else None)
    ranks = {q["query_id"]: q["rank"] for q in report["query_results"]}
    for r in range(2, wb["검색어"].max_row + 1):
        set_literal(wb["검색어"].cell(r, 9), ranks.get(wb["검색어"].cell(r, 1).value))
    for row in wb["추출결과"].iter_rows(min_row=2, max_col=27):
        for cell in row:
            set_literal(cell, None)
    for r, identity in enumerate((d for d in docs if d in predictions), 2):
        for c, key in enumerate(COLS, 1):
            set_literal(wb["추출결과"].cell(r, c), predictions[identity][key])
        set_literal(wb["추출결과"].cell(r, 27), info["run_id"])
    m = report["metrics"]
    note = (f"{info['run_kind']}; 검색={report['search_verdict']}; 전체={report['all_stages_verdict']}; "
            + "; ".join(f"{k} {v['completed']}/{v['expected']}" for k, v in report["coverage"].items()))
    row_values = [info[k] for k in ["run_id", "measured_at", "environment", "llm_model", "quantization", "provider", "embedding_model", "prompt_version", "pipeline_version"]]
    row_values += [m["strings"]["preservation"], m["fields"]["문서종류"]["accuracy"], m["fields"]["거래처"]["accuracy"],
                   m["exact_accuracy"], m["hallucination_rate"], m["search"]["hit_at_5"], m["search"]["mrr_at_10"],
                   report["manual_metrics"].get("throughput_docs_per_hour", {}).get("value"),
                   report["search_verdict"], note]
    for c, value in enumerate(row_values, 1):
        set_literal(history.cell(history_row, c), value)
    wb.calculation = CalcProperties(calcMode="auto", fullCalcOnLoad=True, forceFullCalc=True)
    need(formula_map(wb) == before, "기존 수식 변경 감지")


def markdown_report(report):
    def display(v):
        return "미측정" if v is None else f"{v:.2%}"
    m = report["metrics"]
    lines = [f"# RAG 평가 결과 — {report['run_info']['run_id']}", "",
             f"실행 종류: **{report['run_info']['run_kind']}**. 측정일: {report['run_info']['measured_at']}.", ""]
    if report["run_info"]["run_kind"] == "synthetic-test":
        lines += ["**평가기 검증용 가상 입력입니다. 실제 RAG·모델 성능 측정이 아닙니다.**", ""]
    lines += [f"검색 최종 판정(전체 질문 완료 필요): **{report['search_verdict']}**.",
              f"전체 단계 판정(완료 건수 반영): **{report['all_stages_verdict']}**.", "",
              "## 평가 범위", "", "| 입력 | 완료/전체 | 상태 |", "|---|---:|---|"]
    for k, c in report["coverage"].items():
        lines.append(f"| {k} | {c['completed']}/{c['expected']} | {c['status']} |")
    lines += ["", "## 측정된 항목의 점수", "", "빈 입력·누락 문서는 분모에서 제외되므로 아래 점수와 완료 건수를 함께 확인하세요.", "",
              f"- 필수 문자열 보존율: {display(m['strings']['preservation'])} ({m['strings']['measured']}/{m['strings']['expected']}개 평가)",
              f"- 필수 문자열 잘림 비율: {display(m['strings']['cut_rate'])} ({m['strings']['cut_measured']}개 평가)",
              f"- 문서종류 정확도: {display(m['fields']['문서종류']['accuracy'])}",
              f"- 거래처 정확도: {display(m['fields']['거래처']['accuracy'])}",
              f"- 날짜·금액·번호 정확도: {display(m['exact_accuracy'])}",
              f"- 환각률: {display(m['hallucination_rate'])}",
              f"- Recall@5(이 프로젝트의 Hit@5): {display(m['search']['hit_at_5'])}",
              f"- MRR@10: {m['search']['mrr_at_10'] if m['search']['mrr_at_10'] is not None else '미측정'}", "",
              "## 단계별 판정", "", "| 지표 | 측정값 | 기준 | 판정 |", "|---|---:|---:|---|"]
    for g in report["gates"]:
        lines.append(f"| {g['metric']} | {g['value'] if g['value'] is not None else '미측정'} | {g['direction']} {g['threshold'] if g['threshold'] is not None else '참고'} | {g['status']} |")
    lines += ["", "## 해석과 제한", "",
              "- 원본 엑셀의 수식을 보존했습니다. 엑셀의 종합 판정은 완료 건수를 검사하지 않으므로 이 보고서와 다를 수 있습니다.",
              "- report.json의 점수와 실행기록은 Python이 계산한 값입니다. 엑셀 수식은 Excel/LibreOffice에서 열어 재계산해야 합니다.",
              "- 미제공 결과와 빈 결과는 다릅니다. 검색 결과 []는 실패(순위 0), 미제공 질문은 미측정입니다.",
              "- 청크 본문만 문자열 비교에 사용하며 context_header는 제외합니다. 청킹 입력이 없는 문서는 잘림 여부를 판정하지 않습니다.",
              "- 사본 묶음의 이름 자체는 비교하지 않습니다. 같은 묶음에 들어간 문서 쌍으로 정밀도·재현율을 계산합니다.",
              "- 파싱 성공률, OCR CER, 표 셀 정확도 등은 별도 측정 근거가 있어야 기록합니다.",
              "- 상대 날짜 질의는 2026-10 기준입니다. 검색 실행도 같은 기준일을 사용해야 합니다.", ""]
    if report["warnings"]:
        lines += ["## 입력 처리 알림", ""] + [f"- {w}" for w in report["warnings"]] + [""]
    return "\n".join(lines)


def run(args):
    dataset = Path(args.dataset).resolve()
    output = Path(args.output).resolve()
    need(not output.exists(), "출력 폴더가 이미 있습니다. 새 실행 폴더를 지정하세요.")
    need(dataset != output and dataset not in output.parents, "원본 데이터셋 안에 결과를 쓰지 않습니다")
    info = read_json(args.run_info)
    validate_info(info)
    docs, strings, queries = load_gold(dataset)
    templates = list(dataset.glob("*.xlsx"))
    need(args.template or len(templates) == 1, "평가 엑셀을 --template으로 지정하세요")
    template = Path(args.template).resolve() if args.template else templates[0]
    wb = openpyxl.load_workbook(template)
    validate_template(wb, docs, strings, queries)
    supplied = {k: getattr(args, k) is not None for k in ["parsed", "chunks", "metadata", "search"]}
    need(any(supplied.values()), "평가 입력을 최소 하나 지정하세요")
    if supplied["search"]:
        reference_date = info.get("query_reference_date", "")
        need(isinstance(reference_date, str) and re.fullmatch(r"2026-10-\d{2}", reference_date),
             "검색 평가는 query_reference_date=2026-10-DD 필요 (상대 날짜 정답의 기준월)")
        date.fromisoformat(reference_date)
    inputs = {k: keyed(read_records(getattr(args, k)), "query_id" if k == "search" else "doc_id",
                       queries if k == "search" else docs) if supplied[k] else {} for k in supplied}
    metrics, cov, sresults, qresults, predictions, warnings = calculate(docs, strings, queries, **inputs, supplied=supplied)
    manual = read_json(args.manual_metrics) if args.manual_metrics else {}
    gates, final, overall = build_gates(wb, metrics, cov, manual)
    paths = [dataset / "gold" / f for f in ["documents.jsonl", "golden_strings.jsonl", "queries.jsonl"]]
    paths += [template, Path(args.run_info), Path(__file__)] + [Path(getattr(args, k)) for k in supplied if supplied[k]]
    if args.manual_metrics:
        paths.append(Path(args.manual_metrics))
    report = {"evaluator_version": VERSION, "run_info": info, "coverage": cov, "metrics": metrics,
              "gates": gates, "search_verdict": final, "all_stages_verdict": overall,
              "manual_metrics": manual, "warnings": warnings, "string_results": sresults,
              "query_results": qresults, "inputs": [fingerprint(p) for p in paths],
              "workbook_formulas_recalculated": False}
    fill_workbook(wb, report, docs, predictions)
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".rag-eval-", dir=output.parent))
    try:
        xlsx = staging / "evaluation.xlsx"
        wb.save(xlsx)
        saved = openpyxl.load_workbook(xlsx)
        need(formula_map(saved) == formula_map(wb), "저장 후 수식 불일치")
        (staging / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        (staging / "report.md").write_text(markdown_report(report), encoding="utf-8")
        need(not output.exists(), "출력 폴더가 실행 중 생성되었습니다")
        staging.rename(output)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, help="files/와 gold/가 있는 폴더")
    parser.add_argument("--output", required=True, help="새 결과 폴더 (덮어쓰기 금지)")
    parser.add_argument("--run-info", required=True, help="실행 정보 JSON")
    parser.add_argument("--template", help="기본 평가 엑셀 또는 직전 실행 엑셀 (이력 보존)")
    for name in ["parsed", "chunks", "metadata", "search"]:
        parser.add_argument(f"--{name}", help="문서별/질문별 JSONL 또는 JSON 배열")
    parser.add_argument("--manual-metrics", help="별도 실측값과 근거를 담은 JSON")
    args = parser.parse_args()
    try:
        report = run(args)
    except (InputError, ValueError, OSError, KeyError, TypeError) as exc:
        print(f"입력/실행 오류: {exc}", file=sys.stderr)
        return 2
    print(f"평가 저장 완료: {Path(args.output).resolve()}")
    print(f"검색 판정: {report['search_verdict']} / 전체 단계: {report['all_stages_verdict']}")
    if report["run_info"]["run_kind"] == "synthetic-test":
        print("평가기 검증용 가상 입력입니다. 실제 RAG 성능이 아닙니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
