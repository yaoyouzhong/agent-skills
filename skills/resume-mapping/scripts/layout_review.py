"""Heuristic layout warnings and hash-proven reuse of actually reviewed page images."""
import argparse
from pathlib import Path
from extract_sources import sha
from source_audit import dump,load


def analyze(render):
    import pdfplumber
    pages=[];warnings=[]
    with pdfplumber.open(render['pdf']) as pdf:
        for i,p in enumerate(pdf.pages):
            chars=[c for c in p.chars if c.get('text','').strip()]
            lines={round(c['top']/3) for c in chars}
            box=[min(c['x0'] for c in chars),min(c['top'] for c in chars),max(c['x1'] for c in chars),max(c['bottom'] for c in chars)] if chars else None
            own=[]
            if not chars:own.append('no_text_check_images_or_blank_page')
            elif len(pdf.pages)>1 and len(lines)<=5 and len(chars)<160:own.append('short_tail_page')
            if box and (box[0]<2 or box[1]<2 or box[2]>p.width-2 or box[3]>p.height-2):own.append('text_near_page_edge')
            text_lines=(p.extract_text() or '').strip().splitlines()
            if box and box[3]>p.height*.85 and text_lines and text_lines[-1].strip() in ('项目经历','工作经历','教育经历','项目介绍','项目职责','相关项目经验','具备的特长与专业技能'):
                own.append('possible_orphan_heading')
            page={'page':i+1,'text_characters':len(chars),'approximate_text_lines':len(lines),'text_bbox':box,'warnings':own}
            pages.append(page)
            warnings.extend({'page':i+1,'code':code,'reason':'自动提示需视觉判定；不会自行认定截断或删除页面。'} for code in own)
    return {'pdf_sha256':sha(render['pdf']),'pages':pages,'warnings':warnings,'status':'warnings' if warnings else 'passed',
            'limitations':'文字边界不能判断表格边框、图片裁切或语义完整度，仍须查看所有未验证页面。'}


def plan(render,old_receipt_path):
    receipt=load(old_receipt_path);state=receipt['bindings'];visual=state.get('visual')
    if not visual or sha(visual['path'])!=visual['sha256']:raise ValueError('Old visual evidence changed or is missing.')
    reviewed=load(visual['path']);old_pdf=state['rendered_pdf']
    if reviewed.get('status')!='passed' or reviewed.get('pdf_sha256')!=old_pdf['sha256'] or sha(old_pdf['path'])!=old_pdf['sha256']:
        raise ValueError('Old visual review does not bind the reviewed PDF.')
    if reviewed.get('reviewed_pages')!=list(range(1,len(state['page_images'])+1)):raise ValueError('Old visual review is incomplete.')
    old={}
    for i,p in enumerate(state['page_images'],1):
        if sha(p['path'])!=p['sha256']:raise ValueError('Old reviewed image changed.')
        old.setdefault(p['sha256'],[]).append(i)
    pages=[]
    for p in render['pages']:
        h=sha(p['png']);match=old.get(h,[])
        pages.append({'page':p['page'],'png_sha256':h,'status':'reused' if match else 'needs_visual_review','old_pages':match})
    return {'pdf_sha256':sha(render['pdf']),'old_receipt':{'path':str(Path(old_receipt_path).resolve()),'sha256':sha(old_receipt_path)},
            'pages':pages,'reused_pages':[p['page'] for p in pages if p['status']=='reused'],
            'needs_visual_review':[p['page'] for p in pages if p['status']!='reused'],
            'scope':'Only pixel-identical reviewed images are reused. Business facts, audits and code are revalidated separately.'}


def complete(render,reuse,new_review):
    if reuse['pdf_sha256']!=sha(render['pdf']) or new_review.get('pdf_sha256')!=reuse['pdf_sha256']:
        raise ValueError('Visual plan or new review refers to a different PDF.')
    # Regenerate rather than trusting a manually edited reuse plan.
    if plan(render,reuse['old_receipt']['path'])!=reuse:raise ValueError('Stale or edited visual reuse plan.')
    fresh=set(new_review.get('reviewed_pages',[]));required=set(reuse['needs_visual_review'])
    if new_review.get('status')!='passed' or not required<=fresh or not fresh<=set(range(1,len(render['pages'])+1)):
        raise ValueError('Every changed page requires an actual successful visual review.')
    return {'status':'passed','pdf_sha256':reuse['pdf_sha256'],'reviewed_pages':list(range(1,len(render['pages'])+1)),
            'page_images':[{'page':p['page'],'sha256':sha(p['png'])} for p in render['pages']],
            'reused_pages':reuse['reused_pages'],'newly_reviewed_pages':sorted(fresh),'reuse_evidence':reuse['old_receipt'],
            'notes':new_review.get('notes',[])}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['analyze','plan','complete'])
    p.add_argument('--render',type=Path,required=True);p.add_argument('--old-receipt',type=Path);p.add_argument('--plan',type=Path)
    p.add_argument('--new-review',type=Path);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    if a.out.exists():p.error('Use a new report path.')
    r=analyze(load(a.render)) if a.command=='analyze' else plan(load(a.render),a.old_receipt) if a.command=='plan' else complete(load(a.render),load(a.plan),load(a.new_review))
    dump(a.out,r);print({k:v for k,v in r.items() if k in ('status','reused_pages','needs_visual_review')})


if __name__=='__main__':main()
