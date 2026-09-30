'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const cuts=require('../cut-mapping.js');
const profiles=require('../shop-profiles.js');
const expected=JSON.parse(fs.readFileSync(path.join(__dirname,'cut-mapping-defaults.json'),'utf8'));
assert.deepEqual(cuts.validate(cuts.defaults()),cuts.validate(expected));
const profile={...profiles.defaults()[1],cutMapping:expected};
const exported={format:'eznest.shop-profiles',version:1,profiles:[profile]};
assert.deepEqual(profiles.importProfiles(JSON.parse(JSON.stringify(exported)))[0].cutMapping,cuts.validate(expected));
for(const key of ['spot','layer']){
  const value=cuts.defaults();value.outputs.kiss[key]=value.outputs.thru[key];
  assert.throws(()=>cuts.validate(value),/different/);
}
const conflict=cuts.defaults();conflict.rules.push({...conflict.rules[0],operation:'kiss'});
assert.throws(()=>cuts.validate(conflict),/different/);
assert.equal(cuts.formatCounts({thru:1,kiss:2,contour:0}),'1 thru-cut path · 2 kiss-cut paths');
const html=fs.readFileSync(path.join(__dirname,'../production.html'),'utf8');
assert.ok(html.indexOf('/cut-mapping.js')<html.indexOf('/shop-profiles.js'));
assert.equal(html,fs.readFileSync(path.join(__dirname,'../index.html'),'utf8'));
console.log('Cut mapping defaults, profile sharing, conflict validation and count labels passed.');
