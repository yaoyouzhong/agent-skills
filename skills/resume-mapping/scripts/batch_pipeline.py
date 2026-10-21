"""Prepare, review, sample, compile and verify a resume batch without relaxing its gates."""
import argparse
import copy
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path
from batch_state import Task, digest, engines, file_hash, read, write

HERE = Path(__file__).parent


def runtime():
    packages = {}
    for name in ('pdfplumber', 'python-docx', 'lxml', 'openpyxl', 'pypdfium2'):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    return {'python': platform.python_version(), 'platform': sys.platform, 'packages': packages}


def dependency_hashes():
    return engines(*sorted(p.name for p in HERE.glob('*.py') if p.name != 'batch_state.py'))


def source_state(manifest):
    # Always rehash current originals and extraction artifacts before using any
    # cached semantic/build stage, including when the filename did not change.
    from source_audit import current_bindings
    return current_bindings({'people': []}, manifest)['sources']


def prepare(args):
    from extract_sources import EXTENSIONS, extract_one
    from review_bundle import bundle, snapshot
    task = Task(args.workdir, create=not (Path(args.workdir)/'batch-state.json').exists())
    paths, ignored = set(), []
    for value in args.input:
        value = value.resolve(strict=True)
        if value.is_dir():
            if task.root.is_relative_to(value):
                raise ValueError('The task directory must be outside scanned input directories.')
            for p in value.rglob('*'):
                if p.is_file() and not p.name.startswith('~$'):
                    (paths.add(p.resolve()) if p.suffix.lower() in EXTENSIONS else ignored.append(str(p)))
        else:
            if value.suffix.lower() not in EXTENSIONS:
                raise ValueError('Unsupported explicit input: '+str(value))
            paths.add(value)
    if not paths:
        raise ValueError('No original resume files found.')
    ids = task.state.setdefault('source_ids', {})
    order_map = read(args.pdf_order_map) if args.pdf_order_map else {}
    env = runtime()
    extraction_engines = engines('batch_pipeline.py', 'extract_sources.py', 'pdf_intake.py', 'excel_intake.py',
                                 'libreoffice_bridge.py', 'office_bridge.ps1')
    records = []
    for path in sorted(paths, key=str):
        if str(path) not in ids:
            ids[str(path)] = 's'+str(len(ids)+1).zfill(4)
        sid = ids[str(path)]
        bindings = {'path': str(path), 'sha256': file_hash(path), 'order': order_map.get(str(path)),
                    'engines': extraction_engines, 'runtime': env, 'id': sid}
        def action(folder, path=path, sid=sid, bindings=bindings):
            record = extract_one(path, folder, sid, bindings['order'])
            if record['sha256'] != bindings['sha256'] or file_hash(path) != bindings['sha256']:
                raise ValueError('Original changed during extraction.')
            if record['status'] == 'error':
                write(folder/'error.json', record)
                raise ValueError(record['error'])
            return record
        records.append(task.step('extract-'+sid, bindings, action))
    previous = task.state.get('prepared')
    previous_target = task.state.get('original_target')
    old = read(previous['sources'])['sources'] if previous else []
    old_by_path = {s['source']: s for s in old}
    changes = {'added': [], 'changed': [], 'removed': sorted(set(old_by_path)-{r['source'] for r in records}), 'unchanged': []}
    for record in records:
        before = old_by_path.get(record['source'])
        key = 'added' if before is None else 'unchanged' if all(before.get(k) == record.get(k) for k in ('sha256', 'detail_sha256', 'text_sha256')) else 'changed'
        changes[key].append(record['id'])
    template = args.template.resolve(strict=True)
    if template.suffix.lower() not in ('.docx', '.xlsx'):
        raise ValueError('Prepare an editable DOCX/XLSX target copy using the existing format adapter first.')
    def assemble(folder):
        manifest = {'sources': records, 'ignored_files': ignored}
        write(folder/'sources.json', manifest)
        target = folder/('template'+template.suffix.lower())
        shutil.copyfile(template, target)
        if file_hash(target) != file_hash(template):
            raise ValueError('Target changed during preparation.')
        if target.suffix == '.docx':
            from template_docx import inspect_template
            inspection = inspect_template(target)
        else:
            from extract_sources import read_xlsx
            inspection = read_xlsx(target)[0]
        write(folder/'template-inspection.json', inspection)
        result = {'sources': str(folder/'sources.json'), 'source_snapshot': snapshot(manifest), 'template': str(target),
                  'inspection': str(folder/'template-inspection.json'), **bundle(manifest, folder/'source-bundles')}
        return result
    prepared = task.step('prepare-bundle', {'records': records, 'ignored': ignored, 'target': str(template),
                         'target_sha256': file_hash(template), 'engines': engines('batch_pipeline.py', 'review_bundle.py',
                         'source_audit.py', 'template_docx.py', 'extract_sources.py'), 'runtime': env}, assemble)
    task.state['prepared'] = prepared
    task.state['source_changes'] = changes
    task.state['original_target'] = {'path': str(template), 'sha256': file_hash(template)}
    affected_sources = set(changes['changed']+changes['added']) | {
        old_by_path[path]['id'] for path in changes['removed']}
    previous_data = task.state.get('latest_core', {}).get('data')
    prior_people = read(previous_data)['people'] if previous_data else []
    plan = {'source_review_required': [p['id'] for p in prior_people if affected_sources.intersection(p['source_ids'])],
            'unchanged_people_available_for_validated_reuse': [p['id'] for p in prior_people if not affected_sources.intersection(p['source_ids'])],
            'new_or_changed_source_ids': sorted(affected_sources),
            'target_changed': previous_target is not None and previous_target['sha256'] != file_hash(template),
            'rule': 'Reread affected people and new source files. Revalidate all exact references and final gates. '
                    'A changed target requires its own field mapping and blank review. Render reuse requires identical reviewed pixels.'}
    task.state['review_plan'] = plan
    task.save()
    return {'status': 'awaiting_agent_source_review', **prepared, 'source_changes': changes, 'review_plan': plan,
            'next': 'Read each full source bundle once; write reviewed-data.json and the current template map. Then run this command with run.'}


