"""Present each source once and hydrate exact evidence references without inventing facts."""
import copy
import json
from pathlib import Path
from source_audit import units_for, load, dump, get_path, validate_unit_owner, validate_person_scope
from extract_sources import sha


def snapshot(manifest):
    result = {}
    for source in manifest['sources']:
        actual = {'source_sha256': sha(source['source']), 'detail_sha256': sha(source['detail_file']),
                  'text_sha256': sha(source['text_file']) if source.get('text_file') else None}
        if actual['source_sha256'] != source['sha256'] or any(source.get(key) and source[key] != actual[key] for key in ('detail_sha256', 'text_sha256')):
            raise ValueError('Source/extraction changed; prepare a current review snapshot first.')
        result[source['id']] = actual
    return result


def bundle(manifest, folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=False)
    index = []
    for source in manifest['sources']:
        if source['status'] == 'error':
            index.append({'source_id': source['id'], 'status': 'error', 'error': source.get('error')})
            continue
        units = units_for(source)
        path = folder/(source['id']+'.md')
        lines = [f"# {source['id']}", '', 'Source: '+source['source'],
                 'Warnings: '+json.dumps(source.get('warnings', []), ensure_ascii=False), '',
                 'One file is not necessarily one person. Retain every business fact; verify ownership and record boundaries.', '']
        for unit in units:
            locator = unit.get('locator') or ('page '+str(unit.get('page', '?')))
            # Full original unit text, no model summary or character truncation.
            lines.extend([f"[{unit['unit_id']} | {locator}]", unit['text'], ''])
        path.write_text('\n'.join(lines), encoding='utf-8')
        index.append({'source_id': source['id'], 'source': source['source'], 'source_sha256': source['sha256'],
                      'bundle': str(path.resolve()), 'unit_count': len(units),
                      'text_characters': sum(len(u['text']) for u in units), 'warnings': source.get('warnings', [])})
    dump(folder/'index.json', {'sources': index, 'scope': 'Complete source units; not a semantic extraction.'})
    return {'index': str((folder/'index.json').resolve()), 'source_count': len(index)}


