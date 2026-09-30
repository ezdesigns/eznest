'use strict';

const $=id=>document.getElementById(id),NS='http://www.w3.org/2000/svg';

const colors=['#2879c4','#ce733c','#8b63b5','#4a9059','#bd4586','#398e96'];

const basePresets=[{id:'demo',name:'Example material',units:'mm',settings:{width:180,maxLength:null,gap:3,margin:5,seconds:5,rotations:[0,90,180,270]}},{id:'shop53',name:'Shop roll · check width',units:'in',settings:{width:1346.2,maxLength:null,gap:5.08,margin:6.35,seconds:15,rotations:[0,90,180,270]}}];

let preferences={presets:basePresets,active:'demo',autoNest:false,autoImprove:false,fillArea:'gaps',groupBy:'folder',precision:2};

try{preferences={...preferences,...JSON.parse(localStorage.getItem('eznest.production.settings')||'{}')};}catch{}

// Remove only the old starter-preset defaults. Keep custom limits and explicit
// per-batch overrides; a blank override must remain automatic after reload.
if(!preferences.rollLengthDefaultsMigrated){for(const p of preferences.presets){if((p.id==='demo'&&p.settings.maxLength===400)||(p.id==='shop53'&&p.settings.maxLength===3000))p.settings.maxLength=null;}preferences.rollLengthDefaultsMigrated=true;}
for(const p of preferences.presets){if(p.id==='demo'&&p.name==='Demo material · 180 mm')p.name='Example material';if(p.id==='shop53'&&p.name==='53 in roll · review settings')p.name='Shop roll · check width';}

preferences.shopProfiles=preferences.shopProfiles||EZNProfiles.defaults();preferences.shopProfile=preferences.shopProfile||'generic-svg';
if(!preferences.shopProfiles.some(p=>p.id==='generic-pdf'))preferences.shopProfiles.push(EZNProfiles.defaults().find(p=>p.id==='generic-pdf'));
const activeShop=()=>preferences.shopProfiles.find(p=>p.id===preferences.shopProfile)||preferences.shopProfiles[0];
const outputIncomplete=state=>state?.manifest?.outputCheck?.ready===false;
let queue=[],preparedBatches=[],token='',current=null,busy=false,saving=false,importing=false,folder=null,folderBusy=false,folderTimer=null,runSignature='',autoAttempts=0,noBetter=0,autoTimer=null,db=null,saveTimer=null,settingsUnit='mm',highlightJob='',editingJob=null,hadSelectedFill=false;

const activePreset=()=>preferences.presets.find(p=>p.id===preferences.active)||preferences.presets[0];

const scale=EZNQueue.unitScale;

const displayUnit=()=>preferences.units||activePreset().units;

const activeEntries=()=>queue.filter(e=>!EZNQueue.isPrepared(e));
const wasPrepared=state=>!outputIncomplete(state)&&(state?.deliveryCompleted===true||preparedBatches.some(b=>b.id===state?.id));

const dimension=mm=>(mm/scale(displayUnit())).toFixed(preferences.precision??2)+' '+displayUnit();

function status(message,error=false){$('status').textContent=message;$('status').classList.toggle('error',error);$('batch-status').dataset.state=error?'error':busy?'running':current?'ready':'idle';if(error&&!current){$('batch-status').hidden=false;$('batch-status').textContent='Check input';}}

