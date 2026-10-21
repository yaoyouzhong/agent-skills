"""Render a DOCX to a new PDF and page PNGs; actual visual review remains separate."""
import argparse
import json
import subprocess
import tempfile
from pathlib import Path
from extract_sources import office_convert, sha


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    input_group=parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument('--docx', type=Path)
    input_group.add_argument('--xlsx', type=Path)
    parser.add_argument('--sheet', help='Selected sheet for native Excel PDF export.')
    parser.add_argument('--outdir', type=Path, required=True)
    parser.add_argument('--soffice', type=Path, help='Existing LibreOffice executable, including a local or host-provided installation.')
    parser.add_argument('--scale', type=float, default=1.5)
    args = parser.parse_args()
    source=args.docx or args.xlsx
    if args.xlsx and not args.sheet:parser.error('Excel rendering requires --sheet.')
    if args.outdir.exists():
        parser.error('Render output directory must be new.')
    args.outdir.mkdir(parents=True)
    before = sha(source)
    if args.soffice:
        if not args.soffice.is_file():parser.error('soffice must be an existing executable path.')
        from libreoffice_bridge import convert
        pdf=args.outdir/'rendered.pdf'
        convert(source,pdf,'pdf',args.soffice,sheet=args.sheet if args.xlsx else None)
    else:
        pdf = args.outdir / 'rendered.pdf'
        office_convert(source.resolve(), pdf.resolve(), 'RenderExcel' if args.xlsx else 'RenderWord',args.sheet)
    import pypdfium2 as pdfium
    page_stats = []
    with pdfium.PdfDocument(str(pdf)) as document:
        for index in range(len(document)):
            page = document[index]
            textpage = page.get_textpage()
            text = textpage.get_text_range()
            textpage.close()
            bitmap = page.render(scale=args.scale)
            png = args.outdir / f'page-{index+1:03d}.png'
            bitmap.to_pil().save(png)
            bitmap.close()
            page.close()
            page_stats.append({'page': index+1, 'png': str(png.resolve()), 'text': text, 'characters': len(text.strip())})
    if sha(source) != before:
        raise ValueError('Input document changed during rendering.')
    summary = {'pdf': str(pdf.resolve()), 'docx_sha256': before, 'input_format':source.suffix.lower(),'input_sha256':before,'pdf_sha256': sha(pdf), 'pages': page_stats, 'input_unchanged': True, 'visual_review': 'pending',
               'nearly_empty_pages': [p['page'] for p in page_stats if p['characters'] < 5]}
    from layout_review import analyze
    layout=analyze(summary)
    layout_path=args.outdir/'layout.json'
    layout_path.write_text(json.dumps(layout,ensure_ascii=False,indent=2),encoding='utf8')
    summary['layout_report']={'path':str(layout_path.resolve()),'sha256':sha(layout_path),'warnings':len(layout['warnings'])}
    (args.outdir / 'render.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'pages': len(page_stats), 'pdf': str(pdf), 'nearly_empty_pages': summary['nearly_empty_pages'],
                      'visual_review': 'pending'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
