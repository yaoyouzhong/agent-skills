"""Check rendered PDF text within each person's own output range."""
import argparse
import json
import sys
from pathlib import Path
from source_audit import dump,load,norm,get_path
from template_docx import leaves,omitted
from extract_sources import sha


def split_cell_match(value, pages, siblings):
    """Match a table cell continued on the immediately following page.

    Only the last/first physical lines qualify. Any text after the prefix must
    be an exact value of another cell in the same record, not an arbitrary gap.
    """
    for left,right in zip(pages,pages[1:]):
        last=next((norm(x) for x in reversed(left['text'].splitlines()) if norm(x)), '')
        first=next((norm(x) for x in right['text'].splitlines() if norm(x)), '')
        for at in range(1,len(value)):
            prefix,suffix=value[:at],value[at:]
            if len(prefix)<4 or len(suffix)<2 or not first.startswith(suffix):continue
            position=last.rfind(prefix)
            if position>=0 and last[position+len(prefix):] in siblings:
                return {'left_page':left['page'],'right_page':right['page'],'prefix':prefix,'suffix':suffix}
    return None


def check(data,mapping,render):
    text=norm('\n'.join(p['text'] for p in render['pages']));starts=[];issues=[]
    ordered=mapping.get('person_boundary',{}).get('mode')=='ordered_name_occurrences'
    single=mapping.get('person_boundary',{}).get('mode')=='single_person'
    if single and len(data['people'])!=1:raise ValueError('single_person boundaries require exactly one person.')
    if ordered and mapping['person_boundary'].get('order')!=[p['id'] for p in data['people']]:
        raise ValueError('Ordered boundaries must bind the exact output person order.')
    name_occurrences={}
    for person in data['people']:
        if single:starts.append(0);continue
        name=norm(person['fields']['meta']['name']);marker=norm('姓名：')+name
        positions=[];pos=0
        while True:
            at=text.find(marker,pos)
            if at<0:break
            positions.append(at);pos=at+len(marker)
        occurrence=name_occurrences.get(name,0);name_occurrences[name]=occurrence+1
        expected=sum(norm(p['fields']['meta']['name'])==name for p in data['people']) if ordered else 1
        if len(positions)!=expected:issues.append({'person_id':person['id'],'issue':'Name marker occurrence count differs from the declared person order','occurrences':len(positions)})
        starts.append(positions[occurrence if ordered else 0] if len(positions)==expected else -1)
    if any(x<0 for x in starts) or starts!=sorted(starts):return {'status':'failed','issues':issues+[{'issue':'Person boundaries unavailable or out of order'}]}
    continuations=[]
    page_starts=[];offset=0
    for page in render['pages']:
        page_starts.append(offset);offset+=len(norm(page['text']))
    for index,person in enumerate(data['people']):
        own=text[starts[index]:starts[index+1] if index+1<len(starts) else len(text)]
        end=starts[index+1] if index+1<len(starts) else len(text)
        own_pages=[page for page,pos in zip(render['pages'],page_starts) if pos<end and pos+len(norm(page['text']))>starts[index]]
        for key,value in leaves(person['fields']):
            if omitted(mapping,key) or norm(value) in own:continue
            record=get_path(person['fields'],key.rsplit('.',1)[0]) if '.' in key else {}
            siblings={norm(v) for _,v in leaves(record) if norm(v)!=norm(value)}|{''}
            match=split_cell_match(norm(value),own_pages,siblings)
            if match:continuations.append({'person_id':person['id'],'field':key,**match})
            else:issues.append({'person_id':person['id'],'field':key,'issue':'Missing in rendered person range'})
    return {'status':'passed' if not issues else 'failed','people':len(starts),'projects':sum(len(p['fields'].get('projects',[])) for p in data['people']),
            'pages':len(render['pages']),'issues':issues,'page_continuations':continuations,'visual_review':'separate_required'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('data','map','render','out'):p.add_argument('--'+key,type=Path,required=True)
    a=p.parse_args()
    if a.out.exists():p.error('Use a new report path.')
    r=check(load(a.data),load(a.map),load(a.render));dump(a.out,r);print(json.dumps(r,ensure_ascii=False));return 0 if r['status']=='passed' else 2


if __name__=='__main__':sys.exit(main())
