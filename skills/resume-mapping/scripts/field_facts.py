"""Separate extracted facts, derived values, policy defaults and reviewed blank fields."""
import argparse
import collections
import copy
import json
import re
import sys
import hashlib
from pathlib import Path
from apply_policies import degree_for
from source_audit import dump, get_path, load, norm, units_for,validate_unit_owner,validate_person_scope

ORIGINS={'source_direct','source_assembled','source_inferred','user_default','source_selected','intentionally_blank','not_provided','needs_review','extraction_failed'}


def fact_binding(data):
    value={'processing_date':data.get('processing_date'),'people':[{'id':p['id'],'fields':p['fields'],'field_facts':p.get('field_facts',{}),
        'education_status_evidence':p.get('education_status_evidence',{}),'education_selection':p.get('education_selection'), 'evidence':p.get('evidence',[])} for p in data['people']]}
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def all_fields(obj,prefix=''):
    if isinstance(obj,dict):
        for key,value in obj.items():
            if not (key=='status' and re.fullmatch(r'education\[\d+\]',prefix)):yield from all_fields(value,prefix+('.' if prefix else '')+key)
    elif isinstance(obj,list):
        for index,value in enumerate(obj):yield from all_fields(value,f'{prefix}[{index}]')
    else:yield prefix,'' if obj is None else str(obj)