async function api(path,data){const response=await fetch(path,data===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-EZ-Token':token},body:JSON.stringify(data)});const result=await response.json();if(!response.ok)throw Error(result.error||'Request failed.');return result;}

function remember(){localStorage.setItem('eznest.production.settings',JSON.stringify(preferences));clearTimeout(saveTimer);saveTimer=setTimeout(()=>{if(!db)return;try{const transaction=db.transaction('state','readwrite');transaction.objectStore('state').put(queue,'queue');transaction.objectStore('state').put(preparedBatches,'prepared');transaction.onerror=()=>status('The queue could not be saved on this browser. Export your batch before closing.',true);}catch(e){status('The queue could not be saved: '+e.message,true);}},180);}

async function openStorage(){return new Promise(resolve=>{const request=indexedDB.open('eznest-production',1);request.onupgradeneeded=()=>request.result.createObjectStore('state');request.onerror=()=>resolve();request.onsuccess=()=>{db=request.result;const transaction=db.transaction('state'),store=transaction.objectStore('state'),jobs=store.get('queue'),prepared=store.get('prepared');jobs.onsuccess=()=>queue=Array.isArray(jobs.result)?jobs.result:[];prepared.onsuccess=()=>preparedBatches=Array.isArray(prepared.result)?prepared.result:[];transaction.oncomplete=()=>resolve();transaction.onerror=()=>resolve();};});}

function signature(){return JSON.stringify({jobs:activeEntries().filter(e=>e.selected).map(e=>[e.id,e.revision,e.sets,e.materialId,e.status,e.role,e.customer,e.order,e.kit,e.data?.reviewed]),preset:activePreset(),outputProfile:EZNProfiles.validate(activeShop()),fillArea:preferences.fillArea,maxLength:readPhysicalField('batch-length',displayUnit())});}

function svgText(text,tag){const el=document.createElement(tag);el.textContent=text;return el;}

function clearPreview(){

  $('preview').setAttribute('hidden','');$('empty').hidden=false;
  const hasJobs=activeEntries().length>0,actions=document.createElement('div');actions.className='empty-actions';
  const add=svgText('Choose artwork files','button');add.className='primary';add.disabled=busy||saving;add.onclick=()=>$('files').click();actions.append(add);
  if(!hasJobs){const example=svgText('Try an example','button');example.disabled=busy||saving;example.onclick=()=>$('demo').click();actions.append(example);}
  const formats=svgText('PDF / compatible AI with cut contours, or SVG. Original print artwork stays local.','p');formats.className='empty-format';
  $('empty').replaceChildren(svgText(hasJobs?'Your layout will appear here.':'Drop PDF, AI or SVG artwork to begin.','strong'),svgText(hasJobs?'Check the width and quantities, then select Nest.':'Choose your roll width, then nest the selected jobs.','p'),actions,formats);

  for(const id of ['metrics','review-tools','completeness','job-key','export-bar','batch-status','output-check'])$(id).hidden=true;

  $('result-title').textContent='Preview';highlightJob='';$('review-tools').open=false;showDestination();

}

function showDestination(){const path=$('output-path').value;$('output-status').textContent=path?'Save to '+pathName(path):'Save to Downloads';$('output-status').title=path||'Your browser download folder';}

function pathName(path){return path.replace(/[\\/]$/,'').split(/[\\/]/).pop()||path;}

function updateSizeSummary(){
  const mm=readPhysicalField('batch-length',displayUnit()),limit=mm===null?null:dimension(mm);
  $('size-summary').textContent=limit?'Up to '+limit:'Automatic';
  $('fill-area-help').textContent=preferences.fillArea==='length'?(limit?'Stickers can use up to '+limit+'.':'Enter the length to fill under Roll length.'):'Required jobs determine the length. Stickers use their leftover space. With only stickers selected, enter a roll length to fill.';
}


function invalidate(){clearTimeout(autoTimer);current=null;$('export').disabled=true;$('improve').disabled=true;$('export').textContent='Export SVG';clearPreview();remember();renderQueue();status('');}

function renderPresets(){const selected=activePreset().id;preferences.active=selected;$('preset').replaceChildren();for(const preset of preferences.presets){const option=new Option(preset.name,preset.id);$('preset').append(option);}$('preset').value=selected;$('fill-area').value=preferences.fillArea||'gaps';setDimensionField('batch-length',Object.hasOwn(preferences.runLengths||{},selected)?preferences.runLengths[selected]:activePreset().settings.maxLength,displayUnit());$('length-unit').textContent=displayUnit();setDimensionField('quick-width',activePreset().settings.width,displayUnit());$('quick-unit').textContent=displayUnit();$('material-info').textContent='Length is calculated from your jobs.';updateSizeSummary();$('shop-shortcut').textContent='Output: '+activeShop().name;}

function renderQueue(){

  const locked=busy||saving,focus=document.activeElement?.dataset.focus,scroll=$('queue').scrollTop;

  $('queue').replaceChildren();$('fill-queue').replaceChildren();

  const regular=activeEntries().filter(e=>e.role!=='fill'),fillers=activeEntries().filter(e=>e.role==='fill');

  const groups=new Map();

  function groupFor(entry){const target=entry.role==='fill'?'fill-queue':'queue',name=EZNQueue.groupName(entry,preferences.groupBy,preferences.presets),key=target+'|'+name;if(!groups.has(key)){const section=document.createElement('section');section.className='queue-group';const heading=document.createElement('h3');heading.textContent=name;section.append(heading);$(target).append(section);groups.set(key,section);}return groups.get(key);}

  $('prepared-count').textContent=preparedBatches.length;

  $('queue-empty').hidden=regular.length>0;$('queue-count').textContent=regular.length||'';

  for(const entry of activeEntries()){

    const row=document.createElement('article');row.className='job'+(entry.selected?' selected':'');

    const checked=document.createElement('input');checked.type='checkbox';checked.checked=entry.selected;checked.disabled=locked||entry.status!=='ready';checked.setAttribute('aria-label','Select '+entry.name);checked.dataset.focus=entry.id+'-select';checked.onchange=()=>{entry.selected=checked.checked;invalidate();};

    const name=document.createElement('label');name.className='job-name';checked.id='select-'+entry.id;name.htmlFor=checked.id;

    const title=document.createElement('span');title.textContent=entry.name.replace(/\.svg$/i,'');title.title=entry.name;name.append(title);

    const perSet=(entry.data?.parts||[]).reduce((n,p)=>n+(p.quantity||1),0),detail=document.createElement('small');

    detail.textContent=entry.status==='ready'?(entry.role==='fill'?perSet+' '+(perSet===1?'sticker':'stickers')+' per set':perSet+(perSet===1?' piece per set':' pieces per set')):(entry.error||'Waiting for the file to finish saving…');

    if(entry.data?.format==='pdf'&&!entry.data.reviewed)detail.textContent+=' · review pieces';
    if(entry.customer||entry.order)detail.textContent+=' · '+[entry.customer,entry.order].filter(Boolean).join(' / ');
    if(entry.status==='error'||entry.status==='missing')detail.className='job-error';

    if(entry.materialId!==activePreset().id&&entry.status==='ready')detail.textContent+=' · '+(preferences.presets.find(p=>p.id===entry.materialId)?.name||'Choose material');

    name.append(detail);row.append(checked,name);

    if(entry.status==='ready'&&entry.selected){const label=document.createElement('label');label.className='job-quantity';label.textContent=entry.role==='fill'?'Up to':'Sets';const qty=document.createElement('input');qty.type='number';qty.min=1;qty.max=100;qty.value=entry.sets;qty.disabled=locked;qty.dataset.focus=entry.id+'-quantity';qty.setAttribute('aria-label',(entry.role==='fill'?'Maximum sets for ':'Sets for ')+entry.name);qty.onchange=()=>{entry.sets=Number(qty.value);invalidate();};label.append(qty);row.append(label);}

    const options=document.createElement('button');options.textContent='•••';options.className='job-options';options.disabled=locked;options.setAttribute('aria-label','Options for '+entry.name);options.title='Job options';options.onclick=()=>openJobOptions(entry);row.append(options);

    groupFor(entry).append(row);

  }

  const selected=activeEntries().filter(e=>e.selected),required=selected.filter(e=>e.role!=='fill'),fill=selected.filter(e=>e.role==='fill'),pieces=required.reduce((sum,e)=>sum+EZNQueue.count(e),0);

  $('fill-count').textContent=fill.length?fill.length+' selected':fillers.length?fillers.length+' available':'';

  if(fill.length&&!hadSelectedFill)$('sticker-section').open=true;hadSelectedFill=!!fill.length;

  $('fill-options').hidden=!fill.length;updateSizeSummary();

  const mismatched=selected.filter(e=>e.materialId!==activePreset().id);$('material-mismatch').hidden=!mismatched.length;

  $('material-mismatch-text').textContent=mismatched.length+' selected '+(mismatched.length===1?'job uses':'jobs use')+' another material.';

  $('use-material').textContent='Use '+activePreset().name;$('use-material').disabled=locked;

  $('selection-summary').textContent=selected.length?(required.length?pieces+' pieces to print'+(fill.length?' + sticker fill':''):'Fill the sheet with stickers'):'Select jobs to begin.';

  const invalidQuantity=selected.some(e=>!Number.isInteger(e.sets)||e.sets<1||e.sets>100);if(invalidQuantity)$('selection-summary').textContent='Enter a quantity from 1 to 100.';else if(pieces>100)$('selection-summary').textContent='Select no more than 100 required pieces.';

  $('nest').disabled=locked||!selected.length||!!mismatched.length||invalidQuantity||pieces>100;

  $('nest').textContent=importing?'Importing…':busy?'Nesting…':current?'Nest again':'Nest selected jobs';$('nest').classList.toggle('primary',!current);

  ['files','fill-files','demo','preset','quick-width','batch-length','fill-area','connect','settings-open','paths-open','change-output','prepared-open','shop-shortcut','quit'].forEach(id=>$(id).disabled=locked);$('cancel').hidden=!busy||importing;

  $('queue').scrollTop=scroll;if(focus){const field=[...document.querySelectorAll('[data-focus]')].find(e=>e.dataset.focus===focus);field?.focus();}

}

function openJobOptions(entry){

  editingJob=entry.id;$('job-settings-title').textContent=entry.name.replace(/\.svg$/i,'');$('job-source').textContent=entry.sourceFile||entry.name;$('job-category').value=entry.category||'';for(const field of ['customer','order','kit'])$('job-'+field).value=entry[field]||'';showDocumentReview(entry);

  $('job-role').value=entry.role||'required';$('job-quantity').value=entry.sets;

  $('job-material').replaceChildren();for(const p of preferences.presets)$('job-material').append(new Option(p.name,p.id));$('job-material').value=entry.materialId;

  for(const id of ['job-role','job-quantity','job-material'])$(id).disabled=entry.status!=='ready';

  $('job-error').textContent=entry.error||'';jobQuantityHelp();$('job-settings').showModal();

}

function jobQuantityHelp(){const fill=$('job-role').value==='fill';$('job-quantity-label').firstChild.textContent=fill?'Maximum complete sets':'Complete sets';$('job-quantity-help').textContent=fill?'The nest adds only what fits, up to this limit.':'Every piece in this file is included once in each set.';}



async function hash(text){const digest=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(text));return [...new Uint8Array(digest)].map(x=>x.toString(16).padStart(2,'0')).join('');}

async function importText(text,name,options={}){

  const revision=options.revision||await hash(text),id=options.id||'file-'+(await hash(name+'\n'+revision)).slice(0,18);

  const old=queue.find(e=>e.id===id);

  if(old&&options.selected!==false)EZNQueue.restorePrepared(old);

  if(old?.revision===revision&&old.data){old.status='ready';old.error=undefined;if(options.sourceRoot)old.sourceRoot=options.sourceRoot;if(options.selected!==false)old.selected=true;if(options.role&&options.role!==old.role){old.role=options.role;old.sets=options.role==='fill'?100:1;}return true;}

  let parsed,error;

  try{parsed=EZNSVG.importSVG(text,name);}catch(e){error=e.message;}

  const entry={id,name,revision,sourceFile:options.sourceFile||name,origin:options.origin||'files',role:options.role||old?.role||'required',folderKey:options.folderKey,sourceRoot:options.sourceRoot||old?.sourceRoot,category:old?.category||'',materialId:old?.materialId||activePreset().id,sets:old?.sets||(options.role==='fill'?100:1),selected:old?.selected??(options.selected!==false),exportedRevision:old?.exportedRevision,status:error?'error':'ready',error,data:parsed};

  if(error)entry.selected=false;

  if(old)queue[queue.indexOf(old)]=entry;else queue.push(entry);

  return true;

}

async function importFiles(files,role='required'){

  if(busy||saving)return;

  let added=0,unsupported=0;const failures=[];
  const documentOptions=files.some(f=>/\.(pdf|ai)$/i.test(f.name))?await requestDocumentOptions():null;
  if(files.some(f=>/\.(pdf|ai)$/i.test(f.name))&&!documentOptions)return;
  busy=true;importing=true;renderQueue();
  try{for(const file of files){
    if(!/\.(svg|pdf|ai)$/i.test(file.name)){unsupported++;continue;}
    const pdf=/\.(pdf|ai)$/i.test(file.name);
    if(file.size>(pdf?20_000_000:8_000_000)){failures.push(file.name+' exceeds the '+(pdf?'20':'8')+' MB limit.');continue;}
    status('Importing '+file.name+'…');
    try{if(pdf?await importDocument(file,role,documentOptions):await importText(await file.text(),file.name,{role}))added++;}catch(e){failures.push(file.name+': '+e.message);}
  }}finally{busy=false;importing=false;renderQueue();}
  if(added)invalidate();
  const messages=[];if(added)messages.push(added+' file(s) loaded. Review PDF pieces in Job options, then Nest.');if(unsupported)messages.push(unsupported+' unsupported file(s). Use PDF, PDF-compatible AI or SVG.');messages.push(...failures);
  if(messages.length)status(messages.join(' '),!!failures.length||!added);
  const review=queue.find(e=>e.selected&&e.data?.format==='pdf'&&!e.data.reviewed);if(review)openJobOptions(review);

}

function svgNode(tag,attrs={},text){const n=document.createElementNS(NS,tag);for(const [k,v]of Object.entries(attrs))n.setAttribute(k,v);if(text!==undefined)n.textContent=text;return n;}

function artworkSVG(state){return state.job.documentSources?documentSVG(state):EZNSVG.buildSVG(state.job,state.result);}

function mapSVG(state,withLegend=false,labels=true,outlines=true){

  const out=artworkSVG(state),r=state.result,m=state.manifest;

  const background=svgNode('rect',{width:r.width,height:r.usedLength,fill:'#ffffff'});out.insertBefore(background,out.firstChild);

  for(const piece of m.pieces){

    const index=m.jobs.findIndex(j=>j.id===piece.jobId),part=state.job.parts.find(p=>p.id===piece.partId),placement=r.placements[piece.placementIndex];

    const outline=svgNode('polygon',{points:part.points.map(p=>p.join(',')).join(' '),transform:`translate(${placement.x} ${placement.y}) rotate(${placement.rotation})`,fill:'none',stroke:colors[index%colors.length],'stroke-width':.35});

    const mark=svgNode('g',{'data-piece-label':piece.label,'data-job':piece.jobId});const w=Math.max(11,piece.label.length*2.05);

    if(outlines)mark.append(outline);if(labels)mark.append(svgNode('rect',{x:piece.labelX-w/2,y:piece.labelY-2.8,width:w,height:5.6,rx:1,fill:'#ffffff',stroke:colors[index%colors.length],'stroke-width':.3}),svgNode('text',{x:piece.labelX,y:piece.labelY+1.05,'text-anchor':'middle','font-family':'Arial, sans-serif','font-size':3.2,fill:'#132b20'},piece.label));out.append(mark);

  }

  for(const sheet of r.sheets||[])if(sheet.index>0)out.append(svgNode('line',{x1:0,x2:r.width,y1:sheet.offset,y2:sheet.offset,stroke:'#222','stroke-width':.5,'stroke-dasharray':'3 2'}));
  if(withLegend){const rows=m.jobs.length,extra=10+rows*7;out.setAttribute('height',(r.usedLength+extra)+'mm');out.setAttribute('viewBox',`0 0 ${r.width} ${r.usedLength+extra}`);m.jobs.forEach((job,i)=>out.append(svgNode('text',{x:3,y:r.usedLength+8+i*7,'font-family':'Arial, sans-serif','font-size':3.2,fill:colors[i%colors.length]},`${job.code} · ${[job.customer,job.order,job.kit,job.name].filter(Boolean).join(" / ")} · ${job.sets} sets · ${job.placed}/${job.expected} pieces`)));}

  return out;

}

function renderLayout(){

  if(!current?.manifest)return;

  const art=mapSVG(current,false,$('show-labels').checked,$('job-colors').checked),preview=$('preview'),r=current.result;

  preview.replaceChildren();preview.setAttribute('viewBox',`-2 -2 ${r.width+4} ${r.usedLength+4}`);preview.append(svgNode('rect',{width:r.width,height:r.usedLength,fill:'#ffffff'}));for(const child of [...art.children])preview.append(child);

  const highlight=highlightJob;

  if(highlight){for(const piece of current.manifest.pieces){const opacity=piece.jobId===highlight?'1':'.14';preview.querySelector('#ez-part-'+(piece.placementIndex+1))?.setAttribute('opacity',opacity);}for(const label of preview.querySelectorAll('[data-job]'))if(label.getAttribute('data-job')!==highlight)label.setAttribute('opacity','.14');}

  for(const chip of $('completeness').querySelectorAll('[data-job-id]')){const active=chip.dataset.jobId===highlight;chip.classList.toggle('active',active);chip.setAttribute('aria-pressed',String(active));}

  $('show-all').hidden=!highlightJob;preview.removeAttribute('hidden');$('empty').hidden=true;

}

function showResult(state){

  current=state;if(!state.manifest)return;

  const m=state.manifest;$('metrics').hidden=false;$('review-tools').hidden=false;$('length').textContent=dimension(state.result.usedLength);$('utilization').textContent=(100*state.result.utilization).toFixed(1)+'%';$('pieces').textContent=String(m.totalPieces);

  $('result-title').textContent=outputIncomplete(state)?(state.deliveryCompleted?'Working files saved':'Layout ready'):wasPrepared(state)?'Last saved layout':'Ready to save';$('batch-status').hidden=true;$('job-key').hidden=false;$('export-bar').hidden=false;

  highlightJob='';

  $('completeness').replaceChildren();for(const [index,job] of m.jobs.entries()){const el=document.createElement('button');el.className='complete-job color-'+(index%colors.length);el.dataset.jobId=job.id;el.setAttribute('aria-label','Highlight '+job.name);el.onclick=()=>{highlightJob=highlightJob===job.id?'':job.id;renderLayout();};const code=document.createElement('span');code.textContent=job.code;el.append(code,document.createTextNode(`${job.name.replace(/\.svg$/i,'')} · ${job.placed}`));$('completeness').append(el);}for(const fill of state.result.fillSummary||[])if(!fill.pieces){const el=document.createElement('span');el.className='muted';el.textContent=fill.code+' · '+fill.name+': no complete set fitted';$('completeness').append(el);}$('completeness').hidden=false;

  $('export').disabled=busy||saving;$('improve').disabled=busy||!!state.released;

  $('export-note').textContent=outputIncomplete(state)?'Does not meet '+state.manifest.outputProfile.rip+' requirements. Jobs stay in queue.':wasPrepared(state)?'Saved in Exports. Choose jobs for your next nest.':'Includes artwork, a piece map and a checklist.';
  $('output-check').hidden=!outputIncomplete(state);$('output-issues').replaceChildren();if(outputIncomplete(state)){$('output-check-title').textContent='Still needed for '+state.manifest.outputProfile.name;for(const issue of state.manifest.outputCheck.issues)$('output-issues').append(svgText(issue,'li'));}

  $('result-explanation').textContent='All required sets are complete. Coverage measures piece area against the material used. '+(state.result.fillSummary?'Sticker fill is the best found within the search and 100-piece limits.':'');$('nest').classList.remove('primary');$('nest').textContent='Nest again';

  updateProductionResult(state);
  const format=state.job.documentSources?'PDF':'SVG';$('export').textContent=(outputIncomplete(state)?'Export working ':'Export ')+format+(state.released?' again':'');
  renderLayout();

}

async function startNest(automatic=false){

  if(busy||saving)return;

  try{

    const job=EZNQueue.compose(activeEntries(),activePreset(),'combined',{fillArea:preferences.fillArea,maxLength:readPhysicalField('batch-length',displayUnit())});job.outputProfile=EZNProfiles.validate(activeShop());runSignature=signature();clearTimeout(autoTimer);autoAttempts=0;noBetter=0;

    busy=true;current=null;clearPreview();renderQueue();$('export').disabled=true;$('improve').disabled=true;$('batch-status').hidden=false;$('batch-status').textContent='Nesting…';$('empty').replaceChildren(svgText('Arranging your jobs…','strong'),svgText('You can stop the search at any time.','p'));

    await api('/api/solve',job);status(automatic?'Source files changed. Updating the layout…':'Nesting your selected jobs…');setTimeout(poll,400);

  }catch(e){busy=false;if(!current)clearPreview();renderQueue();status(e.message,true);}

}

async function improve(automatic=false){

  if(!current||busy||saving||current.released)return;

  clearTimeout(autoTimer);busy=true;renderQueue();$('export').disabled=true;$('improve').disabled=true;

  try{await api('/api/improve',{id:current.id});if(automatic)autoAttempts++;status(automatic?`Optimizing in the background · extra search ${autoAttempts}/5. Your best layout is kept.`:'Trying another fit. Your best layout is kept.');setTimeout(poll,450);}

  catch(e){busy=false;renderQueue();showResult(current);status(e.message,true);}

}

function scheduleImprove(){if(preferences.autoImprove&&current&&!current.released&&autoAttempts<5&&noBetter<3)autoTimer=setTimeout(()=>improve(true),2500);else if(preferences.autoImprove&&current&&!current.released)status('Optimization paused after the search limit. Your best layout is ready to export.');}

async function poll(){

  if(!busy)return;

  try{

    const state=await api('/api/state');if(state.status==='running'){setTimeout(poll,500);return;}

    busy=false;renderQueue();

    if(state.status==='ready'&&state.manifest){

      noBetter=state.note?.startsWith('Kept')?noBetter+1:0;showResult(state);

      if(runSignature!==signature()){$('export').disabled=true;$('improve').disabled=true;status('The queue changed during the search. Nest again to include its current files.',true);if(preferences.autoNest)autoTimer=setTimeout(()=>startNest(true),1500);return;}

      const added=state.result.fillSummary?.reduce((n,f)=>n+f.pieces,0)||0,hasRequired=state.job.productionJobs.some(j=>j.role!=='fill');status(state.note?.startsWith('Kept')?'Kept the better layout.':added?(hasRequired?'All required pieces fit, plus ':'Fitted ')+added+(hasRequired?' extra ':' ')+(added===1?'sticker.':'stickers.'):'All requested pieces fit.');scheduleImprove();

    }else {clearPreview();status(state.error||'Nesting stopped. Select Nest to try again.',state.status==='error');}

  }catch(e){busy=false;if(!current)clearPreview();renderQueue();status(e.message,true);}

}

async function refreshFolder(){

  if(folderBusy)return;folderBusy=true;

  try{

    const snapshot=await api('/api/folder');folder=snapshot;

    if(!snapshot.connected){$('folder-status').hidden=true;return;}

    $('folder-status').hidden=false;$('folder-status').title=snapshot.path;$('folder-status').textContent='Source: '+pathName(snapshot.path)+(snapshot.unsupported?' · '+snapshot.unsupported+' unsupported files':'');$('folder-path').value=snapshot.path;

    if(snapshot.error){status(snapshot.error,true);return;}

    const before=signature(),folderKey=await hash(snapshot.path.toLowerCase());let changed=false;const known=new Set();

    for(const file of snapshot.files){

      const id='folder-'+folderKey.slice(0,10)+'-'+file.id;known.add(id);const old=queue.find(e=>e.id===id);

      if(file.status==='ready'&&preferences.dismissed?.[id]===file.revision)continue;

      if(file.status==='ready'&&(!old||old.revision!==file.revision||old.status==='missing'||old.status==='settling')){

        try{const loaded=await api('/api/folder/file?id='+file.id+'&revision='+file.revision);changed=await importText(loaded.text,file.name,{id,revision:file.revision,sourceFile:file.relativePath,origin:'folder',folderKey,sourceRoot:pathName(snapshot.path),selected:false})||changed;}

        catch(e){status(e.message,true);}

      }else if(file.status!=='ready'&&(!old||old.status!==file.status)){

        const waiting={...old,id,name:file.name,sourceFile:file.relativePath,origin:'folder',folderKey,sourceRoot:pathName(snapshot.path),status:file.status,error:file.error,revision:old?.revision||'',sets:old?.sets||1,selected:old?.selected||false,materialId:old?.materialId||activePreset().id};if(old)queue[queue.indexOf(old)]=waiting;else queue.push(waiting);changed=true;

      }

    }

    for(const entry of queue)if(!EZNQueue.isPrepared(entry)&&entry.folderKey===folderKey&&!known.has(entry.id)&&entry.status!=='missing'){entry.status='missing';entry.error='Source file is no longer in the folder.';entry.selected=false;changed=true;}

    if(changed){remember();renderQueue();if(!busy&&!saving&&!current?.released){if(before!==signature()&&current){current=null;clearPreview();$('export').disabled=true;$('improve').disabled=true;}if(before!==signature()&&preferences.autoNest&&queue.some(e=>e.selected)&&activeEntries().filter(e=>e.selected).every(e=>e.status==='ready')){clearTimeout(autoTimer);autoTimer=setTimeout(()=>startNest(true),1800);}else if(!current)status('Production folder updated. Select ready jobs to include in the next print.');}}

  }catch(e){if(folder?.connected)status('Folder check: '+e.message,true);}finally{folderBusy=false;}

}

function setDimensionField(key,mm,unit){const field=$(key);field.value=mm===null?'':Number((mm/scale(unit)).toFixed(6));field.dataset.mm=mm===null?'':mm;field.dataset.display=field.value;}

function readPhysicalField(key,unit){const field=$(key);if(!field.value.trim())return null;return field.value===field.dataset.display?Number(field.dataset.mm):Number(field.value)*scale(unit);}
function readDimensionField(key){return readPhysicalField(key,settingsUnit);}

function fillSettings(){const p=activePreset();settingsUnit=displayUnit();$('units').value=settingsUnit;$('precision').value=preferences.precision??2;$('group-by').value=preferences.groupBy||'folder';$('preset-name').value=p.name;for(const key of ['width','maxLength','gap','margin'])setDimensionField(key,p.settings[key],settingsUnit);fillProductionSettings(p);for(const label of document.querySelectorAll('.field-unit'))label.textContent=settingsUnit;$('rotations').value=p.settings.rotations===null?'free':p.settings.rotations.join(',');$('seconds').value=p.settings.seconds;$('auto-nest').checked=preferences.autoNest;$('auto-improve').checked=preferences.autoImprove;$('settings-status').textContent='';}

function saveSettings(asNew){

  const name=$('preset-name').value.trim();if(!name)throw Error('Name this material preset.');

  const settings={};for(const key of ['width','maxLength','gap','margin'])settings[key]=readDimensionField(key);settings.seconds=Number($('seconds').value);settings.rotations=$('rotations').value==='free'?null:$('rotations').value.split(',').map(Number);

  readProductionSettings(settings);const clean=EZNQueue.validatePreset({name,units:$('units').value,settings});

  const previous=activePreset(),changed=asNew||name!==previous.name||JSON.stringify(settings)!==JSON.stringify(previous.settings);

  const preset={...clean,id:asNew?'material-'+crypto.randomUUID():previous.id};if(asNew)preferences.presets.push(preset);else preferences.presets[preferences.presets.findIndex(p=>p.id===preset.id)]=preset;

  preferences.active=preset.id;preferences.units=$('units').value;preferences.precision=Number($('precision').value);preferences.groupBy=$('group-by').value;

  if(changed){preferences.runLengths=preferences.runLengths||{};delete preferences.runLengths[preset.id];}

  preferences.autoNest=$('auto-nest').checked;preferences.autoImprove=$('auto-improve').checked;renderPresets();

  if(changed)invalidate();else{remember();renderQueue();if(current)showResult(current);runSignature=signature();}

  $('settings').close();status(changed?'Settings saved. Nest again to use the updated material.':'Workspace settings saved.');

}

$('files').onchange=async e=>{try{await importFiles([...e.target.files]);}catch(error){status(error.message,true);}finally{e.target.value='';}};

document.addEventListener('dragover',e=>{e.preventDefault();document.body.classList.add('dragging');});document.addEventListener('dragleave',e=>{if(!e.relatedTarget)document.body.classList.remove('dragging');});document.addEventListener('drop',async e=>{e.preventDefault();document.body.classList.remove('dragging');if(!busy&&!saving)await importFiles([...e.dataTransfer.files]);});

$('demo').onclick=async()=>{try{$('settings').close();preferences.active='demo';renderPresets();queue.forEach(e=>e.selected=false);const text=await(await fetch('/sample-artwork.svg')).text();await importText(text,'Trail graphics.svg',{id:'demo-trail',selected:true});await importText('<svg xmlns="http://www.w3.org/2000/svg" width="120mm" height="80mm" viewBox="0 0 120 80"><defs><linearGradient id="panel-ink"><stop stop-color="#803c66"/><stop offset="1" stop-color="#efab77"/></linearGradient></defs><path id="side-panel" fill="url(#panel-ink)" d="M5 5H65V23H30V45H5Z"/><rect id="name-plate" x="75" y="5" width="35" height="55" rx="8" fill="#dbc363"/></svg>','Helmet graphics.svg',{id:'demo-helmet',selected:true});for(const e of queue)if(e.id.startsWith('demo-')){EZNQueue.restorePrepared(e);e.selected=true;e.materialId='demo';e.status='ready';}await importText('<svg xmlns="http://www.w3.org/2000/svg" width="24mm" height="18mm" viewBox="0 0 24 18"><rect id="sticker" width="24" height="18" rx="4" fill="#3b8b65"/></svg>','Shop stickers.svg',{id:'demo-sticker',selected:true});const sticker=queue.find(e=>e.id==='demo-sticker');sticker.role='fill';sticker.sets=100;sticker.selected=true;sticker.materialId='demo';preferences.fillArea='gaps';renderPresets();invalidate();status('Example: two required jobs plus stickers to fill the spare space.');}catch(e){status(e.message,true);}};

$('nest').onclick=()=>startNest();$('improve').onclick=()=>improve();$('cancel').onclick=async()=>{clearTimeout(autoTimer);autoAttempts=5;try{await api('/api/cancel',{});}catch(e){status(e.message,true);}};

$('quick-width').onchange=()=>{try{const p=activePreset(),width=readPhysicalField('quick-width',displayUnit());if(width===null)throw Error('Enter your roll width.');const validated=EZNQueue.validatePreset({...p,settings:{...p.settings,width}});p.settings=validated.settings;renderPresets();invalidate();status('Roll width updated. Nest to use this width.');}catch(e){setDimensionField('quick-width',activePreset().settings.width,displayUnit());status(e.message,true);}};

$('help-open').onclick=()=>$('help').showModal();$('help-close').onclick=()=>$('help').close();
$('quit').onclick=async()=>{if(busy||saving)return;try{await api('/api/shutdown',{});clearInterval(folderTimer);clearTimeout(autoTimer);$('help').close();document.querySelectorAll('button,input,select').forEach(el=>el.disabled=true);status('eznest has stopped. You can close this tab. Open eznest again to continue.');}catch(e){$('help-status').textContent=e.message;}};

$('preset').onchange=()=>{preferences.active=$('preset').value;renderPresets();invalidate();};$('batch-length').onchange=()=>{preferences.runLengths=preferences.runLengths||{};preferences.runLengths[activePreset().id]=readPhysicalField('batch-length',displayUnit());invalidate();};$('fill-area').onchange=()=>{preferences.fillArea=$('fill-area').value;invalidate();};

$('show-labels').onchange=renderLayout;$('job-colors').onchange=renderLayout;$('show-all').onclick=()=>{highlightJob='';renderLayout();};

$('settings-open').onclick=()=>{fillSettings();$('settings').showModal();};$('settings-close').onclick=()=>$('settings').close();

$('units').onchange=()=>{const next=$('units').value;for(const key of ['width','maxLength','gap','margin','sheet-length'])setDimensionField(key,readDimensionField(key),next);settingsUnit=next;for(const label of document.querySelectorAll('.field-unit'))label.textContent=next;};

$('settings-form').onsubmit=e=>{e.preventDefault();try{saveSettings(false);}catch(error){$('settings-status').textContent=error.message;$('settings-status').className='error';}};

$('save-copy').onclick=()=>{try{saveSettings(true);}catch(e){$('settings-status').textContent=e.message;$('settings-status').className='error';}};

$('connect').onclick=async()=>{try{status('Choose your print-ready folder in the folder window.');const result=await api('/api/folder/pick',{});if(!result.cancelled)await refreshFolder();else status('Folder selection cancelled.');}catch(e){status(e.message,true);$('paths').showModal();}};

$('connect-path').onclick=async()=>{try{await api('/api/folder/connect',{path:$('folder-path').value});await refreshFolder();$('paths-status').textContent='Source folder connected.';}catch(e){$('paths-status').textContent=e.message;}};

$('disconnect').onclick=async()=>{try{await api('/api/folder/disconnect',{});$('folder-path').value='';await refreshFolder();$('paths-status').textContent='Disconnected. Loaded files remain in the queue.';}catch(e){$('paths-status').textContent=e.message;}};

$('export').onclick=async()=>{
  if(!current||busy||saving)return;
  clearTimeout(autoTimer);saving=true;renderQueue();$('export').disabled=true;
  try{
    const released=await api('/api/release',{id:current.id,workingOnly:outputIncomplete(current),artwork:current.job.documentSources?null:EZNSVG.serialize(artworkSVG(current)),map:EZNSVG.serialize(mapSVG(current,true))});
    current.released=true;current.deliveryCompleted=released.deliveryCompleted===true;current.savedPath=released.savedPath;
    if(released.outputCheck)current.manifest.outputCheck=released.outputCheck;
    if(!released.savedPath){
      const response=await fetch(released.url);
      if(!response.ok)throw Error('The frozen batch is saved, but the download failed. Select Export again to retry.');
      const blob=await response.blob(),url=URL.createObjectURL(blob),link=document.createElement('a');
      link.href=url;link.download='EZ-Nest-Batch-'+released.id.slice(0,8)+'.zip';link.click();
      setTimeout(()=>URL.revokeObjectURL(url),1000);
      await api('/api/delivery/complete',{id:current.id});current.deliveryCompleted=true;
    }
    recordPrepared(current);EZNQueue.markPrepared(queue,current);remember();renderQueue();showResult(current);
    status(outputIncomplete(current)?'Working package saved. Jobs remain in the queue.':released.savedPath?'Files saved. Jobs moved to Exports.':'Download started. The frozen batch is also available in Exports.');
    if(released.savedPath){$('output-status').textContent='Saved to '+pathName($('output-path').value);$('output-status').title=released.savedPath;}
  }catch(e){
    try{const saved=await api('/api/state');if(saved.id===current?.id&&saved.released){if(saved.deliveryCompleted===true){recordPrepared(saved);EZNQueue.markPrepared(queue,saved);remember();}showResult(saved);}}catch{}
    $('export').disabled=false;status(e.message,true);
  }finally{saving=false;renderQueue();if(current)showResult(current);}
};


async function refreshOutput(){const out=await api('/api/output');$('output-path').value=out.path||'';showDestination();}

$('paths-open').onclick=$('change-output').onclick=async()=>{try{await refreshOutput();$('paths-status').textContent='';$('paths').showModal();}catch(e){status(e.message,true);}};

$('paths-close').onclick=()=>$('paths').close();

$('output-save').onclick=async()=>{try{await api('/api/output/connect',{path:$('output-path').value.trim()});await refreshOutput();$('paths-status').textContent='Save destination updated.';}catch(e){$('paths-status').textContent=e.message;}};

$('output-browse').onclick=async()=>{try{const out=await api('/api/output/pick',{});if(!out.cancelled){await refreshOutput();$('paths-status').textContent='Save destination updated.';}}catch(e){$('paths-status').textContent=e.message;}};

function presetFromForm(){const settings={};for(const key of ['width','maxLength','gap','margin'])settings[key]=readDimensionField(key);settings.seconds=Number($('seconds').value);settings.rotations=$('rotations').value==='free'?null:$('rotations').value.split(',').map(Number);readProductionSettings(settings);return EZNQueue.validatePreset({name:$('preset-name').value.trim(),units:$('units').value,settings});}

$('share-preset').onclick=()=>{try{const preset=presetFromForm(),blob=new Blob([JSON.stringify({format:'eznest.material-presets',version:1,presets:[preset]},null,2)],{type:'application/json'}),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='eznest-material-preset.json';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);$('settings-status').textContent='Preset exported. Import this file on another workstation.';}catch(e){$('settings-status').textContent=e.message;}};

