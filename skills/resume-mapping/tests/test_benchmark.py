"""Source-bound scoring must expose omissions, spurious projects and stale inputs."""
import json,sys,tempfile,copy
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from evaluate_benchmark import evaluate
from source_audit import dump
from extract_sources import sha

def run():
    checks={}
    with tempfile.TemporaryDirectory() as td:
        root=Path(td);source=root/'source.txt';source.write_text('示例：已核对原文',encoding='utf8')
        path=root/'prediction.json';data={'people':[{'fields':{'meta':{'name':'示例','title':'开发'},'skills':'熟悉数据库，能够优化查询','projects':[{'name':'甲项目'},{'name':'多余项目'}]}}]};dump(path,data)
        gold={'cases':[{'id':'g','source':str(source),'source_sha256':sha(source),'person_name':'示例','project_names':['甲项目','乙项目'],
          'fields':[{'path':'meta.role','accepted_values':['开发'],'category':'basic','locator':'line1'},
                    {'path':'skills','accepted_values':['优化查询'],'category':'skill','locator':'line1'},
                    {'path':'meta.email','accepted_values':['test@example.com'],'category':'basic','locator':'line1'}]}]}
        prediction={'g':{'data':str(path),'data_sha256':sha(path)}}
        report=evaluate(gold,prediction,{'g':{'meta.role':'meta.title'}})
        assert report['matched_fields']==2 and report['labelled_fields']==3 and report['differences'][0]['missing_path']
        checks['unseen_field_omission_is_scored_as_difference']=True
        assert report['project_boundaries'][0]['false_positive']==1 and report['project_boundaries'][0]['false_negative']==1
        checks['spurious_and_missing_projects_remain_separate']=True
        assert report['status']=='differences' and not report['project_boundaries'][0]['order_matches']
        checks['partial_field_match_cannot_pass_whole_case']=True
        def reject(fn):
            try:fn()
            except ValueError:return
            raise AssertionError('Changed evidence was accepted')
        source.write_text('changed source',encoding='utf8');reject(lambda:evaluate(gold,prediction))
        checks['changed_original_rejected']=True
        gold['cases'][0]['source_sha256']=sha(source);data['people'][0]['fields']['meta']['title']='调整后';dump(path,data)
        reject(lambda:evaluate(gold,prediction))
        checks['changed_sealed_prediction_rejected']=True
    print(json.dumps({'status':'passed','checks':checks}))

if __name__=='__main__':run()
