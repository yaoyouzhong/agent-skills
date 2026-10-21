"""Geometry-aware PDF intake with auditable denoising and stable source units."""
import collections
import hashlib
import json
import logging
import math
import re


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:20]


def style(char):
    color = char.get('non_stroking_color')
    color = tuple(round(float(v), 4) for v in color) if isinstance(color, (tuple, list)) else (round(float(color or 0), 4),)
    return re.sub(r'^[A-Z]{6}\+', '', char.get('fontname', '')), color


def angle(char):
    matrix = char.get('matrix', (1, 0, 0, 1, 0, 0))
    return math.degrees(math.atan2(matrix[1], matrix[0]))


def gray(color):
    return len(color) == 1 or (len(color) == 3 and max(color)-min(color) < .015)


def bbox(chars):
    return [round(min(c['x0'] for c in chars), 2), round(min(c['top'] for c in chars), 2),
            round(max(c['x1'] for c in chars), 2), round(max(c['bottom'] for c in chars), 2)]


def inside(char, rectangle):
    x, y = (char['x0']+char['x1'])/2, (char['top']+char['bottom'])/2
    return rectangle[0] <= x <= rectangle[2] and rectangle[1] <= y <= rectangle[3]


def watermark_candidates(page):
    """Require repeated rotated identifiers plus a gray style; color alone never deletes text."""
    groups = collections.defaultdict(list)
    for char in page.chars:
        groups[style(char)].append(char)
    removed, decisions, watermark_fonts = set(), [], set()
    for (font, color), chars in groups.items():
        rotated = [c for c in chars if 8 < abs(angle(c)) < 172]
        text = ''.join(c['text'] for c in rotated)
        ascii_count = sum(ch.isascii() and not ch.isspace() for ch in text)
        grams = collections.Counter(text[i:i+12] for i in range(0, max(0, len(text)-11), 3))
        repeated = max(grams.values(), default=0) >= 3
        if len(text) >= 60 and ascii_count >= len(text)*.94 and gray(color) and .12 < color[0] < .9 and repeated:
            watermark_fonts.add(font)
            selected = [c for c in chars if abs(angle(c)) > 8 or c['x0'] < 0 or c['bottom'] > page.height]
            removed.update(id(c) for c in selected)
            decisions.append({'kind': 'repeated_rotated_identifier', 'font': font, 'color': color,
                              'characters': len(selected), 'bbox': bbox(selected),
                              'text': ''.join(c['text'] for c in selected), 'confidence': 'multiple_geometry_and_repetition_signals'})
    for (font, color), chars in groups.items():
        if font not in watermark_fonts or not gray(color) or not .12 < color[0] < .9:
            continue
        margin = [c for c in chars if abs(angle(c)) < 1 and (c['bottom'] < 28 or c['top'] > page.height-28)]
        text = ''.join(c['text'] for c in margin).strip()
        if len(text) >= 24 and re.fullmatch(r'[A-Za-z0-9_~\-]+', text) and re.search('[A-Za-z]', text) and re.search('[0-9]', text):
            removed.update(id(c) for c in margin)
            decisions.append({'kind': 'identifier_in_margin_with_matching_watermark_font', 'font': font,
                              'color': color, 'characters': len(margin), 'bbox': bbox(margin), 'text': text})
    return removed, decisions


def make_unit(page_number, kind, text, rectangle, **extra):
    rectangle = [round(float(v), 2) for v in rectangle]
    value = {'page': page_number, 'kind': kind, 'text': text, 'bbox': rectangle, **extra}
    value['unit_id'] = 'u-' + fingerprint(value)
    return value


def column_candidates(words, width):
    """Return alternatives, never silently reorder an ambiguous multi-column page."""
    if len(words) < 35:
        return []
    bins = [0]*int(width)
    for word in words:
        for x in range(max(0, int(word['x0'])), min(len(bins), int(word['x1'])+1)):
            bins[x] += 1
    gaps, start = [], None
    for x in range(int(width*.15), int(width*.85)):
        if bins[x] <= 1:
            start = x if start is None else start
        elif start is not None:
            if x-start >= 22:
                gaps.append((start, x))
            start = None
    candidates = []
    for left, right in gaps:
        split = (left+right)/2
        a, b = [w for w in words if w['x1'] <= split], [w for w in words if w['x0'] >= split]
        if len(a) >= 12 and len(b) >= 12:
            candidates.append({'split_x': split, 'gap': [left, right], 'left_words': len(a), 'right_words': len(b)})
    return candidates