def hydrate(data, manifest, replace_located=False):
    """Expand optional compact references; existing exact evidence stays unchanged.

    refs and field_facts are authored by the Agent. A reference proves only that
    the quotation exists and belongs to the person, not its semantic meaning.
    Existing record and fact gates still validate the resulting data.
    """
    result = copy.deepcopy(data)
    ordered = {s['id']: units_for(s) for s in manifest['sources']}
    inventory = {sid: {u['unit_id']: u for u in units} for sid, units in ordered.items()}
    sources = {s['id']: s for s in manifest['sources']}
    owners = {sid: [p['id'] for p in result['people'] if sid in p['source_ids']] for sid in sources}
    current = snapshot(manifest)
    for person in result['people']:
        if any(person.get(key) for key in ('record_refs', 'field_text_refs', 'evidence_refs', 'blank_review_groups')):
            if any(result.get('source_snapshot', {}).get(sid) != current[sid] for sid in person['source_ids']):
                raise ValueError('Compact evidence/blank reviews refer to an old or missing source_snapshot; reread changed sources.')
        if any(len(owners[sid]) > 1 and not person.get('person_source_scope', {}).get(sid) for sid in person['source_ids']):
            raise ValueError('Shared multi-person sources require explicit person_source_scope before compact references are expanded.')
        def expand(ref):
            sid, uid = ref['source_id'], ref['unit_id']
            if sid not in person['source_ids'] or sid not in inventory or uid not in inventory[sid]:
                raise ValueError('Evidence reference is outside the person source set.')
            validate_person_scope(person, sid, uid)
            unit = inventory[sid][uid]
            validate_unit_owner(person, unit)
            if 'quote' in ref and ref['quote'] != unit['text']:
                raise ValueError('Explicit quote differs from its original source unit.')
            return {**ref, 'quote': unit['text'], 'source_sha256': sources[sid]['sha256'],
                    **{k: unit[k] for k in ('locator', 'page', 'bbox') if k in unit}}
        def selected(spec):
            sid = spec['source_id']
            if sid not in person['source_ids']:
                raise ValueError('Text references contain another person source.')
            ids = spec.get('unit_ids')
            if ids is None:
                all_ids = [u['unit_id'] for u in ordered[sid]]
                first, last = all_ids.index(spec['from_unit']), all_ids.index(spec['through_unit'])
                if last < first:
                    raise ValueError('Reversed original unit range.')
                ids = all_ids[first:last+1]
            if not ids or len(ids) != len(set(ids)):
                raise ValueError('Text references must contain distinct original units.')
            return [expand({'source_id': sid, 'unit_id': uid}) for uid in ids]
        for path, spec in person.pop('record_refs', {}).items():
            import re
            if not re.fullmatch(r'(projects|jobs|education)\[\d+\]', path):
                raise ValueError('Invalid record reference path.')
            get_path(person['fields'], path)
            quotes = selected(spec)
            if spec['anchor_unit_id'] not in [q['unit_id'] for q in quotes] or not spec.get('reason'):
                raise ValueError('Record references need their own anchor and a boundary reason.')
            if path in person.get('record_sources', {}):
                raise ValueError('Use record_refs or full record_sources, not both.')
            person.setdefault('record_sources', {})[path] = {
                'source_id': spec['source_id'], 'anchor_unit_id': spec['anchor_unit_id'],
                'unit_ids': [q['unit_id'] for q in quotes], 'source_sha256': sources[spec['source_id']]['sha256'],
                'pages': sorted({q['page'] for q in quotes if q.get('page') is not None}), 'reason': spec['reason']}
        for path, spec in person.pop('field_text_refs', {}).items():
            value = get_path(person['fields'], path)
            if value not in ('', None):
                raise ValueError('Text references may only materialize an empty draft field.')
            quotes = selected(spec)
            import re
            record_match = re.match(r'((?:projects|jobs|education)\[\d+\])\.', path)
            if record_match:
                record = person.get('record_sources', {}).get(record_match[1])
                if not record or record['source_id'] != spec['source_id'] or not all(q['unit_id'] in record['unit_ids'] for q in quotes):
                    raise ValueError('Text references must stay inside their own verified record scope.')
            separator = spec.get('join', '\n')
            if separator not in ('', ' ', '\n'):
                raise ValueError('Only whitespace separators are supported for exact source text.')
            text = separator.join(q['quote'] for q in quotes)
            prefix = spec.get('strip_prefix', '')
            if prefix:
                if not text.startswith(prefix):
                    raise ValueError('The explicit source label prefix was not found.')
                text = text[len(prefix):]
            # Resolve the actual object, retaining array indices and all other fields.
            tokens = re.findall(r'([^.[\]]+)|\[(\d+)\]', path)
            obj = person['fields']
            for name, index in tokens[:-1]:
                obj = obj[int(index)] if index else obj[name]
            name, index = tokens[-1]
            obj[int(index) if index else name] = text
            if path in person.get('evidence_refs', {}) or any(e['field'] == path for e in person.get('evidence', [])):
                raise ValueError('Text reference fields must not have a second evidence declaration.')
            person.setdefault('evidence', []).append({'field': path, 'source_quotes': quotes,
                'origin': 'source_assembled' if len(quotes) > 1 else 'source_direct'})
        evidence = {e['field']: e for e in person.get('evidence', [])}
        for path, refs in person.pop('evidence_refs', {}).items():
            get_path(person['fields'], path)  # Reject nonexistent field paths.
            if path in evidence and not replace_located:
                raise ValueError('Use evidence_refs or full evidence for a field, not both.')
            evidence[path] = {'field': path, 'source_quotes': [expand(ref) for ref in refs],
                              'origin': 'source_assembled' if len(refs) > 1 else 'source_direct' if refs else 'needs_review'}
        person['evidence'] = list(evidence.values())
        for fact in person.get('field_facts', {}).values():
            if 'source_refs' in fact:
                if fact.get('source_quotes'):
                    raise ValueError('Use source_refs or source_quotes for a fact, not both.')
                fact['source_quotes'] = [expand(ref) for ref in fact.pop('source_refs')]
        for proof in person.get('education_status_evidence', {}).values():
            if 'source_refs' in proof:
                if proof.get('source_quotes'):
                    raise ValueError('Use source_refs or source_quotes for graduation evidence, not both.')
                proof['source_quotes'] = [expand(ref) for ref in proof.pop('source_refs')]
        for group in person.pop('blank_review_groups', []):
            if not group.get('reason') or not group.get('reviewer') or not group.get('fields') or group.get('classification') not in (
                'source_not_provided', 'insufficient', 'unreadable', 'intentional_rule', 'already_represented', 'available_but_missed'):
                raise ValueError('Blank review groups need explicit field paths, classification and source-review reason.')
            for path in group['fields']:
                if get_path(person['fields'], path) not in ('', None):
                    raise ValueError('Blank review groups cannot cover a nonempty field.')
                if path in person.get('blank_reviews', {}):
                    raise ValueError('Duplicate blank review decision.')
                person.setdefault('blank_reviews', {})[path] = {k: v for k, v in group.items() if k != 'fields'}
                # One explicit, version-bound source review feeds both coverage
                # and typed facts; do not ask the Agent to repeat the decision.
                fact = person.setdefault('field_facts', {}).get(path)
                if group['classification'] == 'source_not_provided' and (not fact or fact.get('origin') in ('needs_review', 'not_provided')):
                    person['field_facts'][path] = {'origin': 'not_provided', 'value': '', 'reviewed_value': '',
                        'reason': group['reason'], 'reviewer': group['reviewer'],
                        'source_binding': {sid: sources[sid]['sha256'] for sid in person['source_ids']}}
                elif group['classification'] in ('insufficient', 'unreadable', 'available_but_missed'):
                    person['field_facts'][path] = {'origin': 'needs_review', 'value': '', 'reviewed_value': '',
                        'reason': group['reason'], 'reviewer': group['reviewer'],
                        'source_binding': {sid: sources[sid]['sha256'] for sid in person['source_ids']}}
    return result