def validate_visual(path, render):
    report = read(path)
    expected = list(range(1, len(render['pages'])+1))
    if report.get('status') != 'passed' or report.get('pdf_sha256') != file_hash(render['pdf']) or report.get('reviewed_pages') != expected:
        raise ValueError('Visual evidence must bind the current PDF and every page actually reviewed.')
    if report.get('page_images') is not None and report['page_images'] != [
        {'page': p['page'], 'sha256': file_hash(p['png'])} for p in render['pages']]:
        raise ValueError('Visual page-image evidence changed.')
    return report


def render_context(soffice=None):
    from environment_check import inspect
    context = inspect(soffice)
    directories = ([Path(os.environ.get('WINDIR', r'C:\Windows'))/'Fonts',
                    Path(os.environ.get('LOCALAPPDATA', ''))/'Microsoft/Windows/Fonts'] if sys.platform == 'win32' else
                   [Path('/System/Library/Fonts'), Path('/Library/Fonts'), Path.home()/'Library/Fonts'] if sys.platform == 'darwin' else
                   [Path('/usr/share/fonts'), Path.home()/'.local/share/fonts'])
    context['fonts'], context['font_read_errors'] = {}, []
    for folder in directories:
        if not folder.is_dir():continue
        try:
            for p in sorted(folder.rglob('*')):
                if p.is_file():context['fonts'][str(p.resolve())] = file_hash(p)
        except OSError as error:
            context['font_read_errors'].append(str(error))
    if context.get('libreoffice'):
        context['renderer_hash'] = file_hash(context['libreoffice'])
    if sys.platform == 'win32' and not soffice:
        import winreg
        # Bind the installed Office executable, not just a registration boolean.
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\WINWORD.EXE') as key:
                executable = Path(winreg.QueryValueEx(key, None)[0])
            context['renderer_hash'] = file_hash(executable)
        except FileNotFoundError:
            context['renderer_hash'] = None
    if context['font_read_errors'] or not context.get('renderer_hash'):
        # Conversion can proceed with the existing renderer; persistent render
        # cache is disabled when its actual environment cannot be fully bound.
        context['non_reusable_context'] = time.monotonic_ns()
    return context


