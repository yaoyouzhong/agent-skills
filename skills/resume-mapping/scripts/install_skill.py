"""Install this verified directory bundle for a local agent; no global installs."""
import argparse,hashlib,json,os,re,shutil,subprocess,sys,tempfile,venv
from pathlib import Path,PurePosixPath

NAME='resume-mapping'
ROOT=Path(__file__).resolve().parents[1]


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def manifest(root):
    root=Path(root).resolve()
    m=json.loads((root/'package-manifest.json').read_text('utf8'))
    if m.get('name')!=NAME or not isinstance(m.get('version'),str) or not re.fullmatch(r'[1-9][0-9]*',m['version']):raise ValueError('Unexpected package identity.')
    entries=m['files']
    if 'SKILL.md' not in entries:raise ValueError('Package entrypoint missing.')
    for relative,expected in entries.items():
        p=PurePosixPath(relative)
        if p.is_absolute() or '..' in p.parts or '\\' in relative or ':' in relative:raise ValueError('Unsafe manifest path.')
        target=root/relative
        if not target.is_file() or target.is_symlink() or not target.resolve().is_relative_to(root):raise ValueError('Missing or redirected package member: '+relative)
        if sha(target)!=expected:raise ValueError('Package hash mismatch: '+relative)
    desktop_metadata={'.ds_store','thumbs.db','desktop.ini'}
    actual={p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.name!='package-manifest.json' and p.name.casefold() not in desktop_metadata}
    if actual!=set(entries):raise ValueError('Unexpected or missing public package files.')
    return m


def destination(host,target_dir=None,home=None,environ=None):
    if target_dir is not None:
        target=Path(target_dir).expanduser().absolute()
    else:
        home=Path(home or Path.home());env=os.environ if environ is None else environ
        roots={'claude-code':home/'.claude'/'skills',
               'deepseek-harness':Path(env.get('DSH_HOME') or home/'.dsh')/'skills',
               'codex':home/'.agents'/'skills'}
        if host not in roots:
            raise ValueError('WorkBuddy: use its native ZIP importer, or pass --target-dir after verifying its real configured skills directory. Other clients also need --target-dir.')
        target=roots[host]/NAME
    if target.name!=NAME:raise ValueError('--target-dir must name the full resume-mapping directory.')
    if any(p.is_symlink() for p in (target,*target.parents)):raise ValueError('Redirected install paths require a separate reviewed copy; no symlink traversal.')
    return target.resolve()


def install(root,target,apply=False):
    root=Path(root).resolve();target=Path(target).absolute()
    if any(p.is_symlink() for p in (target,*target.parents)):raise ValueError('Redirected installation path rejected.')
    target=target.resolve();m=manifest(root)
    if target==root:return {'status':'already_installed','target':str(target),'files':len(m['files'])+1,'client_discovery':'unverified'}
    if target.is_relative_to(root) or root.is_relative_to(target):raise ValueError('Install source and target must be separate.')
    if target.exists():
        if not target.is_dir():raise ValueError('Install target is not a directory.')
        expected={**m['files'],'package-manifest.json':sha(root/'package-manifest.json')}
        if all((target/n).is_file() and not (target/n).is_symlink() and sha(target/n)==h for n,h in expected.items()):
            return {'status':'already_installed','target':str(target),'files':len(expected),'client_discovery':'unverified'}
        raise ValueError('A different or locally edited skill already exists; preserved unchanged. Back up and review it before an update.')
    report={'status':'planned','target':str(target),'files':len(m['files'])+1,'client_discovery':'unverified','global_install':False}
    if not apply:return report
    target.parent.mkdir(parents=True,exist_ok=True)
    stage=Path(tempfile.mkdtemp(prefix='.'+NAME+'-',dir=target.parent))
    try:
        for relative in [*m['files'],'package-manifest.json']:
            out=stage/relative;out.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(root/relative,out)
        manifest(stage)
        # No replacing or merging an existing skill, including a concurrent install.
        target.mkdir(exist_ok=False)
        for item in stage.iterdir():shutil.move(str(item),str(target/item.name))
        manifest(target)
    finally:
        # Only the temporary staging directory just created by this invocation.
        if stage.exists() and stage.parent==target.parent and stage.name.startswith('.'+NAME+'-'):shutil.rmtree(stage)
    return {**report,'status':'installed'}


def setup_environment(target,reuse=False,offline=False):
    if sys.version_info<(3,11):raise ValueError('Python3.11+ is required; this installer does not install Python globally.')
    target=Path(target).resolve();package=manifest(target)
    runtime=target.parent/('.'+NAME+'-runtime')/('v'+package['version'])
    if any(p.is_symlink() for p in (runtime,*runtime.parents)):raise ValueError('Redirected runtime path rejected.')
    executable=runtime/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    if runtime.exists():
        if not (runtime/'pyvenv.cfg').is_file() or not executable.is_file() or runtime.is_symlink():raise ValueError('Unrecognized runtime directory preserved.')
    else:venv.EnvBuilder(with_pip=True,system_site_packages=reuse).create(runtime)
    cmd=[str(executable),'-m','pip','install','--disable-pip-version-check','-r',str(target/'requirements.txt')]
    if offline:cmd.append('--no-index')
    result=subprocess.run(cmd,capture_output=True,text=True,encoding='utf8',errors='replace',timeout=600)
    (runtime/'dependency-install.log').write_text(result.stdout+'\n'+result.stderr,encoding='utf8')
    if result.returncode:raise RuntimeError('Dependency setup incomplete; see '+str(runtime/'dependency-install.log'))
    result=subprocess.run([str(executable),str(target/'scripts/environment_check.py')],capture_output=True,text=True,encoding='utf8',timeout=90)
    if result.returncode:raise RuntimeError('Dependency check failed: '+result.stderr)
    check=json.loads(result.stdout)
    (runtime/'environment.json').write_text(json.dumps(check,ensure_ascii=False,indent=2),encoding='utf8')
    if not check['python_dependencies_ready']:raise RuntimeError('Some Python dependencies remain unavailable.')
    return {'python':str(executable),'directory':str(runtime),'environment':check}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--host',help='Optional known-host directory hint; any host can use --target-dir.')
    p.add_argument('--target-dir',type=Path)
    p.add_argument('--apply',action='store_true',help='Write the skill; default is read-only planning.')
    p.add_argument('--setup-env',action='store_true',help='Create a skill-private venv and install requirements; no global pip.')
    p.add_argument('--reuse-system-packages',action='store_true')
    p.add_argument('--offline',action='store_true')
    a=p.parse_args()
    if a.setup_env and not a.apply:p.error('--setup-env requires --apply.')
    target=destination(a.host,a.target_dir)
    report=install(ROOT,target,a.apply)
    if a.setup_env:report['runtime']=setup_environment(target,a.reuse_system_packages,a.offline)
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
