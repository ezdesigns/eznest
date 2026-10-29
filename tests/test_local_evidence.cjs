const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(require('node:path').join(__dirname,'../production-features.js'),'utf8');
const context={structuredClone,EZNComparison:require('../layout-comparison.js'),document:{addEventListener(){}}};vm.createContext(context);
vm.runInContext(source.slice(source.indexOf('// Local layout comparisons'))+'\nthis.evidence=EZNLocalEvidence;',context);
const {comparisonPayload,snapshot,photoKind}=context.evidence;
const job={settings:{width:180,gap:3,margin:5,rotations:[0,90,180,270],seconds:5,seed:42},parts:[{id:'part',quantity:2,points:[[0,0],[10,0],[0,10]]}],productionJobs:[{id:'job',revision:'source-sha'}],fillJobs:[{maxSets:4}]};
const state={id:'a'.repeat(32),released:true,deliveryCompleted:true,job,result:{width:180,usedLength:100,utilization:.7},manifest:{totalPieces:2,createdAt:'2026-10-27',outputCheck:{ready:true}}};
const key=x=>JSON.stringify(comparisonPayload(x));const before=JSON.stringify(job);
const other=structuredClone(state);other.job.settings.seed=43;other.job._progress='/tmp/progress';assert.equal(key(state),key(other));assert.equal(JSON.stringify(job),before);
for(const [field,value] of [['seconds',30],['width',200],['gap',2],['margin',4],['rotations',[0]]]){const changed=structuredClone(state);changed.job.settings[field]=value;assert.notEqual(key(state),key(changed));}
for(const mutate of [j=>j.parts[0].quantity++,j=>j.parts[0].points[1][0]++,j=>j.productionJobs[0].revision='different',j=>j.fillJobs[0].maxSets++]){const changed=structuredClone(state);mutate(changed.job);assert.notEqual(key(state),key(changed));}
const withFill=structuredClone(state);withFill.requestJob=structuredClone(job);withFill.job.parts.push({id:'bonus'});assert.equal(key(state),key(withFill),'resolved filler counts must not change comparison inputs');
const sha='b'.repeat(64);assert.equal(snapshot(state,sha).sha256,sha);assert.equal(snapshot(state,sha).batchId,state.id);
for(const changed of [{...state,released:false},{...state,deliveryCompleted:false},{...state,manifest:{...state.manifest,outputCheck:{ready:false}}},{...state,id:'../path'}])assert.throws(()=>snapshot(changed,sha),/Export and confirm/);
assert.throws(()=>snapshot(state,'not-a-hash'));
assert.equal(photoKind(Uint8Array.from([137,80,78,71,13,10,26,10])),'image/png');
assert.equal(photoKind(Uint8Array.from([255,216,255])),'image/jpeg');
assert.equal(photoKind(Buffer.from('RIFF1234WEBP')),'image/webp');
assert.equal(photoKind(Buffer.from('<svg onload="alert(1)">')),null);assert.equal(photoKind(new Uint8Array()),null);
console.log('Local evidence: comparable source/constraint identity, immutable export binding and raster photo signature checks passed.');

async function testOpeningLock(){
  const elements=new Map();let shown=0,requests=0,resolveFetch;
  const element=id=>{if(!elements.has(id))elements.set(id,{disabled:false,addEventListener(){},showModal(){shown++;},replaceChildren(){}});return elements.get(id);};
  context.document.getElementById=element;context.window={addEventListener(){}};
  context.current=structuredClone(state);context.busy=false;context.saving=false;context.status=()=>{};
  context.fetch=()=>{requests++;return new Promise(resolve=>resolveFetch=resolve);};
  context.evidence.init();
  const pending=element('proof-open').onclick();
  assert.equal(element('proof-drafts-open').disabled,true);
  await element('proof-drafts-open').onclick();
  await element('proof-open').onclick();
  assert.equal(shown,0,'draft navigation must not open another editor during ZIP fingerprinting');
  assert.equal(requests,1,'a re-enabled button must not start a duplicate open');
  resolveFetch({ok:false});await pending;
  assert.equal(element('proof-drafts-open').disabled,false,'failed fingerprinting releases navigation');
  console.log('Local evidence: pending ZIP fingerprint blocks concurrent draft navigation and duplicate opens.');
}
testOpeningLock().catch(error=>{console.error(error);process.exitCode=1;});
