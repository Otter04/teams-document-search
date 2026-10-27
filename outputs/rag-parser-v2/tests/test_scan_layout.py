from pathlib import Path
import sys,tempfile,unittest
from unittest.mock import patch
from PIL import Image,ImageDraw
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scan_layout import detect_tables
import parse


def sample(merge=False):
    image=Image.new('RGB',(1000,1000),'white');d=ImageDraw.Draw(image)
    for y in [200,260,320,380]:d.line((100,y,900,y),fill='black',width=2)
    for x in [100,500,900]:d.line((x,260 if merge and x==500 else 200,x,380),fill='black',width=2)
    return image


class ScanTests(unittest.TestCase):
    def test_grid_dimensions_and_empty_cells(self):
        result=detect_tables(sample())
        self.assertEqual(len(result),1)
        self.assertEqual((result[0]['row_count'],result[0]['column_count']),(3,2))
        self.assertEqual(len(result[0]['cells']),6)

    def test_merged_header_span(self):
        result=detect_tables(sample(True))
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]['cells'][0]['col_span'],2)
        self.assertEqual(len(result[0]['cells']),5)

    def test_flowchart_is_not_table(self):
        im=Image.new('RGB',(1000,1000),'white');d=ImageDraw.Draw(im)
        for box in [(350,100,650,180),(150,350,400,440),(650,350,900,440)]:d.rounded_rectangle(box,20,outline='black',width=3)
        d.line((500,180,275,350),fill='black',width=3);d.line((500,180,775,350),fill='black',width=3)
        self.assertEqual(detect_tables(im),[])

    def test_borderless_text_not_fabricated_as_grid(self):
        im=Image.new('RGB',(1000,1000),'white');d=ImageDraw.Draw(im)
        for y in [200,260,320]:
            for x in [100,500]:d.text((x,y),'sample value',fill='black')
        self.assertEqual(detect_tables(im),[])

    def test_cell_crop_coordinates_reading_order_no_duplicate_page_text(self):
        im=sample();raw={'lines':[{'text':'outside','bbox':[.1,.1,.3,.12]},
                                {'text':'raw cell duplicate','bbox':[.12,.21,.3,.24]}]}
        with tempfile.TemporaryDirectory() as t, patch.object(parse,'run_ocr',return_value={'lines':[{'text':'cell','bbox':[.1,.2,.5,.6],'raw_text':'cell'}]}):
            elements,grids,raw_lines=parse.structure_scan(im,raw,'unused',Path(t),2)
        self.assertEqual(elements[0]['text'],'outside')
        rows=[e for e in elements if e['type']=='table_row']
        self.assertEqual(len(rows),3)
        self.assertEqual(rows[0]['text'],'raw cell duplicate | cell')
        self.assertEqual('\n'.join(e['text'] for e in elements).count('raw cell duplicate'),1)
        self.assertEqual(raw_lines[1]['text'],'raw cell duplicate')
        self.assertEqual(rows[0]['elements'][0]['loc']['page'],2)
        self.assertTrue(all(0<=v<=1 for e in rows[0]['elements'] for v in e['loc']['bbox_normalized']))

if __name__=='__main__':unittest.main()
