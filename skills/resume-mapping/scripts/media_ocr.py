"""Local OCR orientation/quality retries. Scores rank candidates, never certify accuracy."""
import re
import subprocess
from pathlib import Path
from PIL import Image, ImageOps, ImageStat
from extract_sources import sha
from source_audit import dump, load


def text_score(text):
    text=re.sub(r'\s+','',text)
    meaningful=len(re.findall(r'[\u4e00-\u9fffA-Za-z0-9]',text))
    keywords=len(re.findall(r'毕业|学位|大学|学院|姓名|项目|经历|本科|学士|硕士|博士|证书|专业|教育',text))
    broken=text.count('\ufffd')
    strokes=len(re.findall(r'[丶丿丷冫乁巛亻氵]',text))
    punctuation=len(text)-meaningful
    return meaningful+keywords*12-broken*5-strokes*8-punctuation*2


def deskew(image):
    """Conservative small-angle projection search; keep the original on weak evidence."""
    import numpy as np
    sample=ImageOps.grayscale(image.copy());sample.thumbnail((1000,1000))
    def score(im):
        a=np.asarray(im)<150
        return float(np.var(a.mean(axis=1)))
    base=score(sample); candidates=[(base,0)]
    for angle in (-4,-3,-2,-1,1,2,3,4):
        candidates.append((score(sample.rotate(angle,expand=False,fillcolor=255)),angle))
    best,angle=max(candidates)
    if not base or best<base*1.12:angle=0
    return image.rotate(angle,expand=True,fillcolor='white') if angle else image,angle


def recognize_orientations(asset, outdir, input_path=None):
    outdir=Path(outdir);original=Path(input_path or asset['path'])
    if sha(asset['path'])!=asset['sha256']:raise ValueError('Original image changed.')
    with Image.open(original) as im:
        image=ImageOps.exif_transpose(im).convert('RGB')
    original_size=image.size
    image.thumbnail((3200,3200))
    candidates=[]
    for angle in (0,90,180,270):
        oriented=image.rotate(angle,expand=True,fillcolor='white')
        prepared,skew=deskew(oriented)
        png=outdir/f"{asset['id']}-rotate-{angle}.png";prepared.save(png)
        output=png.with_suffix('.ocr.json')
        try:
            subprocess.run(['powershell.exe','-NoProfile','-File',str(Path(__file__).with_name('windows_ocr.ps1')),
                            '-InputPath',str(png.resolve()),'-OutputPath',str(output.resolve())],
                           check=True,capture_output=True,timeout=60)
            raw=load(output)
            candidates.append({'angle':angle,'deskew_degrees':skew,'input':str(png.resolve()),'input_sha256':sha(png),
                'raw_result':str(output.resolve()),'raw_result_sha256':sha(output),'ranking_score':text_score(raw.get('text','')),**raw})
        except (subprocess.SubprocessError,OSError) as error:
            candidates.append({'angle':angle,'status':'failed','reason':str(error),'ranking_score':-1})
    valid=[c for c in candidates if c.get('status')!='failed']
    if not valid:raise RuntimeError('All local OCR orientations failed; inspect candidate logs.')
    if max(c['ranking_score'] for c in valid)<40:
        # Blue/green security lines often dominate a certificate. This is a
        # derived retry only; originals and ordinary OCR results stay intact.
        import numpy as np
        a=np.asarray(image).astype('int16');r,g,b=a[:,:,0],a[:,:,1],a[:,:,2]
        mask=(b-r>8)&(g-r>5)&(r>65)
        a[mask]=255
        cleaned=ImageOps.autocontrast(ImageOps.grayscale(Image.fromarray(a.astype('uint8'))))
        cleaned=cleaned.point(lambda v:255 if v>150 else 0).convert('RGB')
        for angle in (0,90,180,270):
            png=outdir/f"{asset['id']}-security-lines-{angle}.png"
            cleaned.rotate(angle,expand=True,fillcolor='white').save(png);output=png.with_suffix('.ocr.json')
            try:
                subprocess.run(['powershell.exe','-NoProfile','-File',str(Path(__file__).with_name('windows_ocr.ps1')),
                                '-InputPath',str(png.resolve()),'-OutputPath',str(output.resolve())],check=True,capture_output=True,timeout=60)
                raw=load(output)
                candidates.append({'angle':angle,'deskew_degrees':0,'variant':'security-line-suppression',
                    'input':str(png.resolve()),'input_sha256':sha(png),'raw_result':str(output.resolve()),
                    'raw_result_sha256':sha(output),'ranking_score':text_score(raw.get('text','')),**raw})
            except (subprocess.SubprocessError,OSError) as error:
                candidates.append({'angle':angle,'variant':'security-line-suppression','status':'failed','reason':str(error),'ranking_score':-1})
        valid=[c for c in candidates if c.get('status')!='failed']
    chosen=max(valid,key=lambda c:c['ranking_score'])
    text=chosen.get('text','');warnings=[]
    if len(re.sub(r'\s','',text))<12:warnings.append('empty_or_short_ocr')
    if chosen['ranking_score']<20:warnings.append('no_readable_candidate_visual_fallback_required')
    if '\ufffd' in text:warnings.append('replacement_glyphs')
    if len(valid)<4:warnings.append('some_orientation_attempts_failed')
    report={**chosen,'asset_sha256':asset['sha256'],'original_dimensions':original_size,
            'candidates':candidates,'quality_warnings':warnings,'confidence':None,
            'ranking_is_not_confidence':True,'review_status':'machine_unreviewed',
            'preprocessing':'EXIF orientation, max 3200px, conservative deskew, four rotations; original retained'}
    path=outdir/(asset['id']+'.ocr.json');dump(path,report)
    return {'path':str(path.resolve()),'sha256':sha(path),**report}
