"""Fill a missing recorded sex from an owner-verified, format-valid PRC identity number."""
import argparse,copy,json,re,unicodedata
from pathlib import Path
from datetime import date
from source_audit import load,dump,units_for,validate_unit_owner,validate_person_scope
from extract_sources import sha

STANDARD='https://zjw.beijing.gov.cn/Portals/0/zhuanti/fazhan/%E8%BA%AB%E4%BB%BD%E8%AF%81GB11643-1999.pdf'


def identity_sex(value,as_of):
    number=unicodedata.normalize('NFKC',str(value)).strip().upper()
    if not re.fullmatch(r'[1-9]\d{16}[\dX]',number):raise ValueError('A complete 18-character identity number is required; no OCR guessing or masked digits.')
    born=date(int(number[6:10]),int(number[10:12]),int(number[12:14]))
    if born>date.fromisoformat(as_of) or born.year<1800:raise ValueError('Identity birth date is invalid.')
    weights=(7,9,10,5,8,4,2,1,6,3,7,9,10,5,8,4,2)
    if '10X98765432'[sum(int(n)*w for n,w in zip(number[:17],weights))%11]!=number[-1]:raise ValueError('Identity check digit is invalid.')
    if number[14:17]=='000':raise ValueError('Identity sequence is invalid.')
    return '男' if int(number[16])%2 else '女'


def apply(data,manifest,candidates):
    result=copy.deepcopy(data);changes=[];conflicts=[];seen=set()
    people={str(p['id']):p for p in result['people']};sources={s['id']:s for s in manifest['sources']}
    for c in candidates:
        p=people[str(c['person_id'])];key=p['id']
        if key in seen:raise ValueError('Duplicate person derivation.')
        seen.add(key)
        if c.get('owner_person_id')!=p['id'] or c.get('owner_verified') is not True or not isinstance(c.get('reviewer'),str) or not c['reviewer'].strip() or not isinstance(c.get('reason'),str) or not c['reason'].strip():
            raise ValueError('Identity derivation requires an explicitly reviewed owner binding.')
        quotes=c.get('source_quotes',[])
        if not quotes:raise ValueError('Identity derivation requires original source units.')
        for q in quotes:
            sid=q['source_id'];source=sources[sid]
            if sid not in p.get('source_ids',[]) or sha(source['source'])!=source['sha256']:raise ValueError('Identity source is stale or belongs to another person.')
            validate_person_scope(p,sid,q['unit_id'])
            if sum(sid in other.get('source_ids',[]) for other in data['people'])>1 and p.get('person_source_scope') is None:
                raise ValueError('A shared identity source requires an explicit person source scope.')
            for kind in ('text','detail'):
                if source.get(kind+'_sha256') and sha(source[kind+'_file'])!=source[kind+'_sha256']:raise ValueError('Identity extraction changed.')
            unit=next(u for u in units_for(source) if u['unit_id']==q['unit_id'])
            if q['quote']!=unit['text']:raise ValueError('Identity quote is not an exact source unit.')
            validate_unit_owner(p,unit)
        raw=c['identity_number']
        if not any(str(raw) in q['quote'] for q in quotes):raise ValueError('Identity number is absent from the quoted source.')
        gender=identity_sex(raw,data['processing_date']);before=p['fields'].setdefault('meta',{}).get('sex','')
        present=unicodedata.normalize('NFKC','' if before is None else str(before)).strip()
        normalized={'男性':'男','女性':'女','M':'男','F':'女','male':'男','female':'女'}.get(present,present)
        if present:
            if normalized!=gender:conflicts.append({'person_id':p['id'],'field':'meta.sex','reason':'明示性别与身份证顺序码不一致；保留原值，需核对。'})
            continue
        p['fields']['meta']['sex']=gender
        p.setdefault('field_facts',{})['meta.sex']={'value':gender,'origin':'source_inferred','reason':'明确归属本人的完整身份证号通过日期与校验码检查，按第17位顺序码奇偶推导登记性别；不代表证件真实性认证。',
             'source_quotes':quotes,'rule':'prc_id_sequence_sex','standard':STANDARD}
        p.setdefault('evidence',[])[:]=[e for e in p.get('evidence',[]) if e['field']!='meta.sex']+[{'field':'meta.sex','source_quotes':quotes}]
        changes.append({'person_id':p['id'],'field':'meta.sex','before':before,'after':gender,'rule':'prc_id_sequence_sex','identity_number':'[redacted]'})
    return result,{'changes':changes,'conflicts':conflicts,'standard':STANDARD,'limits':'Format/date/check-digit checks do not authenticate identity or historical address codes. No complete identity numbers appear in this summary.'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('data','sources','candidates','out','report'):p.add_argument('--'+k,type=Path,required=True)
    a=p.parse_args()
    if a.out.exists() or a.report.exists():p.error('Use new output paths.')
    result,report=apply(load(a.data),load(a.sources),load(a.candidates));dump(a.out,result);dump(a.report,report);print(json.dumps({'filled':len(report['changes']),'conflicts':len(report['conflicts'])}))

if __name__=='__main__':main()
