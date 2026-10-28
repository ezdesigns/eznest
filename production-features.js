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

// Local layout comparisons and evidence drafts. No OUTPUT or delivery API calls.
const EZNLocalEvidence=(()=>{
  const MAX_PHOTOS=5,MAX_BYTES=25*1024*1024,MAX_FILE=10*1024*1024;
  let storagePromise,generation=0,editor=null,dirty=false,processing=false,opening=false,photoGeneration=0;
  const el=id=>document.getElementById(id);
  const text=(tag,value)=>{const n=document.createElement(tag);n.textContent=value;return n;};
  const digest=async bytes=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),b=>b.toString(16).padStart(2,'0')).join('');
  const canonical=value=>Array.isArray(value)?value.map(canonical):value&&typeof value==='object'?Object.fromEntries(Object.keys(value).sort().map(k=>[k,canonical(value[k])])):value;
  function comparisonPayload(state){
    const request=structuredClone(state.requestJob||state.job);
    delete request._progress;delete request.settings.seconds;delete request.settings.seed;
    return canonical(request);
  }
  function photoKind(bytes){
    if(bytes[0]===255&&bytes[1]===216&&bytes[2]===255)return 'image/jpeg';
    if([137,80,78,71,13,10,26,10].every((b,i)=>bytes[i]===b))return 'image/png';
    if(String.fromCharCode(...bytes.slice(0,4))==='RIFF'&&String.fromCharCode(...bytes.slice(8,12))==='WEBP')return 'image/webp';
    return null;
  }
  function snapshot(state,sha){
    if(!state.released||state.deliveryCompleted!==true||state.manifest?.outputCheck?.ready!==true||!/^[a-f0-9]{32}$/.test(state.id)||!/^[a-f0-9]{64}$/.test(sha))throw Error('Export and confirm a ready layout before creating its evidence draft.');
    return {batchId:state.id,sha256:sha,width:state.result.width,length:state.result.usedLength,pieces:state.manifest.totalPieces,coverage:state.result.utilization,gap:state.job.settings.gap,margin:state.job.settings.margin,createdAt:state.manifest.createdAt};
  }
  function storage(){
    if(!storagePromise)storagePromise=new Promise((resolve,reject)=>{
      const request=indexedDB.open('eznest-local-evidence',1);
      request.onupgradeneeded=()=>{request.result.createObjectStore('revisions',{keyPath:'id'});request.result.createObjectStore('drafts',{keyPath:'id'});};
      request.onerror=()=>reject(Error('Browser storage is unavailable. Your draft has not been saved.'));
      request.onblocked=()=>reject(Error('Close other eznest tabs and try again. Your draft has not been saved.'));
      request.onsuccess=()=>{request.result.onversionchange=()=>{request.result.close();storagePromise=null;};resolve(request.result);};
    }).catch(error=>{storagePromise=null;throw error;});
    return storagePromise;
  }
  async function read(store,key){const db=await storage();return new Promise((resolve,reject)=>{const tx=db.transaction(store),r=key===undefined?tx.objectStore(store).getAll():tx.objectStore(store).get(key);r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);});}
  async function write(store,value,onlyNew=false){const db=await storage();return new Promise((resolve,reject)=>{
    const tx=db.transaction(store,'readwrite'),s=tx.objectStore(store);
    tx.oncomplete=resolve;tx.onerror=tx.onabort=()=>reject(Error('Browser storage could not save this draft. Keep this window open and free storage, then retry.'));
    if(onlyNew){const r=s.get(value.id);r.onsuccess=()=>{if(!r.result)s.put(value);};}else s.put(value);
  });}
  function clear(){generation++;el('layout-insights').hidden=true;}
  async function render(state){
    const ticket=++generation,r=state.result,m=state.manifest;
    el('layout-insights').hidden=false;
    el('insight-coverage').textContent=(100*r.utilization).toFixed(1)+'%';
    el('insight-unused').textContent=(100*(1-r.utilization)).toFixed(1)+'%';
    el('insight-time').textContent=Number(r.elapsed).toFixed(1)+' s';
    const checks=el('layout-checks');checks.replaceChildren();
    const required=m.jobs.filter(j=>j.role!=='fill'),expected=required.reduce((n,j)=>n+j.expected,0),placed=required.reduce((n,j)=>n+j.placed,0);
    for(const [pass,label] of [[m.complete===true&&expected===placed,`${placed} / ${expected} required pieces accounted for`],[r.validated===true,`Geometry verified · gap ≥ ${dimension(state.job.settings.gap)}, edge ≥ ${dimension(state.job.settings.margin)}`],[m.outputCheck?.ready===true,'Export profile requirements met']]){
      const row=text('li',(pass?'✓ ':'— ')+label);row.className=pass?'check-pass':'muted';checks.append(row);
    }
    el('proof-open').disabled=!(state.released&&state.deliveryCompleted===true&&m.outputCheck?.ready===true);
    el('proof-hint').textContent=el('proof-open').disabled?'Save the ready export first to bind evidence to its exact file.':'Local draft only · no buyer notification or submission.';
    const rows=el('layout-revisions');rows.replaceChildren(text('p','Loading comparisons…'));
    try{
      const key=await digest(new TextEncoder().encode(JSON.stringify(comparisonPayload(state))));
      const geometry=await digest(new TextEncoder().encode(JSON.stringify(canonical({placements:r.placements,length:r.usedLength}))));
      const id=key+':'+geometry;
      await write('revisions',{id,key,createdAt:Date.now(),batchId:state.id,length:r.usedLength,coverage:r.utilization,pieces:m.totalPieces,seconds:state.job.settings.seconds},true);
      const revisions=(await read('revisions')).filter(x=>x.key===key).sort((a,b)=>b.createdAt-a.createdAt).slice(0,6);
      if(ticket!==generation)return;
      rows.replaceChildren();
      for(const entry of revisions){const row=document.createElement('div');row.className='revision-row'+(entry.id===id?' current':'');row.append(text('strong',entry.id===id?'Current':new Date(entry.createdAt).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'})),text('span',dimension(entry.length)),text('span',(entry.coverage*100).toFixed(1)+'%'),text('span',entry.pieces+' pcs · '+entry.seconds+' s budget'));rows.append(row);}
      if(revisions.length===1)rows.append(text('p','No earlier comparable layout saved yet. Use “Try a better fit” before exporting.'));
    }catch(error){if(ticket===generation)rows.replaceChildren(text('p','Comparison history unavailable: '+error.message));}
  }
  function dataURL(blob){return new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=()=>reject(Error('Could not read local photo.'));reader.readAsDataURL(blob);});}
  function revoke(){photoGeneration++;el('proof-photos').replaceChildren();el('proof-preview').replaceChildren();}
  function outline(state){
    const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox',`0 0 ${state.result.width} ${state.result.usedLength}`);
    const parts=new Map(state.job.parts.map(p=>[p.id,p]));
    for(const p of state.result.placements){const shape=document.createElementNS(svg.namespaceURI,'polygon');shape.setAttribute('points',parts.get(p.id).points.map(x=>x.join(',')).join(' '));shape.setAttribute('transform',`translate(${p.x} ${p.y}) rotate(${p.rotation})`);shape.setAttribute('fill','#eef4ff');shape.setAttribute('stroke','#626974');shape.setAttribute('stroke-width','.3');svg.append(shape);}
    return new XMLSerializer().serializeToString(svg);
  }
  async function photoList(){
    revoke();const ticket=photoGeneration,draft=editor;const list=el('proof-photos');list.replaceChildren();
    for(const [index,photo] of draft.photos.entries()){
      const row=document.createElement('figure'),img=document.createElement('img');
      let url;try{url=await dataURL(photo.file);}catch(error){if(ticket===photoGeneration)el('proof-status').textContent=error.message;return;}
      if(ticket!==photoGeneration)return;img.src=url;img.alt=photo.name;
      const remove=text('button','Remove');remove.type='button';remove.disabled=processing;remove.setAttribute('aria-label','Remove '+photo.name);remove.onclick=()=>{if(processing)return;editor.photos.splice(index,1);dirty=true;photoList();};
      row.append(img,text('figcaption',photo.name),remove);list.append(row);
    }
    if(ticket!==photoGeneration)return;
    const image=document.createElement('img');image.src='data:image/svg+xml;charset=utf-8,'+encodeURIComponent(draft.outline);image.alt='Saved layout outlines';el('proof-preview').replaceChildren(image);
  }
  function showEditor(draft){
    editor=structuredClone(draft);dirty=false;el('proof-index').hidden=true;el('proof-editor').hidden=false;
    const s=editor.layout;el('proof-batch').textContent='Batch '+s.batchId.slice(0,8)+' · '+s.pieces+' pieces · '+dimension(s.length);
    el('proof-hash').textContent=s.sha256;el('proof-order').value=editor.order||'';el('proof-carrier').value=editor.carrier||'';el('proof-tracking').value=editor.tracking||'';el('proof-notes').value=editor.notes||'';
    el('proof-status').textContent=editor.savedAt?'Saved locally '+new Date(editor.savedAt).toLocaleString():'New draft · not saved yet';
    photoList();el('proof-order').focus();
  }
  async function openCurrent(){
    if(!current||busy||saving||opening||processing)return;
    opening=true;el('proof-drafts-open').disabled=true;
    const state=structuredClone(current);el('proof-open').disabled=true;
    try{
      // Hash only the frozen local ZIP; never the mutable preview or source file.
      if(!state.released||state.deliveryCompleted!==true||state.manifest.outputCheck?.ready!==true)throw Error('Save the ready export first.');
      const response=await fetch('/api/batch/'+state.id);if(!response.ok)throw Error('The saved layout is unavailable.');
      const blob=await response.blob();if(blob.size>100*1024*1024)throw Error('This export is too large to fingerprint in the browser.');
      const sha=await digest(await blob.arrayBuffer()),layout=snapshot(state,sha),id=state.id+':'+sha;
      const saved=await read('drafts',id);
      if(current?.id!==state.id)return;
      showEditor(saved||{id,layout,outline:outline(state),photos:[],order:'',carrier:'',tracking:'',notes:''});el('proof-drawer').showModal();
    }catch(error){status(error.message,true);}finally{opening=false;el('proof-drafts-open').disabled=false;if(current?.id===state.id)el('proof-open').disabled=false;}
  }
  async function openIndex(){
    if(opening||processing)return;
    editor=null;dirty=false;revoke();el('proof-editor').hidden=true;el('proof-index').hidden=false;el('proof-status').textContent='';
    if(!el('proof-drawer').open)el('proof-drawer').showModal();
    const list=el('proof-drafts-list');list.replaceChildren(text('p','Loading local drafts…'));
    try{const drafts=(await read('drafts')).sort((a,b)=>b.savedAt-a.savedAt);list.replaceChildren();if(!drafts.length)list.append(text('p','No saved drafts yet. Export a ready layout, then choose Delivery evidence.'));
      for(const draft of drafts){const button=text('button',(draft.order||'Batch '+draft.layout.batchId.slice(0,8))+' · '+draft.photos.length+' photos · '+new Date(draft.savedAt).toLocaleDateString());button.onclick=()=>showEditor(draft);list.append(button);}
    }catch(error){list.replaceChildren(text('p',error.message));}
  }
  function mayLeave(){return !processing&&(!dirty||confirm('Discard unsaved evidence changes? Your last saved draft will remain.'));}
  async function addPhotos(files){
    if(!editor||processing)return;
    processing=true;el('proof-save').disabled=true;el('proof-fields').disabled=true;
    try{
      if(editor.photos.length+files.length>MAX_PHOTOS)throw Error('Use up to five photos per draft.');
      if(editor.photos.reduce((n,p)=>n+p.file.size,0)+files.reduce((n,f)=>n+f.size,0)>MAX_BYTES)throw Error('Keep the total photo size within 25 MB.');
      const additions=[];
      for(const file of files){if(file.size>MAX_FILE)throw Error('Each photo must be 10 MB or smaller.');const bytes=new Uint8Array(await file.arrayBuffer()),type=photoKind(bytes);if(!type)throw Error('Choose JPEG, PNG or WebP photos.');const blob=new Blob([bytes],{type}),url=await dataURL(blob);
        await new Promise((resolve,reject)=>{const img=new Image();img.onload=()=>resolve();img.onerror=()=>reject(Error('Could not read '+file.name));img.src=url;});
        additions.push({name:file.name,file:blob,sha256:await digest(bytes)});
      }
      editor.photos.push(...additions);dirty=true;el('proof-status').textContent='Photos added · save this draft to keep them.';
    }catch(error){el('proof-status').textContent=error.message;}finally{processing=false;el('proof-save').disabled=false;el('proof-fields').disabled=false;el('proof-files').value='';photoList();}
  }
  async function save(){
    if(!editor||processing)return;
    processing=true;el('proof-save').disabled=true;el('proof-fields').disabled=true;
    const candidate={...editor,order:el('proof-order').value.trim(),carrier:el('proof-carrier').value.trim(),tracking:el('proof-tracking').value.trim(),notes:el('proof-notes').value.trim(),savedAt:Date.now()};
    try{await write('drafts',candidate);editor=candidate;dirty=false;const missing=[];if(!editor.photos.length)missing.push('photos');if(!editor.tracking)missing.push('tracking number');el('proof-status').textContent='Saved in this browser. '+(missing.length?'Still missing: '+missing.join(', ')+'. ':'')+'Nothing has been submitted.';}
    catch(error){el('proof-status').textContent=error.message;}
    finally{processing=false;el('proof-save').disabled=false;el('proof-fields').disabled=false;}
  }
  function init(){
    el('proof-open').onclick=openCurrent;el('proof-drafts-open').onclick=openIndex;
    el('proof-close').onclick=()=>{if(mayLeave()){el('proof-drawer').close();revoke();dirty=false;}};
    el('proof-back').onclick=()=>{if(mayLeave())openIndex();};
    el('proof-drawer').addEventListener('cancel',event=>{if(!mayLeave())event.preventDefault();else{revoke();dirty=false;}});
    el('proof-files').onchange=event=>addPhotos(Array.from(event.target.files));
    el('proof-form').onsubmit=event=>{event.preventDefault();save();};
    el('proof-form').addEventListener('input',()=>{dirty=true;el('proof-status').textContent='Unsaved changes';});
    window.addEventListener('beforeunload',event=>{if(dirty||processing){event.preventDefault();event.returnValue='';}});
  }
  return {render,clear,init,comparisonPayload,photoKind,snapshot};
})();
document.addEventListener('DOMContentLoaded',EZNLocalEvidence.init);
