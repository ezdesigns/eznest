const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const path = require('node:path');
const core = fs.readFileSync(path.join(__dirname, '../illustrator/bridge-core.js'), 'utf8');
const context = {};
vm.createContext(context); vm.runInContext(core, context);
const bridge = context.EZPilot;
const binary = Array.from({length: 256}, (_, i) => String.fromCharCode(i)).join('');
assert.equal(bridge.base64(binary), Buffer.from(binary, 'latin1').toString('base64'));
for (const text of ['', 'x', 'xy', 'xyz', 'abcd']) assert.equal(bridge.base64(text), Buffer.from(text).toString('base64'));
const json = bridge.asciiJSON({sourceKey: 'C:\\客户\\kit.ai', content: 'a"b\n'});
assert.ok(/^[\x00-\x7f]*$/.test(json));
assert.equal(bridge.parse(json).sourceKey, 'C:\\客户\\kit.ai');
assert.throws(() => bridge.parse('{"__proto__":{}}'), /Invalid key/);
function item(layer, spot) {
  return {stroked: !!spot, strokeColor: spot ? {typename:'SpotColor',spot:{name:spot}} : null,
    parent: {typename:'Layer',name:layer}};
}
assert.equal(bridge.cutType(item('thru-cut')), 'thru');
assert.equal(bridge.cutType(item('kiss cut', 'CutContour')), 'kiss');
assert.equal(bridge.cutType(item('print', 'CutContour_Kiss-cut')), 'kiss');
assert.equal(bridge.cutType(item('print', 'Brand red')), '');
assert.throws(() => bridge.cutType(item('thru-cut','CutContour_Kiss-cut')), /disagree/);
assert.throws(() => bridge.cutType(item('print','CutContour')), /Put generic/);
assert.throws(() => bridge.cutType(item('print','CutContour_unknown')), /Unrecognized/);
assert.equal(bridge.cutType({...item('thru-cut'),clipping:true}), '');
assert.throws(()=>bridge.cutType({...item('thru-cut','CutContour'),clipping:true}), /clipping mask/);
const selectedGroup={typename:'GroupItem',parent:{typename:'Layer'}};
const selectedChild={typename:'PathItem',parent:selectedGroup};
assert.equal(bridge.selectionRoots([selectedChild,selectedGroup,selectedGroup]).length,1);
assert.equal(bridge.selectionRoots([selectedChild,selectedGroup])[0],selectedGroup);
const fitDoc={pageItems:[{visibleBounds:[0,100,200,0],geometricBounds:[-1,102,201,-1]}],artboards:[{artboardRect:[0,10,10,0]}]};
const fitted=bridge.fitProductionArtboard(fitDoc,3);
assert.ok(fitted[0]<-1-14 && fitted[1]>102+14 && fitted[2]>201+14 && fitted[3]<-1-14);
assert.deepEqual(fitDoc.pageItems[0].geometricBounds,[-1,102,201,-1]);
let sent;
context.Socket = function() {
  let response = 'HTTP/1.1 200 OK\r\nContent-Length: 11\r\n\r\n{"ok":true}';
  this.eof = false;
  this.open = host => {assert.equal(host, '127.0.0.1:8765'); return true;};
  this.write = text => {sent = text; return true;};
  this.read = () => {this.eof = true; return response;};
  this.close = () => {};
};
assert.equal(bridge.http('POST','/api/illustrator/intake',{name:'客户'},'test-token').ok,true);
const body = sent.split('\r\n\r\n')[1], length = Number(/Content-Length: (\d+)/.exec(sent)[1]);
assert.equal(Buffer.byteLength(body), length);
assert.ok(sent.includes('X-EZ-Token: test-token'));
new vm.Script(fs.readFileSync(path.join(__dirname, '../illustrator/Prepare for EZ Nest.jsx'), 'utf8').replace(/^#.*$/gm, ''));
console.log('Illustrator bridge: binary transport, Unicode JSON, cut classification, conflicts, loopback HTTP and JSX syntax passed.');
const names = ['[PDF/X-4:2008]', 'Shop ONYX'];
const saved = {version:1, material:'regular', pdfPreset:'Shop ONYX', widthIn:51.5, bleedMm:0};
assert.equal(bridge.validPreferences(saved,names),true);
for (const change of [{pdfPreset:'Removed'}, {material:'chrome'}, {widthIn:NaN}, {widthIn:'51.5'}, {bleedMm:26}, {version:2}]) {
  assert.equal(bridge.validPreferences({...saved,...change},names),false);
}
let disk='', closed=0;
const prefFile={exists:true,parent:{exists:true},open:()=>true,close:()=>closed++,write:text=>{disk=text;return true;},read:()=>disk};
bridge.writePreferences(prefFile,saved);
assert.equal(bridge.readPreferences(prefFile,names).pdfPreset,'Shop ONYX');
assert.equal(closed,2);
assert.equal(bridge.readPreferences(prefFile,['Other preset']),null);
disk='{broken';assert.equal(bridge.readPreferences(prefFile,names),null);
prefFile.open=()=>false;
assert.throws(()=>bridge.writePreferences(prefFile,saved),/Cannot save/);
for(const name of ['Nest in eznest.jsx','Prepare and Nest.jsx','Nest whole document.jsx','EZ Nest Settings.jsx']) {
  new vm.Script(fs.readFileSync(path.join(__dirname,'../illustrator',name),'utf8').replace(/^#.*$/gm,''));
}
console.log('Remembered Illustrator settings: roundtrip, removed presets, corrupt files, invalid materials and save failures passed.');
// Exercise the actual JSX fast path with an Illustrator host double: no setup or
// success modal, correct preset/material, source preservation and browser launch.
const script = fs.readFileSync(path.join(__dirname,'../illustrator/Prepare for EZ Nest.jsx'),'utf8').replace(/^#.*$/gm,'');
let exportCount=0, launched=0, sourceActivated=0, intake;
const fileData = {'user/eznest/illustrator-settings.json':JSON.stringify(saved)};
function FakeFile(name) {
  if (!(this instanceof FakeFile)) return new FakeFile(name);
  this.fsName=name;this.parent={fsName:'scripts',exists:true};this.exists=name in fileData;
  this.length=10;this.open=()=>true;this.close=()=>true;
  this.read=()=>fileData[name]||'%PDF-test';this.write=text=>{fileData[name]=text;return true;};
  this.execute=()=>{assert.equal(sourceActivated,1);launched++;return true;};
}
function FakeFolder(name){this.fsName=name;this.exists=true;}
FakeFolder.userData={fsName:'user'};FakeFolder.temp={fsName:'temp'};
const layer={typename:'Layer',name:'thru-cut'};
const copied={typename:'PathItem',parent:layer,stroked:true,filled:false,geometricBounds:[0,10,10,0],visibleBounds:[0,10,10,0],translate:()=>{},move:()=>{}};
const selected={...copied,duplicate:()=>copied};
const source={saved:true,selection:[selected],fullName:{fsName:'synthetic.ai'},documentColorSpace:'CMYK',activate:()=>sourceActivated++};
const layers=[{}];layers.add=()=>({});
const production={layers,spots:{getByName:()=>({})},pageItems:[copied],artboards:[{}],
  saveAs:(file,options)=>{assert.equal(options.pDFPreset,'Shop ONYX');exportCount++;}};
const docs=[source];docs.add=()=>production;
context.File=FakeFile;context.Folder=FakeFolder;
context.$={fileName:'scripts/Prepare for EZ Nest.jsx',global:{},evalFile:()=>{}};
context.app={documents:docs,activeDocument:source,PDFPresetsList:names};
context.Window=()=>{throw Error('Unexpected setup dialog');};
context.alert=message=>{throw Error(message);};
context.SpotColor=function(){};context.PDFSaveOptions=function(){};
context.ElementPlacement={PLACEATEND:1};
bridge.http=(method,url,data)=>{if(method==='GET')return {app:'eznest',token:'test'};intake=data;return {ok:true};};
vm.runInContext(script,context);
assert.equal(exportCount,1);assert.equal(launched,1);
assert.equal(intake.material,'regular');assert.equal(intake.sets,1);assert.equal(intake.widthIn,51.5);
assert.equal(intake.bleedMm,0);
console.log('Illustrator JSX fast path: saved preset export, one set, untouched source and browser launch passed with host doubles.');
const fullSource={typename:'Document'};
const visibleLayer={typename:'Layer',visible:true,parent:fullSource};
const hiddenLayer={typename:'Layer',visible:false,parent:fullSource};
const group={typename:'GroupItem',parent:visibleLayer};
const child={typename:'PathItem',parent:group};
const hiddenItem={typename:'PathItem',parent:hiddenLayer};
const lockedItem={typename:'PathItem',locked:true,parent:visibleLayer};
fullSource.pageItems=[group,child,hiddenItem,lockedItem];
const fullRoots=bridge.documentRoots(fullSource);
assert.equal(fullRoots.length,1);assert.equal(fullRoots[0],group);
assert.equal(fullSource.selection,undefined);

