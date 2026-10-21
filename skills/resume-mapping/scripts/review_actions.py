"""Apply explicit, version-bound review decisions and rerun all fact/source gates."""
import argparse
import copy
import re
from pathlib import Path
from source_audit import current_bindings, dump, get_path, load, audit, units_for, validate_unit_owner
from record_checks import education_binding, validate
from apply_policies import apply
from field_facts import classify
from review_queue import export


def read_decisions(path):
    """CSV uses JSON for typed values/quotes; free text is never evaluated as code."""
    if Path(path).suffix.lower() != '.csv': return load(path)
    import csv
    result=[]
    with Path(path).open(encoding='utf-8-sig', newline='') as f:
        for row in csv.DictReader(f):
            if row.get('decision') and row.get('action') and row['decision']!=row['action']:
                raise ValueError('CSV decision and action columns disagree.')
            action=row.get('decision') or row.get('action')
            if not action: continue
            d={'id':row['id'], 'action':action, 'reviewer':row.get('reviewer',''),
               'reason':row.get('decision_reason',''), 'origin':row.get('origin','')}
            for key in ('expected_value','value','source_quotes','proof'):
                text=row.get(key+'_json','')
                if text:
                    value=__import__('json').loads(text)
                    if key=='proof':d.update(value)
                    else:d[key]=value
            result.append(d)
    return result


def set_path(fields, path, value):
    if not re.fullmatch(r'[A-Za-z_]\w*(?:\[\d+\])?(?:\.[A-Za-z_]\w*(?:\[\d+\])?)*', path):
        raise ValueError('Invalid field path.')
    parts = re.findall(r'([^.[\]]+)|\[(\d+)\]', path)
    obj = fields
    for name, index in parts[:-1]:
        obj = obj[int(index)] if index else obj[name]
    name, index = parts[-1]
    key = int(index) if index else name
    if isinstance(obj[key], (dict, list)) or isinstance(value, (dict, list)):
        raise ValueError('Only existing scalar fields may be corrected.')
    obj[key] = value


