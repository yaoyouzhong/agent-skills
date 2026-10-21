import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from source_audit import dump
from extract_sources import sha
from media_ocr import recognize_orientations


def run():
    checks={}
    with tempfile.TemporaryDirectory() as td:
        root=Path(td);img=root/'raw.png';Image.new('RGB',(4100,800),'white').save(img)
        asset={'id':'a','path':str(img),'sha256':sha(img)}
        def fake(args,**kwargs):
            path=Path(args[args.index('-OutputPath')+1])
            text='姓名 示例甲 毕业证书 示例大学 学士 2020年06月' if 'rotate-90.' in path.name else ''
            dump(path,{'text':text,'confidence':None,'engine':'test-only'})
        with patch('media_ocr.subprocess.run',fake):report=recognize_orientations(asset,root)
        assert report['angle']==90 and len(report['candidates'])==4
        checks['ranks_all_four_orientations']=True
        assert sha(img)==asset['sha256'] and all(Path(c['raw_result']).exists() for c in report['candidates'])
        checks['original_and_all_raw_attempts_retained']=True
        assert report['confidence'] is None and report['review_status']=='machine_unreviewed'
        checks['ranking_cannot_approve_ocr']=True
        assert all(max(Image.open(c['input']).size)<=3200 for c in report['candidates'])
        checks['oversized_scan_is_prepared_for_local_engine']=True
        other=root/'empty';other.mkdir()
        def empty(args,**kwargs):dump(Path(args[args.index('-OutputPath')+1]),{'text':''})
        with patch('media_ocr.subprocess.run',empty):blank=recognize_orientations(asset,other)
        assert 'empty_or_short_ocr' in blank['quality_warnings']
        checks['blank_output_remains_quality_warning']=True
    print(json.dumps({'status':'passed','checks':checks}))


if __name__=='__main__':run()
