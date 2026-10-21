"""Real target gaps, faithful dates and owner-bound identity derivation."""
import copy,json,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from source_audit import dump
from extract_sources import sha
from fill_coverage import coverage
from normalize_dates import canonical,normalize
from record_checks import education_binding
from cross_fields import identity_sex,apply

def run():
    checks={}
    data={'processing_date':'2026-10-20','people':[{'id':'p','fields':{'meta':{'name':'示例','phone':''},'projects':[{'role':'','resp':'已写职责'},{'role':'','resp':''}]}}]}
    mapping={'tables':[{'index':0,'fields':[{'row':0,'cell':0,'key':'meta.phone'}], 'repeat':[{'key':'projects','fields':[{'keys':['role','resp']}]}]}]}
    r=coverage(data,mapping);assert (r['total_slots'],r['filled_slots'],r['blank_slots'])==(3,1,2)
    checks['combined_target_cell_is_not_counted_empty_for_one_blank_key']=True
    mapping['tables'][0]['repeat'][0]['trailing_rows']=[{'when_nonempty':'role','fields':[{'key':'role'}]}]
    assert coverage(data,mapping)['total_slots']==3
    checks['unrendered_optional_rows_do_not_inflate_blank_slots']=True
    from lxml import etree as E
    from template_docx import fill,q,content
    node=E.Element(q('tc'));E.SubElement(node,q('p'));used=set()
    fill({'keys':['start','end'],'key_labels':{'start':'开始：','end':'结束：'},'separator':'\n'},{'start':'','end':'2024-06'},node,'',used)
    assert content(node)=='结束：2024-06' and used=={'start','end'}
    fill({'keys':['start','end'],'key_labels':{'start':'开始：','end':'结束：'}},{'start':'','end':''},node,'',set());assert content(node)==''
    checks['single_ended_date_keeps_its_semantic_label_and_absent_date_stays_blank']=True
    from template_docx import make_person,ordered_records,NS
    prototype=E.Element(q('body'));table=E.SubElement(prototype,q('tbl'))
    for count in (2,1):
        row=E.SubElement(table,q('tr'))
        for _ in range(count):E.SubElement(E.SubElement(row,q('tc')),q('p'))
    education_table=E.SubElement(prototype,q('tbl'));E.SubElement(E.SubElement(E.SubElement(education_table,q('tr')),q('tc')),q('p'))
    person={'id':'fixture','fields':{'projects':[
        {'name':'旧项目','start':'2020','client':'客户甲','role':'开发','desc':'旧职责'},
        {'name':'新项目','start':'2024-05','client':'客户乙','role':'测试','desc':'新职责'},
        {'name':'未定日期项目','start':'','client':'客户丙','role':'实施','desc':'未定日期职责'}],
        'education':[{'school':'本科院校','level':'本科'},{'school':'硕士院校','level':'硕士研究生'}]}}
    snapshot=copy.deepcopy(person)
    mapping2={'tables':[{'index':0,'omit_rows':[1],'repeat':[{'key':'projects','rows':[0,0],'fields':[{'row':0,'cell':0,'text':'{index}'},{'row':0,'cell':1,'keys':['name','start','client','role'],'separator':'｜'}],
        'trailing_rows':[{'rows':[1,1],'fields':[{'row':0,'cell':0,'key':'desc'}]}]}]},
        {'index':1,'repeat':[{'key':'education','rows':[0,0],'combine_records':True,'fields':[{'row':0,'cell':0,'keys':['school','level'],'separator':'｜'}]}]}]}
    output=make_person(prototype,mapping2,person);rows=output[0].findall(q('tr'))
    assert [tuple(content(c) for c in r.findall(q('tc'))) for r in rows]==[('1','新项目｜2024-05｜客户乙｜测试'),('新职责',),('2','旧项目｜2020｜客户甲｜开发'),('旧职责',),('3','未定日期项目｜客户丙｜实施'),('未定日期职责',)] and person==snapshot
    checks['reverse_chronology_moves_complete_project_and_continuation_without_mutating_source_indexes']=True
    assert len(output[1].findall(q('tr')))==1 and len(output[1].findall('.//w:tc',NS))==1
    assert [content(p) for p in output[1].findall('.//w:p',NS)]==['本科院校｜本科','硕士院校｜硕士研究生']
    assert coverage({'people':[person]},mapping2)['total_slots']==7
    checks['multiple_education_records_keep_separate_paragraphs_in_one_template_cell']=True
    dates=[{'start':'2024'},{'start':'2024-05'},{'start':'2025-01'},{'start':'2024-05'},{'start':''},{'start':'bad'}]
    assert [i for i,_ in ordered_records(dates,{'key':'projects'})]==[2,0,1,3,4,5]
    assert [i for i,_ in ordered_records(dates,{'key':'projects','order':'source'})]==list(range(6))
    checks['ambiguous_precision_ties_and_undated_records_are_stable_and_explicit_source_order_is_supported']=True
    data['people'][0]['blank_reviews']={'meta.phone':{'classification':'source_not_provided'},'projects[1].role':{'classification':'insufficient'},'projects[1].resp':{'classification':'source_not_provided'}}
    r=coverage(data,mapping);assert r['unreviewed_blank_slots']==0 and r['blank_reasons']=={'source_not_provided':1,'insufficient':1}
    checks['fresh_blank_review_preserves_insufficient_evidence_instead_of_claiming_absence']=True
    for before,after in [('2020.3','2020-03'),('2020年3月2日','2020-03-02'),('2020','2020'),('预计2028.06','预计2028-06'),('2020-03-02T00:00:00','2020-03-02'),('present','至今')]:assert canonical(before)==after
    checks['date_normalization_preserves_precision_and_qualifiers']=True
    def reject(fn):
        try:fn()
        except (ValueError,KeyError):return
        raise AssertionError('Invalid evidence was accepted')
    for value in ('2020-02-30','1905-07-07T21:36:00','2020.03-2020.04','202003'):reject(lambda:canonical(value))
    checks['ambiguous_dates_and_nonzero_times_are_not_repaired']=True
    d={'people':[{'id':'p','fields':{'education':[{'school':'示例大学','start':'2016.09','end':'2020.06','status':'completed'}]}}]}
    p=d['people'][0];p['education_status_evidence']={'education[0]':{'record_sha256':education_binding(p['fields']['education'][0])}}
    out,_=normalize(d);assert out['people'][0]['education_status_evidence']['education[0]']['record_sha256']==education_binding(out['people'][0]['fields']['education'][0])
    p['education_status_evidence']['education[0]']['record_sha256']='already-stale';out,_=normalize(d)
    assert out['people'][0]['education_status_evidence']['education[0]']['record_sha256']=='already-stale'
    checks['format_only_changes_rebind_only_previously_current_proofs']=True
    d['coverage_decisions']={'current':{'person_id':'p','field_values':{'education':copy.deepcopy(p['fields']['education'])}},'stale':{'person_id':'p','field_values':{'education':[{'end':'wrong'}]}}}
    out,_=normalize(d);assert out['coverage_decisions']['current']['field_values']['education']==out['people'][0]['fields']['education']
    assert out['coverage_decisions']['stale']['field_values']['education']==[{'end':'wrong'}]
    checks['whole_record_coverage_snapshots_follow_only_format_changes_and_stale_snapshots_stay_stale']=True
    expected=copy.deepcopy(out['people'][0]['fields']['education'])
    d['coverage_decisions']['collision']={'person_id':'p','field_values':{'education':expected}}
    p['education_status_evidence']['education[0]']['record_sha256']=education_binding(expected[0])
    out,_=normalize(d)
    assert out['coverage_decisions']['collision']['stale_before_date_normalization']==['education']
    assert out['people'][0]['education_status_evidence']['education[0]']['stale_before_date_normalization'] is True
    checks['stale_snapshots_and_proofs_cannot_revive_by_coincidental_format_equality']=True
    # Public example from GB11643; no real personnel data in the test package.
    number='11010519491231002X';assert identity_sex(number,'2026-10-20')=='女'
    reject(lambda:identity_sex(number[:-1]+'0','2026-10-20'));reject(lambda:identity_sex('110105********002X','2026-10-20'))
    checks['identity_sequence_requires_complete_number_and_valid_check_digit']=True
    with tempfile.TemporaryDirectory() as td:
        w=Path(td);source=w/'source.txt';source.write_text('公开标准示例 '+number,encoding='utf8');detail=w/'detail.json'
        dump(detail,{'units':[{'unit_id':'id1','kind':'text_line','text':source.read_text(encoding='utf8'),'locator':'line1'}]})
        manifest={'sources':[{'id':'s','source':str(source),'sha256':sha(source),'detail_file':str(detail)}]}
        d={'processing_date':'2026-10-20','people':[{'id':'p','source_ids':['s'],'fields':{'meta':{'name':'公开标准示例','sex':''}}}]}
        c={'person_id':'p','owner_person_id':'p','owner_verified':True,'reviewer':'synthetic fixture','reason':'Public standard example bound to fixture person.',
           'identity_number':number,'source_quotes':[{'source_id':'s','unit_id':'id1','quote':source.read_text(encoding='utf8')}]}
        out,report=apply(d,manifest,[c]);assert out['people'][0]['fields']['meta']['sex']=='女' and number not in json.dumps(report)
        checks['blank_sex_is_filled_with_source_inferred_origin_and_redacted_summary']=True
        wrong=copy.deepcopy(c);wrong['owner_person_id']='other';reject(lambda:apply(d,manifest,[wrong]))
        checks['cross_person_identity_derivation_rejected']=True
        d['people'][0]['fields']['meta']['sex']='男';out,r=apply(d,manifest,[c]);assert out['people'][0]['fields']['meta']['sex']=='男' and len(r['conflicts'])==1
        checks['explicit_sex_is_not_overwritten_on_conflict']=True
        source.write_text('changed',encoding='utf8');reject(lambda:apply(d,manifest,[c]))
        checks['changed_identity_source_is_rejected']=True
    with tempfile.TemporaryDirectory() as td:
        from field_facts import classify
        w=Path(td);source=w/'source.txt';detail=w/'detail.json';source.write_text('岗位起点未明',encoding='utf8')
        dump(detail,{'units':[{'unit_id':'u','kind':'text_line','text':'岗位起点未明'}]})
        m={'sources':[{'id':'s','source':str(source),'sha256':sha(source),'detail_file':str(detail)}]}
        d={'processing_date':'2026-10-20','people':[{'id':'p','source_ids':['s'],'fields':{'meta':{'role_years':''}}}]}
        decision={'p:meta.role_years':{'origin':'needs_review','reviewed_value':'','reason':'Same role start is unknown; employment start is not substituted.','reviewer':'fixture'}}
        first,_=classify(d,m,decision);second,r=classify(first,m)
        assert second['people'][0]['field_facts']['meta.role_years']==first['people'][0]['field_facts']['meta.role_years'] and r['status']=='needs_review'
        changed=copy.deepcopy(first);changed['people'][0]['fields']['meta']['role_years']='3年'
        third,_=classify(changed,m);assert third['people'][0]['field_facts']['meta.role_years'].get('reviewer')!='fixture'
        checks['reviewed_unresolved_blank_keeps_specific_reason_without_closing_or_reusing_changed_value']=True
    with tempfile.TemporaryDirectory() as td:
        from record_checks import completion
        w=Path(td);source=w/'source.txt';detail=w/'detail.json'
        for text,eligible in [('曾获优秀学生干部、优秀毕业生',True),('获得优秀毕业生称号',True),('荣获优秀毕业生提名',False),('并非被评为优秀毕业生',False),('优秀毕业生候选人',False),('未曾获优秀毕业生',False)]:
            source.write_text('示例大学 本科\n'+text,encoding='utf8')
            units=[{'unit_id':'school','kind':'text_line','text':'示例大学 本科'},{'unit_id':'honor','kind':'text_line','text':text}];dump(detail,{'units':units})
            m={'sources':[{'id':'s','source':str(source),'sha256':sha(source),'detail_file':str(detail)}]}
            p={'id':'p','source_ids':['s'],'fields':{'education':[{'school':'示例大学','level':'本科','start':'2014-09','end':'2018-06','status':'completed','degree':''}]},'record_sources':{'education[0]':{'source_id':'s','unit_ids':['school','honor']}}}
            p['education_status_evidence']={'education[0]':{'record_sha256':education_binding(p['fields']['education'][0]),'basis':'explicit_source','source_quotes':[{'source_id':'s','unit_id':u['unit_id'],'quote':u['text']} for u in units]}}
            assert completion(p,0,m)['eligible']==eligible,text
            p['record_sources']={};assert not completion(p,0,m)['eligible']
        checks['graduation_honor_requires_affirmative_award_and_same_reviewed_education_scope']=True
        from apply_policies import apply as policies
        from source_audit import audit
        for text,allowed in [('为示例电信建设业务平台',True),('供应商：示例电信提供技术',False)]:
            units=[{'unit_id':'school','kind':'text_line','text':'示例大学 本科'},{'unit_id':'honor','kind':'text_line','text':'曾获优秀毕业生'},{'unit_id':'project','kind':'text_line','text':'项目甲'},{'unit_id':'tech','kind':'text_line','text':text}]
            source.write_text('\n'.join(u['text'] for u in units),encoding='utf8');dump(detail,{'units':units})
            m={'sources':[{'id':'s','source':str(source),'sha256':sha(source),'detail_file':str(detail)}]}
            p={'id':'p','source_ids':['s'],'fields':{'meta':{'name':'示例人员'},'education':[],'projects':[{'name':'项目甲','tech':text,'client':''}]},'record_sources':{'projects[0]':{'source_id':'s','unit_ids':['project','tech'],'anchor_unit_id':'project'},'education[0]':{'source_id':'s','unit_ids':['school','honor']}}}
            p['fields']['education']=[{'school':'示例大学','level':'本科','start':'2014','end':'2018','status':'completed','degree':''}]
            p['education_status_evidence']={'education[0]':{'record_sha256':education_binding(p['fields']['education'][0]),'basis':'explicit_source','source_quotes':[{'source_id':'s','unit_id':u['unit_id'],'quote':u['text']} for u in units[:2]]}}
            c={'person_id':'p','index':0,'client':'示例电信','quote':text,'source_id':'s','unit_id':'tech','role_review':{'role':'client','reviewer':'fixture','reason':'same project service recipient','reviewed_quote':text}}
            out,_,_=policies({'processing_date':'2026-10-20','people':[p]},[c],m)
            assert bool(out['people'][0]['fields']['projects'][0]['client'])==allowed
            audit(out,m) # Education scope must not be treated as another project anchor.
        checks['same_project_technical_description_can_identify_client_but_vendor_stays_rejected']=True
        checks['education_and_project_scopes_coexist_in_source_audit']=True
    print(json.dumps({'status':'passed','checks':checks}))

if __name__=='__main__':run()
