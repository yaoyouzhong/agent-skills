"""Extract anchored Office media or scanned PDF pages; optional local Windows OCR."""
import argparse
import hashlib
import json
import posixpath
import re
import subprocess
from pathlib import Path
from zipfile import ZipFile
from extract_sources import sha
from source_audit import dump, load


def office_assets(path, outdir):
    from lxml import etree as E
    assets = []
    with ZipFile(path) as z:
        rels, xml = {}, {}
        for name in z.namelist():
            if name.endswith('.xml') or name.endswith('.rels'):
                try: xml[name] = E.fromstring(z.read(name))
                except E.XMLSyntaxError: continue
        for name, root in xml.items():
            if not name.endswith('.rels'): continue
            part = posixpath.join(posixpath.dirname(posixpath.dirname(name)), posixpath.basename(name)[:-5])
            rels[part] = {n.get('Id'):posixpath.normpath(posixpath.join(posixpath.dirname(part),n.get('Target',''))).lstrip('/')
                          if not n.get('Target','').startswith('/') else n.get('Target').lstrip('/')
                          for n in root if n.get('TargetMode') != 'External'}
        formulas = []
        for name, root in xml.items():
            if name.startswith('xl/worksheets/') and name.endswith('.xml'):
                for cell in root.xpath('//*[local-name()="c"]'):
                    for f in cell.xpath('./*[local-name()="f"]'):
                        formulas.append({'part':name,'cell':cell.get('r'),'formula':f.text or ''})
        for name in sorted(n for n in z.namelist() if re.match(r'(?:word|xl)/media/', n) and not n.endswith('/')):
            raw=z.read(name); suffix=Path(name).suffix.lower(); file=outdir/(f'asset-{len(assets)+1:04d}'+suffix)
            file.write_bytes(raw); refs=[]
            for part, mapping in rels.items():
                ids={rid for rid,target in mapping.items() if target==name}
                root=xml.get(part)
                if root is None or not ids: continue
                for node in root.iter():
                    if not any(v in ids for k,v in node.attrib.items() if E.QName(k).localname in ('embed','id','link')):continue
                    anc=node
                    while anc.getparent() is not None and E.QName(anc).localname not in ('pic','p','twoCellAnchor','oneCellAnchor','absoluteAnchor'):
                        anc=anc.getparent()
                    # Capture WPS cell-image IDs and ordinary DrawingML anchor cells.
                    ref={'part':part,'xml_path':root.getroottree().getpath(node)}
                    names=anc.xpath('.//*[local-name()="cNvPr"]/@name | .//*[local-name()="docPr"]/@descr')
                    if names:ref['image_names']=names
                    ref['formula_cells']=[f for f in formulas if any(n in f['formula'] for n in names)]
                    anchor=anc
                    while anchor.getparent() is not None and E.QName(anchor).localname not in ('twoCellAnchor','oneCellAnchor','absoluteAnchor','p'):
                        anchor=anchor.getparent()
                    start=anchor.xpath('./*[local-name()="from"]')
                    if start:ref['drawing_anchor']={E.QName(n).localname:n.text for n in start[0]}
                    refs.append(ref)
            assets.append({'id':f'a{len(assets)+1:04d}','package_part':name,'path':str(file.resolve()),'sha256':hashlib.sha256(raw).hexdigest(),
                           'references':refs,'review_status':'pending','unreferenced':not bool(refs)})
    return assets


def pdf_assets(path,outdir,all_pages=False):
    import pdfplumber
    import pypdfium2 as pdfium
    assets=[]
    with pdfplumber.open(path) as info, pdfium.PdfDocument(str(path)) as pdf:
        for i,p in enumerate(info.pages):
            if not all_pages and len((p.extract_text() or '').strip())>=30:continue
            page=pdf[i];bitmap=page.render(scale=2);file=outdir/f'page-{i+1:04d}.png'
            bitmap.to_pil().save(file);bitmap.close();page.close()
            assets.append({'id':f'page{i+1:04d}','path':str(file.resolve()),'sha256':sha(file),'page':i+1,
                           'references':[{'page':i+1,'kind':'source_page_render'}],'review_status':'pending'})
    return assets


