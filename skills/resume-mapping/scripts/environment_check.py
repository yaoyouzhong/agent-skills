"""Report available conversion dependencies without installing or opening applications."""
import argparse,importlib.util,json,sys,os,shutil,platform
from pathlib import Path

def inspect(soffice=None):
    modules={name:importlib.util.find_spec(name) is not None for name in ('lxml','docx','pdfplumber','pypdfium2','PIL','numpy','openpyxl')}
    office={}
    if sys.platform=='win32':
        import winreg
        for app in ('Word.Application','Excel.Application'):
            try:
                with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT,app+'\\CLSID'):office[app]=True
            except FileNotFoundError:office[app]=False
    candidates=[soffice,os.environ.get('RESUME_SOFFICE'),shutil.which('soffice'),shutil.which('libreoffice')]
    if sys.platform=='darwin':candidates.append('/Applications/LibreOffice.app/Contents/MacOS/soffice')
    libreoffice=next((str(Path(p).expanduser().resolve()) for p in candidates if p and Path(p).expanduser().is_file()),None)
    ready=sys.version_info>=(3,11) and all(modules.values())
    return {'python':sys.executable,'python_version':platform.python_version(),'platform':sys.platform,
            'modules':modules,'python_dependencies_ready':ready,'office_registered':office,'libreoffice':libreoffice,
            'capabilities':{'docx_structure':modules['lxml'] and modules['docx'],
                            'xlsx_structure':modules['lxml'] and modules['openpyxl'],
                            'word_render_configured':bool(office.get('Word.Application') or libreoffice),
                            'excel_render_configured':bool(office.get('Excel.Application') or libreoffice)},
            'renderer_runtime_tested':False,
            'ocr':'optional; Windows language availability is checked only when OCR is requested',
            'status':'python_ready' if ready else 'missing_dependencies','application_launch_performed':False}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--soffice',type=Path)
    print(json.dumps(inspect(p.parse_args().soffice)))
