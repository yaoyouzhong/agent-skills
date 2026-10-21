"""Read mixed resume files into source text plus location-preserving JSON."""
import argparse
import csv
import hashlib
import io
import json
import re
import subprocess
import sys
import time
from datetime import date, datetime
from pathlib import Path

EXTENSIONS = {'.pdf', '.docx', '.doc', '.rtf', '.xlsx', '.xlsm', '.xls', '.csv', '.tsv', '.txt', '.md'}


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def dump(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def office_convert(source, output, mode, sheet=None):
    if sys.platform != 'win32':
        from libreoffice_bridge import convert
        extensions={'ConvertWord':'docx','ConvertExcel':'xlsx','RenderWord':'pdf','RenderExcel':'pdf'}
        if mode not in extensions:raise ValueError('Unknown Office conversion mode.')
        return convert(source,output,extensions[mode],sheet=sheet if mode=='RenderExcel' else None)
    attempts=[]
    for attempt in range(3):
        command=['powershell.exe', '-NoProfile', '-File', str(Path(__file__).with_name('office_bridge.ps1')),
                 '-Mode', mode, '-InputPath', str(source), '-OutputPath', str(output)]
        if sheet:command+=['-SheetName',sheet]
        result = subprocess.run(command,
                               capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=180)
        attempts.append({'attempt':attempt+1,'returncode':result.returncode,'stdout':result.stdout,'stderr':result.stderr})
        dump(str(output)+'.office-attempts.json',attempts)
        if not result.returncode:return
        message=result.stderr.strip() or result.stdout.strip() or 'Office conversion failed.'
        if not any(code in message for code in ('0x800706BA','RPC server is unavailable','0x80010001')) or Path(output).exists() or attempt==2:
            raise RuntimeError(message)
        time.sleep(attempt+1)


def read_pdf(path, reading_order=None):
    from pdf_intake import read_pdf as intake
    return intake(path, reading_order)


def read_docx(path):
    from zipfile import ZipFile
    from lxml import etree as E
    ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    warnings, blocks = [], []
    def text(node):
        parts = []
        for child in node.iter():
            name = E.QName(child).localname
            if name == 't':
                parts.append(child.text or '')
            elif name == 'tab':
                parts.append('\t')
            elif name in ('br', 'cr'):
                parts.append('\n')
        return ''.join(parts)
    def walk(parent, location):
        for index, node in enumerate(parent):
            kind = E.QName(node).localname
            loc = f'{location}/{kind}[{index}]'
            if kind == 'p':
                blocks.append({'location': loc, 'text': text(node)})
            elif kind == 'tbl':
                for ri, row in enumerate(node.findall('w:tr', ns)):
                    for ci, cell in enumerate(row.findall('w:tc', ns)):
                        walk(cell, f'{loc}/row[{ri}]/cell[{ci}]')
            elif kind == 'sdt':
                for content in node.findall('w:sdtContent', ns):
                    walk(content, loc)
    with ZipFile(path) as package:
        parts = ['word/document.xml'] + sorted(n for n in package.namelist()
                    if re.fullmatch(r'word/(header\d+|footer\d+|footnotes|endnotes)\.xml', n))
        for part in parts:
            root = E.fromstring(package.read(part))
            parent = root.find('w:body', ns) if part == 'word/document.xml' else root
            if parent is not None:
                if part.endswith(('footnotes.xml', 'endnotes.xml')):
                    for note in parent:
                        walk(note, f"{part}/note[{note.get('{'+ns['w']+'}id', '')}]")
                else:
                    walk(parent, part)
            if root.xpath('//w:txbxContent', namespaces=ns):
                warnings.append({'kind': 'textboxes_require_reading_order_review', 'part': part})
        if any(n.startswith('word/media/') for n in package.namelist()):
            warnings.append({'kind': 'images_require_visual_review'})
    return {'blocks': blocks}, '\n'.join(f"[{b['location']}] {b['text']}" for b in blocks), warnings


def scalar(value):
    return value.isoformat() if isinstance(value, (date, datetime)) else value


def read_xlsx(path):
    from excel_intake import open_readonly
    formulas,cached,raw_cells,warnings,package_review=open_readonly(path)
    sheets, lines = [], []
    try:
        for sheet in formulas:
            target = cached[sheet.title]
            cells = []
            lines.append(f'[sheet {sheet.title}]')
            for row in sheet:
                for cell in row:
                    if cell.value is None and cell.comment is None:
                        continue
                    is_formula = cell.data_type == 'f'
                    value = target[cell.coordinate].value if is_formula else cell.value
                    item = {'cell': cell.coordinate, 'value': scalar(value), 'number_format': cell.number_format,
                            'type': cell.data_type, 'row_hidden': bool(sheet.row_dimensions[cell.row].hidden),
                            'column_hidden': bool(sheet.column_dimensions[cell.column_letter].hidden)}
                    item.update(raw_cells.get(sheet.title,{}).get(cell.coordinate,{}))
                    if is_formula:
                        item['formula'] = cell.value if isinstance(cell.value, str) else str(cell.value)
                        if value is None:
                            warnings.append({'kind': 'formula_cache_missing', 'sheet': sheet.title, 'cell': cell.coordinate})
                    if cell.comment:
                        item['comment'] = cell.comment.text
                    if cell.data_type == 'e':
                        warnings.append({'kind': 'cell_error', 'sheet': sheet.title, 'cell': cell.coordinate, 'value': value})
                    cells.append(item)
                    display = str(scalar(value)) if value is not None else ''
                    if isinstance(value,float) and value.is_integer() and cell.number_format.lower()=='general':
                        display=str(int(value))
                    if isinstance(value,(date,datetime)):
                        fmt=re.sub(r'"[^"]*"','',cell.number_format).lower()
                        if not isinstance(value,datetime) or (value.hour==0 and value.minute==0 and value.second==0):
                            display=value.strftime('%Y-%m-%d' if 'd' in fmt else '%Y-%m' if 'm' in fmt else '%Y' if 'y' in fmt else '%Y-%m-%d')
                    if isinstance(value, (float, int)) and re.fullmatch('0+', cell.number_format):
                        display = f'{int(value):0{len(cell.number_format)}d}'
                    item['display_value']=display
                    extra = f" [formula={item['formula']}]" if is_formula else ''
                    comment = f" [comment={item['comment']}]" if 'comment' in item else ''
                    lines.append(f'[{sheet.title}!{cell.coordinate}] {display}{extra}{comment}')
            sheets.append({'sheet': sheet.title, 'state': sheet.sheet_state,
                           'merged_ranges': [str(r) for r in sheet.merged_cells.ranges], 'cells': cells})
            if sheet._images:
                warnings.append({'kind': 'sheet_images_require_visual_review', 'sheet': sheet.title})
    finally:
        formulas.close()
        cached.close()
    return {'sheets': sheets,'package_review':package_review}, '\n'.join(lines), warnings


def read_text(path):
    raw = path.read_bytes()
    for encoding in ('utf-8-sig', 'gb18030', 'utf-16'):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeError:
            continue
    else:
        raise ValueError('Unrecognized text encoding; convert encoding without replacement characters.')
    if path.suffix.lower() in ('.csv', '.tsv'):
        rows = list(csv.reader(io.StringIO(text), delimiter='\t' if path.suffix.lower() == '.tsv' else ','))
        return {'encoding': encoding, 'rows': rows}, '\n'.join(f'[row {i}] '+json.dumps(r, ensure_ascii=False) for i, r in enumerate(rows, 1)), []
    return {'encoding': encoding}, text, []


def extract_one(path, work, sid, reading_order=None):
    """Extract one file; shared by the standalone CLI and incremental batch runner."""
    path, work = Path(path), Path(work)
    record = {'id': sid, 'source': str(path.resolve()), 'type': path.suffix.lower(), 'sha256': sha(path)}
    try:
        converted = path
        if path.suffix.lower() in ('.doc', '.rtf', '.xls'):
            converted = work/(sid+('.xlsx' if path.suffix.lower() == '.xls' else '.docx'))
            office_convert(path, converted, 'ConvertExcel' if path.suffix.lower() == '.xls' else 'ConvertWord')
            record['converted_copy'] = str(converted)
        suffix = converted.suffix.lower()
        if suffix == '.pdf':
            details, text, warnings = read_pdf(converted, reading_order)
        elif suffix == '.docx':
            details, text, warnings = read_docx(converted)
        elif suffix in ('.xlsx', '.xlsm'):
            details, text, warnings = read_xlsx(converted)
        elif suffix in ('.csv', '.tsv', '.txt', '.md'):
            details, text, warnings = read_text(converted)
        else:
            raise ValueError('Unsupported source format: '+suffix)
        actual = text if suffix in ('.txt', '.md') else re.sub(r'(?m)^\[[^\]\n]*\]\s*', '', text)
        if not any(ch.isalnum() for ch in actual):
            warnings.append({'kind': 'empty_content_requires_review'})
        text_path, detail_path = work/f'{sid}.txt', work/f'{sid}.json'
        text_path.write_text(text, encoding='utf-8')
        for unit in details.get('units', []):
            unit['source_id'], unit['source_sha256'] = sid, record['sha256']
        dump(detail_path, details)
        record.update(status='needs_review' if warnings else 'ok', warnings=warnings,
                      text_file=str(text_path.resolve()), detail_file=str(detail_path.resolve()), characters=len(text))
        record.update(text_sha256=sha(text_path), detail_sha256=sha(detail_path))
    except Exception as error:
        message = error.stderr.strip() if isinstance(error, subprocess.CalledProcessError) and error.stderr else str(error)
        record.update(status='error', error=message)
        if any(t in message.lower() for t in ('文件阻止', 'file block', 'trust center')):
            record.update(error_kind='office_file_blocked', next_action='Use an available offline converter or a modern-format copy; do not change Office security settings automatically.')
    if sha(path) != record['sha256']:
        record.update(status='error', error='Source changed during extraction.')
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, nargs='+', required=True)
    parser.add_argument('--workdir', type=Path, required=True, help='New extraction directory, outside input directories.')
    parser.add_argument('--pdf-order-map', type=Path, help='Reviewed column ranges by absolute source path and page number.')
    args = parser.parse_args()
    order_map = json.loads(args.pdf_order_map.read_text(encoding='utf-8-sig')) if args.pdf_order_map else {}
    work = args.workdir.resolve()
    if work.exists():
        parser.error('workdir must be new; retain earlier extractions and use a new run directory.')
    paths, ignored = set(), []
    for value in args.input:
        value = value.resolve(strict=True)
        if value.is_dir():
            if work.is_relative_to(value):
                parser.error('workdir must be outside scanned input directories.')
            for path in value.rglob('*'):
                if path.is_file() and not path.name.startswith('~$'):
                    (paths.add(path) if path.suffix.lower() in EXTENSIONS else ignored.append(str(path)))
        else:
            paths.add(value)
    if not paths:
        parser.error('No source files found.')
    work.mkdir(parents=True)
    records = []
    for index, path in enumerate(sorted(paths, key=str), 1):
        sid = f's{index:04d}'
        records.append(extract_one(path, work, sid, order_map.get(str(path.resolve()))))
    dump(work / 'sources.json', {'sources': records, 'ignored_files': ignored})
    print(json.dumps({'manifest': str(work / 'sources.json'), 'files': len(records),
                      'ok': sum(r['status'] == 'ok' for r in records),
                      'needs_review': sum(r['status'] == 'needs_review' for r in records),
                      'errors': sum(r['status'] == 'error' for r in records)}, ensure_ascii=False))
    return 1 if any(r['status'] == 'error' for r in records) else 2 if any(r['status'] == 'needs_review' for r in records) else 0


if __name__ == '__main__':
    sys.exit(main())
