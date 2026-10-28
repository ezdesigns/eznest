const assert=require('node:assert/strict');
const {compose,codeFor}=require('../queue-core.js');
const preset={id:'vinyl',name:'Vinyl',settings:{width:180}};
function entry(id){return {id,name:id,sourceFile:id+'.svg',revision:'hash-'+id,sets:2,selected:true,status:'ready',materialId:'vinyl',data:{svgSource:{defs:'<defs/>'},parts:[{id:'same-id',name:'Part',quantity:1,points:[[0,0],[10,0],[10,10]]}]}};}
const batch=compose([entry('a'),entry('b')],preset);
assert.equal(batch.parts.length,2);assert.notEqual(batch.parts[0].id,batch.parts[1].id);
assert.deepEqual(batch.parts.map(p=>p.quantity),[2,2]);assert.deepEqual(batch.productionJobs.map(j=>j.code),['A','B']);
assert.equal(Object.keys(batch.svgSources).length,2);
assert.throws(()=>compose([entry('a'),entry('b')],preset,'single'),/one job/);
assert.throws(()=>compose([{...entry('a'),materialId:'paper'}],preset),/material/);
assert.throws(()=>compose([{...entry('a'),sets:1.5}],preset),/whole/);
assert.equal(compose([{...entry('run'),sets:200}],preset).parts[0].quantity,200);
assert.throws(()=>compose([{...entry('over'),sets:801}],preset),/800/);
const sectionPreset={...preset,settings:{...preset.settings,sheetLength:1524}};
assert.equal(compose([{...entry('stickers'),sets:1000}],sectionPreset).parts[0].quantity,1000);
assert.throws(()=>compose([{...entry('over'),sets:5001}],sectionPreset),/5000/);
assert.throws(()=>compose([{...entry('a'),status:'settling'}],preset),/not ready/);
assert.equal(codeFor(26),'AA');
console.log('Job identity, set counts, material compatibility and single-job checks passed.');
const filler={...entry('stickers'),role:'fill',sets:100};
const fillBatch=compose([entry('kit'),filler],preset,'combined',{fillArea:'length',maxLength:120});
assert.equal(fillBatch.parts.length,1);assert.equal(fillBatch.parts[0].quantity,2);
assert.equal(fillBatch.fillJobs[0].maxSets,100);assert.equal(fillBatch.fillJobs[0].source.code,'B');
assert.equal(fillBatch.settings.maxLength,120);assert.equal(fillBatch.fillArea,'length');
const {importPresets}=require('../queue-core.js');
const shared={format:'eznest.material-presets',version:1,presets:[{id:'do-not-reuse',name:'Shop',units:'in',settings:{width:1346.2,maxLength:3000,gap:5.08,margin:6.35,seconds:15,rotations:[0,90,180,270]},outputPath:'private'}]};
const clean=importPresets(shared)[0];assert.equal(clean.settings.width,1346.2);assert.equal(clean.id,undefined);assert.equal(clean.outputPath,undefined);
assert.throws(()=>importPresets({...shared,version:2}),/version/);
assert.throws(()=>importPresets({...shared,presets:[{...shared.presets[0],settings:{...clean.settings,gap:-1}}]}),/Invalid/);
console.log('Sticker fill composition and portable preset validation passed.');
const automaticPreset={...shared.presets[0],settings:{...clean.settings,maxLength:null}};
assert.equal(importPresets({...shared,presets:[automaticPreset]})[0].settings.maxLength,null);
const automaticBatch=compose([entry('kit')],{...preset,settings:{width:180,maxLength:120}},'combined',{maxLength:null});
assert.equal(automaticBatch.settings.width,180);
assert.equal(automaticBatch.settings.maxLength,null,'automatic length overrides an older preset cap');
assert.throws(()=>compose([filler],preset,'combined',{maxLength:null}),/Enter a roll length/);
assert.throws(()=>compose([entry('kit'),filler],preset,'combined',{maxLength:null,fillArea:'length'}),/Enter a roll length/);
assert.equal(compose([entry('kit'),filler],preset,'combined',{maxLength:null,fillArea:'gaps'}).settings.maxLength,null);
console.log('Fixed roll width, automatic length and explicit sticker-area checks passed.');
const {isPrepared,markPrepared,restorePrepared,groupName,unitScale}=require('../queue-core.js');
const staged=[entry('a'),entry('b'),{...entry('sticker'),role:'fill'}];
const preparedState={id:'abc',released:false,job:{productionJobs:staged.map(e=>({id:e.id,revision:e.revision}))},manifest:{createdAt:'2026-09-29T12:00:00Z',jobs:[{id:'a',placed:2},{id:'b',placed:2},{id:'sticker',placed:0}]}};
assert.equal(markPrepared(staged,preparedState),0,'unsaved output must not clear the queue');
staged[1].revision='new-source';preparedState.released=true;
assert.equal(markPrepared(staged,preparedState),0,'a frozen package alone is not a successful destination save');
preparedState.deliveryCompleted=true;
assert.equal(markPrepared(staged,preparedState),1,'only successfully placed, matching revisions leave the queue');
assert.ok(isPrepared(staged[0]));assert.ok(!isPrepared(staged[1]));assert.ok(!isPrepared(staged[2]));
staged[0].selected=true;assert.throws(()=>compose([staged[0]],preset),/Select/,'archived jobs cannot enter a batch');
restorePrepared(staged[0]);assert.equal(staged[0].selected,false);assert.ok(!isPrepared(staged[0]));
assert.equal(markPrepared(staged,preparedState),0,'saving an old batch again must not remove a requeued job');
assert.equal(groupName({...entry('nested'),origin:'folder',sourceRoot:'Print jobs',sourceFile:'Moto\\Customer A\\kit.svg'},'folder'),'Print jobs / Moto / Customer A');
assert.equal(groupName({...entry('a'),category:'Stickers'},'category'),'Stickers');
assert.equal(groupName(entry('a'),'material',[preset]),'Vinyl');
assert.equal(unitScale('in'),25.4);assert.equal(unitScale('cm'),10);assert.equal(25.4/unitScale('in'),1);assert.throws(()=>unitScale('pixels'));
console.log('Prepared queue lifecycle, source grouping and physical unit conversions passed.');