$('import-preset').onchange=async event=>{try{const file=event.target.files[0];if(!file)return;if(file.size>200000)throw Error('Preset file is too large.');const presets=EZNQueue.importPresets(JSON.parse(await file.text()));for(const p of presets){if(preferences.presets.some(existing=>existing.name===p.name))p.name=p.name.slice(0,69)+' (imported)';p.id='material-'+crypto.randomUUID();preferences.presets.push(p);}preferences.active=presets[0].id;renderPresets();invalidate();fillSettings();$('settings-status').textContent=presets.length+' preset(s) imported as new entries. Assign jobs to the imported material before nesting.';}catch(e){$('settings-status').textContent=e.message;}finally{event.target.value='';}};





$('fill-files').onchange=async e=>{try{await importFiles([...e.target.files],'fill');$('sticker-section').open=true;}catch(error){status(error.message,true);}finally{e.target.value='';}};

$('use-material').onclick=()=>{for(const e of queue)if(e.selected)e.materialId=activePreset().id;invalidate();};

$('job-close').onclick=()=>$('job-settings').close();

$('job-role').onchange=()=>{if($('job-role').value==='fill'&&Number($('job-quantity').value)===1)$('job-quantity').value=100;else if($('job-role').value==='required'&&Number($('job-quantity').value)===100)$('job-quantity').value=1;jobQuantityHelp();};

