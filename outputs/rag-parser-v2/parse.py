#!/usr/bin/env python3
"""Local structural parsing baseline. Input manifest contains IDs and paths only."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, date, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import re
import statistics
import subprocess
import tempfile
import time
import unicodedata

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
import openpyxl
from openpyxl.utils import get_column_letter
import pdfplumber
import pypdfium2
from PIL import Image, ImageOps
from scan_layout import detect_tables

VERSION = "parser-1.1.0"
CLAUSE = re.compile(r"^제\s*\d+\s*조\s*\([^\n]{1,60}\)$")
CONTRACT_ID = re.compile(r"\bCT-\d{4}-\d+\b")
TIMESTAMP = re.compile(r"\b\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?\b")
LEVEL = re.compile(r"\[\s*(TRACE|DEBUG|INFO|WARN(?:ING)?|ERROR|FATAL)\s*\]", re.I)
ERROR_CODE = re.compile(r"\b(?:[A-Z][A-Z0-9]*-)+[A-Z]?\d{3,}\b")


def serial(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def text_value(value):
    if value is None:
        return ""
    if isinstance(value, (date, datetime)):
        return value.isoformat(sep=" ") if isinstance(value, datetime) else value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def block(kind, text, loc, heading=(), **extra):
    return {"type": kind, "text": text, "loc": loc, "heading_path": list(heading), **extra}


def final_text(element):
    """Final tracked-change view: accept inserts/moveTo; skip deletions/moveFrom."""
    pieces = []
    def visit(node):
        if node.tag in (qn("w:del"), qn("w:moveFrom"), qn("w:delText")):
            return
        if node.tag == qn("w:t"):
            pieces.append(node.text or "")
        elif node.tag in (qn("w:br"), qn("w:cr")):
            pieces.append("\n")
        elif node.tag == qn("w:tab"):
            pieces.append("\t")
        else:
            for child in node:
                visit(child)
    visit(element)
    return "".join(pieces)


def body_items(element):
    for child in element:
        if child.tag in (qn("w:del"), qn("w:moveFrom")):
            continue
        if child.tag in (qn("w:p"), qn("w:tbl")):
            yield child
        elif child.tag != qn("w:sectPr"):
            yield from body_items(child)


def parse_docx(path, options):
    document = Document(path)
    blocks, headings, warnings, identifiers = [], [], [], []
    paragraph_n = table_n = 0
    for element in body_items(document.element.body):
        if element.tag == qn("w:p"):
            paragraph_n += 1
            p = Paragraph(element, document)
            text = final_text(element).strip()
            if not text:
                continue
            style = p.style.name if p.style else ""
            match = re.match(r"(?:Heading|제목)\s*(\d+)$", style, re.I)
            outline = element.find("./" + qn("w:pPr") + "/" + qn("w:outlineLvl"))
            level = int(match[1]) if match else int(outline.get(qn("w:val"))) + 1 if outline is not None else None
            method = "style" if level else None
            if level is None and CLAUSE.fullmatch(text):
                level, method = 2, "clause_pattern"
            if level is None and (style.lower() == "title" or any(r.font.size and r.font.size.pt >= 18 for r in p.runs)) and len(text) < 180:
                level, method = 1, "title_style_or_font"
            if level and level <= 9:
                headings = [(n, t) for n, t in headings if n < level] + [(level, text)]
            blocks.append(block("heading" if level else "paragraph", text, {"paragraph": paragraph_n},
                                [t for _, t in headings], style=style, heading_method=method))
        else:
            table_n += 1
            table = Table(element, document)
            anchors = {}
            for row_n, row in enumerate(table.rows, 1):
                if row._tr.find("./" + qn("w:trPr") + "/" + qn("w:del")) is not None:
                    continue
                cells, texts, row_seen = [], [], set()
                for col_n, cell in enumerate(row.cells, 1):
                    key = cell._tc
                    anchor = anchors.setdefault(key, (row_n, col_n))
                    text = "\n".join(final_text(p) for p in cell._tc.findall(qn("w:p"))).strip()
                    cells.append({"row": row_n, "column": col_n, "text": text,
                                  "anchor_row": anchor[0], "anchor_column": anchor[1]})
                    if key not in row_seen:
                        texts.append(text)
                        row_seen.add(key)
                    if cell.tables:
                        warnings.append({"code": "nested_docx_table", "table": table_n, "row": row_n,
                                         "message": "중첩 표의 구조 처리는 별도 필요"})
                marked_header = row._tr.find("./" + qn("w:trPr") + "/" + qn("w:tblHeader")) is not None
                blocks.append(block("table_row", " | ".join(texts), {"table": table_n, "row": row_n},
                                    [t for _, t in headings], cells=cells, is_header=marked_header or row_n == 1,
                                    header_method="marked" if marked_header else "first_row_candidate" if row_n == 1 else None))
    parts = set()
    for section in document.sections:
        for part_name in ["header", "first_page_header", "even_page_header", "footer", "first_page_footer", "even_page_footer"]:
            part = getattr(section, part_name)
            if not part._has_definition or str(part.part.partname) in parts:
                continue
            parts.add(str(part.part.partname))
            for token in CONTRACT_ID.findall(final_text(part._element)):
                identifiers.append({"kind": "contract_number", "text": token, "loc": {"part": str(part.part.partname)}})
    return blocks, warnings, {"header_footer_identifiers": identifiers, "tracked_changes_view": "final", "page_numbers": "unavailable_without_layout_engine"}


def walk_shapes(shapes, parents=()):
    for shape in shapes:
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            yield from walk_shapes(shape.shapes, parents + (shape.shape_id,))
        else:
            yield shape, parents


def bbox_shape(shape):
    return [int(shape.left), int(shape.top), int(shape.left + shape.width), int(shape.top + shape.height)]


def run_ocr(image_path, executable):
    if not executable:
        raise RuntimeError("OCR 실행기가 지정되지 않았습니다")
    process = subprocess.run([str(executable), str(image_path)], capture_output=True, text=True, timeout=120)
    if process.returncode:
        raise RuntimeError(process.stderr.strip() or "OCR 실패")
    result = json.loads(process.stdout)
    if not isinstance(result.get("lines"), list):
        raise ValueError("OCR 응답 lines 배열 없음")
    return result


def order_ocr_lines(lines):
    """Top-to-bottom, left-to-right baseline; never infer table relationships."""
    if not lines:
        return []
    heights = [l["bbox"][3]-l["bbox"][1] for l in lines]
    tolerance = statistics.median(heights) * 0.6
    ordered = sorted(({**l, "engine_order": i} for i, l in enumerate(lines, 1)),
                     key=lambda l: (l["bbox"][1]+l["bbox"][3])/2)
    rows = []
    for line in ordered:
        cy = (line["bbox"][1]+line["bbox"][3])/2
        if not rows or abs(cy-rows[-1][0]) > tolerance:
            rows.append((cy, [line]))
        else:
            rows[-1][1].append(line)
    return [l for _, row in rows for l in sorted(row, key=lambda l: l["bbox"][0])]


def parse_pptx(path, options):
    deck = Presentation(path)
    blocks, warnings = [], []
    for slide_n, slide in enumerate(deck.slides, 1):
        elements, texts = [], []
        title = slide.shapes.title.text.strip() if slide.shapes.title and slide.shapes.title.has_text_frame else ""
        # XML order is kept. Each nested element retains shape coordinates for visual reading order.
        candidates = []
        for shape, parents in walk_shapes(slide.shapes):
            loc = {"slide": slide_n, "shape_id": shape.shape_id, "group_path": list(parents), "bbox_emu": bbox_shape(shape)}
            if shape.has_text_frame and shape.text.strip():
                text = shape.text.strip()
                elements.append({"type": "shape_text", "text": text, "loc": loc})
                texts.append(text)
                candidates.append((shape.top, shape.left, text))
            if shape.has_table:
                for rn, row in enumerate(shape.table.rows, 1):
                    cells = []
                    for cn, c in enumerate(row.cells, 1):
                        cells.append({"row": rn, "column": cn, "text": c.text, "is_spanned": c.is_spanned,
                                      "row_span": c.span_height if c.is_merge_origin else 1,
                                      "col_span": c.span_width if c.is_merge_origin else 1})
                    text = " | ".join(c["text"] for c in cells if not c["is_spanned"])
                    elements.append({"type": "table_row", "text": text, "loc": {**loc, "row": rn}, "cells": cells,
                                     "is_header": rn == 1, "header_method": "first_row_candidate" if rn == 1 else None})
                    texts.append(text)
            if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
                if options.ocr_images and options.ocr:
                    try:
                        with tempfile.TemporaryDirectory() as temp:
                            image = Path(temp) / ("image." + shape.image.ext)
                            image.write_bytes(shape.image.blob)
                            ocr = run_ocr(image, options.ocr)
                        text = "\n".join(l["text"] for l in ocr["lines"])
                        elements.append({"type": "image_text", "text": text, "loc": loc, "ocr": ocr})
                        texts.append(text)
                    except Exception as exc:
                        warnings.append({"code": "picture_ocr_failed", "slide": slide_n, "message": str(exc)})
                else:
                    warnings.append({"code": "picture_ocr_not_run", "slide": slide_n, "shape_id": shape.shape_id})
        if not title and candidates:
            title = min(candidates)[2].splitlines()[0]
        if slide.has_notes_slide:
            notes = slide.notes_slide.notes_text_frame
            if notes and notes.text.strip():
                elements.append({"type": "speaker_notes", "text": notes.text, "loc": {"slide": slide_n, "part": "notes"}})
                texts.append(notes.text)
        blocks.append(block("slide", "\n".join(texts), {"slide": slide_n}, [title] if title else [],
                            elements=elements, title_method="placeholder" if slide.shapes.title and slide.shapes.title.text else "topmost_text_candidate"))
    return blocks, warnings, {"slides": len(deck.slides), "coordinate_units": "EMU; grouped shape coordinates remain in group frame"}


def parse_xlsx(path, options):
    formulas = openpyxl.load_workbook(path, data_only=False)
    cached = openpyxl.load_workbook(path, data_only=True)
    blocks, warnings, sheets = [], [], []
    for sheet in formulas:
        sheets.append({"name": sheet.title, "state": sheet.sheet_state})
        if sheet.sheet_state != "visible" and options.hidden_sheets == "exclude":
            warnings.append({"code": "hidden_sheet_excluded", "sheet": sheet.title})
            continue
        if sheet.max_row * sheet.max_column > 2_000_000:
            raise ValueError(f"과도한 셀 범위: {sheet.title}")
        merged = {}
        for area in sheet.merged_cells.ranges:
            for r in range(area.min_row, area.max_row + 1):
                for c in range(area.min_col, area.max_col + 1):
                    merged[(r, c)] = (area.min_row, area.min_col, str(area))
        candidates = []
        for row in sheet:
            populated = [c for c in row if c.value is not None]
            if len(populated) >= 3 and all(isinstance(c.value, str) and c.data_type != "f" for c in populated):
                candidates.append(row[0].row)
        table_ranges = list(sheet.tables.values())
        header_rows = {openpyxl.utils.range_boundaries(t.ref)[1] for t in table_ranges if t.headerRowCount}
        if not header_rows:
            # Candidate, not a semantic guarantee. Record this heuristic in every affected row.
            header_rows = set(candidates)
        for rn in range(1, sheet.max_row + 1):
            cells, texts, seen = [], [], set()
            for cn in range(1, sheet.max_column + 1):
                ar, ac, merged_range = merged.get((rn, cn), (rn, cn, None))
                origin = sheet.cell(ar, ac)
                value = cached[sheet.title].cell(ar, ac).value if origin.data_type == "f" else origin.value
                if origin.value is None:
                    continue
                address, anchor = f"{get_column_letter(cn)}{rn}", origin.coordinate
                formula = origin.value if origin.data_type == "f" else None
                if formula and value is None and (ar, ac) not in seen:
                    warnings.append({"code": "missing_formula_cache", "sheet": sheet.title, "cell": anchor, "formula": formula})
                text = text_value(value)
                cells.append({"address": address, "source_cell": anchor, "value": serial(value), "text": text,
                              "formula": formula, "merged_range": merged_range, "number_format": origin.number_format})
                if (ar, ac) not in seen:
                    texts.append(text)
                    seen.add((ar, ac))
            if not cells:
                continue
            h = max((r for r in header_rows if r <= rn), default=None)
            headers = [] if h is None else [text_value(sheet.cell(h, c).value) for c in range(1, sheet.max_column+1)]
            blocks.append(block("table_row", " | ".join(texts), {"sheet": sheet.title, "row": rn,
                                "cell_range": f"A{rn}:{get_column_letter(sheet.max_column)}{rn}"}, [sheet.title],
                                cells=cells, sheet_state=sheet.sheet_state, is_header=rn in header_rows,
                                header_row=h, headers=headers, header_method="excel_table" if table_ranges else "text_row_candidate",
                                row_hidden=bool(sheet.row_dimensions[rn].hidden)))
    formulas.close()
    cached.close()
    return blocks, warnings, {"sheets": sheets, "hidden_sheet_policy": options.hidden_sheets, "formula_policy": "cached_value_only; no recalculation"}


def in_box(char, box):
    x, y = (char["x0"] + char["x1"])/2, (char["top"] + char["bottom"])/2
    return box[0] <= x <= box[2] and box[1] <= y <= box[3]


def structure_scan(image, ocr, executable, temp, page_number):
    """Assign OCR lines by detected grid; crop ambiguous/missing cells only."""
    width,height=image.size
    grids=detect_tables(image)
    lines=order_ocr_lines(ocr["lines"])
    def within(line, box):
        b=line["bbox"];x=(b[0]+b[2])*width/2;y=(b[1]+b[3])*height/2
        return box[0]<=x<=box[2] and box[1]<=y<=box[3]
    def line_block(line, extra=None):
        return block("ocr_line",line["text"],{"page":page_number,"bbox_normalized":line["bbox"],**(extra or {})},
                     confidence=line.get("confidence"),raw_text=line.get("raw_text",line["text"]),
                     spacing_correction_applied=line.get("spacing_correction_applied",False),
                     unaccepted_language_alternative=line.get("unaccepted_language_alternative"),
                     engine_order=line.get("engine_order"))
    events=[]
    for ln,line in enumerate(lines,1):
        if not any(within(line,t["bbox_pixels"]) for t in grids):
            events.append((line["bbox"][1]*height,line["bbox"][0]*width,line_block(line,{"line":ln})))
    for tn,grid in enumerate(grids,1):
        grid["table"]=tn
        row_cells={};row_lines={}
        for cell in grid["cells"]:
            x0,y0,x1,y1=cell["bbox_pixels"]
            # Trim ruling, then add white margin. Detection never reads QA text.
            inset=max(3,round(height/800))
            left,top,right,bottom=x0+inset,y0+inset,x1-inset,y1-inset
            crop=image.crop((left,top,right,bottom));pad=12
            crop=ImageOps.expand(crop,border=pad,fill="white")
            file=temp/f"table-{tn}-r{cell['row']}-c{cell['column']}.png";crop.save(file)
            page_lines=[l for l in lines if within(l,cell["bbox_pixels"])]
            contained=[l for l in page_lines if max(0,min(x1,l["bbox"][2]*width)-max(x0,l["bbox"][0]*width)) / max(1,(l["bbox"][2]-l["bbox"][0])*width) >= .75]
            mapped=[]
            method="page_ocr_assigned_by_grid" if contained and len(contained)==len(page_lines) else "cell_crop"
            if method=="page_ocr_assigned_by_grid":
                recognized=contained
            else:
                recognized=order_ocr_lines(run_ocr(file,executable)["lines"])
                transformed=[]
                for line in recognized:
                    b=line["bbox"];cw,ch=crop.size
                    global_box=[(b[0]*cw-pad+left)/width,(b[1]*ch-pad+top)/height,
                                (b[2]*cw-pad+left)/width,(b[3]*ch-pad+top)/height]
                    transformed.append({**line,"bbox":[max(0,min(1,v)) for v in global_box]})
                recognized=transformed
            for line in recognized:
                mapped.append(line_block(line,{"table":tn,"row":cell["row"],"column":cell["column"]}))
            value={**cell,"text":"\n".join(l["text"] for l in mapped),
                   "bbox_normalized":[x0/width,y0/height,x1/width,y1/height],"ocr_method":method}
            row_cells.setdefault(cell["row"],[]).append(value)
            row_lines.setdefault(cell["row"],[]).extend(mapped)
        for rn,cells in row_cells.items():
            box=[min(c["bbox_pixels"][0] for c in cells),min(c["bbox_pixels"][1] for c in cells),
                 max(c["bbox_pixels"][2] for c in cells),max(c["bbox_pixels"][3] for c in cells)]
            loc={"page":page_number,"table":tn,"row":rn,"bbox_normalized":[box[0]/width,box[1]/height,box[2]/width,box[3]/height]}
            row=block("table_row"," | ".join(c["text"] for c in cells),loc,cells=cells,elements=row_lines[rn],
                      is_header=rn==1,header_method="first_row_candidate",source_method="scan_ruled_grid")
            events.append((box[1],box[0],row))
    return [e[2] for e in sorted(events,key=lambda e:(e[0],e[1]))],grids,lines


def parse_pdf(path, options):
    blocks, warnings, pages_info = [], [], []
    rendered = None
    with pdfplumber.open(path) as pdf:
        heading = []
        for pn, page in enumerate(pdf.pages, 1):
            native = page.extract_text(x_tolerance=2, y_tolerance=3) or ""
            use_ocr = len("".join(native.split())) < options.min_pdf_chars
            info = {"page": pn, "width": page.width, "height": page.height,
                    "native_nonspace_chars": len("".join(native.split())), "method": "ocr" if use_ocr else "text_layer"}
            pages_info.append(info)
            if use_ocr:
                if rendered is None:
                    rendered = pypdfium2.PdfDocument(path)
                with tempfile.TemporaryDirectory() as temp:
                    image = Path(temp)/"page.png"
                    rp = rendered[pn-1]
                    bitmap = rp.render(scale=options.ocr_dpi/72)
                    pil = bitmap.to_pil().convert("RGB")
                    pil.save(image)
                    bitmap.close()
                    rp.close()
                    ocr = run_ocr(image, options.ocr)
                    elements, grids, raw_lines = structure_scan(pil, ocr, options.ocr, Path(temp), pn)
                info.update({"ocr_engine": ocr.get("engine"), "ocr_revision": ocr.get("revision"),
                             "ocr_languages": ocr.get("languages"), "ocr_dpi": options.ocr_dpi,
                             "correction_policy": ocr.get("correction_policy"), "tables": grids})
                if not elements:
                    warnings.append({"code": "empty_ocr_page", "page": pn})
                blocks.append(block("ocr_page", "\n".join(e["text"] for e in elements), {"page": pn}, [], elements=elements,
                                    ocr_engine=ocr.get("engine"), ocr_revision=ocr.get("revision"), raw_page_lines=raw_lines,
                                    layout_status="ruled_tables_reconstructed; borderless_tables_and_diagram_edges_unsupported"))
                continue
            tables = page.find_tables()
            table_boxes = [t.bbox for t in tables]
            events = []
            for tn, table in enumerate(tables, 1):
                for rn, (row, row_geometry) in enumerate(zip(table.extract(), table.rows), 1):
                    cells = []
                    for cn, (value, bbox) in enumerate(zip(row, row_geometry.cells), 1):
                        cells.append({"row": rn, "column": cn, "text": value or "", "bbox": list(bbox) if bbox else None})
                    loc = {"page": pn, "table": tn, "row": rn, "bbox": list(row_geometry.bbox)}
                    events.append((row_geometry.bbox[1], row_geometry.bbox[0], "table_row", " | ".join(c["text"] for c in cells), loc, cells))
            outside = page.filter(lambda obj: obj.get("object_type") != "char" or not any(in_box(obj, b) for b in table_boxes))
            for ln, line in enumerate(outside.extract_text_lines(x_tolerance=2, y_tolerance=3), 1):
                loc = {"page": pn, "line": ln, "bbox": [line["x0"], line["top"], line["x1"], line["bottom"]]}
                events.append((line["top"], line["x0"], "text_line", line["text"], loc, None))
            for _, _, kind, text, loc, cells in sorted(events, key=lambda e: (e[0], e[1])):
                if CLAUSE.fullmatch(text.strip()):
                    heading = [text.strip()]
                    kind = "heading"
                extra = {"cells": cells, "is_header": loc["row"] == 1, "header_method": "first_row_candidate" if loc["row"] == 1 else None} if cells else {}
                blocks.append(block(kind, text, loc, heading, **extra))
    if rendered is not None:
        rendered.close()
    return blocks, warnings, {"pages": pages_info, "ocr_threshold_nonspace_chars": options.min_pdf_chars,
                              "bbox_units": "PDF points, top-left origin; OCR boxes normalized",
                              "ocr_reading_order": "geometric rows then left-to-right; original engine_order retained"}


def decode_bytes(raw):
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16"), "utf-16-bom"
    try:
        return raw.decode("utf-8-sig"), "utf-8-sig" if raw.startswith(b"\xef\xbb\xbf") else "utf-8"
    except UnicodeDecodeError:
        return raw.decode("cp949"), "cp949"


def parse_text(path, options):
    text, encoding = decode_bytes(path.read_bytes())
    lines = text.splitlines()
    blocks = []
    if path.suffix.lower() == ".log":
        for number, line in enumerate(lines, 1):
            if not line.strip():
                continue
            ts, level = TIMESTAMP.search(line), LEVEL.search(line)
            blocks.append(block("log_line", line, {"line_start": number, "line_end": number}, [],
                                timestamp=ts[0] if ts else None, level=level[1].upper() if level else None,
                                error_codes=ERROR_CODE.findall(line)))
    else:
        start, buffer = None, []
        for number, line in enumerate(lines + [""], 1):
            if line.strip():
                if start is None:
                    start = number
                buffer.append(line)
            elif buffer:
                blocks.append(block("paragraph", "\n".join(buffer), {"line_start": start, "line_end": number-1}, []))
                start, buffer = None, []
    warnings = [{"code": "replacement_character", "count": text.count("\ufffd")}] if "\ufffd" in text else []
    return blocks, warnings, {"encoding": encoding, "source_lines": len(lines), "decoding_policy": "strict; utf8 then cp949, UTF16 only with BOM"}


PARSERS = {"docx": parse_docx, "pptx": parse_pptx, "xlsx": parse_xlsx, "pdf": parse_pdf, "txt": parse_text, "log": parse_text}


def parse_file(path, doc_id, options):
    started = time.perf_counter()
    record = {"doc_id": doc_id, "source": {"file_name": path.name, "format": path.suffix[1:].lower(),
                                          "sha256": hashlib.sha256(path.read_bytes()).hexdigest()},
              "parser_version": VERSION, "blocks": [], "warnings": []}
    try:
        blocks, warnings, info = PARSERS[path.suffix[1:].lower()](path, options)
        for n, b in enumerate(blocks, 1):
            b["block_id"] = f"{doc_id}-B{n:05d}"
        record.update(blocks=blocks, warnings=warnings, details=info,
                      status="partial" if warnings else "ok" if any(b["text"].strip() for b in blocks) else "empty")
    except Exception as exc:
        record.update(status="failed", error=f"{type(exc).__name__}: {exc}")
    record["elapsed_seconds"] = round(time.perf_counter()-started, 4)
    return record


def run(args):
    root, output = Path(args.files_root).resolve(), Path(args.output).resolve()
    if output.exists() or output == root or root in output.parents:
        raise ValueError("새 출력 폴더를 지정하세요. 원본 files 안에는 기록하지 않습니다.")
    entries = [json.loads(l) for l in Path(args.manifest).read_text(encoding="utf-8").splitlines() if l.strip()]
    mapping = {unicodedata.normalize("NFC", str(p.relative_to(root))): p for p in root.rglob("*") if p.is_file()}
    ids, resolved = set(), []
    for item in entries:
        if set(item) != {"doc_id", "relative_path"} or not isinstance(item["doc_id"], str) or item["doc_id"] in ids:
            raise ValueError("manifest에는 중복 없는 doc_id와 relative_path 두 키만 허용됩니다")
        key = unicodedata.normalize("NFC", item["relative_path"])
        path = mapping.get(key)
        if path is None or root not in path.resolve().parents:
            raise ValueError(f"원본 범위 밖/누락 파일: {key}")
        ids.add(item["doc_id"])
        resolved.append((item, path))
    if not entries:
        raise ValueError("빈 manifest")
    output.mkdir(parents=True)
    parsed, statuses = [], Counter()
    try:
        for item, path in resolved:
            record = parse_file(path, item["doc_id"], args)
            record["source"]["relative_path"] = item["relative_path"]
            parsed.append(record)
            statuses[record["status"]] += 1
            print(f"{record['doc_id']} {path.suffix[1:]} {record['status']} blocks={len(record['blocks'])}", flush=True)
        (output/"parsed.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in parsed)+"\n", encoding="utf-8")
        manifest_bytes = Path(args.manifest).read_bytes()
        (output/"manifest.jsonl").write_bytes(manifest_bytes)
        provenance = {"parser_version": VERSION, "parsed_at_utc": datetime.now(timezone.utc).isoformat(),
                      "platform": platform.platform(), "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
                      "source_code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                      "layout_code_sha256": hashlib.sha256(Path(__file__).with_name("scan_layout.py").read_bytes()).hexdigest(),
                      "packages": {p: importlib.metadata.version(p) for p in ["python-docx", "python-pptx", "openpyxl", "pdfplumber", "pypdfium2", "opencv-python-headless", "numpy", "Pillow"]},
                      "settings": {"hidden_sheets": args.hidden_sheets, "min_pdf_chars": args.min_pdf_chars,
                                   "ocr_dpi": args.ocr_dpi, "ocr_images": args.ocr_images,
                                   "ocr_executable_sha256": hashlib.sha256(Path(args.ocr).read_bytes()).hexdigest() if args.ocr else None},
                      "documents": len(parsed), "status_counts": dict(statuses),
                      "block_count": sum(len(r["blocks"]) for r in parsed)}
        (output/"provenance.json").write_text(json.dumps(provenance, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    except BaseException:
        (output/"INCOMPLETE.txt").write_text("실행이 중단되었습니다. 평가에 사용하지 마세요.", encoding="utf-8")
        raise
    return 1 if statuses["failed"] or statuses["empty"] else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--files-root", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--ocr", type=Path, help="이미지 경로 한 개를 받아 JSON을 반환하는 OCR 실행기")
    parser.add_argument("--ocr-dpi", type=int, default=200)
    parser.add_argument("--min-pdf-chars", type=int, default=20)
    parser.add_argument("--ocr-images", action="store_true", help="PPTX 삽입 이미지에도 OCR 적용")
    parser.add_argument("--hidden-sheets", choices=["include", "exclude"], default="include")
    args = parser.parse_args()
    if not 72 <= args.ocr_dpi <= 600 or args.min_pdf_chars < 0:
        parser.error("OCR dpi는 72~600, 글자 임계값은 0 이상")
    raise SystemExit(run(args))


if __name__ == "__main__":
    main()