def recognize(asset,outdir,cache=None):
    """A per-run cache only; validate cached output and pixels before reuse."""
    outdir=Path(outdir);cache=cache if cache is not None else {}
    if sha(asset['path'])!=asset['sha256']:raise ValueError('Media changed before OCR.')
    previous=cache.get(asset['sha256'])
    if previous and sha(previous['path'])==previous['sha256']:
        asset['ocr']={**previous,'reused_identical_pixels':True};return asset['ocr']
    result=outdir/(asset['id']+'.ocr.json')
    try:
        input_path=asset['path'];derived=None
        if Path(input_path).suffix.lower() in ('.emf','.wmf'):
            raster=outdir/(asset['id']+'.raster.png')
            subprocess.run(['powershell.exe','-NoProfile','-File',str(Path(__file__).with_name('rasterize_media.ps1')),
                            '-InputPath',input_path,'-OutputPath',str(raster.resolve())],check=True,capture_output=True,timeout=60)
            input_path=str(raster.resolve())
            derived={'path':input_path,'sha256':sha(raster),'source_asset_sha256':asset['sha256'],'method':'Windows GDI metafile rasterization; maximum 3200 pixels'}
        from media_ocr import recognize_orientations
        asset['ocr']=recognize_orientations(asset,outdir,input_path)
        if derived:asset['ocr']['rasterization']=derived
        cache[asset['sha256']]=asset['ocr']
    except (subprocess.SubprocessError,OSError,RuntimeError) as error:
        detail=error.stderr.decode('utf8',errors='replace')[-1800:] if isinstance(error,subprocess.CalledProcessError) and error.stderr else str(error)
        asset['ocr']={'status':'failed','reason':detail,'review_status':'pending'}
    return asset['ocr']


def extract(path,outdir,ocr=False,all_pages=False):
    path=Path(path);outdir=Path(outdir);outdir.mkdir(parents=True,exist_ok=False);before=sha(path)
    if path.suffix.lower() in ('.docx','.xlsx','.xlsm'):assets=office_assets(path,outdir)
    elif path.suffix.lower()=='.pdf':assets=pdf_assets(path,outdir,all_pages)
    else:raise ValueError('Convert a copy of legacy Office documents before media extraction.')
    for a in assets:
        if ocr:
            recognize(a,outdir)
    if sha(path)!=before:raise ValueError('Source changed while reading media.')
    report={'source':str(path.resolve()),'source_sha256':before,'assets':assets,
            'status':'needs_review' if assets else 'no_media','ocr_is_not_human_review':True}
    dump(outdir/'media.json',report);return report


def compare(report,person):
    """Locate claims for side-by-side review; absence is not proof of contradiction."""
    findings=[]
    for asset in report['assets']:
        text=asset.get('ocr',{}).get('text','')
        if not text:continue
        values={'meta.name':person['fields'].get('meta',{}).get('name','')}
        for i,e in enumerate(person['fields'].get('education',[])):
            values.update({f'education[{i}].{k}':e.get(k,'') for k in ('school','major','level','degree','end')})
        compact=re.sub(r'\s+','',text)
        findings.append({'asset_id':asset['id'],'asset_sha256':asset['sha256'],'source':report['source'],
                         'matches':{k:v for k,v in values.items() if v and re.sub(r'\s+','',str(v)) in compact},
                         'unmatched_claims':{k:v for k,v in values.items() if v and re.sub(r'\s+','',str(v)) not in compact},
                         'date_mentions':re.findall(r'(?:19|20)\d{2}\s*[年./-]\s*\d{1,2}(?:\s*[月./-]\s*\d{1,2})?\s*日?',text),
                         'reason':'需区分毕业时间、入学时间、发证时间；OCR 未命中不等于原件不存在。','status':'pending'})
    return findings