def import_decisions(data, manifest, queue, decisions, outdir):
    if queue['bindings'] != current_bindings(data, manifest):
        raise ValueError('Review queue is stale; re-export it before applying decisions.')
    result = copy.deepcopy(data)
    people = {str(p['id']): p for p in result['people']}
    rows = {r['id']: r for r in queue['rows']}
    seen, changed, deferred, fact_decisions = set(), [], [], {}
    for d in decisions:
        rid = d['id']
        if rid not in rows or rid in seen:
            raise ValueError('Unknown or duplicate review ID.')
        seen.add(rid)
        row = rows[rid]
        if not d.get('reviewer') or not d.get('reason'):
            raise ValueError('Every decision requires a reviewer and a specific reason.')
        action = d.get('action')
        if action == 'defer':
            deferred.append({**d, 'person_id': row['person_id']}); continue
        p = people[str(row['person_id'])]
        path = d.get('field', row['field'])
        if path != row['field']:
            raise ValueError('Decision field must match the exported issue.')
        if action == 'review_source':
            sid=d['source_id']
            source=next(s for s in manifest['sources'] if s['id']==sid)
            if sid not in p['source_ids'] or row['category']!='source_warnings':
                raise ValueError('Source review must match a source-warning row and its owner.')
            from source_quality import required_warnings
            need_media=data.get('media_policy')=='review_all' or any(w.get('kind') in ('needs_ocr_or_visual_review','empty_content_requires_review') for w in required_warnings(data,source))
            media=load(d['media_report']) if d.get('media_report') else {'source':source['source'],'source_sha256':source['sha256'],'assets':[]}
            from extract_sources import sha
            if media['source_sha256']!=source['sha256'] or Path(media['source']).resolve()!=Path(source['source']).resolve():
                raise ValueError('Source media report belongs to a different source.')
            reviewed={v['asset_id']:v for v in d.get('reviewed_assets',[])}
            if (need_media and set(reviewed)!={a['id'] for a in media['assets']}) or d.get('all_source_content_reviewed') is not True:
                raise ValueError('Review every source page and every media asset before closing source quality.')
            # A fabricated empty media inventory cannot clear a populated Office source.
            if need_media and Path(source['source']).suffix.lower() in ('.docx','.xlsx','.xlsm'):
                from zipfile import ZipFile
                with ZipFile(source['source']) as z:
                    members={n for n in z.namelist() if re.match(r'(word|xl)/media/',n) and not n.endswith('/')}
                    if members!={a.get('package_part') for a in media['assets']}:
                        raise ValueError('Media inventory does not cover the original package.')
            if need_media and Path(source['source']).suffix.lower()=='.pdf':
                import pypdfium2 as pdfium
                with pdfium.PdfDocument(source['source']) as pdf:
                    if {a.get('page') for a in media['assets']}!=set(range(1,len(pdf)+1)):
                        raise ValueError('Source-page review does not cover all PDF pages.')
            for asset in media['assets']:
                if asset['id'] not in reviewed:continue
                v=reviewed[asset['id']]
                if sha(asset['path'])!=asset['sha256'] or v.get('asset_sha256')!=asset['sha256'] or not v.get('finding'):
                    raise ValueError('Asset pixels changed or visual finding is missing.')
            result.setdefault('source_reviews',{})[sid]={'status':'passed','reason':d['reason'],'reviewer':d['reviewer'],
                'source_sha256':source['sha256'],'detail_sha256':sha(source['detail_file']),
                'media_report_sha256':sha(d['media_report']) if d.get('media_report') else None,'reviewed_assets':list(reviewed.values())}
            changed.append({'id':rid,'person_id':p['id'],'field':path,'action':action,'reviewer':d['reviewer'],'reason':d['reason']})
            continue
        if action == 'resolve_conflict':
            cid=path.removeprefix('source_conflict:')
            conflict=next((c for c in result.get('source_conflicts',[]) if c['id']==cid),None)
            if not path.startswith('source_conflict:') or conflict is None:
                raise ValueError('Select an exported conflict record.')
            replacements=d.get('coverage_decisions',{})
            for key,value in list(result.get('coverage_decisions',{}).items()):
                if value.get('conflict_id')==cid:
                    if key not in replacements:raise ValueError('Resolve every retained original unit explicitly.')
                    result['coverage_decisions'][key]=replacements[key]
            result.setdefault('resolved_conflicts',[]).append({'original':conflict,'reviewer':d['reviewer'],'reason':d['reason']})
            result['source_conflicts']=[c for c in result['source_conflicts'] if c['id']!=cid]
            changed.append({'id':rid,'person_id':p['id'],'field':path,'action':action,'reviewer':d['reviewer'],'reason':d['reason']})
            continue
        before = copy.deepcopy(get_path(p['fields'], path))
        if d.get('expected_value') != before:
            raise ValueError('Reviewed value changed or expected_value is missing.')
        quotes = d.get('source_quotes', [])
        if action == 'correct_field':
            origin = d.get('origin')
            if origin not in ('source_direct', 'source_assembled', 'source_inferred', 'not_provided', 'intentionally_blank'):
                raise ValueError('Use a source/blank origin; defaults cannot be approved here.')
            if origin.startswith('source_') and not quotes:
                raise ValueError('Source correction requires original quotations.')
            set_path(p['fields'], path, d['value'])
            if origin in ('not_provided', 'intentionally_blank') and d['value']:
                raise ValueError('Blank decisions must leave a blank value.')
            # Replace evidence as well as its value, so a previous bad quote cannot survive.
            p['evidence'] = [e for e in p.get('evidence', []) if e['field'] != path]
            p['evidence'].append({'field': path, 'source_quotes': quotes})
            fact_decisions[f"{p['id']}:{path}"] = {'origin': origin, 'reason': d['reason'],
                'reviewer': d['reviewer'], 'reviewed_value': str(d['value']), 'source_quotes': quotes}
        elif action == 'confirm_completion':
            match = re.fullmatch(r'education\[(\d+)\]\.status', path)
            if not match:
                raise ValueError('Completion decisions must identify an education status issue.')
            index = int(match[1]); record = p['fields']['education'][index]
            record['status'] = 'completed'
            proof = {k: d[k] for k in ('basis', 'reviewer', 'reason')}
            proof.update(record_sha256=education_binding(record), source_quotes=quotes)
            for k in ('asset_sha256', 'owner_verified', 'confirmation_reference'):
                if k in d: proof[k] = d[k]
            p.setdefault('education_status_evidence', {})[f'education[{index}]'] = proof
            from record_checks import completion
            if not completion(p, index, manifest)['eligible']:
                raise ValueError('Decision does not prove completion of this education record.')
        else:
            raise ValueError('Unsupported review action.')
        changed.append({'id': rid, 'person_id': p['id'], 'field': path, 'before': before,
                        'after': copy.deepcopy(get_path(p['fields'], path)), 'reviewer': d['reviewer'],
                        'reason': d['reason'], 'action': action})
    result, policy_changes, _ = apply(result, manifest=manifest)
    result, facts = classify(result, manifest, fact_decisions)
    records = validate(result, manifest); source = audit(result, manifest)
    # No caller-supplied "closed" flag can change a gate. Untouched conflicts remain open.
    outdir = Path(outdir); outdir.mkdir(parents=True, exist_ok=False)
    for name, value in [('data', result), ('facts', facts), ('records', records), ('audit', source),
                        ('decisions-applied', {'changes': changed, 'deferred': deferred, 'policy_changes': policy_changes,
                         'input_bindings': queue['bindings']})]:
        dump(outdir/(name+'.json'), value)
    new_queue = export(result, manifest, {'facts': facts, 'records': records, 'source_audit': source}, outdir/'review-queue')
    old_ids = set(rows); new_ids = {r['id'] for r in new_queue['rows']}
    # Removed IDs alone do not prove factual closure: list remaining person/field issues too.
    summary = {'applied': len(changed), 'deferred': len(deferred), 'remaining': len(new_queue['rows']),
               'remaining_by_person': {pid: sum(str(r['person_id']) == pid for r in new_queue['rows']) for pid in people},
               'status': 'passed' if not new_queue['rows'] else 'needs_review', 'rechecked': ['policies','facts','records','source_audit']}
    dump(outdir/'summary.json', summary)
    return result, summary


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for arg in ('data','sources','queue','decisions','outdir'): p.add_argument('--'+arg, type=Path, required=True)
    a = p.parse_args()
    _, report = import_decisions(load(a.data), load(a.sources), load(a.queue), read_decisions(a.decisions), a.outdir)
    print(__import__('json').dumps(report, ensure_ascii=False))


if __name__ == '__main__': main()
