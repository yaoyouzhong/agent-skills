"""Locate record anchors and source quotations without copying project-specific line numbers."""
import argparse
import copy
import difflib
import json
import re
import sys
from pathlib import Path
from source_audit import coverage, dump, get_path, leaves, load, norm, payload, units_for


def anchor_name(value):
    return re.sub(r'[（(](?:个人作品|个人项目)[）)]', '', value).strip()


def word_project_row(unit, inventory):
    """Recognize a row-oriented Word project table from its actual column labels."""
    match=re.match(r'(.*/tbl\[\d+\])/row\[(\d+)\]/',unit.get('locator',''))
    if unit.get('kind')!='word_block' or not match:return None
    table,row=match[1],int(match[2]);headers={}
    for candidate in inventory:
        m=re.match(re.escape(table)+r'/row\[(\d+)\]/',candidate.get('locator',''))
        if m and int(m[1])<row:headers.setdefault(m[1],set()).add(norm(candidate['text']))
    for labels in headers.values():
        if '项目名称' in labels and '客户名称' in labels and any('起止时间' in t or '担任' in t or '项目状态' in t for t in labels):
            return table+'/row['+str(row)+']/'
    return None


def locate(data, manifest):
    result = copy.deepcopy(data)
    sources = {s['id']: s for s in manifest['sources']}
    inventories = {sid: units_for(source) for sid, source in sources.items()}
    anchor_options = {}
    for sid, inventory in inventories.items():
        options = [(i, u, [u]) for i,u in enumerate(inventory)]
        cells = {}
        for i,unit in enumerate(inventory):
            if unit.get('parent_cell_id'):
                cells.setdefault(unit['parent_cell_id'], []).append((i,unit))
        for found in cells.values():
            if len(found)>1:
                options.append((found[0][0],found[0][1],[u for _,u in found]))
        for i,unit in enumerate(inventory):
            if unit['kind']=='line':
                following=[unit]
                for candidate in inventory[i+1:i+3]:
                    if candidate['kind']=='line' and candidate.get('page')==unit.get('page'):
                        following.append(candidate)
                        options.append((i,unit,list(following)))
        anchor_options[sid]=options
    all_inventories=inventories;all_anchor_options=anchor_options
    problems, records, fields = [], [], []
    for person in result['people']:
        scope=person.get('person_source_scope')
        inventories={sid:[u for u in values if scope is None or u['unit_id'] in scope.get(sid,[])] for sid,values in all_inventories.items()}
        anchor_options={sid:[option for option in options if all(scope is None or u['unit_id'] in scope.get(sid,[]) for u in option[2])] for sid,options in all_anchor_options.items()}
        person['record_sources'] = {}
        person['evidence'] = []
        for path,value in leaves(person['fields']):
            if path.startswith(('projects[','jobs[','education[')):
                continue
            quoted=[]
            for sid in person['source_ids']:
                for unit in inventories[sid]:
                    text=norm(payload(unit['text']))
                    if (norm(value) and norm(value) in text) or (len(text)>=6 and text in norm(value)):
                        quoted.append({'source_id':sid,'source_sha256':sources[sid]['sha256'],'unit_id':unit['unit_id'],
                                       'locator':unit.get('locator'),'page':unit.get('page'),'bbox':unit.get('bbox'),'quote':unit['text']})
            person['evidence'].append({'field':path,'source_quotes':quoted,'origin':'source_assembled' if len(quoted)>1 else 'source_direct' if quoted else 'needs_review'})
        for collection, identity in [('projects', 'name'), ('jobs', 'company'), ('education', 'school')]:
            anchors = []
            for index, record in enumerate(person['fields'].get(collection, [])):
                value = anchor_name(str(record.get(identity, '')))
                key = f'{collection}[{index}]'
                if not value:
                    if collection == 'projects':
                        problems.append({'person_id': person['id'], 'record': key, 'issue': 'Missing project name.'})
                    continue
                candidates = []
                for sid in person['source_ids']:
                    for ui, unit, parts in anchor_options[sid]:
                        text = norm(''.join(p['text'] for p in parts))
                        target = norm(value)
                        if target and target in text:
                            begin=text.index(target)
                            offset=0; matched=[]
                            for part in parts:
                                size=len(norm(part['text']))
                                if offset < begin+len(target) and offset+size > begin:
                                    matched.append(part)
                                offset+=size
                            unit=matched[0]
                            ui=inventories[sid].index(unit)
                            # Prefer compact title cells/lines; long narrative mentions are secondary.
                            penalty = .12*len(text)/max(1,len(target))
                            context = inventories[sid][max(0,ui-2):ui+18]
                            context_text = [norm(u['text']) for u in context]
                            narrative = str(record.get('desc',''))+' '+str(record.get('resp',''))
                            if narrative.strip():
                                penalty -= 3*coverage(narrative[:260], context_text)
                            date = str(record.get('start', ''))
                            if date and any(norm(date) in t for t in context_text[:7]):
                                penalty -= 2
                            if date and norm(date) in norm(unit['text']) and re.search(r'工程师|开发|负责人|项目名称',unit['text']):
                                penalty -= 2
                            if norm(payload(unit['text'])) == target:
                                penalty -= 1
                            if re.match(r'^\s*项目(?:名称|[一二三四五六七八九十\d]+)\s*[:：]',unit['text']):
                                penalty -= .3
                            candidates.append((penalty, sid, ui, unit, matched))
                explicit = person.get('anchor_overrides', {}).get(key)
                if explicit:
                    sid = explicit['source_id']
                    unit = next(u for u in inventories[sid] if u['unit_id'] == explicit['unit_id'])
                    if not explicit.get('reason') or norm(explicit['quote']) not in norm(unit['text']):
                        raise ValueError('Anchor override lacks actual source quote/reason.')
                    candidates = [(0, sid, inventories[sid].index(unit), unit, [unit])]
                if not candidates:
                    problems.append({'person_id': person['id'], 'record': key, 'value': value, 'issue': 'No exact source name anchor; inspect original and provide a quoted override.'})
                    continue
                _, sid, ui, unit, parts = min(candidates, key=lambda c:(c[0],c[1],c[2]))
                if collection=='projects' and 'table' in unit:
                    row_units=[(i,u) for i,u in enumerate(inventories[sid]) if u.get('page')==unit['page'] and u.get('table')==unit['table'] and u.get('row')==unit['row']]
                    counts={ci:sum(u.get('cell')==ci for _,u in row_units) for ci in {u.get('cell') for _,u in row_units}}
                    if len(counts)>=3 and max(counts.values())<=4:
                        ui=min(i for i,_ in row_units)
                if collection=='projects' and ui:
                    previous=inventories[sid][ui-1]
                    match=re.match(r'^\s*项目[一二三四五六七八九十\d]+\s*[:：]\s*(.+)',previous['text'])
                    if match and norm(match[1]) in norm(value):
                        ui-=1
                if collection=='projects' and unit.get('kind')=='excel_cell':
                    row=re.search(r'\d+$',unit['cell'])[0]
                    ui=min(i for i,u in enumerate(inventories[sid]) if u.get('sheet')==unit['sheet'] and re.search(r'\d+$',u.get('cell','')) and re.search(r'\d+$',u['cell'])[0]==row)
                word_row=word_project_row(unit,inventories[sid]) if collection=='projects' else None
                if word_row:
                    ui=min(i for i,u in enumerate(inventories[sid]) if u.get('locator','').startswith(word_row))
                anchors.append({'path': key, 'record': record, 'sid': sid, 'index': ui, 'unit': unit, 'parts':parts})
            # A project is bounded by the next project, not by arbitrary fixed row counts.
            for anchor in anchors:
                sid, start = anchor['sid'], anchor['index']
                inventory = inventories[sid]
                if collection == 'projects':
                    next_starts = [a['index'] for a in anchors if a['sid']==sid and a['index']>start]
                    stop = min(next_starts) if next_starts else len(inventory)
                    section_labels = {'教育背景','教育经历','工作经历','工作经验','专业技能','职业技能','自我评价','相关证明','学信网截图','学历证书','学位证书','身份证照片正反面'}
                    body_positions=sorted(u['bbox'][0] for u in inventory[start: min(stop,start+24)] if u.get('bbox') and len(norm(u['text']))>=20)
                    body_left=body_positions[len(body_positions)//2] if body_positions else anchor['unit'].get('bbox',[0])[0]
                    for ui in range(start+1,stop):
                        candidate=inventory[ui]
                        table=re.match(r'(.*/tbl\[\d+\])/row\[',anchor['unit'].get('locator',''))
                        if table and anchor['unit'].get('kind')=='word_block' and not candidate.get('locator','').startswith(table[1]+'/'):
                            stop=ui
                            break
                        if anchor['unit'].get('sheet') and candidate.get('sheet')!=anchor['unit']['sheet']:
                            stop=ui
                            break
                        label=norm(re.sub(r'[A-Za-z ]','',candidate['text']))
                        sidebar=(candidate.get('bbox') and candidate['bbox'][2]<body_left-10)
                        employment=(re.match(r'^\s*(?:19|20)\d{2}',candidate['text']) and len(candidate['text'])<140 and
                                    any(norm(j.get('company','')) in norm(candidate['text']) for j in person['fields'].get('jobs',[]) if j.get('company')))
                        education_heading=bool(re.match(r'^教育(?:背景|经历)',label))
                        if ((label in section_labels or education_heading) and not sidebar) or employment:
                            stop = ui
                            break
                    selected = inventory[start:stop]
                    word_row=word_project_row(anchor['unit'],inventory)
                    if word_row:selected=[u for u in inventory if u.get('locator','').startswith(word_row)]
                else:
                    selected = inventory[max(0,start-1):min(len(inventory),start+4)]
                    word_row=re.match(r'(.*/row\[\d+\]/)',anchor['unit'].get('locator','')) if anchor['unit'].get('kind')=='word_block' else None
                    if word_row:selected=[u for u in inventory if u.get('locator','').startswith(word_row[1])]
                    if anchor['unit'].get('kind')=='excel_cell':
                        row=re.search(r'\d+$',anchor['unit']['cell'])[0]
                        selected=[u for u in inventory if u.get('sheet')==anchor['unit']['sheet'] and re.search(r'\d+$',u.get('cell','')) and re.search(r'\d+$',u['cell'])[0]==row]
                key = anchor['path']
                if collection == 'projects':
                    explicit_scope=person.get('record_scope_overrides',{}).get(key)
                    if explicit_scope:
                        by_unit={u['unit_id']:u for u in inventory}
                        ids=explicit_scope.get('unit_ids',[])
                        if explicit_scope.get('source_id')!=sid or not explicit_scope.get('reason') or explicit_scope.get('anchor_quote')!=anchor['unit']['text'] or anchor['unit']['unit_id'] not in ids or len(ids)!=len(set(ids)) or any(uid not in by_unit for uid in ids):
                            raise ValueError('Record scope override lacks exact source geometry/anchor/reason.')
                        selected=[u for u in inventory if u['unit_id'] in set(ids)]
                    person['record_sources'][key] = {'source_id':sid,'anchor_unit_id':anchor['unit']['unit_id'],
                        'unit_ids':[u['unit_id'] for u in selected], 'name_quote':'\n'.join(u['text'] for u in anchor['parts']),
                        'anchor_unit_ids':[u['unit_id'] for u in anchor['parts']],
                        'pages':sorted({u['page'] for u in selected if u.get('page') is not None})}
                record_result = {'person_id':person['id'],'record':key,'source_id':sid,
                                 'anchor_unit_id':anchor['unit']['unit_id'],'locator':anchor['unit'].get('locator'),
                                 'page':anchor['unit'].get('page'),'bbox':anchor['unit'].get('bbox'),'quote':anchor['unit']['text'],
                                 'anchor_parts':[{'unit_id':u['unit_id'],'quote':u['text'],'bbox':u.get('bbox'),'locator':u.get('locator')} for u in anchor['parts']]}
                records.append(record_result)
                for name, value in anchor['record'].items():
                    if (name == 'status' and collection=='education') or not isinstance(value,(str,int,float)) or not str(value).strip():
                        continue
                    quotes=[]
                    normalized=norm(str(value))
                    for unit in selected:
                        source_text=norm(payload(unit['text']))
                        common=difflib.SequenceMatcher(None,normalized,source_text,autojunk=False).find_longest_match()
                        if (normalized and normalized in source_text) or (source_text and source_text in normalized) or common.size >= min(12,max(3,len(normalized)//3)):
                            quotes.append({'source_id':sid,'source_sha256':sources[sid]['sha256'],'unit_id':unit['unit_id'],
                                           'locator':unit.get('locator'),'page':unit.get('page'),'bbox':unit.get('bbox'),'quote':unit['text']})
                    if not quotes and name == identity:
                        quotes=[{**record_result,'source_sha256':sources[sid]['sha256'],'unit_id':anchor['unit']['unit_id']}]
                    entry={'field':key+'.'+name,'source_quotes':quotes,'origin':'source_assembled' if len(quotes)>1 else 'source_direct' if quotes else 'needs_review'}
                    person['evidence'].append(entry)
                    fields.append({'person_id':person['id'],'field':entry['field'],'quotes':len(quotes)})
    return result, {'records':records,'field_evidence':fields,'issues':problems,
                    'summary':{'project_records':sum(x['record'].startswith('projects[') for x in records),
                               'all_records':len(records),'fields_with_quotes':sum(bool(x['quotes']) for x in fields),
                               'fields_needing_review':sum(not x['quotes'] for x in fields),'anchor_issues':len(problems)}}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data',type=Path,required=True)
    parser.add_argument('--sources',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args()
    if args.out.exists() or args.report.exists() or args.out.resolve()==args.report.resolve():
        parser.error('Use distinct new output and report paths.')
    result,report=locate(load(args.data),load(args.sources))
    dump(args.out,result);dump(args.report,report)
    print(json.dumps(report['summary'],ensure_ascii=False))
    return 2 if report['issues'] else 0


if __name__=='__main__':sys.exit(main())
