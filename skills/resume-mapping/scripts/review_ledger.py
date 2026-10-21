"""Create and verify version-bound review receipts; never treat stale checks as current."""
import argparse
import json
import sys
from pathlib import Path
from extract_sources import sha
from source_audit import current_bindings, dump, load


def bindings(files):
    result={k:{'path':str(Path(v).resolve()),'sha256':sha(v)} for k,v in files.items()}
    manifest=load(files['sources'])
    result['source_state']=current_bindings(load(files['data']),manifest)
    scripts=Path(__file__).resolve().parent
    result['engines']={p.name:sha(p) for p in sorted(scripts.iterdir()) if p.is_file() and p.suffix in ('.py','.ps1','.mjs')}
    return result


def create(files, visual=None, legacy=None):
    audit=load(files['source_audit']);facts=load(files['facts']);render=load(files['render']);build=load(files['build'])
    if build.get('sample_only'):
        raise ValueError('A layout sample cannot close a full-batch review receipt.')
    state=bindings(files)
    if audit.get('bindings')!=state['source_state']:
        raise ValueError('Source audit is stale.')
    if build.get('output_sha256')!=state['output']['sha256'] or build.get('template_sha256')!=state['template']['sha256']:
        raise ValueError('Build report does not describe the current output/template.')
    from template_docx import sha_bytes
    if build.get('mapping_sha256')!=sha_bytes(json.dumps(load(files['map']),ensure_ascii=False,sort_keys=True).encode()):
        raise ValueError('Build report does not describe the current template map.')
    if not render.get('input_unchanged') or render.get('docx_sha256')!=state['output']['sha256']:
        raise ValueError('Render does not bind the current output.')
    pending=[]
    data=load(files['data'])
    from record_checks import validate
    records=validate(data,load(files['sources']))
    if records['issues']:pending.append('record_checks')
    from source_quality import source_pending
    if any(source_pending(data,s) for s in load(files['sources'])['sources']):
        pending.append('source_warnings')
    from field_facts import fact_binding
    if facts.get('data_facts_sha256')!=fact_binding(load(files['data'])):
        raise ValueError('Field-facts report refers to different data/facts.')
    if audit.get('status')!='passed':pending.append('source_coverage')
    if facts.get('status')!='passed':pending.append('field_facts')
    if render.get('nearly_empty_pages'):pending.append('nearly_empty_pages')
    if 'render_check' not in files or load(files['render_check']).get('status')!='passed':pending.append('rendered_content')
    pages=list(range(1,len(render['pages'])+1))
    visual_report=load(visual) if visual else {}
    if visual_report.get('reviewed_pages')!=pages or visual_report.get('status')!='passed' or visual_report.get('pdf_sha256')!=sha(render['pdf']):
        pending.append('visual_review')
    if visual_report.get('page_images') is not None and visual_report['page_images']!=[{'page':p['page'],'sha256':sha(p['png'])} for p in render['pages']]:
        raise ValueError('Visual review page-image evidence changed.')
    if visual:state['visual']={'path':str(Path(visual).resolve()),'sha256':sha(visual)}
    state['rendered_pdf']={'path':render['pdf'],'sha256':sha(render['pdf'])}
    state['page_images']=[{'path':p['png'],'sha256':sha(p['png'])} for p in render['pages']]
    from review_queue import person_gates
    people=person_gates(data,audit,facts,records,load(files['render_check']) if 'render_check' in files else None,not any(x in pending for x in ('visual_review','nearly_empty_pages')),load(files['sources']))
    return {'schema_version':2,'status':'closed' if not pending else 'candidate','pending':pending,'people':people,'bindings':state,
            'legacy_review':{'path':str(Path(legacy).resolve()),'sha256':sha(legacy),'disposition':'superseded_by_current_source_reaudit; historical candidates are not counted as confirmed omissions'} if legacy else None}


def verify(receipt,require_closed=True):
    state=receipt['bindings']
    for key,value in state.items():
        if isinstance(value,dict) and 'path' in value and sha(value['path'])!=value['sha256']:
            raise ValueError('Review invalidated by changed '+key)
    files={k:v['path'] for k,v in state.items() if isinstance(v,dict) and 'path' in v and k not in ('visual','rendered_pdf')}
    fresh=bindings(files)
    if fresh['source_state']!=state['source_state'] or fresh['engines']!=state['engines']:
        raise ValueError('Review invalidated by changed data/source/extraction/engine.')
    for page in state['page_images']:
        if sha(page['path'])!=page['sha256']:raise ValueError('Rendered page changed.')
    if receipt.get('legacy_review') and sha(receipt['legacy_review']['path'])!=receipt['legacy_review']['sha256']:
        raise ValueError('Historical review changed.')
    fresh_receipt=create(files,state.get('visual',{}).get('path'),receipt.get('legacy_review',{}).get('path') if receipt.get('legacy_review') else None)
    if fresh_receipt['status']!=receipt['status'] or fresh_receipt['pending']!=receipt['pending'] or fresh_receipt['bindings']!=state or fresh_receipt['people']!=receipt.get('people'):
        raise ValueError('Review receipt does not match the current gates.')
    if require_closed and receipt['status']!='closed':raise ValueError('Review has unresolved gates: '+', '.join(receipt['pending']))
    return {'status':'passed','receipt_status':receipt['status'],'version_bindings_verified':True}


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    c=sub.add_parser('create');c.add_argument('--files',type=Path,required=True);c.add_argument('--visual',type=Path);c.add_argument('--legacy',type=Path);c.add_argument('--out',type=Path,required=True)
    v=sub.add_parser('check');v.add_argument('--receipt',type=Path,required=True);v.add_argument('--allow-candidate',action='store_true')
    a=p.parse_args()
    if a.command=='create':
        if a.out.exists():p.error('Use a new receipt path.')
        r=create(load(a.files),a.visual,a.legacy);dump(a.out,r);print(json.dumps({'status':r['status'],'pending':r['pending']}));return 0 if r['status']=='closed' else 2
    print(json.dumps(verify(load(a.receipt),not a.allow_candidate)));return 0


if __name__=='__main__':sys.exit(main())
