"""Derive a clean DOCX form from a selected table with an explicit sample-clear plan."""
import argparse,copy,sys
import subprocess
from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED
from lxml import etree as E
from source_audit import load,dump,norm
from extract_sources import sha
from template_docx import q,set_text,inspect_template


def clean_native(native,plan,output):
    with ZipFile(native) as z:parts={n:z.read(n) for n in z.namelist()}
    root=E.fromstring(parts['word/document.xml']);tables=root.findall('./'+q('body')+'/'+q('tbl'))
    if len(tables)!=1:raise ValueError('A selected form must contain exactly one top-level table.')
    table=tables[0];rows=table.findall(q('tr'))
    for item in plan['blank_cells']:
        row,cell=item['row'],item['cell'];node=rows[row].findall(q('tc'))[cell]
        actual=''.join(n.text or '' for n in node.iter(q('t')))
        if norm(actual)!=norm(item['expected_text']):raise ValueError('Sample-clear plan refers to changed content.')
        set_text(node,'')
    for index in sorted(set(plan.get('remove_rows',[])),reverse=True):table.remove(rows[index])
    allowed={norm(t) for t in plan['keep_text']}
    for cell in table.iter(q('tc')):
        text=''.join(n.text or '' for n in cell.iter(q('t')))
        if text.strip() and norm(text) not in allowed:raise ValueError('Unexpected sample content remains: '+text[:100])
    # Drawings/media are not silently stripped: the plan must explicitly clear them.
    media=[n for n in parts if '/media/' in n and not n.endswith('/')]
    if media or root.findall('.//'+q('drawing')):
        raise ValueError('Selected form still contains images; provide a task-specific image-slot plan.')
    parts['word/document.xml']=E.tostring(root,xml_declaration=True,encoding='UTF-8',standalone=True)
    if Path(output).exists():raise ValueError('Output must be new.')
    with ZipFile(output,'x',ZIP_DEFLATED) as z:
        for n,value in parts.items():z.writestr(n,value)
    return {'template_sha256':sha(output),'blanked_cells':len(plan['blank_cells']),
            'removed_rows':len(plan.get('remove_rows',[])),'remaining_labels':sorted(allowed),'sample_media':media}


def select_ooxml(source,output,table_index):
    with ZipFile(source) as z:parts={n:z.read(n) for n in z.namelist()}
    # This bounded path never attempts to copy unsupported media/linked text silently.
    for n,value in parts.items():
        if n.startswith('word/') and n.endswith('.xml') and n!='word/document.xml':
            if any(n.startswith(prefix) for prefix in ('word/header','word/footer','word/comments','word/footnotes','word/endnotes')) and E.fromstring(value).find('.//'+q('t')) is not None:
                raise ValueError('Sample content outside the selected body table requires a task-specific template adapter.')
    root=E.fromstring(parts['word/document.xml']);body=root.find(q('body'));tables=body.findall(q('tbl'))
    if not isinstance(table_index,int) or table_index<0 or table_index>=len(tables):raise ValueError('TableIndex is zero-based and must match a real top-level table.')
    table=copy.deepcopy(tables[table_index]);section=body.find(q('sectPr'))
    for child in list(body):body.remove(child)
    body.append(table)
    if section is not None:body.append(section)
    parts['word/document.xml']=E.tostring(root,xml_declaration=True,encoding='UTF-8',standalone=True)
    with ZipFile(output,'x',ZIP_DEFLATED) as z:
        for n,value in parts.items():z.writestr(n,value)


def prepare(source,plan,outdir,backend='auto'):
    source=Path(source).resolve();outdir=Path(outdir);outdir.mkdir(parents=True,exist_ok=False)
    before=sha(source)
    if plan.get('source_sha256')!=before:raise ValueError('Template source changed; reinspect it.')
    native=(outdir/'native-form.docx').resolve()
    selected=('word' if sys.platform=='win32' else 'ooxml') if backend=='auto' else backend
    if selected=='word':
        subprocess.run(['powershell.exe','-NoProfile','-File',str(Path(__file__).with_name('copy_template_form.ps1')),
                        '-Source',str(source),'-Destination',str(native),'-TableIndex',str(plan['table_index'])],check=True,capture_output=True,timeout=180)
    elif selected=='ooxml':select_ooxml(source,native,plan['table_index'])
    else:raise ValueError('Unknown template preparation backend.')
    output=(outdir/'template.docx').resolve();report=clean_native(native,plan,output)
    if sha(source)!=before:raise ValueError('Original template changed.')
    report.update(source=str(source),source_sha256=before,table_index=plan['table_index'],output=str(output),backend=selected,
                  native_copy_sha256=sha(native),office_open_and_visual_review='pending')
    dump(outdir/'preparation.json',report);dump(outdir/'inspection.json',inspect_template(output))
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,required=True);p.add_argument('--plan',type=Path,required=True);p.add_argument('--outdir',type=Path,required=True)
    p.add_argument('--backend',choices=['auto','word','ooxml'],default='auto')
    a=p.parse_args();print(__import__('json').dumps(prepare(a.source,load(a.plan),a.outdir,a.backend),ensure_ascii=False))

if __name__=='__main__':main()
