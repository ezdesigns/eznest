'use strict';

function documentSVG(state){
  const out=svgNode('svg',{xmlns:NS,width:state.result.width+'mm',height:state.result.usedLength+'mm',viewBox:`0 0 ${state.result.width} ${state.result.usedLength}`});
  const parts=new Map(state.job.parts.map(p=>[p.id,p]));
  state.result.placements.forEach((placement,i)=>{const part=parts.get(placement.id),group=svgNode('g',{id:'ez-part-'+(i+1),transform:`translate(${placement.x} ${placement.y}) rotate(${placement.rotation})`});
    if(part.preview)group.append(svgNode('image',{href:part.preview,width:part.previewWidth,height:part.previewHeight}));
    else group.append(svgNode('polygon',{points:part.points.map(p=>p.join(',')).join(' '),fill:'#ddd'}));
    out.append(group);
  });
  return out;
}

function requestDocumentOptions(){
  $('document-bleed').value=preferences.pdfBleedMm??0;
  $('document-cut-spot').value=preferences.pdfCutSpot||activeShop().cutSpot||'CutContour';
  $('document-import-error').textContent='';
  return new Promise(resolve=>{
    const dialog=$('document-import');
    const closed=()=>{dialog.removeEventListener('close',closed);resolve(dialog.returnValue==='import'?{bleedMm:Number($('document-bleed').value),cutSpot:$('document-cut-spot').value.trim()}:null);};
    dialog.addEventListener('close',closed);dialog.returnValue='';dialog.showModal();
  });
}

async function importDocument(file,role,options){
  const bytes=new Uint8Array(await file.arrayBuffer());let binary='';
  for(let i=0;i<bytes.length;i+=32768)binary+=String.fromCharCode(...bytes.subarray(i,i+32768));
  const parsed=await api('/api/document/import',{content:btoa(binary),...options});
  const id='pdf-'+(await hash(file.name+'\n'+parsed.documentId)).slice(0,18),old=queue.find(e=>e.id===id);
  if(old){old.selected=true;EZNQueue.restorePrepared(old);return true;}
  const entry={id,name:file.name,sourceFile:file.name,revision:parsed.documentId,origin:'files',role,category:'',customer:'',order:'',kit:'',materialId:activePreset().id,sets:role==='fill'?100:1,selected:true,status:'ready',data:parsed};
  queue.push(entry);
  if(activeShop().id==='generic-svg'){preferences.shopProfile='generic-pdf';renderPresets();}
  return true;
}

function showDocumentReview(entry){
  $('document-review').hidden=entry.data?.format!=='pdf';
  if(entry.data?.format!=='pdf')return;
  $('document-reviewed').checked=entry.data.reviewed===true;
  $('document-review-summary').textContent=entry.data.parts.length+' detected pieces. '+entry.data.bleedMm+' mm of existing bleed is reserved. Color management and registration marks stay in the RIP.';
  $('document-piece-list').replaceChildren();
  for(const part of entry.data.parts){const item=document.createElement('figure'),img=document.createElement('img');img.src=part.preview;img.alt=part.name;item.append(img,svgText(part.name+' · '+dimension(part.previewWidth)+' × '+dimension(part.previewHeight),'figcaption'));$('document-piece-list').append(item);}
}

function fillProductionSettings(preset){
  setDimensionField('sheet-length',preset.settings.sheetLength??null,settingsUnit);
  $('material-cost').value=preset.settings.costPerSquareMeter??'';
  $('material-currency').value=preset.settings.currency||'USD';
}

function readProductionSettings(settings){
  settings.sheetLength=readPhysicalField('sheet-length',settingsUnit);
  settings.costPerSquareMeter=$('material-cost').value.trim()===''?null:Number($('material-cost').value);
  settings.currency=$('material-currency').value.trim().toUpperCase();
  return settings;
}

function updateProductionResult(state){
  const sheets=state.manifest.sheets||[],cost=state.manifest.materialCost;
  $('sheet-summary').textContent=sheets.length>1?sheets.length+' sheets · total length '+dimension(state.result.usedLength):'One sheet';
  $('material-cost-result').textContent=cost?cost.currency+' '+cost.total.toFixed(2)+' estimated material cost':'Add material pricing in Settings to estimate cost.';
  $('job-costs').replaceChildren();
  if(cost){$('job-costs').append(svgText(cost.allocation+' Excludes ink, laminate, labor, overhead and profit.','p'));for(const item of cost.jobs){const source=state.manifest.jobs.find(j=>j.id===item.jobId);$('job-costs').append(svgText([source.customer,source.order,source.name].filter(Boolean).join(' / ')+': '+cost.currency+' '+item.cost.toFixed(2),'p'));}}
  $('benchmark-download').disabled=false;
}

document.addEventListener('DOMContentLoaded',()=>{
  $('document-import-cancel').onclick=()=>$('document-import').close('cancel');
  $('document-import-form').onsubmit=event=>{event.preventDefault();const bleed=Number($('document-bleed').value),spot=$('document-cut-spot').value.trim();if(!Number.isFinite(bleed)||bleed<0||bleed>25||!spot){$('document-import-error').textContent='Enter existing bleed from 0 to 25 mm and the exact cut spot name.';return;}preferences.pdfBleedMm=bleed;preferences.pdfCutSpot=spot;remember();$('document-import').close('import');};
  $('benchmark-download').onclick=()=>{if(!current)return;const data={format:'eznest.benchmark',version:1,batchId:current.id,sourceRevisions:current.manifest.jobs.map(j=>({name:j.sourceFile,revision:j.revision,sets:j.sets,customer:j.customer,order:j.order})),settings:current.job.settings,eznest:{widthMm:current.result.width,totalLengthMm:current.result.usedLength,sheets:current.manifest.sheets.length,pieces:current.manifest.totalPieces,engineSeconds:current.result.elapsed,complete:current.manifest.complete},comparison:{tool:'MX',lengthMm:null,operatorSeconds:null,engineSeconds:null,pieces:null,printedAtCorrectSize:null,cutAligned:null,allKitsComplete:null,notes:''},status:'Not compared on physical equipment'};downloadText(JSON.stringify(data,null,2),'eznest-comparison-'+current.id.slice(0,8)+'.json','application/json');};
});