const fullRoll={...automaticPreset,settings:{...automaticPreset.settings,maxLength:45720,sheetLength:1524}};
assert.equal(importPresets({...shared,presets:[fullRoll]})[0].settings.maxLength,45720);
assert.throws(()=>importPresets({...shared,presets:[{...fullRoll,settings:{...fullRoll.settings,maxLength:1000001}}]}),/Invalid/);

// Exercise the real browser event handlers with controlled download/HTTP outcomes.
// Dispatching a browser download (including cancellation) cannot retire jobs.
async function testDownloadAcknowledgement(){
  const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
  const source=fs.readFileSync(path.join(__dirname,'../queue-app.js'),'utf8');
  const handlers=source.slice(source.indexOf("$('export').onclick=async()=>{"),source.indexOf('async function refreshOutput()'));
  function harness(options={}){
    const elements=new Map(),calls=[],events=[],jobs=[entry('a')];
    const state={id:'a'.repeat(32),job:{productionJobs:[{id:'a',revision:jobs[0].revision}]},manifest:{jobs:[{id:'a',placed:2}],outputCheck:{ready:!options.working}}};
    const context={current:state,queue:jobs,busy:false,saving:false,autoTimer:null,
      $:id=>{if(!elements.has(id))elements.set(id,{value:''});return elements.get(id);},
      clearTimeout(){},setTimeout(){},URL:{createObjectURL:()=> 'blob:example',revokeObjectURL(){}},
      document:{createElement:()=>({click(){events.push('download');}})},
      EZNSVG:{serialize:()=>'<svg/>'},artworkSVG(){},mapSVG(){},EZNQueue:require('../queue-core.js'),
      outputIncomplete:s=>s.manifest.outputCheck.ready===false,
      renderQueue(){},showResult(s){context.current=s;},remember(){},pathName:p=>p,
      recordPrepared(s){if(s.deliveryCompleted===true&&!context.outputIncomplete(s))events.push('prepared');},
      status(message){events.push(message);},
      async fetch(){if(options.networkFailure)throw Error('Offline');return {ok:true,blob:async()=>({})};},
      async api(route){
        calls.push(route);
        if(route==='/api/release')return {id:state.id,deliveryCompleted:!!options.folder,savedPath:options.folder?'/test/output':null,url:'/batch'};
        if(route==='/api/state')return state;
        if(route==='/api/delivery/complete'){
          if(options.ackFailure)throw Error('Server unavailable');
          return {ok:true};
        }
        throw Error('Unexpected API route');
      }
    };
    vm.createContext(context);vm.runInContext(handlers,context);
    return {context,jobs,state,calls,events,export:()=>context.$('export').onclick(),confirm:()=>context.$('confirm-download').onclick()};
  }
  const pending=harness();await pending.export();
  assert.ok(pending.events.includes('download'));
  assert.equal(pending.state.deliveryCompleted,false);
  assert.equal(pending.jobs[0].selected,true);
  assert.equal(isPrepared(pending.jobs[0]),false);
  assert.ok(!pending.calls.includes('/api/delivery/complete'));
  await pending.export(); // Retry after cancelling the first browser download.
  assert.equal(isPrepared(pending.jobs[0]),false);
  const reloaded=harness();Object.assign(reloaded.state,JSON.parse(JSON.stringify(pending.state)));
  assert.equal(isPrepared(reloaded.jobs[0]),false);
  await reloaded.confirm();
  assert.equal(reloaded.state.deliveryCompleted,true);
  assert.equal(isPrepared(reloaded.jobs[0]),true);
  await reloaded.confirm();
  assert.equal(reloaded.calls.filter(p=>p==='/api/delivery/complete').length,1);
  const failed=harness({networkFailure:true});await failed.export();
  assert.equal(isPrepared(failed.jobs[0]),false);
  assert.ok(!failed.calls.includes('/api/delivery/complete'));
  const ackOptions={ackFailure:true},ack=harness(ackOptions);await ack.export();await ack.confirm();
  assert.equal(isPrepared(ack.jobs[0]),false);assert.equal(ack.state.deliveryCompleted,false);
  ackOptions.ackFailure=false;await ack.confirm();assert.equal(isPrepared(ack.jobs[0]),true);
  const folder=harness({folder:true});await folder.export();
  assert.equal(isPrepared(folder.jobs[0]),true);assert.ok(!folder.events.includes('download'));
  const working=harness({working:true});await working.export();await working.confirm();
  assert.equal(working.state.deliveryCompleted,true);assert.equal(isPrepared(working.jobs[0]),false);
  const premature=harness();await premature.confirm();assert.equal(premature.calls.length,0);
  console.log('Browser download retry, pending reload, acknowledgement failure, folder save and working-file lifecycle passed.');
}
testDownloadAcknowledgement().catch(error=>{console.error(error);process.exitCode=1;});