def classify(data,manifest,decisions=None):
    result=copy.deepcopy(data);problems=[];counts=collections.Counter()
    from record_checks import validate
    record_report = validate(result, manifest)
    problems.extend(record_report['issues'])
    sources={s['id']:{u['unit_id']:u for u in units_for(s)} for s in manifest['sources']}
    decisions=decisions or {}
    for person in result['people']:
        facts=person.get('field_facts',{});evidence={e['field']:e for e in person.get('evidence',[])}
        source_binding={s['id']:s['sha256'] for s in manifest['sources'] if s['id'] in person['source_ids']}
        for path,value in all_fields(person['fields']):
            existing=facts.get(path)
            if existing and str(existing.get('value',''))!=value:
                existing=None
            decision=decisions.get(str(person['id'])+':'+path)
            quotes=evidence.get(path,{}).get('source_quotes',[])
            for quote in quotes:
                sid,uid=quote['source_id'],quote['unit_id']
                validate_person_scope(person,sid,uid)
                if sid not in person['source_ids'] or uid not in sources[sid] or quote['quote']!=sources[sid][uid]['text']:
                    raise ValueError('Fact evidence is not an original source quote.')
                validate_unit_owner(person,sources[sid][uid])
            if decision:
                fact={**decision,'value':value}
                if 'reviewed_value' in fact and str(fact['reviewed_value'])!=value:
                    raise ValueError('Field review refers to a different value.')
                if fact.get('origin') not in ORIGINS or not fact.get('reason'):
                    raise ValueError('Fact decision needs a typed origin and a specific reason.')
                for quote in fact.get('source_quotes',[]):
                    validate_person_scope(person,quote['source_id'],quote['unit_id'])
                    if quote['source_id'] not in person['source_ids'] or quote['quote']!=sources[quote['source_id']][quote['unit_id']]['text']:
                        raise ValueError('Fact decision source quote changed.')
                    validate_unit_owner(person,sources[quote['source_id']][quote['unit_id']])
                    record=re.match(r'(projects\[\d+\])\.',path)
                    if record:
                        scope=person.get('record_sources',{}).get(record[1],{})
                        if quote['source_id']!=scope.get('source_id') or quote['unit_id'] not in scope.get('unit_ids',[]):
                            section_context=(path.endswith('.name') and norm(quote['quote']) in {'个人作品','个人项目','开源项目','在校实践','课程设计'} and norm(quote['quote']) in norm(value))
                            if not section_context:raise ValueError('Fact quote belongs to another project: '+str(person['id'])+':'+path)
                if fact['origin']=='source_inferred' and not fact.get('source_quotes'):
                    raise ValueError('Inferred facts require source quotations.')
                if fact['origin'] in ('source_direct','source_assembled') and not fact.get('source_quotes'):
                    raise ValueError('Source facts require original source quotations.')
                if fact['origin'] in ('not_provided','intentionally_blank') and value:
                    raise ValueError('A nonempty fact cannot be classified as a blank field.')
            elif existing and existing.get('origin') in ('user_default','source_selected','intentionally_blank','source_inferred'):
                fact=existing
            elif existing and existing.get('origin')=='not_provided' and existing.get('source_binding')==source_binding:
                fact=existing
            elif existing and existing.get('origin') in ('source_direct','source_assembled') and existing.get('source_binding')==source_binding and existing.get('source_quotes'):
                # Preserve an unchanged, already reviewed assembly rather than
                # discarding its exact reviewed quotes for a heuristic relocalization.
                fact=existing
            elif existing and existing.get('origin')=='needs_review' and existing.get('reviewed_value')==value and existing.get('source_binding')==source_binding and existing.get('reviewer') and existing.get('reason'):
                # A scoped unresolved decision remains unresolved on reclassification.
                # Keep its reviewed reason instead of replacing it with a generic blank.
                fact=existing
            elif value:
                exact=any(norm(value) in norm(q['quote']) for q in quotes)
                assembled=quotes and all(norm(value)[i:i+3] in norm(''.join(q['quote'] for q in quotes)) for i in range(max(1,len(norm(value))-2)))
                fact={'value':value,'origin':'source_direct' if exact else 'source_assembled' if assembled else 'needs_review','source_quotes':quotes}
            else:
                college=False;in_progress=False
                match=re.fullmatch(r'education\[(\d+)\]\.degree',path)
                if match:
                    edu=person['fields']['education'][int(match[1])];college=bool(re.search('大专|专科',edu.get('level','')));in_progress=edu.get('status') in ('in_progress','incomplete')
                if path=='meta.degree':college=bool(re.search('大专|专科',person['fields'].get('meta',{}).get('level','')))
                fact={'value':'','origin':'intentionally_blank' if college or in_progress else 'needs_review',
                      'reason':'大专无学位；在读/未毕业不补授予学位。' if college or in_progress else 'Empty target field has not yet been classified against the available source.'}
            if fact['origin'] in ('source_inferred','source_direct','source_assembled'):
                if not fact.get('source_quotes'):raise ValueError('Inferred facts require original source quotations.')
                for quote in fact['source_quotes']:
                    sid,uid=quote['source_id'],quote['unit_id']
                    validate_person_scope(person,sid,uid)
                    if sid not in person['source_ids'] or quote['quote']!=sources[sid][uid]['text']:raise ValueError('Inherited inference evidence changed.')
                    validate_unit_owner(person,sources[sid][uid])
                    record=re.match(r'(projects\[\d+\])\.',path)
                    if record:
                        scope=person.get('record_sources',{}).get(record[1],{})
                        context=path.endswith('.name') and norm(quote['quote']) in {'个人作品','个人项目','开源项目','在校实践','课程设计'} and norm(quote['quote']) in norm(value)
                        if (sid!=scope.get('source_id') or uid not in scope.get('unit_ids',[])) and not context:raise ValueError('Inherited inference belongs to another project.')
            if fact['origin']=='user_default':
                match=re.fullmatch(r'education\[(\d+)\]\.degree',path)
                if not match:
                    raise ValueError('Degree defaults must identify an education record.')
                edu=person['fields']['education'][int(match[1])]
                if not record_report['education'][f"{person['id']}:education[{int(match[1])}]"]['eligible'] or degree_for(edu.get('level',''))!=value:
                    raise ValueError('Degree default conflicts with completed education.')
            if fact['origin']=='source_selected':
                selected=person.get('education_selection',{}).get('index')
                key=path.split('.')[-1]
                if selected is None or not record_report['education'][f"{person['id']}:education[{selected}]"]['eligible'] or str(person['fields']['education'][selected].get(key,''))!=value:
                    if value:
                        raise ValueError('Education summary does not match selected completed record.')
                    fact={**fact,'origin':'not_provided','reason':'No verified completed education was stated in the available resume.'}
            fact['source_binding']=source_binding
            facts[path]=fact;counts[fact['origin']]+=1
            if fact['origin'] in ('needs_review','extraction_failed'):
                problems.append({'person_id':person['id'],'field':path,'value':value,'origin':fact['origin']})
        person['field_facts']=facts
    return result,{'data_facts_sha256':fact_binding(result),'origins':dict(counts),'issues':problems,'open_issues':len(problems),'status':'passed' if not problems else 'needs_review'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data',type=Path,required=True);parser.add_argument('--sources',type=Path,required=True)
    parser.add_argument('--decisions',type=Path);parser.add_argument('--out',type=Path,required=True);parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args()
    if args.out.exists() or args.report.exists() or args.out.resolve()==args.report.resolve():parser.error('Use distinct new output/report paths.')
    data,report=classify(load(args.data),load(args.sources),load(args.decisions) if args.decisions else {})
    dump(args.out,data);dump(args.report,report);print(json.dumps({k:v for k,v in report.items() if k!='issues'},ensure_ascii=False))
    return 0 if not report['issues'] else 2


if __name__=='__main__':sys.exit(main())
