// Execute a Python-preflighted plan using the public Artifact Tool API.
import fs from 'node:fs/promises';
import path from 'node:path';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
const [planFile,modules]=process.argv.slice(2);
if(!planFile||!modules)throw new Error('Usage: node template_xlsx.mjs plan.json bundled_node_modules');
const require=createRequire(path.join(path.resolve(modules),'package.json'));
const {FileBlob,SpreadsheetFile}=await import(pathToFileURL(require.resolve('@oai/artifact-tool')).href);
const plan=JSON.parse(await fs.readFile(planFile,'utf8'));
try{await fs.access(plan.output);throw new Error('Use a new output path.');}catch(e){if(e.code!=='ENOENT')throw e;}
const wb=await SpreadsheetFile.importXlsx(await FileBlob.load(plan.template));
const sheet=wb.worksheets.getItem(plan.sheet);
if(plan.removeDrawings)sheet.deleteAllDrawings();
for(const item of plan.copies)sheet.getRange(item.to).copyFrom(sheet.getRange(item.from),'all');
for(const range of plan.clearRanges)sheet.getRange(range).clear({applyTo:'contents'});
for(const range of plan.unmergeRanges)sheet.unmergeCells(range);
for(const range of plan.merges)sheet.mergeCells(range);
for(const item of plan.cells){
  const range=sheet.getRange(item.cell);
  range.setNumberFormat('@');
  const value=String(item.value??'');
  range.values=[[value.startsWith('=')?"'"+value:value]];
  range.format.wrapText=true;
}
// Row height applies to the entire worksheet row; no template column assumption.
for(const item of plan.rowHeights)sheet.getRange(`A${item.row}`).format.rowHeight=item.height;
wb.recalculate();
const errors=await wb.inspect({kind:'match',sheetId:plan.sheet,range:plan.printArea,
 searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#NUM!|#SPILL!',options:{useRegex:true,maxResults:20},maxChars:2000});
await fs.writeFile(plan.output+'.artifact-check.ndjson',errors.ndjson);
const output=await SpreadsheetFile.exportXlsx(wb);await output.save(plan.output);
if(plan.previewRange){
 const image=await wb.render({sheetName:plan.sheet,range:plan.previewRange,scale:1.5,format:'png'});
 await fs.writeFile(plan.output+'.preview.png',new Uint8Array(await image.arrayBuffer()));
}
console.log(JSON.stringify({status:'exported_requires_native_render',output:plan.output,cells:plan.cells.length}));