$('job-form').onsubmit=e=>{e.preventDefault();const entry=queue.find(e=>e.id===editingJob);if(!entry)return;if(entry.status!=='ready'){ $('job-error').textContent=entry.error||'Wait for the source file to finish saving.';return;}const quantity=Number($('job-quantity').value);if(!Number.isInteger(quantity)||quantity<1||quantity>100){$('job-error').textContent='Enter a whole number from 1 to 100.';return;}for(const field of ['customer','order','kit'])entry[field]=$('job-'+field).value.trim();if(entry.data?.format==='pdf')entry.data.reviewed=$('document-reviewed').checked;entry.category=$('job-category').value.trim();entry.role=$('job-role').value;entry.sets=quantity;entry.materialId=$('job-material').value;$('job-settings').close();invalidate();};

$('job-remove').onclick=()=>{const entry=queue.find(e=>e.id===editingJob);if(!entry)return;if(entry.origin==='folder'){preferences.dismissed=preferences.dismissed||{};preferences.dismissed[entry.id]=entry.revision;}queue=queue.filter(e=>e!==entry);$('job-settings').close();invalidate();};



function recordPrepared(state){

  if(!state?.released||state.deliveryCompleted!==true||!state.manifest||outputIncomplete(state)||preparedBatches.some(b=>b.id===state.id))return;

  const jobs=state.manifest.jobs.filter(j=>j.placed>0).map(j=>{const source=state.job.productionJobs.find(s=>s.id===j.id),entry=queue.find(e=>e.id===j.id&&e.revision===source?.revision);return {id:j.id,revision:source?.revision,name:j.name,placed:j.placed,requestedSets:entry?.sets||source?.sets||1,role:entry?.role||source?.role||'required',group:entry?EZNQueue.groupName(entry,'folder',preferences.presets):'Saved job'};});

  preparedBatches.unshift({id:state.id,createdAt:state.manifest.createdAt,jobs});

}

