"""Isolated-profile LibreOffice conversion on an original-preserving task copy."""
import os,shutil,subprocess,tempfile
from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED


def find_executable(explicit=None):
    candidates=[explicit,os.environ.get('RESUME_SOFFICE'),shutil.which('soffice'),shutil.which('libreoffice'),'/Applications/LibreOffice.app/Contents/MacOS/soffice']
    return next((Path(p).expanduser().resolve() for p in candidates if p and Path(p).expanduser().is_file()),None)


def select_sheet(source,output,sheet):
    from lxml import etree as E
    ns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    with ZipFile(source) as z:parts={n:z.read(n) for n in z.namelist()}
    root=E.fromstring(parts['xl/workbook.xml']);sheets=root.findall('{'+ns+'}sheets/{'+ns+'}sheet')
    matches=[i for i,s in enumerate(sheets) if s.get('name')==sheet]
    if len(matches)!=1:raise ValueError('Selected Excel sheet not found or ambiguous.')
    selected=matches[0]
    for i,s in enumerate(sheets):s.set('state','visible' if i==selected else 'hidden')
    for view in root.findall('{'+ns+'}bookViews/{'+ns+'}workbookView'):view.set('activeTab',str(selected))
    parts['xl/workbook.xml']=E.tostring(root,xml_declaration=True,encoding='UTF-8',standalone=True)
    with ZipFile(output,'x',ZIP_DEFLATED) as z:
        for n,v in parts.items():z.writestr(n,v)


def convert(source,output,extension,soffice=None,sheet=None):
    source=Path(source).resolve();output=Path(output).resolve()
    if output.exists():raise ValueError('Conversion output must be new.')
    executable=find_executable(soffice)
    if not executable:raise RuntimeError('No configured renderer. Provide Word/Excel on Windows, or an existing LibreOffice executable via --soffice / RESUME_SOFFICE; no application was installed.')
    with tempfile.TemporaryDirectory(prefix='resume-lo-') as folder:
        task=Path(folder);src=task/source.name;out=task/'converted';out.mkdir()
        if sheet:select_sheet(source,src,sheet)
        else:shutil.copy2(source,src)
        cmd=[str(executable),'-env:UserInstallation='+(task/'profile').as_uri(),'--headless','--convert-to',extension,'--outdir',str(out),str(src)]
        result=subprocess.run(cmd,capture_output=True,text=True,encoding='utf8',errors='replace',timeout=180)
        generated=out/(src.stem+'.'+extension)
        if result.returncode or not generated.is_file():raise RuntimeError('LibreOffice did not produce the requested conversion: '+result.stdout+' '+result.stderr)
        output.parent.mkdir(parents=True,exist_ok=True)
        with generated.open('rb') as incoming,output.open('xb') as target:shutil.copyfileobj(incoming,target)
    return output
