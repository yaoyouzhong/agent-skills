import copy,json,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from source_audit import dump,validate_unit_owner
from extract_sources import sha
from semantic_checks import check_identity,client_role,credentials
from check_rendered import check

def run():
    checks={}
    cases=[('甲银行','客户：甲银行；实施方：乙公司；产品厂商：丙公司','explicit_client'),
           ('乙公司','客户：甲银行；实施方：乙公司；产品厂商：丙公司','rejected_non_client'),
           ('丙公司','客户：甲银行；实施方：乙公司；产品厂商：丙公司','rejected_non_client'),
           ('甲银行','为甲银行开发核心系统，由乙公司负责实施。','explicit_client'),
           ('乙公司','为甲银行开发核心系统，由乙公司负责实施。','rejected_non_client'),
           ('甲公司','甲公司和乙公司参与项目','needs_role_review')]
    for i,(client,text,expected) in enumerate(cases):
        assert client_role(client,text)==expected;checks['entity_role_case_'+str(i+1)]=True
    assert client_role('甲公司','甲公司项目',{'role':'client','reviewer':'fixture','reason':'Reviewed context','reviewed_quote':'甲公司项目'})=='reviewed_contextual_client'
    checks['contextual_client_requires_explicit_review']=True
    with tempfile.TemporaryDirectory() as td:
        w=Path(td);src=w/'source.txt';src.write_text('PMP 2023-09-01 2025-08-28',encoding='utf8')
        img=w/'asset.bin';img.write_bytes(b'synthetic pixel-binding test')
        u={'unit_id':'u','text':src.read_text(),'kind':'reviewed_media_text','owner_name':'同名','review_status':'visually_reviewed',
           'reviewer':'fixture','asset_path':str(img),'asset_sha256':sha(img)}
        detail=w/'detail.json';dump(detail,{'units':[u]})
        m={'sources':[{'id':'s','source':str(src),'sha256':sha(src),'detail_file':str(detail)}]}
        q={'source_id':'s','unit_id':'u','quote':u['text']}
        p={'id':'p1','source_ids':['s'],'fields':{'meta':{'name':'同名','birth':'1990'}},'evidence':[{'field':'meta.name','source_quotes':[q]}]}
        p2={'id':'p2','source_ids':['s'],'fields':{'meta':{'name':'同名','birth':'1991'}},'evidence':[]}
        def reject(fn):
            try:fn()
            except ValueError:return
            raise AssertionError('Invalid evidence accepted')
        reject(lambda:check_identity({'people':[p,p2]},m));checks['same_name_image_needs_person_id']=True
        u['owner_person_id']='p1';u['identity_checks']=[{'field':'meta.birth','value':'1990'}];dump(detail,{'units':[u]})
        check_identity({'people':[p,p2]},m);checks['stable_id_and_existing_second_identifier_accepted']=True
        reject(lambda:validate_unit_owner(p2,u));checks['same_name_wrong_id_rejected']=True
        bad=copy.deepcopy(p);bad['fields']['meta']['birth']='1992'
        reject(lambda:validate_unit_owner(bad,u));checks['conflicting_second_identifier_rejected']=True
        p['credentials']=[{'id':'old','name':'PMP','issued':'2023-09-01','valid_until':'2025-08-28','used_as_current':True,'source_quotes':[q]}]
        records,issues=credentials(p,m,'2026-10-20');assert issues and records[0]['status']=='expired_attachment'
        checks['expired_attachment_cannot_prove_current_qualification']=True
        p['credentials'][0]['used_as_current']=False
        assert not credentials(p,m,'2026-10-20')[1];checks['historical_certificate_does_not_block_resume']=True
        p['credentials'][0]['valid_until']='2099-01-01'
        reject(lambda:credentials(p,m,'2026-10-20'));checks['invented_expiry_date_rejected']=True
    data={'people':[{'id':'1','fields':{'meta':{'name':'同名','birth':'1990'}}},{'id':'2','fields':{'meta':{'name':'同名','birth':'1991'}}}]}
    mapping={'person_boundary':{'mode':'ordered_name_occurrences','order':['1','2']}}
    render={'pages':[{'page':1,'text':'姓名：同名 出生：1990'},{'page':2,'text':'姓名：同名 出生：1991'}]}
    assert check(data,mapping,render)['status']=='passed';checks['same_name_render_uses_explicit_person_order']=True
    render['pages'][0]['text']='姓名：同名 出生：1991'
    assert check(data,mapping,render)['status']=='failed';checks['same_name_swapped_fields_are_detected']=True
    print(json.dumps({'status':'passed','checks':checks}))

if __name__=='__main__':run()
