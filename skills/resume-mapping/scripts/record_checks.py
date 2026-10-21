"""Verify education eligibility and date chronology before facts or document generation."""
import argparse
import calendar
import hashlib
import json
import re
from datetime import date
from pathlib import Path

UNFINISHED = r'在读|未毕业|肄业|在校|至今|预计|预期|中退|结业'
GRADUATED = r'已毕业|准予毕业|毕业证书|已取得.{0,8}学位|授予.{0,8}学位'
GRADUATION_HONOR = r'(?:曾获|荣获|获得|获评|被评为)[^。；\n]{0,25}优秀毕业生'


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def education_binding(record):
    # A policy-generated degree must never become evidence for its own eligibility.
    return digest({k: record.get(k, '') for k in ('school', 'major', 'level', 'start', 'end', 'status')})


def date_interval(value):
    """Return a precise interval without adding invented months or days to output."""
    text = str(value).strip()
    if not text or text in ('至今', '现在', '目前', '在读', '进行中', 'Present', 'present'):
        return None
    text = re.sub(r'^(?:预计|预期|约)\s*', '', text)
    m = re.fullmatch(r'(\d{4})(?:[年./-](\d{1,2})(?:[月./-](\d{1,2}))?)?[年月日]?(?:[T ](00:00(?::00)?))?', text)
    if not m:
        raise ValueError('日期格式不明确，或混入非零时间。')
    y, mo, day = (int(x) if x else None for x in m.groups()[:3])
    if mo is not None and not 1<=mo<=12 or day is not None and not 1<=day<=31:
        raise ValueError('月份或日期不能为零或越界。')
    if day and not mo:
        raise ValueError('日期缺少月份。')
    low = date(y, mo or 1, day or 1)
    high = date(y, mo or 12, day or calendar.monthrange(y, mo or 12)[1])
    return low, high


def checked_quotes(person, quotes, manifest):
    from source_audit import units_for,validate_unit_owner
    sources = {s['id']: s for s in (manifest or {}).get('sources', [])}
    out = []
    for q in quotes:
        sid = q.get('source_id')
        if sid not in person.get('source_ids', []) or sid not in sources:
            raise ValueError('Graduation evidence belongs to another person or missing source.')
        from extract_sources import sha
        if sha(sources[sid]['source']) != sources[sid]['sha256']:
            raise ValueError('Graduation source changed.')
        for key in ('text','detail'):
            if sources[sid].get(key+'_sha256') and sha(sources[sid][key+'_file'])!=sources[sid][key+'_sha256']:
                raise ValueError('Graduation extraction changed.')
        unit = next((u for u in units_for(sources[sid]) if u['unit_id'] == q.get('unit_id')), None)
        if unit is None or q.get('quote') != unit['text']:
            raise ValueError('Graduation evidence is stale or is not an exact original unit.')
        if unit.get('kind')=='reviewed_media_text':
            validate_unit_owner(person,unit)
        out.append({**q, 'locator': unit.get('locator', ''), 'kind': unit.get('kind', ''),
                    'cell': unit.get('cell', ''), 'sheet': unit.get('sheet', ''),
                    'asset_sha256':unit.get('asset_sha256'), 'reviewer':unit.get('reviewer'),
                    'page':unit.get('page'),'table':unit.get('table'),'row':unit.get('row')})
    return out


def same_record(a, b, school):
    if a['source_id'] != b['source_id']:
        return False
    if a['unit_id'] == b['unit_id']:
        return bool(school and school in a['quote'])
    if all(a.get(k) is not None and b.get(k) is not None for k in ('page','table','row')):
        return all(a[k]==b[k] for k in ('page','table','row'))
    if a.get('kind') == b.get('kind') == 'excel_cell' and a.get('cell') and b.get('cell'):
        return a.get('sheet') == b.get('sheet') and re.search(r'\d+$', str(a['cell']))[0] == re.search(r'\d+$', str(b['cell']))[0]
    ar = re.match(r'(.*/row\[\d+\])/', a.get('locator', ''))
    br = re.match(r'(.*/row\[\d+\])/', b.get('locator', ''))
    return bool(ar and br and ar[1] == br[1])


