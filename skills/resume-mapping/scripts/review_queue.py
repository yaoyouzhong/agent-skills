"""Export a version-bound, person-grouped review queue with source quotations."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
from extract_sources import sha
from source_audit import current_bindings, dump, load


def person_gates(data, audit, facts, records, render_check=None, visual_passed=False, manifest=None):
    result=[]
    def relevant(issue,p):
        conflict=issue.get('conflict',{})
        pid=issue.get('person_id',conflict.get('person_id'))
        if pid is not None:return str(pid)==str(p['id'])
        sids={q['source_id'] for q in conflict.get('source_quotes',[]) if q.get('source_id')}
        if issue.get('source_id'):sids.add(issue['source_id'])
        return bool(sids & set(p.get('source_ids',[]))) if sids else True
    for p in data['people']:
        pending=[]
        from source_quality import source_pending
        if (any(source_pending(data,s) for s in manifest['sources'] if s['id'] in p.get('source_ids',[])) if manifest else any(data.get('source_reviews',{}).get(s,{}).get('status')=='pending' for s in p.get('source_ids',[]))):pending.append('source_warnings')
        for gate,report in [('source_coverage',audit),('field_facts',facts),('record_checks',records)]:
            if any(relevant(i,p) for i in report.get('issues',[])):pending.append(gate)
            elif report.get('status')!='passed' and not report.get('issues'):pending.append(gate)
        if not render_check or render_check.get('status')!='passed' and (not render_check.get('issues') or any(relevant(i,p) for i in render_check['issues'])):
            pending.append('rendered_content')
        if not visual_passed:pending.append('visual_review')
        result.append({'person_id':p['id'],'name':p['fields'].get('meta',{}).get('name',''),'status':'closed' if not pending else 'candidate','pending':pending})
    return result


def export(data,manifest,reports,outdir):
    outdir=Path(outdir);outdir.mkdir(parents=True,exist_ok=False)
    sources={s['id']:s for s in manifest['sources']};people={p['id']:p for p in data['people']}
    rows=[];seen=set()
    for category,report in reports.items():
        for issue in report.get('issues',[]):
            if issue.get('status')=='resolved':continue
            if not issue.get('conflict') and issue.get('resolution',{}).get('conflict_id'):
                conflict=next((c for c in data.get('source_conflicts',[]) if c['id']==issue['resolution']['conflict_id']),None)
                if conflict:issue={**issue,'conflict':conflict}
            if issue.get('conflict'):
                issue={**issue,**issue['conflict'],'field':'source_conflict:'+issue['conflict'].get('id',''),
                       'code':'retained_conflict','reason':issue['conflict'].get('reason','来源存在未解决矛盾。')}
            p=people.get(issue.get('person_id'),{})
            if not p:
                sids={q.get('source_id') for q in issue.get('source_quotes',[])}|{issue.get('source_id')}
                owners=[p for p in data['people'] if set(p.get('source_ids',[])) & sids]
                if len(owners)==1:p=owners[0]
            path=issue.get('field',issue.get('record',''))
            signature=json.dumps({k:issue.get(k) for k in ('person_id','source_id','field','record','code','value','reason','issue','origin')},ensure_ascii=False,sort_keys=True)
            if signature in seen:continue
            seen.add(signature)
            quotes=list(issue.get('source_quotes',[]))+[q for e in p.get('evidence',[]) if e['field']==path for q in e.get('source_quotes',[])]
            if issue.get('quote',issue.get('text')):quotes.append({'quote':issue.get('quote',issue.get('text')),'source_id':issue.get('source_id'),'locator':issue.get('locator','')})
            row={'person_id':p.get('id',issue.get('person_id','')),'name':p.get('fields',{}).get('meta',{}).get('name',''),
                 'field':path,'category':category,'code':issue.get('code',issue.get('origin',issue.get('status',''))),
                 'value':issue.get('value',''),'reason':issue.get('reason',issue.get('issue',issue.get('resolution',{}).get('reason','原文与输出需对照。'))),
                 'source_quotes':quotes,'source_files':[sources[s]['source'] for s in p.get('source_ids',[])],
                 'decision':'','reviewer':'','decision_reason':''}
            row['id']=hashlib.sha256(json.dumps(row,ensure_ascii=False,sort_keys=True).encode()).hexdigest()[:20];rows.append(row)
    for sid,source in sources.items():
        review=data.get('source_reviews',{}).get(sid,{})
        from source_quality import source_pending
        if not source_pending(data,source):continue
        for p in data['people']:
            if sid not in p['source_ids']:continue
            rows.append({'id':f"source-{p['id']}-{sid}",'person_id':p['id'],'name':p['fields'].get('meta',{}).get('name',''),
                         'field':'source/media','category':'source_warnings','code':'pending','value':'',
                         'reason':review.get('reason','原件图片或提取告警未核清。'),'source_quotes':[],
                         'source_files':[sources[sid]['source']],'decision':'','reviewer':'','decision_reason':''})
    groups={}
    for row in rows:
        key=(str(row['person_id']),row['field'],row['code'])
        group=groups.setdefault(key,{'person_id':row['person_id'],'field':row['field'],'code':row['code'],'row_ids':[],'categories':[]})
        group['row_ids'].append(row['id'])
        if row['category'] not in group['categories']:group['categories'].append(row['category'])
    state={'schema_version':2,'bindings':current_bindings(data,manifest),'rows':rows,'groups':list(groups.values()),'status':'needs_review' if rows else 'passed',
           'decisions_are_not_automatic_fact_approval':True}
    dump(outdir/'queue.json',state)
    cols=['id','person_id','name','field','category','code','value','reason','source_files','source_quotes','decision','reviewer','decision_reason',
          'expected_value_json','value_json','origin','source_quotes_json','proof_json']
    with (outdir/'review.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=cols);writer.writeheader()
        for row in rows:
            cells={k:json.dumps(v,ensure_ascii=False) if isinstance(v,(list,dict)) else str(v) for k,v in row.items()}
            # Prevent source text from executing as spreadsheet formulas.
            writer.writerow({k:("'"+v if v.startswith(('=','+','-','@')) else v) for k,v in cells.items()})
    lines=['# 逐人待核清单','','每项附原文定位；填写复核意见后需更新实际字段/证据并重新校验。填写本表不会直接解除事实或生成门禁。','']
    for p in data['people']:
        own=[r for r in rows if r['person_id']==p['id']]
        if not own:continue
        lines += [f"## {p['id']} {p['fields'].get('meta',{}).get('name','')}",'']
        for r in own:
            lines += [f"- `{r['id']}` **{r['field'] or r['category']}**：{r['reason']}",f"  - 当前值：{str(r['value']).replace(chr(10),' / ')}"]
            for q in r['source_quotes']:lines.append(f"  - 原文 {q.get('source_id','')} {q.get('locator','')}：{q['quote'].replace(chr(10),' / ')}")
            for f in r['source_files']:lines.append(f"  - 来源：{f}")
            lines.append('  - 复核意见：待填写')
        lines.append('')
    (outdir/'review.md').write_text('\n'.join(lines),encoding='utf8');return state


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--data',type=Path,required=True);p.add_argument('--sources',type=Path,required=True)
    p.add_argument('--report',type=Path,action='append',required=True);p.add_argument('--outdir',type=Path,required=True);a=p.parse_args()
    r=export(load(a.data),load(a.sources),{f.stem:load(f) for f in a.report},a.outdir)
    print(json.dumps({'rows':len(r['rows']),'status':r['status']}))


if __name__=='__main__':main()
