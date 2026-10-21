"""Graduation proof, real calendar dates, chronology and stale-evidence negatives."""
import copy
import json
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from record_checks import completion, date_interval, education_binding, validate
from apply_policies import apply
from source_audit import dump, units_for
from extract_sources import sha


def run():
    checks = {}
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); src = root / 'source.txt'
        src.write_text('示例大学 已毕业\n另一学校 在读\n', encoding='utf8'); dump(root/'detail.json', {})
        m = {'sources': [{'id':'s','source':str(src),'sha256':sha(src),'text_file':str(src),'detail_file':str(root/'detail.json')}]}
        u = units_for(m['sources'][0])[0]
        q = {'source_id':'s','unit_id':u['unit_id'],'quote':u['text']}
        p = {'id':'p','source_ids':['s'],'fields':{'education':[{'school':'示例大学','level':'本科','end':'2020','status':'completed','degree':''}]}}
        data = {'processing_date':'2026-10-20','people':[p]}
        assert not completion(p,0,m)['eligible']
        assert apply(data,manifest=m)[0]['people'][0]['fields']['meta']['level'] == ''
        checks['past_date_does_not_prove_graduation'] = True
        p['education_status_evidence']={'education[0]':{'basis':'explicit_source','record_sha256':education_binding(p['fields']['education'][0]),'source_quotes':[q]}}
        out = apply(data,manifest=m)[0]
        assert out['people'][0]['fields']['meta']['degree']=='学士'
        checks['explicit_record_graduation_allows_default'] = True
        changed = copy.deepcopy(out); changed['people'][0]['fields']['education'][0]['school']='另一学校'
        out2 = apply(changed,manifest=m)[0]
        assert out2['people'][0]['fields']['meta']['degree']=='' and out2['people'][0]['fields']['education'][0]['degree']==''
        checks['stale_proof_withdraws_default'] = True
        changed = copy.deepcopy(data); changed['people'][0]['fields']['education'][0]['end']='2028'
        changed['people'][0]['education_status_evidence']['education[0]']['record_sha256']=education_binding(changed['people'][0]['fields']['education'][0])
        assert not apply(changed,manifest=m)[0]['people'][0]['fields']['meta']['degree']
        checks['future_graduation_excluded'] = True
        for value in ('2025-02-29','2024-13','2020-04-31','1905-07-07T21:36:00','2020-00','2020-01-00'):
            try: date_interval(value)
            except ValueError: pass
            else: raise AssertionError(value)
        assert date_interval('2024-02-29')[0].day == 29
        assert date_interval('2020')[0].isoformat()=='2020-01-01'
        assert date_interval('2020')[1].isoformat()=='2020-12-31'
        checks['real_calendar_and_partial_precision'] = True
        bad = copy.deepcopy(data)
        bad['people'][0]['fields']['jobs']=[{'start':'1905-07-07T21:36:00','end':'2020'}]
        bad['people'][0]['fields']['projects']=[{'start':'2027-02-14','end':'2027-08-31'},{'start':'2016-09-10','end':'2016-05-01'}]
        codes={i['code'] for i in validate(bad,m)['issues']}
        assert {'invalid_date','future_record','end_before_start'} <= codes
        checks['all_record_date_preflight'] = True
        changed=copy.deepcopy(out);changed['people'][0]['fields']['meta']['level']='博士'
        assert any(i['code']=='summary_source_mismatch' for i in validate(changed,m)['issues'])
        checks['manual_summary_cannot_bypass_education_policy']=True
        tied={'processing_date':'2026-10-20','people':[{'id':'t','fields':{'education':[{'school':'A','level':'本科','end':'2020','status':'completed'},
              {'school':'B','level':'硕士研究生','end':'2020-06','status':'completed'}]}}]}
        tp=tied['people'][0];tp['education_status_evidence']={f'education[{i}]':{'basis':'user_confirmation','record_sha256':education_binding(e),
           'reviewer':'synthetic_fixture','reason':'Synthetic completed records with overlapping date precision.','confirmation_reference':'fixture'} for i,e in enumerate(tp['fields']['education'])}
        tied_out=apply(tied)[0];assert not tied_out['people'][0]['fields']['meta']['level']
        assert any(i['code']=='graduation_selection_ambiguous' for i in validate(tied_out)['issues'])
        checks['overlapping_graduation_precision_remains_ambiguous']=True
        # Explicitly awarded source degree must belong to the SAME education row.
        detail={'units':[{'unit_id':'s1','kind':'excel_cell','sheet':'简历','cell':'C4','text':'示例大学'},
                         {'unit_id':'d1','kind':'excel_cell','sheet':'简历','cell':'F4','text':'学士'},
                         {'unit_id':'d2','kind':'excel_cell','sheet':'简历','cell':'F5','text':'学士'}]}
        dump(root/'detail.json',detail); p=copy.deepcopy(data['people'][0]);p.pop('education_status_evidence')
        p['fields']['education'][0]['degree']='学士'
        p['evidence']=[{'field':'education[0].school','source_quotes':[{'source_id':'s','unit_id':'s1','quote':'示例大学'}]},
                       {'field':'education[0].degree','source_quotes':[{'source_id':'s','unit_id':'d1','quote':'学士'}]}]
        assert completion(p,0,m)['eligible']
        p['evidence'][1]['source_quotes'][0]['unit_id']='d2';assert not completion(p,0,m)['eligible']
        p['evidence'][1]['source_quotes'][0]['unit_id']='d1';p['field_facts']={'education[0].degree':{'origin':'user_default'}}
        assert not completion(p,0,m)['eligible']
        checks['same_row_awarded_degree_and_no_default_circularity'] = True
        p.pop('field_facts');detail['units'][0].update(kind='cell_line',page=1,table=0,row=2,cell=0)
        detail['units'][1].update(kind='cell_line',page=1,table=0,row=2,cell=3)
        dump(root/'detail.json',detail);assert completion(p,0,m)['eligible']
        detail['units'][1]['row']=3;dump(root/'detail.json',detail);assert not completion(p,0,m)['eligible']
        checks['pdf_awarded_degree_requires_same_page_table_row']=True
        # Graduation labels bind to their own value, never a different date in a row.
        def graduation_fixture(values,end='2018',omit=()):
            units=[{'unit_id':f'g{i}','kind':'excel_cell','sheet':'教育','cell':chr(65+i)+'2','text':v} for i,v in enumerate(values) if v]
            dump(root/'detail.json',{'units':units})
            person={'id':'g','source_ids':['s'],'fields':{'education':[{'school':values[0],'level':'本科','end':end,'status':'completed','degree':''}]}}
            person['education_status_evidence']={'education[0]':{'basis':'source_declared_graduation_date',
                'record_sha256':education_binding(person['fields']['education'][0]),
                'source_quotes':[{'source_id':'s','unit_id':u['unit_id'],'quote':u['text']} for u in units if u['unit_id'] not in omit]}}
            return person
        gp=graduation_fixture(['示例大学','毕业时间','2018'])
        assert completion(gp,0,m)['eligible']
        checks['explicit_graduation_label_uses_its_adjacent_value']=True
        gp=graduation_fixture(['示例大学','结束时间','2018','毕业时间',''])
        assert not completion(gp,0,m)['eligible']
        assert not apply({'processing_date':'2026-10-20','people':[gp]},manifest=m)[0]['people'][0]['fields']['meta']['degree']
        checks['blank_graduation_value_cannot_borrow_end_date_or_default_degree']=True
        for omit in ((),('g3',)):
            gp=graduation_fixture(['示例大学','毕业时间','2018','预计毕业'],omit=omit)
            assert not completion(gp,0,m)['eligible']
        checks['unfinished_source_row_blocks_even_when_conflict_quote_omitted']=True
        gp=graduation_fixture(['示例大学','毕业时间','2028'],end='2028')
        assert not apply({'processing_date':'2026-10-20','people':[gp]},manifest=m)[0]['people'][0]['fields']['meta']['degree']
        checks['explicit_graduation_label_still_checks_future_date']=True
    print(json.dumps({'status':'passed','checks':checks},ensure_ascii=False))


if __name__=='__main__':run()
