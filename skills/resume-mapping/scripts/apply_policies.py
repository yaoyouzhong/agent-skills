"""Apply completed-education and evidence-backed client policies, with an audit."""
import argparse
import copy
import json
import re
import sys
from pathlib import Path


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def dump(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def norm(text):
    return re.sub(r'\s+', '', str(text))


def degree_for(level):
    if '大专' in level or '专科' in level:
        return ''
    if '博士' in level:
        return '博士'
    if '硕士' in level or '研究生' in level:
        return '硕士'
    if '本科' in level or '学士' in level:
        return '学士'
    return ''


def date_key(value):
    from record_checks import date_interval
    try:
        interval = date_interval(value)
    except (ValueError, OverflowError):
        return None
    return interval


def apply(data, client_candidates=None, manifest=None):
    result = copy.deepcopy(data)
    audit, review = [], []
    from record_checks import validate
    checks = validate(result, manifest, check_summary=False)
    review.extend(checks['issues'])
    by_id = {str(p['id']): p for p in result['people']}
    if len(by_id) != len(result['people']):
        raise ValueError('Person IDs must be unique.')
    def change(person, obj, key, value, reason, evidence, path=None):
        old = obj.get(key, '')
        obj[key] = value
        if old != value:
            audit.append({'person_id': person['id'], 'field': path or key, 'before': old, 'after': value,
                          'reason': reason, 'evidence': evidence})
        person.setdefault('field_facts',{})[path or key]={'origin':'user_default' if reason=='user_degree_default' else 'source_selected' if reason=='latest_completed_education' else 'intentionally_blank' if reason=='college_has_no_degree' else 'source_inferred',
            'value':value,'rule':reason,'reason':reason,'evidence':evidence}
    for person in result['people']:
        fields = person['fields']
        completed = []
        for index, entry in enumerate(fields.get('education', [])):
            state = entry.get('status', 'unknown')
            level = str(entry.get('level', ''))
            if re.search(r'大专|专科', level):
                if str(entry.get('degree','')).strip() not in ('','无','无学位','没有','不适用','—','-','None'):
                    review.append({'person_id': person['id'], 'education': index, 'issue': 'College education has an unexpected degree; output left blank.'})
                change(person, entry, 'degree', '', 'college_has_no_degree', {'education': index},f'education[{index}].degree')
            words = ' '.join(str(entry.get(k, '')) for k in ('level', 'end', 'status_text'))
            unfinished = bool(re.search(r'在读|未毕业|肄业|在校|至今|预计|预期|中退|结业', words))
            if state == 'completed' and unfinished:
                review.append({'person_id': person['id'], 'education': index, 'issue': 'Conflicting completed/in-progress evidence.'})
                continue
            proof = checks['education'][f"{person['id']}:education[{index}]"]
            if state != 'completed' or not proof['eligible']:
                fact = person.get('field_facts', {}).get(f'education[{index}].degree', {})
                if fact.get('origin') == 'user_default':
                    change(person, entry, 'degree', '', 'withdraw_unsupported_degree_default', {'education': index}, f'education[{index}].degree')
                    person['field_facts'][f'education[{index}].degree'].update(origin='intentionally_blank', reason=proof['reason'])
                if state not in ('in_progress', 'incomplete') and not unfinished:
                    review.append({'person_id': person['id'], 'education': index, 'issue': 'Graduation status must be verified.'})
                continue
            completed.append((index, entry))
            level = str(entry.get('level', ''))
            if '大专' in level or '专科' in level:
                if str(entry.get('degree','')).strip() not in ('','无','无学位','没有','不适用','—','-','None'):
                    review.append({'person_id': person['id'], 'education': index, 'issue': 'College education has an unexpected degree; output left blank.'})
                change(person, entry, 'degree', '', 'college_has_no_degree', {'education': index},f'education[{index}].degree')
            elif not entry.get('degree') and degree_for(level):
                change(person, entry, 'degree', degree_for(level), 'user_degree_default', {'education': index, 'level': level},f'education[{index}].degree')
        selected = None
        if len(completed) == 1:
            selected = completed[0]
        elif completed:
            keys = [date_key(e.get('end', '')) for _, e in completed]
            if all(keys):
                choices = [pair for pair, key in zip(completed, keys)
                           if all(key[1] >= other[0] for other in keys)]
                if len(choices) == 1:
                    selected = choices[0]
            if selected is None:
                review.append({'person_id': person['id'], 'issue': 'Latest completed education is ambiguous; verify graduation dates.'})
        else:
            review.append({'person_id': person['id'], 'issue': 'No verified graduated education; summary left blank.'})
        meta = fields.setdefault('meta', {})
        summary = selected[1] if selected else {}
        person['education_selection']={'index':selected[0] if selected else None,'rule':'latest_completed_education','based_on':'verified completion evidence for the source record; not an independent credential verification',
            'completion_evidence':checks['education'].get(f"{person['id']}:education[{selected[0]}]") if selected else None}
        evidence = {'education': selected[0], 'end': summary.get('end', '')} if selected else {'education': None}
        for key in ('level', 'degree'):
            change(person, meta, key, summary.get(key, ''), 'latest_completed_education', evidence,'meta.'+key)
    for candidate in client_candidates or []:
        person = by_id[str(candidate['person_id'])]
        collection = candidate.get('collection', 'projects')
        if collection not in ('projects', 'jobs'):
            raise ValueError('Client evidence must belong to projects or jobs.')
        index = candidate['index']
        if not isinstance(index, int) or index < 0:
            raise ValueError('Client record index must be a nonnegative integer.')
        record = person['fields'][collection][index]
        if record.get('client'):
            continue
        client, quote = candidate['client'].strip(), candidate['quote'].strip()
        source = norm('\n'.join(str(record.get(k, '')) for k in ('name', 'desc', 'intro', 'details','resp','tech')))
        if not client or not quote or norm(quote) not in source or any(norm(c) not in norm(quote) for c in re.split('[、;；]', client) if c):
            raise ValueError(f'Unsubstantiated client evidence for {person["id"]}/{collection}/{index}.')
        if manifest is None:
            raise ValueError('Client enrichment requires the original source manifest and a quoted source unit.')
        from source_audit import units_for
        source_record=next(s for s in manifest['sources'] if s['id']==candidate['source_id'])
        unit=next(u for u in units_for(source_record) if u['unit_id']==candidate['unit_id'])
        if candidate['source_id'] not in person['source_ids'] or quote not in unit['text']:
            raise ValueError('Client quote does not come from the original source.')
        if collection=='projects' and candidate['unit_id'] not in person['record_sources'][f'projects[{index}]']['unit_ids']:
            raise ValueError('Client quote belongs to another project.')
        from semantic_checks import client_role
        role=client_role(client,quote,candidate.get('role_review'))
        if role not in ('explicit_client','reviewed_contextual_client'):
            review.append({'person_id':person['id'],'field':f'{collection}[{index}].client','code':role,
                           'reason':'原文实体需核对客户/实施方/供应商角色；客户暂留空。','value':client})
            continue
        change(person, record, 'client', client, 'extract_client_from_corresponding_project',
               {'collection': collection, 'index': index, 'quote': quote, 'source_id':candidate['source_id'],'unit_id':candidate['unit_id'],
                'locator':unit.get('locator','')},f'{collection}[{index}].client')
        person['field_facts'][f'{collection}[{index}].client']['source_quotes']=[{'source_id':candidate['source_id'],'unit_id':candidate['unit_id'],'quote':unit['text'],'locator':unit.get('locator','')}]
    return result, audit, review


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--clients', type=Path)
    parser.add_argument('--sources',type=Path)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--audit', type=Path, required=True)
    args = parser.parse_args()
    if args.out.resolve() == args.audit.resolve() or args.out.exists() or args.audit.exists():
        parser.error('Use distinct new output/audit paths.')
    result, audit, review = apply(load(args.data), load(args.clients) if args.clients else [],load(args.sources) if args.sources else None)
    dump(args.out, result)
    dump(args.audit, {'changes': audit, 'needs_review': review})
    print(json.dumps({'people': len(result['people']), 'changes': len(audit), 'needs_review': len(review)}))
    return 2 if review else 0


if __name__ == '__main__':
    sys.exit(main())
