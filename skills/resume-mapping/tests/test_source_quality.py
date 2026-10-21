import copy,json,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from source_quality import source_pending,required_warnings
from source_audit import dump
from review_queue import person_gates

def run():
    checks={}
    with tempfile.TemporaryDirectory() as td:
        detail=Path(td)/'detail.json';dump(detail,{'sheets':[{'sheet':'简历','cells':[{'cell':'B2','formula':'=_xlfn.DISPIMG("id",1)'}]}]})
        s={'id':'s','status':'needs_review','sha256':'source','detail_sha256':'detail','detail_file':str(detail),
           'warnings':[{'kind':'package_media_require_visual_review'}]}
        d={'people':[{'id':'p','source_ids':['s'],'fields':{'meta':{'name':'测试'}}}],
           'source_reviews':{'s':{'status':'pending'}}}
        assert not source_pending(d,s)
        checks['photos_do_not_require_ocr_or_block_complete_text']=True
        clean={'status':'passed','issues':[]}
        assert person_gates(d,clean,clean,clean,clean,True,{'sources':[s]})[0]['status']=='closed'
        checks['per_person_gate_uses_same_optional_media_policy']=True
        facts={'status':'needs_review','issues':[{'person_id':'p','field':'education[0].status'}]}
        assert person_gates(d,clean,facts,clean,clean,True,{'sources':[s]})[0]['status']=='candidate'
        checks['missing_graduation_fact_still_blocks']=True
        x=copy.deepcopy(s);x['warnings'].append({'kind':'formula_cache_missing','sheet':'简历','cell':'B2'})
        assert not source_pending(d,x)
        checks['dispimg_attachment_formula_is_optional']=True
        x['warnings'].append({'kind':'formula_cache_missing','sheet':'简历','cell':'B3'})
        assert source_pending(d,x)
        checks['business_formula_failure_still_blocks']=True
        assert source_pending({**d,'media_policy':'review_all'},s)
        checks['explicit_full_attachment_review_is_respected']=True
    print(json.dumps({'status':'passed','checks':checks}))

if __name__=='__main__':run()
