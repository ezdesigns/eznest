// Boundary policy fixtures; live Illustrator validation remains separate.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const code=fs.readFileSync(require('node:path').join(__dirname,'fixtures/legacy-host-boundary.jsx'),'utf8').replace(/^#.*$/gm,'');
const context={File:()=>({parent:{parent:{fsName:'.'}}}),$:{fileName:'host.jsx'}};
vm.createContext(context);vm.runInContext(code,context);
const resolve=context.EZN.boundary;
function path(name='',extra={}){return {typename:'PathItem',name,stroked:false,...extra};}
function group(children,clipped=false){const node={typename:'GroupItem',pageItems:children,clipped};children.forEach(c=>c.parent=node);return node;}
const a=path('EZN_BOUNDARY'),b=path('CutContour_Kiss-cut');
assert.equal(resolve(group([a,b])).path,a,'Explicit production boundary must outrank a smaller trim path');
const mask=path('',{clipping:true});
assert.equal(resolve(group([mask,path('decoration')],true)).path,mask,'Outer mask bounds the complete clipped part');
const spot=path('',{stroked:true,strokeColor:{typename:'SpotColor',spot:{name:'CutContour_Kiss-cut'}}});
assert.equal(resolve(group([group([spot]),path('print')])).path,spot,'Nested named spot cut is associated with the whole selected group');
assert.throws(()=>resolve(group([path('CutContour_a'),path('CutContour_b')])),/Multiple cut contours/);
assert.throws(()=>resolve(group([path('EZN_BOUNDARY'),path('EZN_BOUNDARY')])),/More than one/);
assert.throws(()=>resolve(group([path('decoration'),path('background')])),/No unambiguous/);
assert.throws(()=>resolve({typename:'CompoundPathItem',pathItems:[]}),/Compound boundaries/);
console.log('7 boundary-policy checks passed');
