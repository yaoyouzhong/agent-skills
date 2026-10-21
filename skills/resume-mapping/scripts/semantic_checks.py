"""Identity, client-role and credential semantics beyond substring coverage."""
import re
from collections import Counter
from datetime import date
from source_audit import norm,get_path,units_for,validate_unit_owner,validate_person_scope


def check_identity(data,manifest):
    people=data['people'];names=Counter(norm(p['fields'].get('meta',{}).get('name','')) for p in people)
    inventories={s['id']:{u['unit_id']:u for u in units_for(s)} for s in manifest['sources']}
    for p in people:
        used=[q for e in p.get('evidence',[]) for q in e.get('source_quotes',[])]+[q for f in p.get('field_facts',{}).values() for q in f.get('source_quotes',[])]
        used += [q for proof in p.get('education_status_evidence',{}).values() for q in proof.get('source_quotes',[])]
        used += [q for credential in p.get('credentials',[]) for q in credential.get('source_quotes',[])]
        for q in used:
            unit=inventories[q['source_id']][q['unit_id']]
            validate_person_scope(p,q['source_id'],q['unit_id'])
            validate_unit_owner(p,unit)
            if unit.get('kind')=='reviewed_media_text' and names[norm(p['fields'].get('meta',{}).get('name',''))]>1 and str(unit.get('owner_person_id',''))!=str(p['id']):
                raise ValueError('Same-name people require the reviewed image to bind an explicit person ID.')


def client_role(client,text,review=None):
    original=text;entity=re.escape(client);text=re.sub(r'\s+','',text)
    negative=(r'(?:实施方|承建商|供应商|产品厂商|开发商|任职单位)[:：为是]*'+entity,
              entity+r'(?:负责实施|负责承建|提供技术|提供产品)')
    if any(re.search(p,text) for p in negative):return 'rejected_non_client'
    positive=(r'(?:客户(?:名称)?|业主|委托方|建设单位|服务对象|最终用户)[:：为是]+'+entity,
              entity+r'(?:委托|采购|招标|提出需求|作为客户|作为业主)',
              r'为'+entity+r'.{0,6}(?:建设|开发|提供|实施|交付)')
    if any(re.search(p,text) for p in positive):return 'explicit_client'
    if review and review.get('role')=='client' and review.get('reviewer') and review.get('reason') and review.get('reviewed_quote')==original:
        return 'reviewed_contextual_client'
    return 'needs_role_review'


def credentials(person,manifest,processing_date):
    from record_checks import date_interval,checked_quotes
    today=date.fromisoformat(processing_date);results=[];issues=[]
    entries=person.get('credentials',[]);ids=[c['id'] for c in entries]
    if len(ids)!=len(set(ids)):raise ValueError('Credential IDs must be unique per person.')
    for i,c in enumerate(entries):
        quotes=checked_quotes(person,c.get('source_quotes',[]),manifest)
        if not quotes:raise ValueError('Credential dates require original reviewed evidence.')
        raw=' '.join(q['quote'] for q in quotes)
        from datetime import datetime
        english_dates=[]
        for found in re.finditer(r'\b\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}\b',raw,re.I):
            english_dates.append(datetime.strptime(found[0],'%d %B %Y').date().isoformat())
        parsed={};text=norm(raw+' '+' '.join(english_dates))
        for key in ('obtained','issued','valid_until'):
            if not c.get(key):continue
            if norm(c[key]) not in text:raise ValueError('Credential date does not occur in the quoted evidence.')
            try:parsed[key]=date_interval(c[key])
            except (ValueError,OverflowError):
                issues.append({'person_id':person['id'],'field':f'credentials[{i}].{key}','code':'invalid_credential_date','value':c[key]})
        end=parsed.get('valid_until');state='validity_unknown'
        if end:state='expired_attachment' if end[1]<today else 'expiry_precision_ambiguous' if end[0]<=today<=end[1] and end[0]!=end[1] else 'within_stated_period'
        if c.get('supersedes'):
            previous=next((old for old in entries if old['id']==c['supersedes']),None)
            if previous is None or previous['id']==c['id'] or previous.get('name')!=c.get('name'):
                raise ValueError('Renewal must reference a different existing credential of the same type.')
        if c.get('used_as_current') and state in ('expired_attachment','validity_unknown','expiry_precision_ambiguous'):
            issues.append({'person_id':person['id'],'field':f'credentials[{i}].valid_until','code':'current_credential_unverified',
                           'value':c.get('valid_until',''),'reason':'当前资格需核对有效期或续证；历史附件不自动证明当前有效。'})
        if parsed.get('issued') and end and parsed['issued'][0]>end[1]:
            issues.append({'person_id':person['id'],'field':f'credentials[{i}]','code':'credential_dates_reversed','value':c.get('issued')})
        results.append({'id':c['id'],'name':c.get('name',''),'status':state,'used_as_current':bool(c.get('used_as_current'))})
    return results,issues
