#!/usr/bin/env python3
"""Copy verified LibreOffice caches into an original XLSX without changing formulas/styles.

The caller must first recalculate a separate copy using LibreOffice. This utility
requires matching formula strings and inputs (numeric round-trip tolerance 1e-14).
"""
import argparse
from copy import deepcopy
import json
import math
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from lxml import etree
import openpyxl

NS={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
TAG='{'+NS['s']+'}'


def values(wb):
    return {(s.title,c.coordinate):c.value for s in wb for row in s for c in row if c.value is not None}


def equivalent(a,b):
    if a.keys()!=b.keys():return False
    for key,x in a.items():
        y=b[key]
        if x==y:continue
        if isinstance(x,(int,float)) and isinstance(y,(int,float)) and math.isclose(x,y,rel_tol=1e-14,abs_tol=1e-14):continue
        return False
    return True


def cache(original, recalculated, output):
    if output.exists():raise ValueError('출력 파일이 이미 존재합니다')
    a=openpyxl.load_workbook(original);b=openpyxl.load_workbook(recalculated)
    if a.sheetnames!=b.sheetnames or not equivalent(values(a),values(b)):raise ValueError('재계산 사본의 수식/입력값이 달라 캐시 전송을 중단합니다')
    count=0
    with ZipFile(original) as src,ZipFile(recalculated) as calc,ZipFile(output,'w',ZIP_DEFLATED) as out:
        shared=[]
        if 'xl/sharedStrings.xml' in calc.namelist():
            shared=[''.join(si.itertext()) for si in etree.fromstring(calc.read('xl/sharedStrings.xml'))]
        for entry in src.infolist():
            data=src.read(entry.filename)
            if entry.filename.startswith('xl/worksheets/sheet') and entry.filename.endswith('.xml'):
                x=etree.fromstring(data);y=etree.fromstring(calc.read(entry.filename))
                current={c.get('r'):c for c in y.findall('.//s:sheetData/s:row/s:c',NS)}
                for c in x.findall('.//s:sheetData/s:row/s:c',NS):
                    if c.find('s:f',NS) is None:continue
                    donor=current[c.get('r')]
                    for child in list(c):
                        if child.tag in [TAG+'v',TAG+'is']:c.remove(child)
                    if donor.get('t')=='s':c.set('t','str')
                    elif donor.get('t'):c.set('t',donor.get('t'))
                    else:c.attrib.pop('t',None)
                    for child in donor:
                        if child.tag in [TAG+'v',TAG+'is']:
                            copied=deepcopy(child)
                            if donor.get('t')=='s' and child.tag==TAG+'v':copied.text=shared[int(child.text)]
                            c.append(copied)
                    count+=1
                data=etree.tostring(x)
            out.writestr(entry,data)
    if values(openpyxl.load_workbook(output))!=values(a):raise ValueError('캐시 기록 후 값/수식이 달라졌습니다')
    return count


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--original',required=True,type=Path);p.add_argument('--recalculated',required=True,type=Path)
    p.add_argument('--output',required=True,type=Path)
    a=p.parse_args();print(json.dumps({'formula_caches_copied':cache(a.original,a.recalculated,a.output)}))