function renderPrepared(){

  const list=$('prepared-list');list.replaceChildren();$('prepared-status').textContent='';

  const batches=[...preparedBatches],legacy=queue.filter(e=>EZNQueue.isPrepared(e)&&!batches.some(b=>b.jobs.some(j=>j.id===e.id&&j.revision===e.revision)));

  if(legacy.length)batches.push({id:'earlier',jobs:legacy.map(e=>({id:e.id,revision:e.revision,name:e.name,placed:e.savedPieces,group:EZNQueue.groupName(e,'folder',preferences.presets)}))});

  if(!batches.length){list.append(svgText('No exports yet. Your saved batches will appear here.','p'));return;}

  for(const batch of batches){const section=document.createElement('section');section.className='prepared-batch';const head=document.createElement('div');head.className='prepared-head';head.append(svgText(batch.createdAt?new Date(batch.createdAt).toLocaleString():'Saved earlier','h3'));if(/^[a-f0-9]{32}$/.test(batch.id)){const link=document.createElement('a');link.className='button';link.href='/api/batch/'+batch.id;link.download='eznest-'+batch.id.slice(0,8)+'.zip';link.textContent='Download batch';head.append(link);}section.append(head);list.append(section);

    for(const job of batch.jobs){const entry=queue.find(e=>e.id===job.id&&e.revision===job.revision),row=document.createElement('div');row.className='prepared-job';const info=document.createElement('div');info.append(svgText(job.name.replace(/\.svg$/i,''),'strong'),svgText(job.placed+(job.placed===1?' piece saved · ':' pieces saved · ')+job.group,'p'));const restore=document.createElement('button');restore.textContent=!entry?'Source changed or removed':EZNQueue.isPrepared(entry)?'Add to queue':'In queue';restore.disabled=!entry||!EZNQueue.isPrepared(entry);restore.setAttribute('aria-label',restore.textContent+' · '+job.name);restore.onclick=()=>{EZNQueue.restorePrepared(entry);entry.sets=job.requestedSets||entry.sets;entry.role=job.role||entry.role;remember();renderQueue();renderPrepared();$('prepared-status').textContent=job.name+' added back. Select it in the queue to prepare another print.';};row.append(info,restore);section.append(row);}

  }

}

