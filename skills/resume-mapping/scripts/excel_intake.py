"""Open XLSX read-only while retaining raw values and unsupported validation metadata."""
import io,posixpath,warnings
from zipfile import ZipFile,ZIP_DEFLATED
from lxml import etree as E

N={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main','r':'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}


def open_readonly(path):
    import openpyxl
    changes=[];raw={};metadata={'validation_repairs':[],'media_parts':[]}
    buffer=io.BytesIO()
    with ZipFile(path) as source,ZipFile(buffer,'w',ZIP_DEFLATED) as target:
        workbook=E.fromstring(source.read('xl/workbook.xml'))
        rels=E.fromstring(source.read('xl/_rels/workbook.xml.rels'))
        relationships={r.get('Id'):r.get('Target') for r in rels}
        names={posixpath.normpath('xl/'+relationships[s.get('{'+N['r']+'}id')]).lstrip('/'):s.get('name') for s in workbook.findall('s:sheets/s:sheet',N)}
        names={k.replace('xl/xl/','xl/'):v for k,v in names.items()}
        for entry in source.infolist():
            payload=source.read(entry.filename)
            if entry.filename.startswith('xl/media/'):metadata['media_parts'].append(entry.filename)
            if entry.filename.startswith('xl/worksheets/') and entry.filename.endswith('.xml'):
                root=E.fromstring(payload);modified=False
                raw[names.get(entry.filename,entry.filename)]={c.get('r'):{'raw_value':c.findtext('s:v',namespaces=N),'raw_type':c.get('t'),'style_index':c.get('s'),'raw_formula':c.findtext('s:f',namespaces=N)} for c in root.findall('s:sheetData/s:row/s:c',N)}
                for node in root.findall('s:dataValidations/s:dataValidation',N):
                    kind=node.get('type')
                    if kind is not None and kind not in {'decimal','whole','date','list','custom','time','textLength','none'}:
                        metadata['validation_repairs'].append({'part':entry.filename,'xml':E.tostring(node,encoding='unicode'),'reason':'Unsupported validation enum; removed only from in-memory reader copy; cell XML unchanged.'})
                        node.getparent().remove(node);modified=True
                if modified:payload=E.tostring(root,encoding='UTF-8',xml_declaration=True)
            target.writestr(entry,payload)
    content=buffer.getvalue()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        formulas=openpyxl.load_workbook(io.BytesIO(content),data_only=False,keep_links=False)
        cached=openpyxl.load_workbook(io.BytesIO(content),data_only=True,keep_links=False)
    notices=[{'kind':'xlsx_reader_warning','message':str(x.message)} for x in caught]
    if metadata['validation_repairs']:notices.append({'kind':'invalid_validation_reader_copy','count':len(metadata['validation_repairs'])})
    if metadata['media_parts']:notices.append({'kind':'package_media_require_visual_review','parts':metadata['media_parts']})
    return formulas,cached,raw,notices,metadata
