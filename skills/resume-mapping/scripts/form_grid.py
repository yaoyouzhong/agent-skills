"""Reusable label, merged-neighbor and table discovery for task-specific form maps."""
import collections
import re
import unicodedata


def label(value):
    return re.sub(r'[\s:：()（）?？]', '', unicodedata.normalize('NFKC', str(value or ''))).replace('可多选','')


def address(cell):
    m=re.fullmatch(r'([A-Za-z]+)(\d+)',cell)
    if not m:raise ValueError('Invalid A1 address: '+str(cell))
    col=0
    for ch in m[1].upper():col=col*26+ord(ch)-64
    return col,int(m[2])


def value(cell):
    if not cell:return ''
    v=cell.get('display_value',cell.get('value',''))
    return '' if v is None else str(v).strip()


class FormGrid:
    def __init__(self,sheet):
        self.sheet=sheet;self.rows=collections.defaultdict(list);self.cells=sheet['cells']
        for cell in self.cells:
            col,row=address(cell['cell']);self.rows[row].append((col,cell))
        for row in self.rows:self.rows[row].sort(key=lambda p:p[0])

    def find(self,names,bounds=None):
        names={label(n) for n in ([names] if isinstance(names,str) else names)}
        return [c for c in self.cells if label(value(c)) in names and (not bounds or bounds[0]<=address(c['cell'])[1]<bounds[1])]

    def after(self,cell):
        col,row=address(cell['cell'])
        for region in self.sheet.get('merged_ranges',[]):
            first,last=region.split(':') if ':' in region else (region,region)
            left,top=address(first);right,bottom=address(last)
            if left==col and top==row:col=right;break
        return next((c for ci,c in self.rows[row] if ci==col+1 and value(c)),None)

    def at(self,names,bounds=None):
        found=self.find(names,bounds)
        populated=[c for c in found if value(self.after(c))]
        if populated:found=populated
        if len(found)>1 and len({value(self.after(c)) for c in found})>1:
            raise ValueError('Ambiguous repeated label; restrict to a record/section: '+str(names))
        return (found[0],self.after(found[0])) if found else (None,None)

    def sections(self,aliases):
        found=[]
        for c in self.cells:
            text=label(value(c))
            for key,names in aliases.items():
                if any(text.startswith(label(n)) for n in names):found.append((address(c['cell'])[1],key));break
        found=sorted(set(found));bounds={}
        for i,(row,key) in enumerate(found):
            if key in bounds:raise ValueError('Repeated section; specify a narrower grid: '+key)
            bounds[key]=(row,found[i+1][0] if i+1<len(found) else max(self.rows,default=0)+1)
        return bounds

    def table_records(self,bounds,aliases,required=(),header_scan=10):
        """Locate the actual header; never assume it is section_row + 1."""
        lo,hi=bounds;headers=[]
        normalized={key:{label(n) for n in names} for key,names in aliases.items()}
        for row in range(lo,min(hi,lo+header_scan)):
            columns={}
            for ci,c in self.rows[row]:
                for key,names in normalized.items():
                    if label(value(c)) in names:columns[key]=ci
            if len(columns)>=2 and all(k in columns for k in required):headers.append((len(columns),row,columns))
        if not headers:return []
        best=max(h[0] for h in headers);choices=[h for h in headers if h[0]==best]
        if len(choices)>1:raise ValueError('Ambiguous table headers; narrow section bounds.')
        _,header,columns=choices[0];records=[]
        for row in range(header+1,hi):
            selected={key:next((c for ci,c in self.rows[row] if ci==col),None) for key,col in columns.items()}
            obj={key:value(c) for key,c in selected.items()}
            if any(obj.values()):records.append((row,obj,selected))
        return records


def word_table_grid(table):
    """Adapt a python-docx table; do not duplicate horizontally merged cells."""
    cells=[];merged=[]
    def letters(n):
        s=''
        while n:n,r=divmod(n-1,26);s=chr(65+r)+s
        return s
    for ri,row in enumerate(table._tbl.tr_lst,1):
        col=1
        for tc in row.tc_lst:
            from docx.oxml.ns import qn
            text='\n'.join(''.join(t.text or '' for t in p.iter(qn('w:t'))) for p in tc.iter(qn('w:p')))
            span=tc.tcPr.gridSpan.val if tc.tcPr is not None and tc.tcPr.gridSpan is not None else 1
            cell=f'{letters(col)}{ri}';cells.append({'cell':cell,'value':text,'display_value':text,'word_row':ri-1,'word_cell':len([c for c in cells if c.get('word_row')==ri-1])})
            if span>1:merged.append(cell+':'+letters(col+span-1)+str(ri))
            col+=span
    return FormGrid({'sheet':'word_table','cells':cells,'merged_ranges':merged})