def exceptions(data, manifest, mapping, coverage, reports, folder):
    """Group actual target blanks and issues, with links to complete source bundles."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=False)
    by_person = {str(p['id']): {'person_id': p['id'], 'name': p['fields'].get('meta', {}).get('name', ''),
                 'source_ids': p['source_ids'], 'blank_slots': [], 'issues': []} for p in data['people']}
    # Coverage schema is deliberately consumed without dropping unfamiliar slots.
    slots = coverage.get('slots', coverage.get('rows', []))
    if not slots:
        slots = [s for person in coverage.get('people', []) for s in person.get('slots', [])]
    for slot in slots:
        pid = str(slot.get('person_id', ''))
        if slot.get('empty') or slot.get('status') in ('blank', 'empty') or slot.get('filled') is False:
            if pid not in by_person:
                raise ValueError('Blank slot has no known person.')
            by_person[pid]['blank_slots'].append(slot)
    unassigned = []
    for name, report in reports.items():
        for issue in report.get('issues', []):
            row = {'report': name, **issue}
            pid = str(issue.get('person_id', ''))
            (by_person[pid]['issues'] if pid in by_person else unassigned).append(row)
    result = {'people': list(by_person.values()), 'unassigned_issues': unassigned,
              'source_manifest': {s['id']: {'source': s['source'], 'detail': s.get('detail_file')} for s in manifest['sources']},
              'review_rule': 'Check each target blank against all relevant source text; prior not_provided is not fresh review. '
                             'Resolve omission/misassignment; keep truly unsupported fields blank. No automatic approval.'}
    dump(folder/'review.json', result)
    return {'review': str((folder/'review.json').resolve()), 'people': len(by_person),
            'blank_slots': sum(len(p['blank_slots']) for p in by_person.values()),
            'issues': len(unassigned)+sum(len(p['issues']) for p in by_person.values())}