def render_stage(task, output, context, soffice=None):
    def action(folder):
        command = [sys.executable, str(HERE/'render_output.py'), '--docx', str(output), '--outdir', str(folder/'render')]
        if soffice:
            command += ['--soffice', str(soffice)]
        proc = subprocess.run(command, capture_output=True, text=True, encoding='utf-8')
        (folder/'render.log').write_text(proc.stdout+'\n'+proc.stderr, encoding='utf-8')
        if proc.returncode:
            raise RuntimeError('Native rendering failed; see '+str(folder/'render.log'))
        return {'render': str(folder/'render/render.json')}
    return task.step('render', {'output': file_hash(output), 'context': context,
                     'engines': engines('batch_pipeline.py', 'render_output.py', 'layout_review.py', 'extract_sources.py',
                                        'office_bridge.ps1', 'libreoffice_bridge.py')}, action)


def run(args):
    from review_bundle import hydrate, exceptions
    from normalize_dates import normalize
    from record_evidence import locate
    from apply_policies import apply
    from field_facts import classify
    from source_audit import audit
    from record_checks import validate
    from fill_coverage import coverage
    from template_docx import build, verify, check_sources, leaves, selected_people
    task = Task(args.workdir)
    prepared = task.state['prepared']
    manifest = read(prepared['sources'])
    source_binding = source_state(manifest)
    target = Path(prepared['template'])
    original = task.state['original_target']
    if file_hash(original['path']) != original['sha256'] or file_hash(target) != original['sha256']:
        raise ValueError('Original target or prepared target changed; prepare a new revision first.')
    mapping = read(args.map)
    data = read(args.data)
    if target.suffix != '.docx':
        raise ValueError('The common prepare/cache/bundle stage supports XLSX targets; use the existing template_xlsx.py native adapter for generation and review. No format substitution is performed.')
    def core(folder):
        expanded, dates = normalize(hydrate(data, manifest))
        # Never replace already provided record/evidence scopes with a looser search.
        reports = []
        for index, person in enumerate(expanded['people']):
            if any(f'projects[{i}]' not in person.get('record_sources', {}) for i in range(len(person['fields'].get('projects', [])))):
                partial = {**expanded, 'people': [person]}
                located, report = locate(partial, manifest)
                expanded['people'][index] = located['people'][0]
                reports.append(report)
        expanded['require_record_evidence'] = True
        normalized, policy, policy_issues = apply(expanded, read(args.clients) if args.clients else [], manifest)
        result, facts = classify(normalized, manifest, read(args.decisions) if args.decisions else {})
        records = validate(result, manifest)
        source_audit = audit(result, manifest)
        fill = coverage(result, mapping)
        values = {'data': result, 'dates': dates, 'location': reports, 'policies': {'changes': policy, 'issues': policy_issues},
                  'facts': facts, 'records': records, 'source-audit': source_audit, 'coverage': fill}
        paths = {}
        for name, value in values.items():
            path = folder/(name+'.json');write(path, value);paths[name] = str(path)
        paths['review'] = exceptions(result, manifest, mapping, fill, {'facts': facts, 'records': records, 'source': source_audit}, folder/'exceptions')
        return paths
    result = task.step('review-and-check', {'data': file_hash(args.data), 'map': file_hash(args.map),
                       'clients': file_hash(args.clients) if args.clients else None,
                       'decisions': file_hash(args.decisions) if args.decisions else None,
                       'sources': source_binding, 'engines': dependency_hashes(), 'runtime': runtime()}, core)
    task.state['latest_core'] = result
    task.state['latest_input'] = {'data': str(args.data.resolve()), 'map': str(args.map.resolve())}
    task.save()
    final = read(result['data']);source_audit = read(result['source-audit']);fill = read(result['coverage'])
    # A missing blank review or source omission is returned as work for the Agent,
    # never converted into an automatic "not provided" classification.
    if fill['unreviewed_blank_slots']:
        return {'status': 'awaiting_blank_source_review', 'unreviewed_blank_slots': fill['unreviewed_blank_slots'], **result}
    missed = [s for s in fill['slots'] if not s['filled'] and s['blank_reason'] == 'available_but_missed']
    if missed:
        return {'status': 'available_information_still_unfilled', 'missed_slots': missed, **result}
    check_sources(final, manifest, source_audit)
    projection = [{'id': p['id'], 'fields': p['fields']} for p in final['people']]
    sizes = sorted((sum(len(str(v)) for _, v in leaves(p['fields'])), i, str(p['id'])) for i, p in enumerate(final['people']))
    ids = list(dict.fromkeys([sizes[0][2], sizes[-1][2]]))
    def output_stage(folder, sample=None):
        path = folder/('layout-sample.docx' if sample is not None else 'resumes.docx')
        report = build(target, mapping, final, manifest, path, source_audit, sample)
        write(folder/'build.json', report)
        return {'output': str(path), 'build': str(folder/'build.json')}
    sample_projection = [p for p in projection if str(p['id']) in ids]
    sample = task.step('layout-sample', {'template': file_hash(target), 'map': file_hash(args.map),
                       'people': sample_projection, 'order': ids, 'mode': final.get('output_mode'),
                       'engines': engines('batch_pipeline.py', 'template_docx.py')}, lambda folder: output_stage(folder, ids))
    if args.defer_render:
        return {'status': 'layout_sample_built_not_rendered', **result, 'sample': sample}
    context = task.step('render-context', {'runtime': runtime(), 'soffice': str(args.soffice), 'engines': engines('batch_pipeline.py', 'environment_check.py'),
                        # Always inspect current fonts/renderer; no prior context is trusted here.
                        'nonce': len(task.state['events'])}, lambda folder: render_context(args.soffice))
    sample_render = render_stage(task, Path(sample['output']), context, args.soffice)
    if not args.pilot_review:
        return {'status': 'awaiting_layout_sample_visual_review', **result, 'sample': sample,
                'sample_person_ids': ids, **sample_render,
                'next': 'Actually inspect all sample page images; provide a hash-bound --pilot-review, then rerun.'}
    validate_visual(args.pilot_review, read(sample_render['render']))
    complete = task.step('build', {'template': file_hash(target), 'map': file_hash(args.map), 'people': projection,
                         'mode': final.get('output_mode'), 'engines': engines('batch_pipeline.py', 'template_docx.py')}, output_stage)
    # Cached output is rechecked against CURRENT data and CURRENT source gates.
    current = task.step('verify-current', {'data': file_hash(result['data']), 'map': file_hash(args.map),
                        'sources': source_binding, 'audit': file_hash(result['source-audit']), 'output': file_hash(complete['output']),
                        'engines': dependency_hashes()}, lambda folder: verify(target, mapping, final, manifest, Path(complete['output']), source_audit))
    full_render = render_stage(task, Path(complete['output']), context, args.soffice)
    from check_rendered import check
    def rendered(folder):
        report = check(final, mapping, read(full_render['render']))
        write(folder/'render-check.json', report)
        return {'report': str(folder/'render-check.json'), 'status': report['status']}
    rendered_check = task.step('render-check', {'people': projection, 'map': file_hash(args.map), 'render': file_hash(full_render['render']),
                              'engines': engines('batch_pipeline.py', 'check_rendered.py', 'source_audit.py')}, rendered)
    task.state['latest_output'] = {**complete, **full_render, 'render_check': rendered_check['report'], 'pilot_render': sample_render['render']}
    task.save()
    if rendered_check['status'] != 'passed':
        return {'status': 'rendered_content_requires_review', **result, **task.state['latest_output']}
    if not args.visual:
        reuse = None
        if args.previous_receipt:
            from layout_review import plan
            reuse = plan(read(full_render['render']), args.previous_receipt)
            path = task.root/('visual-reuse-'+digest(reuse)[:20]+'.json')
            if not path.exists():write(path, reuse)
            reuse = str(path)
        return {'status': 'awaiting_full_visual_review', **result, **task.state['latest_output'],
                'reuse_plan': reuse, 'next': 'Actually inspect every unreviewed page, then supply --visual. Pixel-identical previously reviewed pages may use layout_review complete.'}
    validate_visual(args.visual, read(full_render['render']))
    from review_ledger import create, verify as verify_receipt
    files = {'sources': prepared['sources'], 'data': result['data'], 'source_audit': result['source-audit'], 'facts': result['facts'],
             'template': str(target), 'map': str(args.map.resolve()), **{k: complete[k] for k in ('output', 'build')},
             'render': full_render['render'], 'render_check': rendered_check['report']}
    def receipt(folder):
        report = create(files, args.visual)
        write(folder/'review-files.json', files);write(folder/'receipt.json', report)
        check = verify_receipt(report, require_closed=False)
        write(folder/'receipt-check.json', check)
        return {'receipt': str(folder/'receipt.json'), 'receipt_status': report['status'], 'pending': report['pending']}
    closure = task.step('receipt', {'files': {k: file_hash(v) for k, v in files.items()}, 'visual': file_hash(args.visual),
                        'sources': source_binding, 'engines': dependency_hashes()}, receipt)
    # This also runs on a cache hit, rehashing current external files and source
    # originals after rendering/visual work rather than trusting an old receipt.
    verify_receipt(read(closure['receipt']), require_closed=False)
    task.event('conversion_complete', output=complete['output'], receipt=closure['receipt'])
    return {'status': 'converted_and_visually_reviewed', **result, **task.state['latest_output'], **closure,
            'quality_scope': 'Existing-information conversion; receipt may remain candidate for unresolved source facts.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    prep = commands.add_parser('prepare')
    prep.add_argument('--input', type=Path, nargs='+', required=True);prep.add_argument('--template', type=Path, required=True)
    prep.add_argument('--workdir', type=Path, required=True);prep.add_argument('--pdf-order-map', type=Path)
    process = commands.add_parser('run')
    for name in ('workdir', 'data', 'map'):
        process.add_argument('--'+name, type=Path, required=True)
    for name in ('clients', 'decisions', 'pilot-review', 'visual', 'previous-receipt', 'soffice'):
        process.add_argument('--'+name, type=Path)
    process.add_argument('--defer-render', action='store_true', help='Stop at a sample candidate; never counts as layout approval.')
    status = commands.add_parser('status');status.add_argument('--workdir', type=Path, required=True)
    mark = commands.add_parser('mark');mark.add_argument('--workdir', type=Path, required=True)
    mark.add_argument('--phase', required=True);mark.add_argument('--state', choices=['start', 'stop'], required=True)
    args = parser.parse_args()
    try:
        if args.command == 'prepare':
            result = prepare(args)
        elif args.command == 'run':
            result = run(args)
        else:
            task = Task(args.workdir)
            if args.command == 'mark':task.mark(args.phase, args.state)
            result = {'prepared': task.state.get('prepared'), 'source_changes': task.state.get('source_changes'),
                      'latest_core': task.state.get('latest_core'), 'latest_output': task.state.get('latest_output'), 'timing': task.timing()}
        write(Path(args.workdir)/'last-command.json', result)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result.get('status') in (None, 'converted_and_visually_reviewed') else 2
    except Exception as error:
        print(json.dumps({'status': 'failed', 'error': str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
