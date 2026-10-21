import json,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from install_skill import install,destination,manifest,sha,NAME


def run():
    checks={}
    with tempfile.TemporaryDirectory() as folder:
        w=Path(folder);source=w/'source';source.mkdir();(source/'SKILL.md').write_text('---\nname: '+NAME+'\ndescription: synthetic fixture\n---\n',encoding='utf8')
        def refresh():
            m={'name':NAME,'version':'7','files':{'SKILL.md':sha(source/'SKILL.md')}}
            (source/'package-manifest.json').write_text(json.dumps(m),encoding='utf8')
        refresh();target=destination('an-unlisted-agent',w/'任何宿主技能' / NAME)
        (source/'.DS_Store').write_bytes(b'finder metadata');manifest(source)
        (source/'unexpected.py').write_text('unexpected executable',encoding='utf8')
        try:manifest(source)
        except ValueError:pass
        else:raise AssertionError('Unexpected executable accepted as desktop metadata.')
        (source/'unexpected.py').unlink()
        checks['desktop_metadata_is_tolerated_without_allowing_extra_executable_payload']=True
        assert install(source,target)['status']=='planned' and not target.exists()
        checks['unlisted_client_explicit_directory_and_read_only_plan']=True
        assert install(source,target,True)['status']=='installed' and manifest(target)['version']=='7'
        checks['actual_copy_is_hash_verified']=True
        before=sha(target/'SKILL.md');assert install(source,target,True)['status']=='already_installed' and before==sha(target/'SKILL.md')
        checks['repeat_install_is_idempotent']=True
        (target/'SKILL.md').write_text('user changes',encoding='utf8')
        try:install(source,target,True)
        except ValueError:pass
        else:raise AssertionError('Local edits overwritten.')
        assert (target/'SKILL.md').read_text('utf8')=='user changes'
        checks['locally_modified_skill_is_preserved']=True
        (source/'SKILL.md').write_text('tampered',encoding='utf8')
        try:install(source,w/'new'/NAME,True)
        except ValueError:pass
        else:raise AssertionError('Corrupt package installed.')
        assert not (w/'new'/NAME).exists();checks['tampered_bundle_rejected_before_write']=True
        refresh();m=json.loads((source/'package-manifest.json').read_text('utf8'));m['files']['../outside']='x';(source/'package-manifest.json').write_text(json.dumps(m))
        try:manifest(source)
        except ValueError:pass
        else:raise AssertionError('Unsafe manifest accepted.')
        checks['manifest_path_traversal_rejected']=True
        h=w/'home'
        assert destination('claude-code',home=h)==(h/'.claude/skills'/NAME).resolve()
        assert destination('deepseek-harness',home=h,environ={'DSH_HOME':str(w/'custom-dsh')})==(w/'custom-dsh/skills'/NAME).resolve()
        checks['known_host_hints_respect_home_and_custom_configuration']=True
        for host in ('workbuddy','new-future-client'):
            try:destination(host,home=h,environ={})
            except ValueError:pass
            else:raise AssertionError('Unverified host directory guessed.')
        checks['unknown_directory_is_not_guessed']=True
    print(json.dumps({'status':'passed','checks':checks}))


if __name__=='__main__':run()
