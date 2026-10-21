"""Evaluate source-bound human labels; report only the labelled scope, not corpus accuracy."""
import argparse,re
from collections import Counter
from pathlib import Path
from source_audit import load,dump,get_path,norm
from extract_sources import sha


def text_norm(value):
    # Formatting list numbers are not semantic content. Versions inside a line remain.
    text=re.sub(r'(?m)^\s*\d+[.、)]\s*','',str(value))
    return norm(text)


def evaluate(gold,predictions,adapters=None):
    adapters=adapters or {};rows=[];projects=[]
    for case in gold['cases']:
        if sha(case['source'])!=case['source_sha256']:raise ValueError('Benchmark original changed.')
        entry=predictions[case['id']]
        if sha(entry['data'])!=entry['data_sha256']:raise ValueError('Benchmark prediction changed after sealing.')
        data=load(entry['data']);person=next(p for p in data['people'] if p['fields'].get('meta',{}).get('name')==case['person_name'])
        for label in case['fields']:
            path=adapters.get(case['id'],{}).get(label['path'],label['path'])
            try:value=get_path(person['fields'],path);present=True
            except (KeyError,IndexError,TypeError):value='';present=False
            accepted=label['accepted_values'];long=label.get('category')=='skill' or any(k in label['path'] for k in ('.desc','.resp','.tech','.platform','.structure','.mode','.modules','.features','.design','.outcomes','self_evaluation'))
            matched=any(text_norm(v)==text_norm(value) or (long and text_norm(v) and text_norm(v) in text_norm(value)) for v in accepted)
            rows.append({'case':case['id'],'field':label['path'],'prediction_field':path,'category':label['category'],
                         'matched':bool(matched),'prediction':value,'accepted_values':accepted,'missing_path':not present,
                         'match_rule':'normalized_contains' if long else 'normalized_exact','locator':label['locator']})
        actual=[p.get('name','') for p in person['fields'].get('projects',[])];expected=case['project_names']
        ac,ec=Counter(map(norm,actual)),Counter(map(norm,expected));tp=sum((ac&ec).values())
        projects.append({'case':case['id'],'expected_count':len(expected),'actual_count':len(actual),'true_positive':tp,
            'false_positive':sum((ac-ec).values()),'false_negative':sum((ec-ac).values()),'order_matches':list(map(norm,actual))==list(map(norm,expected))})
    correct=sum(r['matched'] for r in rows);total=len(rows)
    return {'status':'passed' if correct==total and all(not p['false_positive'] and not p['false_negative'] and p['order_matches'] for p in projects) else 'differences',
            'labelled_fields':total,'matched_fields':correct,'field_match_rate':correct/total if total else None,
            'cases':len(projects),'project_boundaries':projects,'differences':[r for r in rows if not r['matched']],
            'per_category':{c:{'matched':sum(r['matched'] for r in rows if r['category']==c),'total':sum(r['category']==c for r in rows)} for c in sorted({r['category'] for r in rows})},
            'limitations':'Only explicitly labelled fields were scored. Long text uses normalized containment. This is not accuracy for all people or unseen formats.'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for arg in ('gold','predictions','out'):p.add_argument('--'+arg,type=Path,required=True)
    p.add_argument('--adapters',type=Path);a=p.parse_args()
    if a.out.exists():p.error('Use a new benchmark report path.')
    result=evaluate(load(a.gold),load(a.predictions),load(a.adapters) if a.adapters else None);dump(a.out,result)
    print(__import__('json').dumps({k:v for k,v in result.items() if k not in ('differences','per_category')},ensure_ascii=False))

if __name__=='__main__':main()
