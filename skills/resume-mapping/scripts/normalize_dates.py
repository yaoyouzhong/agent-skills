"""Standardize date formatting without inventing precision or repairing ambiguous dates."""
import argparse,copy,re,json,unicodedata
from pathlib import Path
from datetime import date
from source_audit import load,dump,get_path,norm
from record_checks import date_interval,education_binding


def canonical(value):
    text=unicodedata.normalize('NFKC',str(value)).strip()
    if not text:return text
    if text.lower() in ('present','now') or text in ('至今','现在','目前'):return '至今'
    qualifier=''
    m=re.match(r'^(预计|预期|约)\s*',text)
    if m:qualifier=m[1];text=text[m.end():]
    text=re.sub(r'[ T]00:00(?::00)?$','',text)
    m=re.fullmatch(r'(\d{4})(?:[年./-](\d{1,2})(?:[月./-](\d{1,2}))?)?[年月日]?',text)
    if not m:raise ValueError('Ambiguous date; preserve the original.')
    year,month,day=m.groups();candidate=year+('-'+month.zfill(2) if month else '')+('-'+day.zfill(2) if day else '')
    date_interval(candidate)
    return qualifier+candidate


def equivalent(before,after):
    try:return canonical(before)==canonical(after)
    except (ValueError,OverflowError):return False


def normalize(data):
    result=copy.deepcopy(data);changes=[];warnings=[]
    for p in result['people']:
        original_fields=copy.deepcopy(p['fields'])
        old_education=copy.deepcopy(p['fields'].get('education',[]))
        paths=[f'meta.{k}' for k in ('start','birth','birth_date') if k in p['fields'].get('meta',{})]
        paths += [f'{collection}[{i}].{key}' for collection in ('education','jobs','projects') for i,r in enumerate(p['fields'].get(collection,[])) for key in ('start','end') if key in r]
        for path in paths:
            before=get_path(p['fields'],path)
            if not before:continue
            try:after=canonical(before)
            except (ValueError,OverflowError):warnings.append({'person_id':p['id'],'field':path,'value':before,'reason':'原日期不明确/非法，保留原文，不猜改。'});continue
            if str(before)==after:continue
            from review_actions import set_path
            set_path(p['fields'],path,after)
            changes.append({'person_id':p['id'],'field':path,'before':before,'after':after,'rule':'date_format_only_preserve_precision'})
            fact=p.get('field_facts',{}).get(path)
            if fact and str(fact.get('value',''))==str(before):fact.update(value=after,normalization={'raw_value':before,'rule':'date_format_only_preserve_precision'})
        # A reviewed snapshot may bind an entire education list, not just a leaf.
        # Follow only snapshots that were exact before this format-only operation;
        # a previously stale snapshot must remain stale.
        for decision in result.get('coverage_decisions',{}).values():
            if decision.get('person_id')!=p['id']:continue
            for path,snapshot in list(decision.get('field_values',{}).items()):
                try:old=get_path(original_fields,path);new=get_path(p['fields'],path)
                except (KeyError,IndexError,TypeError):continue
                if snapshot==old:decision['field_values'][path]=copy.deepcopy(new)
                elif old!=new:
                    decision.setdefault('stale_before_date_normalization',[])
                    if path not in decision['stale_before_date_normalization']:decision['stale_before_date_normalization'].append(path)
        for i,(old,new) in enumerate(zip(old_education,p['fields'].get('education',[]))):
            proof=p.get('education_status_evidence',{}).get(f'education[{i}]')
            if old!=new and proof:
                if proof.get('record_sha256')!=education_binding(old):
                    proof['stale_before_date_normalization']=True
                elif all(equivalent(old.get(k,''),new.get(k,'')) for k in ('start','end')):
                    proof['format_normalization_from_record_sha256']=proof['record_sha256'];proof['record_sha256']=education_binding(new)
    return result,{'changes':changes,'warnings':warnings,'date_format':'YYYY-MM-DD / YYYY-MM / YYYY; ongoing=至今; qualifiers retained'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('data','out','report'):p.add_argument('--'+k,type=Path,required=True)
    a=p.parse_args()
    if a.out.exists() or a.report.exists():p.error('Use new output paths.')
    result,report=normalize(load(a.data));dump(a.out,result);dump(a.report,report);print(json.dumps({'changes':len(report['changes']),'warnings':len(report['warnings'])}))

if __name__=='__main__':main()
