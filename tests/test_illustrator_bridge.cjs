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
