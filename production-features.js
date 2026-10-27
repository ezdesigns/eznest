'use strict';

function profileCutMapping(profile){
  if(profile.cutMapping)return EZNCuts.validate(profile.cutMapping);
  const mapping=EZNCuts.defaults();
  mapping.outputs.contour.spot=profile.cutSpot||'CutContour';
  mapping.outputs.contour.layer=profile.cutLayer||profile.cutSpot||'CutContour';
  return mapping;
}

function fillCutMappingForm(profile){
  const mapping=profileCutMapping(profile),container=$('cut-mapping-fields');container.replaceChildren();
  if(profile.cutMapping){$('shop-cut-spot').value=mapping.outputs.contour.spot;$('shop-cut-layer').value=mapping.outputs.contour.layer;}
  const field=(parent,label,id,value,multiline=false)=>{const wrap=document.createElement('label');wrap.textContent=label;const input=document.createElement(multiline?'textarea':'input');input.id=id;input.value=value;if(multiline){input.rows=3;input.maxLength=9000;}else input.maxLength=80;wrap.append(input);parent.append(wrap);};
  for(const [op,title] of [['thru','Thru-cut'],['kiss','Kiss-cut'],['contour','Generic cut'],['regmark','Old registration marks']]){
    const section=document.createElement('details');section.append(svgText(title,'summary'));
    const inputs=document.createElement('div');inputs.className='fields';
    for(const source of ['layer','spot'])field(inputs,'Source '+(source==='spot'?'spot colors':'layers'),'cut-'+op+'-'+source,mapping.rules.filter(r=>r.operation===op&&r.source===source).map(r=>(r.match==='prefix'?'prefix:':'')+r.name).join('\n'),true);
    section.append(inputs);
    if(op!=='regmark'){
      const outputs=document.createElement('div');outputs.className='fields';
      if(op!=='contour'){field(outputs,'Output spot color','cut-'+op+'-output-spot',mapping.outputs[op].spot);field(outputs,'Output layer','cut-'+op+'-output-layer',mapping.outputs[op].layer);}
      field(outputs,'Shop tool note (optional)','cut-'+op+'-tool',mapping.outputs[op].toolHint);section.append(outputs);
    }
    container.append(section);
  }
  $('cut-generic').value=mapping.genericOperation;
  $('cut-suspect-prefixes').value=mapping.suspectPrefixes.join('\n');
}

function readCutMappingForm(){
  const mapping=EZNCuts.defaults();mapping.rules=[];
  for(const op of [...EZNCuts.operations,'regmark']){
    for(const source of ['layer','spot'])for(const line of $('cut-'+op+'-'+source).value.split('\n').map(s=>s.trim()).filter(Boolean))mapping.rules.push({source,operation:op,match:line.startsWith('prefix:')?'prefix':'exact',name:line.startsWith('prefix:')?line.slice(7).trim():line});
    if(op!=='regmark')mapping.outputs[op]={spot:op==='contour'?$('shop-cut-spot').value||'CutContour':$('cut-'+op+'-output-spot').value,layer:op==='contour'?$('shop-cut-layer').value||$('shop-cut-spot').value||'CutContour':$('cut-'+op+'-output-layer').value,toolHint:$('cut-'+op+'-tool').value};
  }
  mapping.genericOperation=$('cut-generic').value;mapping.suspectPrefixes=$('cut-suspect-prefixes').value.split('\n').map(s=>s.trim()).filter(Boolean);
  return EZNCuts.validate(mapping);
}

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
  const mapping=profileCutMapping(activeShop());
  $('document-generic-cut').value=mapping.genericOperation;
  $('document-import-error').textContent='';
  return new Promise(resolve=>{
    const dialog=$('document-import');
    const closed=()=>{dialog.removeEventListener('close',closed);mapping.genericOperation=$('document-generic-cut').value;resolve(dialog.returnValue==='import'?{bleedMm:Number($('document-bleed').value),cutSpot:$('document-cut-spot').value.trim(),cutMapping:mapping}:null);};
    dialog.addEventListener('close',closed);dialog.returnValue='';dialog.showModal();
  });
}

async function importDocument(file,role,options){
  const parsed=await api('/api/document/import-file',options,file);
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
  $('document-review-summary').textContent=entry.data.parts.length+' detected pieces. '+entry.data.bleedMm+' mm of existing bleed is reserved. Artwork and every cut path move together.';
  $('document-review-warnings').replaceChildren();for(const warning of entry.data.warnings||[])$('document-review-warnings').append(svgText(warning,'p'));
  $('document-piece-list').replaceChildren();
  for(const part of entry.data.parts){const item=document.createElement('figure'),img=document.createElement('img');img.src=part.preview;img.alt=part.name;item.append(img,svgText(part.name+' · '+dimension(part.previewWidth)+' × '+dimension(part.previewHeight),'figcaption'),svgText(EZNCuts.formatCounts(part.cutCounts),'p'));$('document-piece-list').append(item);}
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
  $('cut-summary').textContent=state.manifest.cutSummary?EZNCuts.formatCounts(state.manifest.cutSummary):'';
}

document.addEventListener('DOMContentLoaded',()=>{
  $('document-import-cancel').onclick=()=>$('document-import').close('cancel');
  $('document-import-form').onsubmit=event=>{event.preventDefault();const bleed=Number($('document-bleed').value),spot=$('document-cut-spot').value.trim();if(!Number.isFinite(bleed)||bleed<0||bleed>25||!spot){$('document-import-error').textContent='Enter existing bleed from 0 to 25 mm and the exact cut spot name.';return;}preferences.pdfBleedMm=bleed;preferences.pdfCutSpot=spot;remember();$('document-import').close('import');};
  $('benchmark-download').onclick=()=>{if(!current)return;const data={format:'eznest.benchmark',version:1,batchId:current.id,sourceRevisions:current.manifest.jobs.map(j=>({name:j.sourceFile,revision:j.revision,sets:j.sets,customer:j.customer,order:j.order})),settings:current.job.settings,eznest:{widthMm:current.result.width,totalLengthMm:current.result.usedLength,sheets:current.manifest.sheets.length,pieces:current.manifest.totalPieces,engineSeconds:current.result.elapsed,complete:current.manifest.complete},comparison:{tool:'MX',lengthMm:null,operatorSeconds:null,engineSeconds:null,pieces:null,printedAtCorrectSize:null,cutAligned:null,allKitsComplete:null,notes:''},status:'Not compared on physical equipment'};downloadText(JSON.stringify(data,null,2),'eznest-comparison-'+current.id.slice(0,8)+'.json','application/json');};
});
