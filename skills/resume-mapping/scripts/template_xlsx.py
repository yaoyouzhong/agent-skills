"""Source-gated Excel template mapping, dynamic blocks and native print settings."""
import argparse,json,re,subprocess,copy
from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED
from lxml import etree as E
from source_audit import load,dump,get_path
from template_docx import check_sources,leaves,omitted,sha_bytes,ordered_records
from extract_sources import sha

NS='http://schemas.openxmlformats.org/spreadsheetml/2006/main'


def range_bounds(address):
    match=re.fullmatch(r'\$?([A-Za-z]+)\$?(\d+):\$?([A-Za-z]+)\$?(\d+)',address)
    if not match:raise ValueError('Use an explicit rectangular A1 template range.')
    left,top,right,bottom=match.groups()
    return left.upper(),int(top),right.upper(),int(bottom)


def next_column(column):
    number=0
    for char in column.upper():number=number*26+ord(char)-64
    number+=1;result=''
    while number:number,remainder=divmod(number-1,26);result=chr(65+remainder)+result
    return result


def patch_print(path,sheet,area,break_rows=()):
    # Artifact Tool's documented surface has no native print-area setter.
    # Patch only print metadata after export; never reserialize worksheet cells.
    with ZipFile(path) as z:parts={n:z.read(n) for n in z.namelist()}
    root=E.fromstring(parts['xl/workbook.xml']);sheets=root.findall('{'+NS+'}sheets/{'+NS+'}sheet')
    index=next(i for i,s in enumerate(sheets) if s.get('name')==sheet)
    names=root.find('{'+NS+'}definedNames')
    if names is None:names=E.SubElement(root,'{'+NS+'}definedNames')
    for n in list(names):
        if n.get('localSheetId')==str(index) and n.get('name')=='_xlnm.Print_Area':names.remove(n)
    n=E.SubElement(names,'{'+NS+'}definedName',name='_xlnm.Print_Area',localSheetId=str(index));n.text="'"+sheet.replace("'","''")+"'!"+area
    parts['xl/workbook.xml']=E.tostring(root,xml_declaration=True,encoding='UTF-8',standalone=True)
    # Resolve the actual relationship instead of assuming sheet index == part number.
    rid=sheets[index].get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')
    rels=E.fromstring(parts['xl/_rels/workbook.xml.rels']);target=next(x.get('Target') for x in rels if x.get('Id')==rid)
    import posixpath
    part=target.lstrip('/') if target.startswith('/') else posixpath.normpath('xl/'+target)
    content=parts[part];ws=E.fromstring(content)
    # Insert setup in its schema-defined location before drawing/table/ext parts.
    setup=ws.find('{'+NS+'}pageSetup')
    if setup is None:
        setup=E.Element('{'+NS+'}pageSetup')
        later={'headerFooter','rowBreaks','colBreaks','customProperties','cellWatches','ignoredErrors','smartTags','drawing','legacyDrawing','legacyDrawingHF','picture','oleObjects','controls','webPublishItems','tableParts','extLst'}
        at=next((i for i,c in enumerate(ws) if E.QName(c).localname in later),len(ws));ws.insert(at,setup)
    setup.set('paperSize','9');setup.set('fitToWidth','1');setup.set('fitToHeight','0')
    pr=ws.find('{'+NS+'}sheetPr')
    if pr is None:pr=E.Element('{'+NS+'}sheetPr');ws.insert(0,pr)
    pagepr=pr.find('{'+NS+'}pageSetUpPr')
    if pagepr is None:pagepr=E.SubElement(pr,'{'+NS+'}pageSetUpPr')
    pagepr.set('fitToPage','1')
    if break_rows:
        old=ws.find('{'+NS+'}rowBreaks')
        if old is not None:ws.remove(old)
        breaks=E.Element('{'+NS+'}rowBreaks',count=str(len(break_rows)),manualBreakCount=str(len(break_rows)))
        for row in break_rows:E.SubElement(breaks,'{'+NS+'}brk',id=str(row-1),min='0',max='16383',man='1')
        later={'colBreaks','customProperties','cellWatches','ignoredErrors','smartTags','drawing','legacyDrawing','legacyDrawingHF','picture','oleObjects','controls','webPublishItems','tableParts','extLst'}
        at=next((i for i,c in enumerate(ws) if E.QName(c).localname in later),len(ws));ws.insert(at,breaks)
    parts[part]=E.tostring(ws,xml_declaration=True,encoding='UTF-8',standalone=True)
    temp=Path(str(path)+'.print-metadata.tmp')
    with ZipFile(temp,'x',ZIP_DEFLATED) as z:
        for name,value in parts.items():z.writestr(name,value)
    temp.replace(path)


