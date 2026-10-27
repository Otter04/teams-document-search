import copy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import openpyxl
from docx import Document
from pptx import Presentation
from pptx.util import Inches
from PIL import Image
from reportlab.pdfgen import canvas
import native
from parse import Builder,parse_docx,parse_xlsx,parse_pptx,parse_pdf,parse_text,validation,usable_pdf_table,bbox,render_copy_with_font,digest,visible_slide_text
from evaluate import project_literal


class NativeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name)
        self.args=SimpleNamespace(render_dpi=72,min_pdf_chars=20,soffice=None,work_dir=str(self.root))
    def tearDown(self): self.temp.cleanup()
    def build(self,path):
        return Builder(path,{'doc_id':'TEST','relative_path':path.name},self.root/'out',self.args)
    def valid(self,b): self.assertEqual([],validation.check(b.doc))

    def test_cp949_and_line_location(self):
        p=self.root/'memo.txt'; p.write_bytes('고객 요청\n두 번째 줄\n\n다음 문단'.encode('cp949'))
        b=self.build(p);parse_text(b);self.valid(b)
        self.assertEqual('cp949',b.doc['source']['encoding'])
        self.assertEqual(2,b.doc['blocks'][0]['loc']['line_end'])

    def test_log_fraction_level_and_message_word(self):
        p=self.root/'a.log';p.write_text('2025-09-02 02:25:41,738 ERROR [step] ORA-01555\nmessage mentions ERROR\n')
        b=self.build(p);parse_text(b);self.valid(b)
        self.assertEqual('2025-09-02 02:25:41,738',b.doc['blocks'][0]['log']['timestamp_raw'])
        self.assertEqual('ERROR',b.doc['blocks'][0]['log']['level'])
        self.assertIsNone(b.doc['blocks'][1]['log']['level'])

    def test_merged_excel_anchor_only_and_missing_cache(self):
        p=self.root/'a.xlsx';wb=openpyxl.Workbook();s=wb.active
        s.merge_cells('A1:C1');s['A1']='Merged title';s['A2']=2;s['B2']='=A2*2';wb.save(p)
        b=self.build(p);parse_xlsx(b);self.valid(b)
        cells=[c for x in b.doc['blocks'] for c in x.get('cells',[])]
        self.assertEqual(1,sum(c['text']=='Merged title' for c in cells))
        self.assertEqual(3,next(c for c in cells if c['text']=='Merged title')['column_span'])
        formula=next(c for c in cells if c['formula'])
        self.assertEqual('missing_cache',formula['value_status']);self.assertIsNone(formula['value'])

    def test_hidden_excel_sheet_is_included(self):
        p=self.root/'a.xlsx';wb=openpyxl.Workbook();wb.active['A1']='visible'
        hidden=wb.create_sheet('secret');hidden.sheet_state='hidden';hidden['A1']='hidden value';wb.save(p)
        b=self.build(p);parse_xlsx(b);self.valid(b)
        self.assertIn('hidden value',' '.join(x['text'] for x in b.doc['blocks']))

    def test_docx_vertical_and_horizontal_merge(self):
        p=self.root/'a.docx';d=Document();t=d.add_table(rows=3,cols=3)
        t.cell(0,0).merge(t.cell(0,2)).text='title'
        t.cell(1,0).merge(t.cell(2,0)).text='two rows';d.save(p)
        b=self.build(p);parse_docx(b);self.valid(b)
        cells=[c for x in b.doc['blocks'] for c in x.get('cells',[])]
        self.assertEqual(1,sum(c['text']=='two rows' for c in cells))
        self.assertEqual(2,next(c for c in cells if c['text']=='two rows')['row_span'])

    def test_pptx_shapes_require_visual_review_without_images(self):
        p=self.root/'a.pptx';d=Presentation();s=d.slides.add_slide(d.slide_layouts[6])
        s.shapes.add_textbox(Inches(1),Inches(1),Inches(3),Inches(1)).text='Network diagram';d.save(p)
        b=self.build(p);parse_pptx(b);self.valid(b)
        self.assertEqual(1,len(b.queue));self.assertEqual('pending',b.doc['coverage']['units'][-1]['status'])
        self.assertEqual('',b.doc['blocks'][0]['text'])

    def test_scan_pdf_is_pending_and_not_empty_success(self):
        p=self.root/'scan.pdf';img=self.root/'image.png';Image.new('RGB',(200,100),'gray').save(img)
        pdf=canvas.Canvas(str(p));pdf.drawImage(str(img),10,10,200,100);pdf.save()
        b=self.build(p);parse_pdf(b);self.valid(b)
        self.assertEqual([],b.doc['blocks']);self.assertEqual(1,len(b.queue))
        self.assertEqual(1,len(b.doc['assets']))

    def test_literal_projection_excludes_claims_and_node_copies(self):
        p=self.root/'a.txt';p.write_text('actual text');b=self.build(p);parse_text(b)
        block=b.doc['blocks'][0]
        block['claims']=[{'claim_id':'c','text':'not in source','status':'inferred','evidence_ids':['source']}]
        projected=project_literal(b.doc)
        self.assertEqual('actual text',projected['blocks'][0]['text'])
        self.assertNotIn('not in source',json.dumps(projected))

    def test_design_examples_cannot_be_evaluated_as_runs(self):
        p=self.root/'a.txt';p.write_text('x');b=self.build(p);parse_text(b);b.doc['record_kind']='design_example'
        with self.assertRaises(ValueError):project_literal(b.doc)

    def test_invalid_evidence_is_rejected(self):
        p=self.root/'a.txt';p.write_text('x');b=self.build(p);parse_text(b)
        b.doc['blocks'][0]['claims']=[{'claim_id':'c','text':'x','status':'observed','evidence_ids':['missing']}]
        self.assertTrue(validation.check(b.doc))

    def test_page_border_not_a_table(self):
        t=SimpleNamespace(rows=[SimpleNamespace(cells=[(-.01,-.01,0,700),(0,0,900,700)])])
        self.assertFalse(usable_pdf_table(t))
        good=SimpleNamespace(rows=[SimpleNamespace(cells=[(0,0,30,10),(30,0,60,10)])])
        self.assertTrue(usable_pdf_table(good))

    def test_normalized_bbox_clamp_and_zero_area_rejection(self):
        box=bbox({'asset_id':'a'},[-.01,0,100.01,100],100,100)
        self.assertEqual(0,box['x0']);self.assertEqual(1,box['x1'])
        with self.assertRaises(ValueError):bbox({'asset_id':'a'},[-1,0,0,10],100,100)

    def test_font_substitution_preserves_source_and_text(self):
        p=self.root/'a.pptx';d=Presentation();s=d.slides.add_slide(d.slide_layouts[6])
        s.shapes.add_textbox(Inches(1),Inches(1),Inches(3),Inches(1)).text='한글 구성도 FortiGate × 2';d.save(p)
        before=digest(p);target=self.root/'render.pptx';render_copy_with_font(p,target,'Arial Unicode MS')
        self.assertEqual(before,digest(p));self.assertEqual(visible_slide_text(s),visible_slide_text(Presentation(target).slides[0]))

if __name__=='__main__':unittest.main()