def cell_column(quote):
    if quote.get('kind')=='excel_cell':
        match=re.match(r'\$?([A-Za-z]+)',quote.get('cell',''))
        if match:
            result=0
            for char in match[1].upper():result=result*26+ord(char)-64
            return result
    match=re.search(r'/cell\[(\d+)\]',quote.get('locator',''))
    return int(match[1]) if match else None


def graduation_date_bound(label, value, end):
    """A date must be the graduation field's value, not another date in its row."""
    from source_audit import norm
    if label['unit_id']==value['unit_id']:
        match=re.search(r'毕业(?:时间|年月|日期)\s*[:：]?\s*(.*)',label['quote'])
        return bool(match and norm(match[1]).startswith(norm(end)))
    column=cell_column(label)
    return column is not None and cell_column(value)==column+1 and norm(value['quote'])==norm(end)


def completion(person, index, manifest=None):
    record = person['fields']['education'][index]
    state = record.get('status', 'unknown')
    words = ' '.join(str(record.get(k, '')) for k in ('level', 'end', 'status_text'))
    base = {'record_sha256': education_binding(record), 'status': state, 'eligible': False}
    if re.search(UNFINISHED, words) or state in ('in_progress', 'incomplete'):
        return {**base, 'reason': '在读或未毕业记录不参与学历学位选择。', 'conflict': state == 'completed'}
    if state != 'completed':
        return {**base, 'reason': '毕业状态尚无明确依据。'}
    prefix = f'education[{index}]'
    evidence = {e['field']: e.get('source_quotes', []) for e in person.get('evidence', [])}
    proof = person.get('education_status_evidence', {}).get(prefix)
    if proof:
        if proof.get('record_sha256') != base['record_sha256'] or proof.get('stale_before_date_normalization'):
            return {**base, 'reason': '毕业状态复核所绑定的教育记录已变化。'}
        quotes = checked_quotes(person, proof.get('source_quotes', []), manifest)
        basis = proof.get('basis')
        if basis=='source_declared_graduation_date':
            from source_audit import norm
            school=record.get('school','');end=record.get('end','')
            label=[q for q in quotes if re.search(r'毕业(?:时间|年月|日期)',q['quote']) and not re.search(UNFINISHED,q['quote'])]
            schools=[q for q in quotes if school and school in q['quote']]
            dates=[q for q in quotes if end and norm(end) in norm(q['quote'])]
            # Inspect the full source row, including cells omitted from proof quotes.
            # A nearby "预计毕业" must not be hidden by quoting only positive cells.
            from source_audit import units_for
            source_map={s['id']:s for s in (manifest or {}).get('sources',[])}
            row_conflict=any(re.search(UNFINISHED,u['text']) and same_record(s,dict(u,source_id=s['source_id'],quote=u['text']),school)
                             for s in schools for u in units_for(source_map[s['source_id']]))
            if not row_conflict and label and schools and dates and any(same_record(s,l,school) and same_record(s,d,school) and graduation_date_bound(l,d,end) for s in schools for l in label for d in dates):
                return {**base,'eligible':True,'basis':basis,'source_quotes':quotes,
                        'reason':'原文明示毕业时间，学校、毕业标签与对应日期处于同一记录；仍由日期门禁检查未来/无效日期。'}
        if basis == 'user_confirmation' and proof.get('reviewer') and proof.get('reason') and proof.get('confirmation_reference'):
            return {**base, 'eligible': True, 'basis': basis, 'reason': proof['reason'], 'source_quotes': quotes}
        if basis in ('explicit_source', 'credential_review') and quotes:
            text = ' '.join(q['quote'] for q in quotes)
            school = record.get('school', '')
            honor=bool(re.search(GRADUATION_HONOR,text)) and not re.search(r'候选|提名|申报|评选|争取|拟获|拟评|并非|并未|不是|未曾获|未获|未荣获|未被评为|没有获得|没有荣获',text)
            if honor:
                scope=person.get('record_sources',{}).get(prefix,{})
                honor=bool(scope) and all(q['source_id']==scope.get('source_id') and q['unit_id'] in scope.get('unit_ids',[]) for q in quotes)
            if school and school in text and (re.search(GRADUATED, text) or honor) and not re.search(UNFINISHED, text):
                if basis != 'credential_review' or (proof.get('reviewer') and proof.get('asset_sha256') and proof.get('owner_verified') and any(q.get('asset_sha256')==proof['asset_sha256'] and q.get('reviewer')==proof['reviewer'] for q in quotes)):
                    return {**base, 'eligible': True, 'basis': basis, 'source_quotes': quotes,
                            'reason': '同一教育记录的毕业原文；证书真实性不由此脚本鉴定。'}
    school_quotes = checked_quotes(person, evidence.get(prefix + '.school', []), manifest)
    for q in school_quotes + checked_quotes(person, evidence.get(prefix + '.status_text', []), manifest):
        if record.get('school') and record['school'] in q['quote'] and re.search(GRADUATED, q['quote']) and not re.search(UNFINISHED, q['quote']):
            return {**base, 'eligible': True, 'basis': 'explicit_source', 'source_quotes': [q], 'reason': '原文明示毕业。'}
    degree = str(record.get('degree', '')).strip()
    default = person.get('field_facts', {}).get(prefix + '.degree', {}).get('origin') == 'user_default'
    if not default and degree in ('学士', '硕士', '博士') and not re.search(r'大专|专科', record.get('level', '')):
        degree_quotes = checked_quotes(person, evidence.get(prefix + '.degree', []), manifest)
        for dq in degree_quotes:
            if degree in dq['quote'] and not re.search(UNFINISHED, dq['quote']):
                for sq in school_quotes:
                    if same_record(dq, sq, record.get('school', '')):
                        return {**base, 'eligible': True, 'basis': 'source_declared_awarded_degree',
                                'source_quotes': [sq, dq], 'reason': '同一教育行原文明确填写授予学位；未独立核验证书。'}
    return {**base, 'reason': '已结束日期、学历名称和默认学位不能证明已经毕业。'}