def make_plan(template,data,mapping,manifest,source_audit,output):
    check_sources(data,manifest,source_audit)
    if len(data['people'])!=1:raise ValueError('Write one workbook per person; scope the source manifest accordingly.')
    person=data['people'][0];fields=person['fields'];used=set();cells=[];copies=[];merges=list(mapping.get('merges',[]));heights=copy.deepcopy(mapping.get('row_heights',[]))
    occupied=set()
    def put(cell,value):
        if cell in occupied:raise ValueError('Overlapping Excel output cell: '+cell)
        occupied.add(cell);cells.append({'cell':cell,'value':value})
    def value(binding,obj,prefix='',index=1):
        keys=binding.get('keys',[binding['key']] if 'key' in binding else [])
        values=[]
        for key in keys:
            v=get_path(obj,key);used.add(prefix+key)
            if isinstance(v,(dict,list)):raise ValueError('Map scalar fields, not entire objects.')
            if v is not None and str(v):values.append(str(v))
        return binding['text'].replace('{index}',str(index)) if 'text' in binding else binding.get('prefix','')+binding.get('separator','\n').join(values)
    for binding in mapping.get('fields',[]):put(binding['cell'],value(binding,fields))
    for item in mapping.get('static_cells',[]):put(item['cell'],item['text'])
    last=mapping.get('minimum_last_row',1)
    for repeat in mapping.get('repeat',[]):
        start=repeat['start_row'];height=repeat['height'];collection=fields.get(repeat['key'],[])
        left,top,right,bottom=range_bounds(repeat['template_range'])
        if height!=bottom-top+1:raise ValueError('Repeat height must match its template range.')
        for ordinal,(i,record) in enumerate(ordered_records(collection,repeat)):
            base=start+ordinal*height
            copies.append({'from':repeat['template_range'],'to':f"{left}{base}:{right}{base+height-1}"})
            for binding in repeat['fields']:
                put(binding['column']+str(base+binding['row']),value(binding,record,f"{repeat['key']}[{i}].",ordinal+1))
            for label in repeat.get('static_cells',[]):put(label['column']+str(base+label['row']),label['text'].replace('{index}',str(ordinal+1)))
            for pattern in repeat.get('merges',[]):merges.append(pattern.format(row=base,**{f'r{k}':base+k for k in range(height)}))
            for j,h in enumerate(repeat.get('row_heights',[])):heights.append({'row':base+j,'height':h})
            last=max(last,base+height-1)
    remaining=[(p,v) for p,v in leaves(fields) if p not in used and not omitted(mapping,p)]
    append=mapping.get('append_unmapped')
    if remaining and not append:raise ValueError('Unmapped nonempty fields: '+', '.join(p for p,_ in remaining[:8]))
    if append:
        row=max(last+2,append.get('start_row',1));labels=append['labels']
        left,top,right,bottom=range_bounds(append['template_range'])
        if top!=bottom or left==right:raise ValueError('Append prototype must be one row with at least two columns.')
        label_column=append.get('label_column',left);value_column=append.get('value_column',next_column(left))
        for p,v in remaining:
            if p not in labels:raise ValueError('Provide a reader-facing label for '+p)
            # Excel cannot split a merged row across pages. Continue long fields
            # in bounded rows without reducing the template font size.
            chunks=[v[i:i+append.get('chunk_chars',600)] for i in range(0,len(v),append.get('chunk_chars',600))]
            for i,chunk in enumerate(chunks):
                copies.append({'from':append['template_range'],'to':f'{left}{row}:{right}{row}'})
                put(label_column+str(row),labels[p]+('（续）' if i else ''));put(value_column+str(row),chunk)
                if value_column!=right:merges.append(f'{value_column}{row}:{right}{row}')
                heights.append({'row':row,'height':min(360,max(30,(len(chunk)//45+chunk.count('\n')+2)*15))});row+=1
            used.add(p)
        last=max(last,row-1)
    if any(h['height']>409 for h in heights):raise ValueError('Excel row height exceeds its native capacity.')
    return {'template':str(Path(template).resolve()),'template_sha256':sha(template),'sheet':mapping['sheet'],'output':str(Path(output).resolve()),
            'clearRanges':[r.format(last=last) for r in mapping['clear_ranges']],
            'unmergeRanges':[r.format(last=last) for r in mapping.get('unmerge_ranges',[])],
            'removeDrawings':mapping.get('remove_sample_drawings',False),'copies':copies,'cells':cells,'merges':merges,
            'rowHeights':heights,'printArea':mapping['print_area'].format(last=last),'previewRange':mapping.get('preview_range'),
            'person_id':person['id'],'fields_written':sorted(used),'last_row':last}


def build(template,data,mapping,manifest,source_audit,output,node,modules,workdir,backend='auto'):
    workdir=Path(workdir);workdir.mkdir(parents=True,exist_ok=False)
    output=Path(output)
    if output.exists():raise ValueError('Use a new Excel output path.')
    plan=make_plan(template,data,mapping,manifest,source_audit,output);dump(workdir/'plan.json',plan)
    selected=('artifact-tool' if node and modules else 'openpyxl') if backend=='auto' else backend
    if selected=='artifact-tool':
        if not node or not modules:raise ValueError('Artifact backend requires --node and --modules; use openpyxl in a generic environment.')
        result=subprocess.run([str(node),str(Path(__file__).with_suffix('.mjs')),str(workdir/'plan.json'),str(modules)],capture_output=True,text=True,encoding='utf8',timeout=240)
        (workdir/'artifact-log.txt').write_text(result.stdout+'\n'+result.stderr,encoding='utf8')
        if result.returncode:raise RuntimeError('Artifact Excel build failed; see '+str(workdir/'artifact-log.txt'))
    elif selected=='openpyxl':
        from xlsx_portable import write_plan
        dump(workdir/'portable-log.json',write_plan(plan))
    else:raise ValueError('Unknown XLSX backend.')
    patch_print(output,mapping['sheet'],plan['printArea'],mapping.get('page_break_rows',[]))
    if sha(template)!=plan['template_sha256']:raise ValueError('Original Excel template changed.')
    report={'status':'built_requires_native_render','backend':selected,'template_sha256':plan['template_sha256'],'output_sha256':sha(output),
            'mapping_sha256':sha_bytes(json.dumps(mapping,ensure_ascii=False,sort_keys=True).encode()),'person_id':plan['person_id'],
            'fields_written':plan['fields_written'],'rows':plan['last_row'],'print_area':plan['printArea']}
    dump(workdir/'build.json',report);return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for arg in ('template','data','map','sources','source-audit','output','workdir'):p.add_argument('--'+arg,type=Path,required=True)
    for arg in ('node','modules'):p.add_argument('--'+arg,type=Path)
    p.add_argument('--backend',choices=['auto','openpyxl','artifact-tool'],default='auto')
    a=p.parse_args();print(json.dumps(build(a.template,load(a.data),load(a.map),load(a.sources),load(a.source_audit),a.output,a.node,a.modules,a.workdir,a.backend),ensure_ascii=False))

if __name__=='__main__':main()
