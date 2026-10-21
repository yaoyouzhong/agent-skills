"""Inspect, populate and verify a user-supplied DOCX template using an explicit map."""
import argparse
import copy
import json
import re
import sys
from pathlib import Path
from zipfile import ZipFile
from lxml import etree as E
from extract_sources import sha

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
NS = {'w': W}


def q(name):
    return '{' + W + '}' + name


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def dump(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def content(node):
    return '\n'.join(''.join(p.xpath('.//w:t/text()', namespaces=NS)) for p in node.iter(q('p')))


def norm(value):
    return re.sub(r'\s+', '', str(value))


def get(obj, path):
    if not path:
        return obj
    for key, index in re.findall(r'([^.\[\]]+)|\[(\d+)\]', path):
        if index:
            if not isinstance(obj,list):raise ValueError('Field path crosses a non-list: '+path)
            obj=obj[int(index)] if int(index)<len(obj) else ''
        else:
            if obj=='':return ''
            if not isinstance(obj,dict):raise ValueError('Field path crosses a non-object: '+path)
            obj=obj.get(key,'')
    return obj


def leaves(obj, prefix=''):
    if isinstance(obj, dict):
        for key, value in obj.items():
            # Graduation status is extraction metadata, not mandatory displayed content.
            if not (key == 'status' and re.fullmatch(r'education\[\d+\]', prefix)):
                yield from leaves(value, prefix + ('.' if prefix else '') + key)
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            yield from leaves(value, f'{prefix}[{index}]')
    elif obj is not None and str(obj).strip():
        yield prefix, str(obj)


def set_text(node, value):
    if not isinstance(value, (str, int, float)):
        raise ValueError('A binding must resolve to scalar text.')
    if node.tag == q('tc') and node.find(q('tbl')) is not None:
        raise ValueError('Mapped cells containing nested tables need a task-specific adapter.')
    paragraphs = node.findall(q('p')) if node.tag == q('tc') else [node]
    prototype = paragraphs[0] if paragraphs else E.Element(q('p'))
    pp = prototype.find(q('pPr'))
    rp = prototype.find('.//w:rPr', NS)
    if node.tag == q('tc'):
        for child in list(node):
            if child.tag != q('tcPr'):
                node.remove(child)
        target = node
    else:
        for child in list(node):
            if child.tag != q('pPr'):
                node.remove(child)
        target = None
    for index, line in enumerate(str(value).split('\n')):
        paragraph = E.SubElement(target, q('p')) if target is not None else node
        if target is not None and pp is not None:
            paragraph.append(copy.deepcopy(pp))
        if target is None and index:
            E.SubElement(paragraph, q('r')).append(E.Element(q('br')))
        run = E.SubElement(paragraph, q('r'))
        if rp is not None:
            run.append(copy.deepcopy(rp))
        text = E.SubElement(run, q('t'))
        text.text = line
        text.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')


def paragraph_flag(paragraph,name,enabled=True):
    pp=paragraph.find(q('pPr'))
    if pp is None:pp=E.Element(q('pPr'));paragraph.insert(0,pp)
    flag=pp.find(q(name))
    if flag is None:flag=E.SubElement(pp,q(name))
    flag.set(q('val'),'1' if enabled else '0')


def inspect_template(path):
    with ZipFile(path) as package:
        tree = E.fromstring(package.read('word/document.xml'))
        parts = {n: sha_bytes(package.read(n)) for n in package.namelist()}
    body = tree.find(q('body'))
    return {'template': str(path.resolve()), 'sha256': sha(path), 'parts': parts,
            'sections': len(tree.findall('.//w:sectPr', NS)),
            'paragraphs': [{'index': i, 'text': content(p)} for i, p in enumerate(body.findall(q('p')))],
            'tables': [{'index': i, 'rows': [
                {'row': ri, 'cells': [{'cell': ci, 'text': content(c),
                                      'properties_xml': E.tostring(c.find(q('tcPr')), encoding='unicode') if c.find(q('tcPr')) is not None else ''}
                                     for ci, c in enumerate(row.findall(q('tc')))]}
                for ri, row in enumerate(table.findall(q('tr')))]}
                for i, table in enumerate(body.findall(q('tbl')))]}


def sha_bytes(value):
    import hashlib
    return hashlib.sha256(value).hexdigest()


def check_sources(data, manifest, audit_report):
    from record_checks import validate
    records = validate(data, manifest)
    if records['issues'] and data.get('output_mode') != 'candidate':
        raise ValueError('Unresolved graduation/date checks allow candidate output only.')
    from source_audit import current_bindings
    candidate_conflicts=(audit_report and audit_report.get('status')=='needs_review' and data.get('output_mode')=='candidate' and audit_report.get('issues') and all(i.get('status')=='retained_conflict' for i in audit_report['issues']))
    if not audit_report or (audit_report.get('status') != 'passed' and not candidate_conflicts):
        raise ValueError('A passed source-to-data completeness audit is required before document generation.')
    if audit_report.get('bindings') != current_bindings(data, manifest):
        raise ValueError('Source audit is stale: data, source, extraction or audit engine changed.')
    for person in data['people']:
        if any(f'projects[{i}]' not in person.get('record_sources',{}) for i,_ in enumerate(person['fields'].get('projects',[]))):
            raise ValueError('Every project needs verified original-source provenance.')
    sources = {s['id']: s for s in manifest['sources']}
    reviews = data.get('source_reviews', {})
    used = set()
    ids = []
    for person in data['people']:
        ids.append(str(person['id']))
        if not person.get('source_ids'):
            raise ValueError(f'Person {person["id"]} has no source_ids.')
        for sid in person['source_ids']:
            source = sources[sid]
            from source_quality import required_warnings
            required=required_warnings(data,source)
            if source['status'] == 'error':
                raise ValueError('Source extraction failed: ' + sid)
            if source['status'] != 'ok' and required and not reviews.get(sid):
                raise ValueError('Unresolved source warnings: ' + sid)
            if source['status'] != 'ok' and required:
                review=reviews[sid]
                if not isinstance(review,dict) or not review.get('reason') or review.get('source_sha256')!=source['sha256'] or review.get('detail_sha256')!=source.get('detail_sha256'):
                    raise ValueError('Source warning review must bind the current source and extraction.')
                if review.get('status')=='pending' and data.get('output_mode')!='candidate':
                    raise ValueError('Unreviewed source warnings allow candidate output only.')
            used.add(sid)
    if not ids or len(ids) != len(set(ids)):
        raise ValueError('People must be nonempty and have unique IDs.')
    exclusions = data.get('excluded_sources', {})
    for sid, reason in exclusions.items():
        if sid not in sources or not str(reason).strip():
            raise ValueError('Invalid source exclusion.')
    if set(sources) - used - set(exclusions):
        raise ValueError('Sources missing from mapping: ' + ', '.join(set(sources) - used - set(exclusions)))
    for source in sources.values():
        if sha(source['source']) != source['sha256']:
            raise ValueError('Source hash changed: ' + source['id'])


def omitted(mapping, path):
    import fnmatch
    def clean(value):
        return re.sub(r'\[(\d*)\]', lambda m: '/' + (m[1] or '*'), value)
    return any(reason and fnmatch.fnmatchcase(clean(path), clean(pattern))
               for pattern, reason in mapping.get('omit_fields', {}).items())


def fill(binding, obj, node, prefix, used, index=1):
    keys = binding.get('keys', [binding['key']] if 'key' in binding else [])
    labels=binding.get('key_labels',{})
    if not isinstance(labels,dict) or any(k not in keys or not isinstance(v,str) for k,v in labels.items()):
        raise ValueError('key_labels must map bound keys to text prefixes.')
    values = []
    for key in keys:
        value = get(obj, key)
        if isinstance(value, (list, dict)):
            raise ValueError('Bind individual scalar fields, not a complete object/list: ' + key)
        used.add(prefix + ('.' if prefix else '') + key)
        if value is not None and str(value):
            values.append(labels.get(key,'')+str(value))
    value = binding.get('separator', '\n').join(values)
    if value and binding.get('prefix'):value=binding['prefix']+value
    if 'text' in binding:
        if keys:
            raise ValueError('A binding must use keys or literal text, not both.')
        value = binding['text'].replace('{index}', str(index))
    set_text(node, value)


def ordered_records(records, repeat):
    """Display project chronology without mutating source indexes or evidence."""
    order=repeat.get('order','start_desc' if repeat['key']=='projects' else 'source')
    if order not in ('source','start_desc'):raise ValueError('Repeat order must be source or start_desc.')
    if order=='source':return list(enumerate(records))
    from record_checks import date_interval
    known=[];unknown=[]
    for index,record in enumerate(records):
        try:interval=date_interval(record.get('start',''))
        except (ValueError,TypeError):interval=None
        if interval:known.append((index,record,interval))
        else:unknown.append((index,record))
    result=[]
    while known:
        # Only enforce dates that are definitely later. Overlapping precision
        # (e.g. year versus month) and exact ties retain stable source priority.
        available=[x for x in known if not any(y[2][0]>x[2][1] for y in known)]
        chosen=min(available,key=lambda x:x[0]);result.append(chosen[:2]);known.remove(chosen)
    return result+unknown


def make_person(prototype, mapping, person):
    cloned = copy.deepcopy(prototype)
    used = set()
    fields = person['fields']
    paragraphs = cloned.findall(q('p'))
    for binding in mapping.get('paragraphs', []):
        fill(binding, fields, paragraphs[binding['index']], '', used)
    tables = cloned.findall(q('tbl'))
    for spec in mapping.get('tables', []):
        table = tables[spec['index']]
        if spec.get('remove_floating'):
            for node in table.findall('w:tblPr/w:tblpPr', NS):
                node.getparent().remove(node)
        rows = table.findall(q('tr'))
        original_rows=[copy.deepcopy(r) for r in rows]
        for offset in spec.get('keep_with_next_rows',[]):
            if offset<0 or offset>=len(rows):raise ValueError('Invalid keep-with-next static row.')
            for paragraph in rows[offset].iter(q('p')):paragraph_flag(paragraph,'keepNext')
        blocks, occupied = {}, set()
        for repeat in spec.get('repeat', []):
            start, end = repeat['rows']
            if start < 0 or end < start or end >= len(rows) or occupied.intersection(range(start, end+1)):
                raise ValueError('Invalid or overlapping repeat rows.')
            occupied.update(range(start, end+1))
            blocks[start] = (end, repeat)
        omit_rows = set(spec.get('omit_rows', []))
        if occupied.intersection(omit_rows) or any(i < 0 or i >= len(rows) for i in omit_rows):
            raise ValueError('Invalid omitted rows or overlap with repeating blocks.')
        for binding in spec.get('fields', []):
            ri = binding['row']
            if ri in occupied or ri in omit_rows:
                raise ValueError('Static binding intersects repeating/omitted rows.')
            fill(binding, fields, rows[ri].findall(q('tc'))[binding['cell']], '', used)
        for row in rows:
            table.remove(row)
        ri = 0
        while ri < len(rows):
            if ri in blocks:
                end, repeat = blocks[ri]
                records = get(fields, repeat['key'])
                if records == '':
                    records = []
                if not isinstance(records, list):
                    raise ValueError('Repeat field must be a list.')
                combine=repeat.get('combine_records',False)
                if not isinstance(combine,bool):raise ValueError('combine_records must be boolean.')
                if combine and (ri!=end or len(rows[ri].findall(q('tc')))!=1 or repeat.get('trailing_rows')):
                    raise ValueError('Combined records require one prototype row with one cell and no trailing rows.')
                combined_cell=None
                for display_index,(index, record) in enumerate(ordered_records(records,repeat)):
                    row_copies = [copy.deepcopy(r) for r in rows[ri:end+1]]
                    for offset in repeat.get('cant_split_rows',[]):
                        if offset<0 or offset>=len(row_copies):raise ValueError('Invalid cant-split repeat row.')
                        trp=row_copies[offset].find(q('trPr'))
                        if trp is None:trp=E.Element(q('trPr'));row_copies[offset].insert(0,trp)
                        flag=trp.find(q('cantSplit'))
                        if flag is None:flag=E.SubElement(trp,q('cantSplit'))
                        flag.set(q('val'),'1')
                    for cell in repeat.get('keep_lines_cells',[]):
                        target=row_copies[cell['row']].findall(q('tc'))[cell['cell']]
                        for paragraph in target.iter(q('p')):paragraph_flag(paragraph,'keepLines')
                    for offset in repeat.get('keep_with_next_rows',[]):
                        if offset<0 or offset>=len(row_copies):raise ValueError('Invalid keep-with-next repeat row.')
                        for paragraph in row_copies[offset].iter(q('p')):
                            paragraph_flag(paragraph,'keepNext')
                    for binding in repeat.get('fields', []):
                        cell = row_copies[binding['row']].findall(q('tc'))[binding['cell']]
                        fill(binding, record, cell, f"{repeat['key']}[{index}]", used, display_index+1)
                    if combine and combined_cell is not None:
                        for paragraph in row_copies[0].findall('w:tc/w:p',NS):combined_cell.append(paragraph)
                    else:
                        table.extend(row_copies)
                        if combine:combined_cell=row_copies[0].find(q('tc'))
                    for extra in repeat.get('trailing_rows',[]):
                        if extra.get('when_nonempty') and not get(record,extra['when_nonempty']):continue
                        a,b=extra['rows']
                        if a<0 or b<a or b>=len(original_rows):raise ValueError('Invalid trailing row prototype.')
                        copies=[copy.deepcopy(r) for r in original_rows[a:b+1]]
                        for binding in extra.get('fields',[]):
                            fill(binding,record,copies[binding['row']].findall(q('tc'))[binding['cell']],f"{repeat['key']}[{index}]",used,display_index+1)
                        table.extend(copies)
                ri = end+1
            else:
                if ri not in omit_rows:
                    table.append(rows[ri])
                ri += 1
        for extra in spec.get('append_rows',[]):
            if extra.get('when_nonempty') and not get(fields,extra['when_nonempty']):continue
            a,b=extra['rows']
            if a<0 or b<a or b>=len(original_rows):raise ValueError('Invalid additional row prototype.')
            copies=[copy.deepcopy(r) for r in original_rows[a:b+1]]
            if extra.get('auto_height'):
                for row in copies:
                    for height in row.findall('w:trPr/w:trHeight',NS):height.getparent().remove(height)
            for binding in extra.get('fields',[]):
                fill(binding,fields,copies[binding['row']].findall(q('tc'))[binding['cell']],'',used)
            table.extend(copies)
    missing = [key for key, _ in leaves(fields) if key not in used and not omitted(mapping, key)]
    if missing:
        raise ValueError(f'Unmapped nonempty fields for {person["id"]}: ' + ', '.join(missing))
    if 'widow_control' in mapping:
        if not isinstance(mapping['widow_control'],bool):raise ValueError('widow_control must be boolean.')
        for paragraph in cloned.iter(q('p')):paragraph_flag(paragraph,'widowControl',mapping['widow_control'])
    if mapping.get('compact_empty_body_paragraphs'):
        for paragraph in cloned.findall(q('p')):
            if not content(paragraph).strip():
                paragraph_flag(paragraph,'snapToGrid',False)
                pp=paragraph.find(q('pPr'))
                if pp is None:pp=E.Element(q('pPr'));paragraph.insert(0,pp)
                spacing=pp.find(q('spacing'))
                if spacing is None:spacing=E.SubElement(pp,q('spacing'))
                for key,value in [('before','0'),('after','0'),('line','1'),('lineRule','exact')]:spacing.set(q(key),value)
                rp=pp.find(q('rPr'))
                if rp is None:rp=E.SubElement(pp,q('rPr'))
                for name in ('sz','szCs'):
                    size=rp.find(q(name))
                    if size is None:size=E.SubElement(rp,q(name))
                    size.set(q('val'),'2')
    return list(cloned)


def selected_people(data, person_ids=None):
    if person_ids is None:
        return data['people']
    if not person_ids or len(person_ids) != len(set(person_ids)):
        raise ValueError('Sample person IDs must be nonempty and distinct.')
    people = {str(p['id']): p for p in data['people']}
    if any(str(pid) not in people for pid in person_ids):
        raise ValueError('Unknown sample person ID.')
    return [people[str(pid)] for pid in person_ids]


def build(template, mapping, data, manifest, output, audit_report=None, person_ids=None):
    check_sources(data, manifest, audit_report)
    if 'page_break_between_people' not in mapping:
        raise ValueError('Map must specify page_break_between_people explicitly.')
    if not isinstance(mapping['page_break_between_people'], bool):
        raise ValueError('page_break_between_people must be a JSON boolean.')
    with ZipFile(template) as package:
        tree = E.fromstring(package.read('word/document.xml'))
    if len(tree.findall('.//w:sectPr', NS)) != 1:
        raise ValueError('Multi-section templates require a task-specific adapter.')
    # Word's editor cursor is not a content bookmark and must not be cloned.
    for cursor in tree.xpath('//w:bookmarkStart[@w:name="_GoBack"]',namespaces=NS):
        identifier=cursor.get(q('id'))
        for ending in tree.xpath('//w:bookmarkEnd[@w:id=$identifier]',namespaces=NS,identifier=identifier):
            ending.getparent().remove(ending)
        cursor.getparent().remove(cursor)
    if tree.xpath('//w:bookmarkStart|//w:docPr|//w:commentRangeStart|//w:footnoteReference|//w:endnoteReference', namespaces=NS) or tree.xpath('//*[local-name()="docPr"]'):
        raise ValueError('Templates with bookmarks, drawings, comments or note references need unique-ID handling in an adapter.')
    body = tree.find(q('body'))
    section = copy.deepcopy(body.find(q('sectPr')))
    prototype = copy.deepcopy(body)
    prototype.remove(prototype.find(q('sectPr')))
    for node in list(body):
        body.remove(node)
    people = selected_people(data, person_ids)
    for index, person in enumerate(people):
        if index and mapping['page_break_between_people']:
            paragraph = E.SubElement(body, q('p'))
            pp=E.SubElement(paragraph,q('pPr'))
            E.SubElement(pp,q('pageBreakBefore'))
            spacing=E.SubElement(pp,q('spacing'))
            for key,value in [('before','0'),('after','0'),('line','1'),('lineRule','exact')]:spacing.set(q(key),value)
        start = E.SubElement(body, q('bookmarkStart'))
        start.set(q('id'), str(90000+index))
        start.set(q('name'), f'resume_person_{index+1}')
        nodes=make_person(prototype, mapping, person)
        if mapping.get('compact_empty_body_paragraphs') and mapping['page_break_between_people'] and index+1<len(people):
            while nodes and nodes[-1].tag==q('p') and not content(nodes[-1]).strip():nodes.pop()
        body.extend(nodes)
        end = E.SubElement(body, q('bookmarkEnd'))
        end.set(q('id'), str(90000+index))
    body.append(section)
    payload = E.tostring(tree, encoding='UTF-8', xml_declaration=True, standalone=True)
    with ZipFile(template) as source, ZipFile(output, 'x') as target:
        for entry in source.infolist():
            target.writestr(entry, payload if entry.filename == 'word/document.xml' else source.read(entry.filename))
    report = verify(template, mapping, data, manifest, output, audit_report, person_ids)
    report['visual_review'] = 'pending'
    return report


def verify(template, mapping, data, manifest, output, audit_report=None, person_ids=None):
    check_sources(data, manifest, audit_report)
    with ZipFile(template) as source, ZipFile(output) as target:
        if set(source.namelist()) != set(target.namelist()):
            raise ValueError('Template package member set changed.')
        changed = [n for n in source.namelist() if source.read(n) != target.read(n)]
        if any(n != 'word/document.xml' for n in changed):
            raise ValueError('Preserve-only template parts changed: ' + str(changed))
        tree = E.fromstring(target.read('word/document.xml'))
    people, current = [], None
    for node in tree.find(q('body')):
        if node.tag == q('bookmarkStart') and node.get(q('name'), '').startswith('resume_person_'):
            current = []
            people.append(current)
        elif node.tag == q('bookmarkEnd'):
            current = None
        elif current is not None:
            current.append(content(node))
    expected_people = selected_people(data, person_ids)
    if len(people) != len(expected_people):
        raise ValueError('Person count mismatch.')
    missing = []
    for person, texts in zip(expected_people, people):
        text = norm('\n'.join(texts))
        for key, value in leaves(person['fields']):
            if not omitted(mapping, key) and norm(value) not in text:
                missing.append({'person_id': person['id'], 'field': key})
    if missing:
        raise ValueError('Missing person-specific content: ' + json.dumps(missing, ensure_ascii=False))
    return {**({'sample_only': True, 'sample_person_ids': person_ids} if person_ids is not None else {}),
            'people': len(people), 'output': str(output.resolve()), 'template_sha256': sha(template),
            'output_sha256': sha(output), 'changed_parts': changed, 'source_hashes_verified': True,
            'mapping_sha256': sha_bytes(json.dumps(mapping,ensure_ascii=False,sort_keys=True).encode()),
            'source_audit_status':audit_report['status'],'output_mode':data.get('output_mode','reviewed'),
            'person_content_verified': True, 'visual_review': 'pending'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    inspection = sub.add_parser('inspect')
    inspection.add_argument('--template', type=Path, required=True)
    inspection.add_argument('--out', type=Path, required=True)
    for name in ('build', 'check'):
        command = sub.add_parser(name)
        command.add_argument('--template', type=Path, required=True)
        command.add_argument('--map', dest='mapping', type=Path, required=True)
        command.add_argument('--data', type=Path, required=True)
        command.add_argument('--sources', type=Path, required=True)
        command.add_argument('--source-audit', type=Path, required=True)
        command.add_argument('--out' if name == 'build' else '--docx', dest='output', type=Path, required=True)
        command.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'inspect':
        if args.out.exists():
            parser.error('Inspection output must be new.')
        dump(args.out, inspect_template(args.template))
        print(str(args.out))
        return 0
    if args.report.exists() or (args.command == 'build' and args.output.exists()):
        parser.error('Use new output and report paths.')
    if args.report.resolve() == args.output.resolve():
        parser.error('Report and document must be distinct.')
    operation = build if args.command == 'build' else verify
    report = operation(args.template, load(args.mapping), load(args.data), load(args.sources), args.output, load(args.source_audit))
    dump(args.report, report)
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
