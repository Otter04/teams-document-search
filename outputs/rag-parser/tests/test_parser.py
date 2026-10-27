from argparse import Namespace
from pathlib import Path
import sys
import tempfile
import unittest
from zipfile import ZipFile, ZIP_DEFLATED

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from pptx import Presentation
from pptx.util import Inches
import openpyxl
from reportlab.pdfgen import canvas

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import parse as p


class ParserTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.options = Namespace(ocr=None, ocr_dpi=200, min_pdf_chars=20, ocr_images=False, hidden_sheets="include")

    def tearDown(self):
        self.tmp.cleanup()

    def test_docx_order_heading_and_no_invented_page(self):
        d = Document()
        d.add_heading("계약", 1)
        d.add_paragraph("제1조(목적)")
        d.add_paragraph("본문")
        t = d.add_table(rows=1, cols=2)
        t.cell(0,0).text = "품목"
        t.cell(0,1).text = "금액"
        d.add_paragraph("표 뒤")
        f = self.root/"test.docx"; d.save(f)
        blocks, warnings, info = p.parse_docx(f,self.options)
        self.assertEqual([b['type'] for b in blocks],['heading','heading','paragraph','table_row','paragraph'])
        self.assertEqual(blocks[2]['heading_path'],['계약','제1조(목적)'])
        self.assertFalse(any('page' in b['loc'] for b in blocks))

    def test_tracked_insert_and_delete(self):
        d = Document(); para = d.add_paragraph("유지")
        for tag, text in [('del','삭제'),('ins','추가')]:
            wrap = OxmlElement('w:'+tag); r=OxmlElement('w:r'); t=OxmlElement('w:t'); t.text=text
            r.append(t); wrap.append(r); para._p.append(wrap)
        f=self.root/'revisions.docx';d.save(f)
        blocks,_,_=p.parse_docx(f,self.options)
        self.assertEqual(blocks[0]['text'],'유지추가')

    def test_docx_merged_cells_and_header_identifier(self):
        d=Document();d.sections[0].header.paragraphs[0].text='기밀 CT-2025-1234'
        t=d.add_table(rows=2,cols=2);t.cell(0,0).merge(t.cell(0,1)).text='병합'
        t.cell(1,0).text='a';t.cell(1,1).text='b'
        f=self.root/'merged.docx';d.save(f)
        blocks,_,info=p.parse_docx(f,self.options)
        self.assertEqual(blocks[0]['text'],'병합')
        self.assertEqual([c['anchor_column'] for c in blocks[0]['cells']],[1,1])
        self.assertEqual(info['header_footer_identifiers'][0]['text'],'CT-2025-1234')
        self.assertNotIn('CT-2025-1234',''.join(b['text'] for b in blocks))

    def test_xlsx_merges_hidden_sheets_and_formula_warning(self):
        w=openpyxl.Workbook();s=w.active;s.title='표'
        s.append(['품목','수량','금액']);s.append(['상품',2,'=2*3']);s.merge_cells('A3:B3');s['A3']='병합'
        h=w.create_sheet('숨김');h.sheet_state='hidden';h['A1']='숨긴 값'
        f=self.root/'book.xlsx';w.save(f)
        blocks,warnings,info=p.parse_xlsx(f,self.options)
        self.assertTrue(any(b['loc']['sheet']=='숨김' for b in blocks))
        self.assertEqual(warnings[0]['code'],'missing_formula_cache')
        merged=next(b for b in blocks if b['loc']=={'sheet':'표','row':3,'cell_range':'A3:C3'})
        self.assertEqual(merged['text'],'병합')
        self.assertEqual([c['source_cell'] for c in merged['cells']],['A3','A3'])
        self.options.hidden_sheets='exclude'
        blocks,_,_=p.parse_xlsx(f,self.options)
        self.assertFalse(any(b['loc']['sheet']=='숨김' for b in blocks))

    def test_xlsx_cached_formula_is_value_not_expression(self):
        w=openpyxl.Workbook();w.active['A1']='=2*3';f=self.root/'cached.xlsx';w.save(f)
        with ZipFile(f) as z: parts={n:z.read(n) for n in z.namelist()}
        parts['xl/worksheets/sheet1.xml']=parts['xl/worksheets/sheet1.xml'].replace(b'<v></v>',b'<v>6</v>')
        with ZipFile(f,'w',ZIP_DEFLATED) as z:
            for n,v in parts.items():z.writestr(n,v)
        blocks,warnings,_=p.parse_xlsx(f,self.options)
        self.assertEqual(blocks[0]['text'],'6');self.assertFalse(warnings)
        self.assertEqual(blocks[0]['cells'][0]['formula'],'=2*3')

    def test_pptx_shapes_notes_tables_in_one_slide(self):
        w=Presentation();s=w.slides.add_slide(w.slide_layouts[6])
        sh=s.shapes.add_textbox(Inches(1), Inches(1), Inches(4), Inches(1));sh.text='제목'
        table=s.shapes.add_table(2,2,Inches(1), Inches(2), Inches(4), Inches(2)).table
        table.cell(0,0).text='host';table.cell(0,1).text='IP';table.cell(1,0).text='srv';table.cell(1,1).text='10.0.0.1'
        s.notes_slide.notes_text_frame.text='발표자 노트'
        f=self.root/'slides.pptx';w.save(f)
        blocks,_,_=p.parse_pptx(f,self.options)
        self.assertEqual(len(blocks),1)
        self.assertIn('10.0.0.1',blocks[0]['text']);self.assertIn('발표자 노트',blocks[0]['text'])
        self.assertEqual(blocks[0]['heading_path'],['제목'])
        self.assertEqual(blocks[0]['elements'][2]['cells'][1]['text'],'10.0.0.1')

    def test_text_cp949_and_line_locations(self):
        f=self.root/'text.txt';f.write_bytes('첫 문단\n두번째 줄\n\n끝'.encode('cp949'))
        blocks,_,info=p.parse_text(f,self.options)
        self.assertEqual(info['encoding'],'cp949')
        self.assertEqual(blocks[0]['loc'],{'line_start':1,'line_end':2})
        self.assertEqual(blocks[1]['loc']['line_start'],4)

    def test_log_structured_and_unchanged(self):
        text='2025-01-01 01:02:03 [ERROR] failed ORA-01555\nstack: line 2'
        f=self.root/'test.log';f.write_text(text)
        blocks,_,_=p.parse_text(f,self.options)
        self.assertEqual(blocks[0]['level'],'ERROR')
        self.assertEqual(blocks[0]['error_codes'],['ORA-01555'])
        self.assertEqual('\n'.join(b['text'] for b in blocks),text)

    def test_corrupt_encoding_never_silently_replaced(self):
        with self.assertRaises(UnicodeDecodeError):p.decode_bytes(b'\x81')

    def test_pdf_text_and_table_location(self):
        f=self.root/'test.pdf';c=canvas.Canvas(str(f));c.drawString(40,800,'Standalone text outside the table')
        for x in [40,140,240]:c.line(x,650,x,750)
        for y in [650,700,750]:c.line(40,y,240,y)
        c.drawString(50,720,'Item');c.drawString(150,720,'Qty');c.drawString(50,670,'Widget');c.drawString(150,670,'3')
        c.save();blocks,_,info=p.parse_pdf(f,self.options)
        rows=[b for b in blocks if b['type']=='table_row']
        self.assertEqual(len(rows),2)
        self.assertEqual(rows[1]['cells'][1]['text'],'3')
        self.assertEqual(rows[1]['loc']['page'],1)
        self.assertEqual(sum('Widget' in b['text'] for b in blocks),1)

    def test_ocr_reading_order_without_changing_text(self):
        raw=[{'text':'right','bbox':[.6,.2,.9,.22]}, {'text':'title','bbox':[.2,.1,.8,.13]},
             {'text':'left','bbox':[.1,.201,.4,.221]}]
        ordered=p.order_ocr_lines(raw)
        self.assertEqual([l['text'] for l in ordered],['title','left','right'])
        self.assertEqual([l['engine_order'] for l in ordered],[2,3,1])


if __name__=='__main__':unittest.main()