def read_pdf(path, reading_order=None):
    import pdfplumber
    logging.getLogger('pdfminer').setLevel(logging.ERROR)
    pages, units, warnings = [], [], []
    with pdfplumber.open(path) as document:
        for number, page in enumerate(document.pages, 1):
            raw = page.extract_text(x_tolerance=2) or ''
            removed, decisions = watermark_candidates(page)
            clean = page.filter(lambda obj: obj.get('object_type') != 'char' or id(obj) not in removed)
            text = clean.extract_text(x_tolerance=2) or ''
            page_units, tables = [], []
            for ti, table in enumerate(clean.find_tables()):
                values = table.extract(x_tolerance=2)
                cells = []
                for ri, row in enumerate(table.rows):
                    for ci, rectangle in enumerate(row.cells):
                        value = values[ri][ci] if ri < len(values) and ci < len(values[ri]) else None
                        if rectangle and value and value.strip():
                            unit = make_unit(number, 'table_cell', value, rectangle, table=ti, row=ri, cell=ci)
                            cells.append(unit['unit_id'])
                            cell_page = clean.filter(lambda obj: obj.get('object_type') != 'char' or inside(obj, rectangle))
                            for li, line in enumerate(cell_page.extract_text_lines(x_tolerance=2, return_chars=False)):
                                if line['text'].strip():
                                    page_units.append(make_unit(number, 'table_cell_line', line['text'],
                                        [line['x0'], line['top'], line['x1'], line['bottom']], table=ti, row=ri, cell=ci,
                                        cell_line=li, parent_cell_id=unit['unit_id']))
                tables.append({'table': ti, 'bbox': list(table.bbox), 'values': values, 'cell_units': cells})
            rectangles = [t['bbox'] for t in tables]
            outside = clean.filter(lambda obj: obj.get('object_type') != 'char' or not any(inside(obj, r) for r in rectangles))
            words = outside.extract_words(x_tolerance=2)
            columns = column_candidates(words, page.width)
            order = (reading_order or {}).get(str(number))
            if order:
                ranges = order.get('columns', [])
                if not order.get('reason') or not ranges or any(b <= a for a, b in ranges):
                    raise ValueError('Reading-order override needs valid column ranges and a review reason.')
                if any(sum(a <= (c['x0']+c['x1'])/2 < b for a, b in ranges) != 1 for c in clean.chars):
                    raise ValueError('Reading-order columns must cover every retained character exactly once.')
                fragments = []
                for a, b in ranges:
                    region = clean.filter(lambda obj: obj.get('object_type') != 'char' or a <= (obj['x0']+obj['x1'])/2 < b)
                    fragments.append(region.extract_text(x_tolerance=2) or '')
                text = '\n\n'.join(fragments)
            for line in outside.extract_text_lines(x_tolerance=2, return_chars=True):
                if line['text'].strip():
                    page_units.append(make_unit(number, 'line', line['text'],
                                                [line['x0'], line['top'], line['x1'], line['bottom']]))
            page_units.sort(key=lambda u: (u['bbox'][1], u['bbox'][0]))
            for unit in page_units:
                unit['locator'] = f"page {number} / " + (f"table {unit['table']} row {unit['row']} cell {unit['cell']} line {unit['cell_line']}" if unit['kind'] == 'table_cell_line' else 'text line')
                if (unit['bbox'][3] < 32 or unit['bbox'][1] > page.height-32) and re.fullmatch(r'\s*(?:第\s*)?\d+\s*(?:页|/\s*\d+)?\s*', unit['text']):
                    unit['classification'] = 'page_number'
            units.extend(page_units)
            if len(re.sub(r'\s', '', text)) < 20:
                warnings.append({'kind': 'needs_ocr_or_visual_review', 'page': number})
            if columns and not order:
                warnings.append({'kind': 'reading_order_review', 'page': number, 'candidates': columns})
            replacement_count = text.count('\ufffd') + len(re.findall(r'\(cid:\d+\)', text))
            if replacement_count:
                warnings.append({'kind': 'unmapped_glyphs', 'page': number, 'count': replacement_count})
            pages.append({'page': number, 'text': text, 'raw_text': raw, 'words': clean.extract_words(x_tolerance=2),
                          'tables': tables, 'width': page.width, 'height': page.height, 'column_candidates': columns,
                          'cleanup': decisions, 'raw_characters': len(page.chars),
                          'reading_order_override': order,
                          'retained_characters': len(page.chars)-len(removed), 'removed_characters': len(removed)})
    repeats = collections.defaultdict(list)
    for unit in units:
        page = pages[unit['page']-1]
        if unit['bbox'][3] < 38 or unit['bbox'][1] > page['height']-38:
            repeats[re.sub(r'\s+', '', unit['text'])].append(unit)
    for text, found in repeats.items():
        if len({u['page'] for u in found}) >= max(2, len(pages)*.6):
            for index, unit in enumerate(found):
                unit['running_repeat_of'] = found[0]['unit_id'] if index else None
    detail = {'schema_version': 2, 'pages': pages, 'units': units,
              'quality': {'raw_preserved': True, 'cleanup_actions': sum(len(p['cleanup']) for p in pages),
                          'removed_characters': sum(p['removed_characters'] for p in pages),
                          'unresolved_warnings': len(warnings)}}
    return detail, '\n\n'.join(f"[page {p['page']}]\n{p['text']}" for p in pages), warnings
