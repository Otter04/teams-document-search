"""Native helpers migrated from parser 1.1.0. No image recognition dependencies."""
from datetime import date, datetime
import re
from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph
from pptx.enum.shapes import MSO_SHAPE_TYPE
CLAUSE = re.compile(r"^제\s*\d+\s*조\s*\([^\n]{1,60}\)$")
CONTRACT_ID = re.compile(r"\bCT-\d{4}-\d+\b")
TIMESTAMP = re.compile(r"\b\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?\b")
LEVEL = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?\s+\[?\s*(TRACE|DEBUG|INFO|WARN(?:ING)?|ERROR|FATAL)\b\s*\]?", re.I)
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

def in_box(char, box):
    x, y = (char["x0"] + char["x1"])/2, (char["top"] + char["bottom"])/2
    return box[0] <= x <= box[2] and box[1] <= y <= box[3]

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
