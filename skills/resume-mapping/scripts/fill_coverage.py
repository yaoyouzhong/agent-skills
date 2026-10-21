"""Count actual template bindings, keeping structured blanks separate from empty output slots."""
import argparse,json
from pathlib import Path
from source_audit import load,dump
from template_docx import get


def coverage(data,mapping):
    slots=[]
    def add(person,binding,obj,prefix,location):
        keys=binding.get('keys',[binding['key']] if 'key' in binding else [])
        if not keys:return
        paths=[prefix+k for k in keys];values=[get(obj,k) for k in keys]
        filled=any(v is not None and str(v).strip() for v in values)
        facts=person.get('field_facts',{});reviews=person.get('blank_reviews',{})
        origins=[facts.get(p,{}).get('origin') for p in paths]
        reviewed=[reviews.get(p,{}) for p in paths]
        classifications=[r.get('classification') for r in reviewed]
        reason='filled' if filled else 'intentional_rule' if all(o=='intentionally_blank' for o in origins) else 'source_not_provided' if all(o in ('not_provided','intentionally_blank') for o in origins) else 'requires_source_check'
        if not filled and all(classifications):
            # A fresh source review supersedes a previous generic missing label.
            reason=next((kind for kind in ('available_but_missed','unreadable','insufficient','source_not_provided','already_represented','intentional_rule') if kind in classifications),'requires_source_check')
        slots.append({'person_id':person['id'],'location':location,'fields':paths,'filled':filled,'blank_reason':reason,
                      'values':values,'source_reviews':reviewed,
                      'blank_review_complete':filled or all(bool(r.get('classification')) for r in reviewed) or reason=='intentional_rule'})
    for p in data['people']:
        fields=p['fields']
        if 'sheet' in mapping:
            for i,b in enumerate(mapping.get('fields',[])):add(p,b,fields,'',f"{mapping['sheet']}!{b['cell']}")
            for ri,r in enumerate(mapping.get('repeat',[])):
                for index,record in enumerate(get(fields,r['key']) or []):
                    for bi,b in enumerate(r['fields']):add(p,b,record,f"{r['key']}[{index}].",f'repeat{ri}:{index}:{bi}')
            used={path for s in slots if s['person_id']==p['id'] for path in s['fields']}
            for path in mapping.get('append_unmapped',{}).get('labels',{}):
                if path not in used and get(fields,path):add(p,{'key':path},fields,'','append:'+path)
        else:
            for b in mapping.get('paragraphs',[]):add(p,b,fields,'',f"paragraph:{b['index']}")
            for t in mapping.get('tables',[]):
                for b in t.get('fields',[]):add(p,b,fields,'',f"table{t['index']}:row{b['row']}:cell{b['cell']}")
                for ri,r in enumerate(t.get('repeat',[])):
                    if r.get('combine_records'):
                        paths=[]
                        for index,record in enumerate(get(fields,r['key']) or []):
                            for b in r.get('fields',[]):
                                paths.extend(f"{r['key']}[{index}]."+k for k in b.get('keys',[b['key']] if 'key' in b else []))
                        if paths:add(p,{'keys':paths},fields,'',f"table{t['index']}:repeat{ri}:combined")
                        continue
                    for index,record in enumerate(get(fields,r['key']) or []):
                        prefix=f"{r['key']}[{index}]."
                        for bi,b in enumerate(r.get('fields',[])):add(p,b,record,prefix,f"table{t['index']}:repeat{ri}:{index}:{bi}")
                        for ei,extra in enumerate(r.get('trailing_rows',[])):
                            if extra.get('when_nonempty') and not get(record,extra['when_nonempty']):continue
                            for bi,b in enumerate(extra.get('fields',[])):add(p,b,record,prefix,f"table{t['index']}:repeat{ri}:{index}:extra{ei}:{bi}")
                for ei,extra in enumerate(t.get('append_rows',[])):
                    if extra.get('when_nonempty') and not get(fields,extra['when_nonempty']):continue
                    for bi,b in enumerate(extra.get('fields',[])):add(p,b,fields,'',f"table{t['index']}:append{ei}:{bi}")
    filled=sum(s['filled'] for s in slots)
    from collections import Counter
    return {'slot_definition':'Actual data-bearing template bindings; combined keys count once; optional rows count only when generated. Fixed labels are excluded.',
            'total_slots':len(slots),'filled_slots':filled,'blank_slots':len(slots)-filled,
            'fill_rate':filled/len(slots) if slots else None,'blank_reasons':dict(Counter(s['blank_reason'] for s in slots if not s['filled'])),
            'unreviewed_blank_slots':sum(not s['blank_review_complete'] for s in slots if not s['filled']),
            'limitations':'Fill rate is not extraction accuracy. Every blank still needs comparison with its own available source.', 'slots':slots}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('data','map','out'):p.add_argument('--'+k,type=Path,required=True)
    a=p.parse_args()
    if a.out.exists():p.error('Use a new report path.')
    r=coverage(load(a.data),load(a.map));dump(a.out,r);print(json.dumps({k:v for k,v in r.items() if k!='slots'}))

if __name__=='__main__':main()
