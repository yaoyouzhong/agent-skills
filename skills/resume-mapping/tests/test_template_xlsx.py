import copy,json,sys,tempfile
from pathlib import Path
from zipfile import ZipFile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from source_audit import dump,audit
from extract_sources import sha
from template_xlsx import make_plan,patch_print,NS
from check_rendered import check
from lxml import etree as E

def run():
    checks={}
    with tempfile.TemporaryDirectory() as td:
        w=Path(td);src=w/'source.txt';src.write_text('示例\n甲项目\n乙项目',encoding='utf8')
        detail=w/'detail.json';dump(detail,{'units':[{'unit_id':str(i),'text':s,'kind':'text_line','locator':str(i)} for i,s in enumerate(src.read_text(encoding='utf8').splitlines())]})
        m={'sources':[{'id':'s','source':str(src),'sha256':sha(src),'detail_file':str(detail),'status':'ok'}]}
        data={'processing_date':'2026-10-20','people':[{'id':'p','source_ids':['s'],'fields':{'meta':{'name':'示例'},'projects':[{'name':'甲项目'},{'name':'乙项目'}]},
           'record_sources':{f'projects[{i}]':{'source_id':'s','anchor_unit_id':str(i+1),'unit_ids':[str(i+1)]} for i in range(2)}}]}
        mapping={'sheet':'简历','fields':[{'cell':'C11','key':'meta.name'}],'clear_ranges':['B1:H{last}'],'print_area':'B10:H{last}',
          'repeat':[{'key':'projects','start_row':33,'height':7,'template_range':'B33:H39','fields':[{'row':0,'column':'C','key':'name'}]}]}
        template=w/'fixture.xlsx'
        with ZipFile(template,'w') as z:
            z.writestr('xl/workbook.xml',f'<workbook xmlns="{NS}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="简历" sheetId="1" r:id="r1"/></sheets></workbook>')
            z.writestr('xl/_rels/workbook.xml.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="r1" Target="worksheets/custom.xml"/></Relationships>')
            z.writestr('xl/worksheets/custom.xml',f'<worksheet xmlns="{NS}"><sheetData/></worksheet>')
            z.writestr('keep.bin',b'untouched')
        report=audit(data,m);p=make_plan(template,data,mapping,m,report,w/'out.xlsx')
        assert [c['cell'] for c in p['cells']]==['C11','C33','C40'] and p['last_row']==46
        checks['dynamic_projects_expand_beyond_one_prototype']=True
        assert p['printArea']=='B10:H46' and p['template_sha256']==sha(template)
        checks['print_extent_and_original_template_are_bound']=True
        def reject(fn):
            try:fn()
            except ValueError:return
            raise AssertionError('Invalid Excel plan accepted')
        bad=copy.deepcopy(data);bad['people'][0]['fields']['skills']='必须保留的技能'
        reject(lambda:make_plan(template,bad,mapping,m,audit(bad,m),w/'missing.xlsx'))
        checks['unmapped_nonempty_business_field_rejected']=True
        badmap=copy.deepcopy(mapping);badmap['fields'].append({'cell':'C11','key':'meta.name'})
        reject(lambda:make_plan(template,data,badmap,m,report,w/'collision.xlsx'))
        checks['overlapping_cell_writes_rejected']=True
        patch_print(template,'简历','B10:H46',[40])
        with ZipFile(template) as z:
            root=E.fromstring(z.read('xl/workbook.xml'));ws=E.fromstring(z.read('xl/worksheets/custom.xml'))
            assert root.find('{'+NS+'}definedNames')[0].text=="'简历'!B10:H46"
            assert ws.find('{'+NS+'}pageSetup').get('fitToHeight')=='0' and z.read('keep.bin')==b'untouched'
        checks['native_print_metadata_uses_real_sheet_relationship']=True
        checks['unrelated_parts_unchanged_by_print_patch']=True
        single={'person_boundary':{'mode':'single_person'}}
        assert check(data,single,{'pages':[{'page':1,'text':'示例 甲项目 乙项目'}]})['status']=='passed'
        assert check(data,single,{'pages':[{'page':1,'text':'示例 甲项目'}]})['status']=='failed'
        checks['single_person_content_check_still_detects_missing_project']=True
        bad=copy.deepcopy(data);bad['people'].append(copy.deepcopy(bad['people'][0]))
        reject(lambda:check(bad,single,{'pages':[{'page':1,'text':'示例 甲项目 乙项目'}]}))
        checks['single_person_mode_cannot_hide_multiple_people']=True
        narrow=copy.deepcopy(mapping)
        narrow['repeat'][0].update(template_range='A33:D39')
        plan=make_plan(template,data,narrow,m,report,w/'narrow.xlsx')
        assert [c['to'] for c in plan['copies']]==['A33:D39','A40:D46']
        checks['dynamic_copy_uses_current_template_columns']=True
        narrow['append_unmapped']={'template_range':'A5:D5','labels':{'skills':'专业技能'}}
        extra=copy.deepcopy(data);extra['people'][0]['fields']['skills']='已核对专业技能'
        plan=make_plan(template,extra,narrow,m,audit(extra,m),w/'extra.xlsx')
        assert plan['copies'][-1]['to'].startswith('A') and plan['merges'][-1].startswith('B') and plan['merges'][-1].endswith('48')
        checks['additional_fields_use_current_template_columns']=True
        wrong=copy.deepcopy(mapping);wrong['repeat'][0]['height']=6
        reject(lambda:make_plan(template,data,wrong,m,report,w/'wrong.xlsx'))
        checks['prototype_height_mismatch_rejected']=True
        dated=copy.deepcopy(data);dated['people'][0]['fields']['projects'][0]['start']='2020';dated['people'][0]['fields']['projects'][1]['start']='2024-05'
        date_map=copy.deepcopy(mapping);date_map['repeat'][0]['fields'] += [{'row':1,'column':'C','key':'start'},{'row':0,'column':'B','text':'{index}'}]
        dated_plan=make_plan(template,dated,date_map,m,audit(dated,m),w/'dated.xlsx');values={c['cell']:c['value'] for c in dated_plan['cells']}
        assert values['C33']=='乙项目' and values['C34']=='2024-05' and values['B33']=='1' and values['C40']=='甲项目' and values['B40']=='2'
        assert 'projects[0].start' in dated_plan['fields_written'] and dated['people'][0]['fields']['projects'][0]['name']=='甲项目'
        checks['excel_project_order_and_numbers_follow_dates_while_source_indexes_stay_unchanged']=True
    print(json.dumps({'status':'passed','checks':checks}))

if __name__=='__main__':run()
