"""Audit original source units against structured resume fields, before template generation."""
import argparse
import collections
import hashlib
import json
import re
import sys
import unicodedata
from functools import lru_cache
from pathlib import Path
from extract_sources import sha
from pdf_intake import fingerprint

LABELS = ('个人信息','个人概况','基本信息','个人简历','教育背景','教育经历','工作经历','工作经验','任职经历','专业技能','职业技能','项目经验','项目经历','具备的特长与专业技能','项目开始时间','项目结束时间','项目名称','客户名称','项目描述','项目介绍','项目简介','技术栈及开发平台','软件环境','开发环境','技术应用','开发技术','技术要点','技术栈','项目职责','责任描述','职责描述','工作内容及职责','工作职务及职责','毕业院校','毕业专业','开始时间','结束时间','就职单位','岗位','职务','学历','学位','技术方向','性别','民族','姓名','移动电话','参加工作时间','本行业工作年限','资质证书')
LABELS += ('主要职责','个人职责','个人职责及使用技术','项目职责与亮点','负责工作','负责业务','核心工作','核心职责','核心贡献与亮点','工作描述','工作内容','项目技术','使用技术','所用技术','软件架构','项目规模（项目团队人员数量）','出生年月','籍贯','婚姻状况','年龄','时间','最高学历','工作年限','联系电话','联系电话/微信','电子邮件','邮箱','手机号码','手机','电话','专业','毕业时间','职位名称','开发周期','项目时间','任职时间','担任职位','内容','背景','定位','业绩产出','项目成果','代表项目','个人优势','核心优势','优势亮点','个人技能','技术能力','荣誉奖项','语言','自我评价','技能水平','求职意向','求职简历','主要项目经验')
LABELS += ('职责',)