$('prepared-open').onclick=()=>{renderPrepared();$('prepared').showModal();};$('prepared-close').onclick=()=>$('prepared').close();

function migratePrepared(state){

  if(state?.deliveryCompleted===true){recordPrepared(state);EZNQueue.markPrepared(queue,state);}if(preferences.preparedQueueVersion===1){remember();renderQueue();return;}

  for(const entry of queue)if(entry.exportedRevision===entry.revision&&entry.savedPieces>0){entry.preparedRevision=entry.revision;entry.selected=false;}

  if(state?.released&&state.deliveryCompleted===undefined&&queue.some(e=>e.exportedRevision===e.revision&&e.savedPieces>0)){const legacy={...state,deliveryCompleted:true};recordPrepared(legacy);EZNQueue.markPrepared(queue,legacy);}

  preferences.preparedQueueVersion=1;remember();renderQueue();

}




function fillShopForm(profile=activeShop()){
  $('shop-select').replaceChildren();for(const p of preferences.shopProfiles)$('shop-select').append(new Option(p.name,p.id));$('shop-select').value=profile.id;
  const mapping={name:'name',rip:'rip',format:'format',color:'colorMode',icc:'iccProfile','cut-spot':'cutSpot','cut-layer':'cutLayer',registration:'registrationOwner',finishing:'finishingSoftware',media:'mediaOwner',joblog:'jobLogOwner'};
  for(const [field,key]of Object.entries(mapping))$('shop-'+field).value=profile[key];$('shop-accepted').value=profile.acceptedFormats.join(', ');$('shop-bleed-unit').textContent=displayUnit();
  if(profile.bleedMm===null){$('shop-bleed').value='';delete $('shop-bleed').dataset.mm;delete $('shop-bleed').dataset.display;}else setDimensionField('shop-bleed',profile.bleedMm,displayUnit());$('shop-status').textContent='';
}
function shopFromForm(){return EZNProfiles.validate({name:$('shop-name').value,rip:$('shop-rip').value,format:$('shop-format').value,acceptedFormats:$('shop-accepted').value.split(',').map(s=>s.trim().toLowerCase()).filter(Boolean),colorMode:$('shop-color').value,iccProfile:$('shop-icc').value,bleedMm:$('shop-bleed').value===''?null:readPhysicalField('shop-bleed',displayUnit()),cutSpot:$('shop-cut-spot').value,cutLayer:$('shop-cut-layer').value,registrationOwner:$('shop-registration').value,finishingSoftware:$('shop-finishing').value,mediaOwner:$('shop-media').value,jobLogOwner:$('shop-joblog').value});}
function saveShopProfile(asNew){const previous=JSON.stringify(EZNProfiles.validate(activeShop())),profile={...shopFromForm(),id:asNew?'shop-'+crypto.randomUUID():$('shop-select').value};if(asNew)preferences.shopProfiles.push(profile);else preferences.shopProfiles[preferences.shopProfiles.findIndex(p=>p.id===profile.id)]=profile;preferences.shopProfile=profile.id;renderPresets();if(previous!==JSON.stringify(EZNProfiles.validate(profile)))invalidate();else remember();$('shop-settings').close();status('Shop requirements saved. Readiness is checked against the next batch.');}
function downloadText(text,name,type='text/plain'){const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([text],{type}));a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);}
$('shop-open').onclick=$('shop-shortcut').onclick=()=>{fillShopForm();$('shop-settings').showModal();};$('shop-close').onclick=()=>$('shop-settings').close();
$('shop-select').onchange=()=>fillShopForm(preferences.shopProfiles.find(p=>p.id===$('shop-select').value));
$('shop-form').onsubmit=e=>{e.preventDefault();try{saveShopProfile(false);}catch(error){$('shop-status').textContent=error.message;}};
$('shop-copy').onclick=()=>{try{saveShopProfile(true);}catch(error){$('shop-status').textContent=error.message;}};
$('shop-export').onclick=()=>{try{downloadText(JSON.stringify({format:'eznest.shop-profiles',version:1,profiles:[shopFromForm()]},null,2),'eznest-shop-profile.json','application/json');$('shop-status').textContent='Profile exported. Local folder paths and artwork are not included.';}catch(error){$('shop-status').textContent=error.message;}};
$('shop-import').onchange=async event=>{try{const file=event.target.files[0];if(!file)return;if(file.size>200000)throw Error('Profile file is too large.');const profiles=EZNProfiles.importProfiles(JSON.parse(await file.text()));for(const profile of profiles){profile.id='shop-'+crypto.randomUUID();if(preferences.shopProfiles.some(p=>p.name===profile.name))profile.name=profile.name.slice(0,69)+' (imported)';preferences.shopProfiles.push(profile);}remember();fillShopForm(profiles[0]);$('shop-status').textContent='Imported as new profiles. Review, then select Use this profile.';}catch(error){$('shop-status').textContent=error.message;}finally{event.target.value='';}};
$('shop-spec').onclick=()=>{try{const p=shopFromForm(),lines=[p.name+' — FILE REQUIREMENTS','RIP: '+p.rip,'Preferred production format: '+p.format.toUpperCase(),'Art accepted by shop: '+p.acceptedFormats.join(', ').toUpperCase(),'Print colors: '+p.colorMode,'ICC profile: '+(p.iccProfile||'Confirm with shop'),'Bleed: '+(p.bleedMm===null?'Confirm with shop':dimension(p.bleedMm)),'Cut spot color: '+(p.cutSpot||'None'),'Separate cut layer: '+(p.cutLayer||'None'),'Registration marks added by: '+p.registrationOwner,'Finishing software: '+(p.finishingSoftware||'Not specified'),'Media presets managed by: '+p.mediaOwner,'Printed job log managed by: '+p.jobLogOwner,'Work at actual physical size. Keep artwork and cut contours aligned.','Sorting maps and checklists are separate from production artwork.','This is a requirements sheet, not verification that an exported file meets it.'];downloadText(lines.join('\n')+'\n','eznest-file-requirements.txt');$('shop-status').textContent='Requirements sheet downloaded.';}catch(error){$('shop-status').textContent=error.message;}};

(async()=>{try{await openStorage();renderPresets();clearPreview();renderQueue();token=(await api('/api/session')).token;const state=await api('/api/state');migratePrepared(state);if(state.status==='ready'&&state.manifest){showResult(state);status(outputIncomplete(state)?'This layout still needs print preparation for the selected shop.':wasPrepared(state)?'Showing your last saved layout. Select jobs for a new print.':'Your last layout is ready to save.');runSignature=signature();}else if(state.status==='running'&&state.job?.productionJobs){busy=true;runSignature=signature();renderQueue();poll();}await refreshFolder();await refreshOutput();folderTimer=setInterval(refreshFolder,4000);}catch(e){status(e.message,true);}})();

