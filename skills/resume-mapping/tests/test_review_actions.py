"""Review decisions change facts, never just the displayed queue status."""
import copy
import json
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from source_audit import dump, units_for, audit
from extract_sources import sha
from field_facts import classify
from record_checks import validate
from review_queue import export
from review_actions import import_decisions,read_decisions


def run():
    checks = {}
    with tempfile.TemporaryDirectory() as td:
        root = Path(td); src = root/'source.txt'; src.write_text('示例甲', encoding='utf8')
        detail = root/'detail.json'; dump(detail, {'units':[{'unit_id':'u1','kind':'text_line','text':'示例甲','locator':'line 1'}]})
        m = {'sources':[{'id':'s','source':str(src),'sha256':sha(src),'detail_file':str(detail)}]}
        data = {'processing_date':'2026-10-20','people':[{'id':'p','source_ids':['s'],'fields':{'meta':{'name':'示例甲','phone':''}},
                'evidence':[{'field':'meta.name','source_quotes':[{'source_id':'s','unit_id':'u1','quote':'示例甲'}]}]}]}
        data, f = classify(data,m)
        q = export(data,m,{'facts':f,'records':validate(data,m),'audit':audit(data,m)},root/'queue')
        row = next(r for r in q['rows'] if r['field']=='meta.phone')
        decision = {'id':row['id'],'action':'correct_field','expected_value':'','value':'','origin':'not_provided',
                    'reviewer':'synthetic-test','reason':'Fixture source contains only a name; no phone supplied.'}
        updated, report = import_decisions(data,m,q,[decision],root/'applied')
        assert report['status']=='passed' and updated['people'][0]['field_facts']['meta.phone']['origin']=='not_provided'
        checks['blank_review_updates_facts_and_closes_recomputed_issue'] = True
        def reject(fn):
            try: fn()
            except (ValueError,KeyError): return
            raise AssertionError('Invalid decision accepted')
        stale=copy.deepcopy(data);stale['people'][0]['fields']['meta']['name']='已变化'
        reject(lambda:import_decisions(stale,m,q,[decision],root/'stale'))
        checks['stale_data_rejected']=True
        bad={**decision,'expected_value':'different'}
        reject(lambda:import_decisions(data,m,q,[bad],root/'value'))
        checks['changed_reviewed_value_rejected']=True
        reject(lambda:import_decisions(data,m,q,[decision,decision],root/'duplicate'))
        checks['duplicate_decision_rejected']=True
        bad={**decision,'value':'123','origin':'source_direct','source_quotes':[{'source_id':'s','unit_id':'u1','quote':'invented'}]}
        reject(lambda:import_decisions(data,m,q,[bad],root/'fake'))
        checks['fabricated_evidence_rejected']=True
        _, report=import_decisions(data,m,q,[{**decision,'action':'defer'}],root/'defer')
        assert report['remaining'] and report['status']=='needs_review'
        checks['defer_does_not_approve_fact']=True
        csvfile=root/'alias.csv';csvfile.write_text('id,action,reviewer,decision_reason\nr1,defer,test,review later\n',encoding='utf-8-sig')
        assert read_decisions(csvfile)[0]['action']=='defer'
        checks['csv_action_alias_is_read']=True
        csvfile.write_text('id,action,decision\nr1,defer,correct_field\n',encoding='utf-8-sig')
        reject(lambda:read_decisions(csvfile))
        checks['conflicting_csv_action_columns_rejected']=True
        src.write_text('source changed',encoding='utf8')
        reject(lambda:import_decisions(data,m,q,[decision],root/'source'))
        checks['changed_original_rejected']=True
    print(json.dumps({'status':'passed','checks':checks}))


if __name__=='__main__':run()