@lru_cache(maxsize=50000)
def norm(value):
    text = unicodedata.normalize('NFKC', str(value))
    text = re.sub(r'((?:19|20)\d{2})\s*年\s*(\d{1,2})(?!\d)\s*月(?:\s*(\d{1,2})(?!\d)\s*日)?',
                  lambda m: m[1]+m[2].zfill(2)+(m[3].zfill(2) if m[3] else ''), text)
    # An ASCII date must not consume the first character of the following cell
    # (for example, 2023-05-31 followed by 日照银行 or 日本三菱).
    text = re.sub(r'((?:19|20)\d{2})\s*[./-]\s*(\d{1,2})(?!\d)(?:\s*[./-]\s*(\d{1,2})(?!\d))?',
                  lambda m: m[1]+m[2].zfill(2)+(m[3].zfill(2) if m[3] else ''), text)
    text = re.sub(r'(?<!\d)((?:19|20)\d{2})\s*年',r'\1',text)
    return re.sub(r'[^A-Za-z0-9\u4e00-\u9fff]', '', text).lower()


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def dump(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def leaves(obj, prefix=''):
    if isinstance(obj, dict):
        for key, value in obj.items():
            if not (key == 'status' and re.fullmatch(r'education\[\d+\]',prefix)):
                yield from leaves(value, prefix + ('.' if prefix else '') + key)
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            yield from leaves(value, f'{prefix}[{index}]')
    elif obj is not None and str(obj).strip():
        yield prefix, str(obj)


def get_path(fields, path):
    obj = fields
    for name, index in re.findall(r'([^.\[\]]+)|\[(\d+)\]', path):
        obj = obj[int(index)] if index else obj[name]
    return obj


def validate_unit_owner(person,unit):
    """Every fact from a reviewed image must belong to this person, not only graduation."""
    if unit.get('kind')!='reviewed_media_text':return
    if unit.get('review_status')!='visually_reviewed' or not unit.get('reviewer') or not unit.get('owner_name') or norm(unit['owner_name'])!=norm(person['fields'].get('meta',{}).get('name','')):
        raise ValueError('Reviewed media fact belongs to another or unverified person.')
    if sha(unit['asset_path'])!=unit['asset_sha256']:raise ValueError('Reviewed media pixels changed.')
    if unit.get('owner_person_id') is not None and str(unit['owner_person_id'])!=str(person['id']):
        raise ValueError('Reviewed media belongs to a different person ID.')
    for check in unit.get('identity_checks',[]):
        if not check.get('field') or str(get_path(person['fields'],check['field']))!=str(check.get('value')):
            raise ValueError('Additional image identity evidence does not match this person.')


def validate_person_scope(person,sid,uid):
    scope=person.get('person_source_scope')
    if scope is not None and uid not in scope.get(sid,[]):
        raise ValueError('Fact quote is outside the selected person source scope.')


def units_for(source):
    detail = load(source['detail_file'])
    if 'units' in detail:
        return detail['units']
    units = []
    for block in detail.get('blocks', []):
        units.append({'kind': 'word_block', 'text': block['text'], 'locator': block['location']})
    for sheet in detail.get('sheets', []):
        for cell in sheet['cells']:
            if cell.get('value') is not None:
                units.append({'kind': 'excel_cell', 'text': cell.get('display_value',str(cell['value'])),
                              'locator': f"{sheet['sheet']}!{cell['cell']}", 'sheet': sheet['sheet'], 'cell': cell['cell'],
                              'hidden': sheet['state'] != 'visible' or cell.get('row_hidden') or cell.get('column_hidden')})
                # A reader can turn an oversized numeric date-style value into
                # #VALUE!. Expose the untouched numeric XML value separately;
                # its date meaning still requires the source label and review.
                raw=cell.get('raw_value')
                if cell.get('type')=='e' and cell.get('raw_type') not in ('e','s','str') and raw is not None and re.fullmatch(r'[+-]?\d+(?:\.\d+)?',str(raw)):
                    units.append({'kind':'excel_raw_cell','text':str(raw),'locator':f"{sheet['sheet']}!{cell['cell']}/raw_value",
                                  'sheet':sheet['sheet'],'cell':cell['cell'],'reader_value':str(cell['value']),
                                  'number_format':cell.get('number_format'),'raw_type':cell.get('raw_type'),'style_index':cell.get('style_index')})
    if 'rows' in detail:
        for ri, row in enumerate(detail['rows'], 1):
            for ci, value in enumerate(row, 1):
                if value:
                    units.append({'kind': 'delimited_cell', 'text': value, 'locator': f'row {ri} column {ci}'})
    if not units and source.get('text_file'):
        for index, line in enumerate(Path(source['text_file']).read_text(encoding='utf-8').splitlines(), 1):
            if line.strip():
                units.append({'kind': 'text_line', 'text': line, 'locator': f'line {index}'})
    for unit in units:
        unit['unit_id'] = 'u-' + fingerprint(unit)
    return units


@lru_cache(maxsize=50000)
def payload(text):
    value = unicodedata.normalize('NFKC', text).strip()
    value = re.sub(r'^\s*[•●▪★·]*\s*', '', value)
    value = re.sub(r'^项目[一二三四五六七八九十\d]+\s*[:：]\s*', '', value)
    for label in sorted(LABELS, key=len, reverse=True):
        pattern = r'\s*'.join(re.escape(ch) for ch in label)
        value = re.sub(pattern + r'\s*[:：]\s*', ' ', value)
    return value


def grams(value):
    if len(value) < 3:
        return {value} if value else set()
    return {value[i:i+3] for i in range(len(value)-2)}


def coverage(value, texts):
    value = norm(payload(value))
    if not value:
        return 1.0
    if any(value in text for text in texts):
        return 1.0
    represented = [False]*len(value)
    for index in range(max(1, len(value)-2)):
        token = value[index:index+3]
        if any(token in text for text in texts):
            for k in range(index, min(len(value), index+3)):
                represented[k] = True
    for text in texts:
        if 0 < len(text) < 3:
            for match in re.finditer(re.escape(text), value):
                for k in range(match.start(), match.end()):
                    represented[k] = True
    return sum(represented)/len(value)


def current_bindings(data, manifest):
    sources = []
    for source in manifest['sources']:
        if source.get('detail_file'):
            for media in load(source['detail_file']).get('media_reviews',[]):
                if sha(media['asset_path'])!=media['asset_sha256']:raise ValueError('Reviewed media pixels changed: '+source['id'])
        sources.append({'id': source['id'], 'source': sha(source['source']),
                        'text': sha(source['text_file']) if source.get('text_file') else None,
                        'detail': sha(source['detail_file']) if source.get('detail_file') else None})
        if sources[-1]['source'] != source['sha256']:
            raise ValueError('Source changed: ' + source['id'])
        for key in ('text', 'detail'):
            expected = source.get(key+'_sha256')
            if expected and sources[-1][key] != expected:
                raise ValueError('Extraction evidence changed: '+source['id']+'/'+key)
    return {'data_sha256': hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
            'sources': sources, 'audit_engine_sha256': sha(__file__)}


def audit(data, manifest):
    bindings = current_bindings(data, manifest)
    from semantic_checks import check_identity
    check_identity(data,manifest)
    people = data['people']
    fields_by_person = {str(p['id']): list(leaves(p['fields'])) for p in people}
    decisions = data.get('coverage_decisions', {})
    source_units={s['id']:{u['unit_id']:u for u in units_for(s)} for s in manifest['sources']}
    for person in people:
        used_anchors=set()
        for index,project in enumerate(person['fields'].get('projects', [])):
            path=f'projects[{index}]'
            record=person.get('record_sources',{}).get(path)
            if not record:
                if data.get('require_record_evidence'):
                    raise ValueError('Missing project provenance: '+str(person['id'])+'/'+path)
                continue
            sid=record['source_id']
            if sid not in person['source_ids'] or any(uid not in source_units[sid] for uid in record['unit_ids']):
                raise ValueError('Project scope contains another source or nonexistent units.')
            for uid in record['unit_ids']:validate_unit_owner(person,source_units[sid][uid])
            anchor=record['anchor_unit_id']
            if anchor not in record['unit_ids'] or (sid,anchor) in used_anchors:
                raise ValueError('Project anchors must be distinct and included in their own scope.')
            used_anchors.add((sid,anchor))
        for entry in person.get('evidence',[]):
            for quote in entry.get('source_quotes',[]):
                sid,uid=quote['source_id'],quote['unit_id']
                if sid not in person['source_ids'] or uid not in source_units[sid] or quote['quote']!=source_units[sid][uid]['text']:
                    raise ValueError('Evidence quote does not match the original source unit.')
                validate_unit_owner(person,source_units[sid][uid])
        records=[(path,record) for path,record in person.get('record_sources',{}).items() if re.fullmatch(r'projects\[\d+\]',path)]
        for path,record in records:
            for other_path,other in records:
                if path!=other_path and record['source_id']==other['source_id'] and other['anchor_unit_id'] in record['unit_ids']:
                    raise ValueError('Project scope includes another project title: '+str(person['id'])+'/'+path)
    results, issues = [], []
    all_keys = set()
    for source in manifest['sources']:
        owners = [p for p in people if source['id'] in p['source_ids']]
        if not owners and source['id'] not in data.get('excluded_sources', {}):
            raise ValueError('Source has no owner or explicit exclusion: ' + source['id'])
        for unit in units_for(source):
            key = source['id']+':'+unit['unit_id']
            all_keys.add(key)
            base = {'key': key, 'source_id': source['id'], 'unit_id': unit['unit_id'], 'locator': unit.get('locator', ''),
                    'text': unit['text'], 'page': unit.get('page'), 'bbox': unit.get('bbox')}
            text = norm(unit['text'])
            if not text:
                base.update(status='non_text')
            elif unit.get('classification') == 'page_number' or unit.get('running_repeat_of'):
                base.update(status='layout_metadata', reason=unit.get('classification') or 'repeated running header/footer')
            elif text in {norm(label) for label in LABELS} or re.fullmatch(r'项目经历\d+', text):
                base.update(status='structure_label')
            elif not owners:
                base.update(status='source_excluded', reason=data['excluded_sources'][source['id']])
            elif key in decisions:
                base.update(status='review')
            else:
                matches = []
                for person in owners:
                    if unit.get('kind')=='reviewed_media_text' and norm(unit.get('owner_name',''))!=norm(person['fields'].get('meta',{}).get('name','')):continue
                    eligible = fields_by_person[str(person['id'])]
                    scopes = [(path, record) for path, record in person.get('record_sources', {}).items()
                              if record['source_id'] == source['id'] and unit['unit_id'] in record['unit_ids']]
                    if scopes:
                        directly_quoted={e['field'] for e in person.get('evidence',[]) if not e['field'].startswith('projects[') and
                                         any(q['source_id']==source['id'] and q['unit_id']==unit['unit_id'] for q in e.get('source_quotes',[]))}
                        eligible = [(k,v) for k,v in eligible if any(k.startswith(path+'.') for path,_ in scopes) or k in directly_quoted]
                    texts = [norm(v) for _,v in eligible]
                    score = coverage(unit['text'], texts)
                    candidates = sorted(((coverage(unit['text'], [norm(value)]), path) for path,value in eligible), reverse=True)
                    matches.append((score, str(person['id']), [path for value,path in candidates[:4] if value > .1], bool(scopes)))
                score, owner, paths, scoped = max(matches)
                base.update(person_id=owner, coverage=round(score,5), candidate_fields=paths,
                            ownership='record' if scoped else 'person', status='covered' if score == 1.0 else 'review')
            decision = decisions.get(key)
            if decision:
                if decision.get('quote', '') != unit['text'] or not decision.get('reason'):
                    raise ValueError('Coverage decision lacks exact source quote/reason: ' + key)
                disposition = decision.get('disposition')
                if disposition not in ('excluded_by_user', 'represented_equivalently', 'source_label', 'non_resume_content','retained_conflict'):
                    raise ValueError('Invalid coverage disposition: ' + key)
                if disposition == 'excluded_by_user' and not decision.get('authority'):
                    raise ValueError('Source exclusion needs the applicable user instruction.')
                if disposition == 'represented_equivalently':
                    if decision.get('stale_before_date_normalization'):
                        raise ValueError('Equivalent representation was already stale before date normalization; review it again.')
                    person = next(p for p in owners if str(p['id']) == str(decision['person_id']))
                    validate_unit_owner(person,unit)
                    if not decision.get('field_paths'):
                        raise ValueError('Equivalent representation must identify output fields.')
                    for path in decision['field_paths']:
                        if not str(get_path(person['fields'], path)).strip():
                            raise ValueError('Equivalent representation refers to an empty output field.')
                        if path not in decision.get('field_values', {}) or decision['field_values'][path] != get_path(person['fields'], path):
                            raise ValueError('Equivalent representation review is stale or lacks the reviewed field value.')
                if disposition=='retained_conflict':
                    conflict=next((c for c in data.get('source_conflicts',[]) if c.get('id')==decision.get('conflict_id')),None)
                    if not conflict or not conflict.get('reason') or not any(q.get('source_id')==source['id'] and q.get('unit_id')==unit['unit_id'] and q.get('quote')==unit['text'] for q in conflict.get('source_quotes',[])):
                        raise ValueError('Conflict disposition lacks a retained exact source fact.')
                base.update(status='retained_conflict' if disposition=='retained_conflict' else 'resolved', resolution=decision)
            results.append(base)
            if base['status'] in ('review','retained_conflict'):
                issues.append(base)
    for conflict in data.get('source_conflicts',[]):
        if not conflict.get('id') or not conflict.get('reason') or not conflict.get('source_quotes'):
            raise ValueError('Source conflict needs an ID, reason and actual source facts.')
        for quote in conflict['source_quotes']:
            if quote.get('quote')!=source_units[quote['source_id']][quote['unit_id']]['text']:
                raise ValueError('Source conflict quote changed.')
        issues.append({'key':conflict['id'],'status':'retained_conflict','conflict':conflict})
    obsolete = set(decisions)-all_keys
    if obsolete:
        raise ValueError('Stale decisions refer to source units that no longer exist: '+str(sorted(obsolete)[:4]))
    return {'schema_version': 2, 'bindings': bindings, 'summary': {'sources': len(manifest['sources']), 'people': len(people),
             'units': len(results), 'statuses': dict(collections.Counter(r['status'] for r in results)), 'open_issues': len(issues)},
            'units': results, 'issues': issues, 'status': 'passed' if not issues else 'needs_review'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--sources', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error('Use a new report path.')
    result = audit(load(args.data), load(args.sources))
    dump(args.out, result)
    print(json.dumps(result['summary'], ensure_ascii=False))
    return 0 if result['status'] == 'passed' else 2


if __name__ == '__main__':
    sys.exit(main())