def attach_reviewed(report,manifest,reviews,outdir):
    """Attach a transcription only AFTER viewing pixels; never auto-approve OCR."""
    import copy
    from record_checks import digest
    from source_audit import units_for
    result=copy.deepcopy(manifest);outdir=Path(outdir);outdir.mkdir(parents=True,exist_ok=False)
    source=next(s for s in result['sources'] if Path(s['source']).resolve()==Path(report['source']).resolve())
    if sha(source['source'])!=source['sha256'] or source['sha256']!=report['source_sha256']:raise ValueError('Media source changed.')
    assets={a['id']:a for a in report['assets']};units=units_for(source);attached=[]
    for review in reviews:
        asset=assets[review['asset_id']]
        if sha(asset['path'])!=asset['sha256'] or review.get('asset_sha256')!=asset['sha256']:
            raise ValueError('Reviewed image pixels changed.')
        if not all(review.get(k) for k in ('reviewer','reason','owner_name','text')) or review.get('status')!='visually_reviewed':
            raise ValueError('A visual transcription needs reviewer, owner, exact text and reason.')
        if asset.get('package_part'):
            with ZipFile(source['source']) as z:
                if hashlib.sha256(z.read(asset['package_part'])).hexdigest()!=asset['sha256']:raise ValueError('Image does not match the original Office package.')
        elif Path(source['source']).suffix.lower()=='.pdf':
            import pypdfium2 as pdfium
            from PIL import Image
            with pdfium.PdfDocument(source['source']) as pdf:
                page=pdf[int(asset['page'])-1];bitmap=page.render(scale=2)
                expected=bitmap.to_pil().convert('RGB')
                with Image.open(asset['path']) as image:
                    actual=image.convert('RGB')
                    if actual.size!=expected.size or actual.tobytes()!=expected.tobytes():
                        raise ValueError('Reviewed pixels do not match the original PDF page.')
                bitmap.close();page.close()
        unit={'kind':'reviewed_media_text','text':review['text'],'locator':'media:'+asset.get('package_part',str(asset.get('page',asset['id']))),
              'asset_sha256':asset['sha256'],'asset_path':asset['path'],'owner_name':review['owner_name'],
              'reviewer':review['reviewer'],'review_status':'visually_reviewed','reason':review['reason']}
        for key in ('owner_person_id','identity_checks'):
            if key in review:unit[key]=review[key]
        unit['unit_id']='media-'+digest(unit)[:20];units.append(unit);attached.append(unit)
    detail=load(source['detail_file']);detail['units']=units;detail['media_reviews']=attached
    path=outdir/'detail-with-reviewed-media.json';dump(path,detail);source.update(detail_file=str(path.resolve()),detail_sha256=sha(path))
    dump(outdir/'sources.json',result);return result


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path);p.add_argument('--outdir',type=Path,required=True)
    p.add_argument('--ocr',action='store_true');p.add_argument('--all-pdf-pages',action='store_true');p.add_argument('--person-data',type=Path)
    p.add_argument('--reviewed-media',type=Path);p.add_argument('--sources',type=Path);p.add_argument('--reviews',type=Path)
    a=p.parse_args()
    if a.reviewed_media:
        if not a.sources or not a.reviews:p.error('Attach requires --sources and --reviews.')
        r=attach_reviewed(load(a.reviewed_media),load(a.sources),load(a.reviews),a.outdir)
        print(json.dumps({'manifest':str(a.outdir/'sources.json'),'sources':len(r['sources'])}));return
    if not a.source:p.error('Extraction requires --source.')
    r=extract(a.source,a.outdir,a.ocr,a.all_pdf_pages)
    if a.person_data:dump(a.outdir/'claim-comparison.json',compare(r,load(a.person_data)))
    print(json.dumps({'assets':len(r['assets']),'ocr_completed':sum(bool(x.get('ocr',{}).get('text')) for x in r['assets']),'status':r['status']}))


if __name__=='__main__':main()
