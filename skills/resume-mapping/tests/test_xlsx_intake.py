"""Regression for real XLSX reader failure classes using synthetic package data only."""
from pathlib import Path
import argparse,sys,json
from zipfile import ZipFile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from extract_sources import read_xlsx,sha
from source_audit import dump,units_for
from record_evidence import locate


def run(root):
 root.mkdir(exist_ok=False,parents=True);p=root/'synthetic.xlsx';ns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
 with ZipFile(p,'x') as z:
  z.writestr('[Content_Types].xml','<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>')
  z.writestr('_rels/.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
  z.writestr('xl/workbook.xml',f'<workbook xmlns="{ns}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="履历" sheetId="1" r:id="rId1"/></sheets></workbook>')
  z.writestr('xl/_rels/workbook.xml.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
  z.writestr('xl/worksheets/sheet1.xml',f'<worksheet xmlns="{ns}"><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>测试人员</t></is></c></row><row r="2"><c r="A2" s="1"><v>19960201</v></c></row><row r="3"><c r="A3"><f>_xlfn.DISPIMG("sample-id",1)</f><v/></c></row></sheetData><dataValidations count="1"><dataValidation type="any" sqref="A1"/></dataValidations></worksheet>')
  z.writestr('xl/styles.xml',f'<styleSheet xmlns="{ns}"><fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts><fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="14" fontId="0" fillId="0" borderId="0" xfId="0"/></cellXfs></styleSheet>')
  z.writestr('xl/media/unrendered-image.bin',b'synthetic media marker; not a real certificate')
 before=sha(p);d,text,warnings=read_xlsx(p);assert sha(p)==before
 assert d['package_review']['validation_repairs'];assert d['sheets'][0]['cells'][1]['raw_value']=='19960201';kinds={w['kind'] for w in warnings}
 assert {'invalid_validation_reader_copy','package_media_require_visual_review','formula_cache_missing','cell_error'}<=kinds
 actual=root/'reader-detail.json';dump(actual,d);source={'id':'s','source':str(p),'sha256':before,'detail_file':str(actual)}
 observed=units_for(source);raw_units=[u for u in observed if u['kind']=='excel_raw_cell']
 assert len(raw_units)==1 and raw_units[0]['text']=='19960201' and raw_units[0]['reader_value']=='#VALUE!'
 assert next(u for u in observed if u.get('cell')=='A2' and u['kind']=='excel_cell')['text']=='#VALUE!'
 assert units_for(source)==observed
 # A true error value must remain an error, even if its payload looks numeric.
 fake=root/'true-error.json';dump(fake,{'sheets':[{'sheet':'履历','state':'visible','cells':[{'cell':'A1','value':'#VALUE!','type':'e','raw_type':'e','raw_value':'19960201'}]}]})
 assert not any(u['kind']=='excel_raw_cell' for u in units_for({'detail_file':str(fake)}))
 # The last project must stop before proof sections and another worksheet.
 detail=root/'regions.json';dump(detail,{'sheets':[{'sheet':'履历','state':'visible','cells':[{'cell':'A1','value':'项目甲'},{'cell':'A2','value':'负责真实业务接口'},{'cell':'A3','value':'相关证明'}]},{'sheet':'字典','state':'visible','cells':[{'cell':'A1','value':'Python只是选项'}]}]})
 manifest={'sources':[{'id':'s','source':str(p),'sha256':sha(p),'detail_file':str(detail)}]};data={'people':[{'id':'x','source_ids':['s'],'fields':{'projects':[{'name':'项目甲','resp':'负责真实业务接口'}]}}]}
 located,report=locate(data,manifest);scope=located['people'][0]['record_sources']['projects[0]']['unit_ids'];u=units_for(manifest['sources'][0]);assert [x['text'] for x in u if x['unit_id'] in scope]==['项目甲','负责真实业务接口']
 dump(root/'results.json',{'status':'passed','original_unchanged':True,'invalid_validation_read_copy':True,'raw_bad_date_preserved':True,'wps_media_and_formula_warning':True,'excel_scope_stops_at_proof_and_sheet':True,'raw_numeric_reader_error_has_stable_separate_evidence':True,'reader_error_and_warning_not_silently_replaced':True,'true_excel_error_not_reinterpreted':True});print((root/'results.json').read_text('utf8'))

if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--workdir',type=Path,required=True);run(p.parse_args().workdir)
