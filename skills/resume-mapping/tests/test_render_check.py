"""Regression checks for dates next to names and genuine split table cells."""
import argparse
import copy
import sys
from zipfile import ZipFile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from source_audit import norm,dump
from check_rendered import check
from extract_sources import read_xlsx,sha


def run(root):
    root.mkdir(exist_ok=False,parents=True)
    assert norm('2023-05-31 日照银行')=='20230531日照银行'
    assert norm('2014-04-01 日本三菱项目')=='20140401日本三菱项目'
    assert norm('2020年1月2日')==norm('2020/01/02')
    assert norm('2020年1月')==norm('2020-01')!=norm('2020-01-01')
    company='测试气体化工装备有限公司'
    data={'people':[{'id':'p1','fields':{'meta':{'name':'测试甲'},'jobs':[{'company':company,'role':'工程师'}],'projects':[]}}]}
    render={'pages':[{'page':1,'text':'姓名：测试甲\n工作经历\n测试气体化工装备 工程师'},{'page':2,'text':'有限公司\n专业技能'}]}
    result=check(data,{},render)
    assert result['status']=='passed' and len(result['page_continuations'])==1
    missing=copy.deepcopy(render);missing['pages'][1]['text']='专业技能'
    assert check(data,{},missing)['status']=='failed'
    gap=copy.deepcopy(render);gap['pages'][0]['text']+='随意插入文本'
    assert check(data,{},gap)['status']=='failed'
    other=copy.deepcopy(render);other['pages'][1]['text']='姓名：测试乙\n有限公司'
    data2=copy.deepcopy(data);data2['people'].append({'id':'p2','fields':{'meta':{'name':'测试乙'},'projects':[]}})
    assert check(data2,{},other)['status']=='failed'
    from openpyxl import Workbook
    book=Workbook();book.active['A1']=12345678901;path=root/'numeric-contact.xlsx';book.save(path)
    with ZipFile(path) as z:parts={n:z.read(n) for n in z.namelist()}
    parts['xl/worksheets/sheet1.xml']=parts['xl/worksheets/sheet1.xml'].replace(b'12345678901',b'1.2345678901E10')
    with ZipFile(path,'w') as z:
        for n,v in parts.items():z.writestr(n,v)
    before=sha(path);detail,_,_=read_xlsx(path);cell=detail['sheets'][0]['cells'][0]
    assert cell['display_value']=='12345678901' and cell['raw_value']=='1.2345678901E10' and before==sha(path)
    dump(root/'results.json',{'status':'passed','checks':{'adjacent_chinese_day_word_preserved':True,'equivalent_dates_preserve_precision':True,'exact_adjacent_page_cell_continuation':True,'missing_suffix_rejected':True,'unrelated_gap_rejected':True,'other_person_suffix_rejected':True,'general_numeric_contact_without_float_suffix':True}})


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--workdir',type=Path,required=True);run(p.parse_args().workdir)