def validate(data, manifest=None, as_of=None, check_summary=True):
    from source_audit import current_bindings
    processing = as_of or data.get('processing_date')
    if not processing:
        raise ValueError('Set processing_date (YYYY-MM-DD) explicitly; do not infer a historical task date.')
    today = date.fromisoformat(processing)
    issues, education = [], {}
    if manifest:
        from semantic_checks import check_identity
        check_identity(data,manifest)
    def issue(pid, field, code, value, reason):
        issues.append({'person_id': pid, 'field': field, 'code': code, 'value': value, 'reason': reason})
    for p in data['people']:
        pid = p['id']
        if p.get('credentials'):
            from semantic_checks import credentials
            _,credential_issues=credentials(p,manifest,processing)
            issues.extend(credential_issues)
        for collection in ('education', 'jobs', 'projects'):
            for i, record in enumerate(p['fields'].get(collection, [])):
                parsed = {}
                for key in ('start', 'end'):
                    value = record.get(key, '')
                    path = f'{collection}[{i}].{key}'
                    try:
                        interval = date_interval(value)
                    except (ValueError, OverflowError):
                        issue(pid, path, 'invalid_date', value, '原日期无法作为有效日历日期解析，需查看原件。')
                        continue
                    if interval:
                        parsed[key] = interval
                        if interval[0].year < int(data.get('minimum_resume_year', 1950)):
                            issue(pid, path, 'implausible_early_date', value, '异常早期年份；不得猜改 Excel 日期原值。')
                        if interval[0] > today and (key == 'start' or collection == 'education' and record.get('status') == 'completed'):
                            issue(pid, path, 'future_record', value, '未来记录需核实为计划经历；不能作为已毕业依据。')
                if 'start' in parsed and 'end' in parsed and parsed['end'][1] < parsed['start'][0]:
                    issue(pid, f'{collection}[{i}]', 'end_before_start', f"{record.get('start')} ~ {record.get('end')}", '结束日期早于开始日期。')
                if collection == 'education':
                    proof = completion(p, i, manifest)
                    if any(x['person_id']==pid and x['field'].startswith(f'education[{i}]') and x['code'] in ('invalid_date','implausible_early_date','end_before_start') for x in issues):
                        proof = {**proof,'eligible':False,'reason':'教育日期存在未解决异常，暂停用于学历学位摘要。'}
                    if parsed.get('end') and parsed['end'][0] > today:
                        proof = {**proof, 'eligible': False, 'reason': '未来毕业时间不能作为已毕业记录。'}
                    education[f'{pid}:education[{i}]'] = proof
                    if (record.get('status') not in ('in_progress', 'incomplete') and not proof['eligible']) or proof.get('conflict'):
                        issue(pid, f'education[{i}].status', 'graduation_unverified', record.get('status', 'unknown'), proof['reason'])
        value = p['fields'].get('meta', {}).get('start', '')
        if value:
            try:
                interval = date_interval(value)
                if interval and (interval[0].year < int(data.get('minimum_resume_year', 1950)) or interval[0] > today):
                    issue(pid, 'meta.start', 'implausible_summary_date', value, '参加工作时间超出合理范围。')
            except (ValueError, OverflowError):
                issue(pid, 'meta.start', 'invalid_date', value, '参加工作时间包含无效日期或非零时间。')
        eligible=[i for i,e in enumerate(p['fields'].get('education',[])) if education.get(f'{pid}:education[{i}]',{}).get('eligible')]
        selected=eligible[0] if len(eligible)==1 else None
        if len(eligible)>1:
            intervals=[]
            for i in eligible:
                try:intervals.append(date_interval(p['fields']['education'][i].get('end','')))
                except ValueError:intervals.append(None)
            choices=[i for i,interval in zip(eligible,intervals) if interval and all(other and interval[1]>=other[0] for other in intervals)]
            if len(choices)==1:selected=choices[0]
            else:issue(pid,'meta.level','graduation_selection_ambiguous','', '多条已毕业教育的日期相同、精度重叠或缺失，无法确定最近一条。')
        if check_summary:
            expected=p['fields']['education'][selected] if selected is not None else {}
            meta=p['fields'].get('meta',{})
            if any(str(meta.get(k,''))!=str(expected.get(k,'')) for k in ('level','degree')) or ('education_selection' in p and p['education_selection'].get('index')!=selected):
                issue(pid,'meta.level/degree','summary_source_mismatch', {k:meta.get(k,'') for k in ('level','degree')}, '学历学位摘要未与最近且有毕业依据的教育记录一致；须重新执行规则。')
    # Original Excel dates must remain visible even if a target value was blanked.
    if manifest:
        from source_audit import units_for
        for s in manifest['sources']:
            owners=[p['id'] for p in data['people'] if s['id'] in p.get('source_ids',[])]
            for u in units_for(s):
                text=str(u.get('text',''))
                if u.get('kind')=='excel_cell' and re.fullmatch(r'\d{4}-\d{2}-\d{2}(?:T[\d:.]+)?',text):
                    try:
                        interval=date_interval(text)
                        anomaly=interval and interval[0].year<int(data.get('minimum_resume_year',1950))
                    except ValueError:anomaly=True
                    if anomaly:
                        for pid in owners:
                            issues.append({'person_id':pid,'source_id':s['id'],'field':'source_date:'+u.get('locator',''),
                                           'code':'source_date_anomaly','value':text,'reason':'原始 Excel 日期单元格异常，即使目标留空也须核对原值/格式。',
                                           'quote':text,'unit_id':u['unit_id'],'locator':u.get('locator','')})
    return {'schema_version': 1, 'as_of': processing,
            'bindings': current_bindings(data, manifest) if manifest else {'data_sha256': digest(data)},
            'education': education, 'issues': issues, 'open_issues': len(issues),
            'status': 'passed' if not issues else 'needs_review'}


def main():
    from source_audit import load, dump
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data', type=Path, required=True); p.add_argument('--sources', type=Path, required=True)
    p.add_argument('--as-of'); p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    if a.out.exists(): p.error('Use a new report path.')
    report = validate(load(a.data), load(a.sources), a.as_of)
    dump(a.out, report)
    print(json.dumps({'status': report['status'], 'open_issues': report['open_issues']}))
    return 0 if not report['issues'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
