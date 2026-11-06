const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const crypto = require('node:crypto');
const source = fs.readFileSync(path.join(__dirname, '../browser-crypto.js'), 'utf8');

async function check() {
  for (const native of [false, true]) {
    let randomCalls = 0;
    const context = vm.createContext({crypto: native ? crypto.webcrypto : {
      getRandomValues(bytes) { randomCalls++; return crypto.webcrypto.getRandomValues(bytes); },
    }});
    vm.runInContext(source, context);
    const api = context.EZNCrypto;
    const ids = new Set(Array.from({length: 100}, () => api.randomUUID()));
    assert.equal(ids.size, 100);
    for (const id of ids) assert.match(id, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    if (!native) assert.equal(randomCalls, 100, 'Fallback IDs must use cryptographic randomness');
    for (const length of [0,1,3,55,56,63,64,65,119,120,127,128,129,1000,1048576]) {
      const bytes = crypto.randomBytes(length);
      const expected = crypto.createHash('sha256').update(bytes).digest('hex');
      assert.equal(await api.sha256(bytes), expected, `SHA-256 length ${length}, native=${native}`);
      const padded = Buffer.concat([Buffer.from('ignore'), bytes, Buffer.from('ignore')]);
      const view = new DataView(padded.buffer, padded.byteOffset + 6, length);
      assert.equal(await api.sha256(view), expected, 'Only the selected view is hashed');
    }
    const text = Buffer.from('員工共用庫存 🖨️');
    assert.equal(await api.sha256(text.buffer.slice(text.byteOffset, text.byteOffset + text.byteLength)), crypto.createHash('sha256').update(text).digest('hex'));
  }
  console.log('Browser UUIDs and SHA-256 match Node with and without secure-context APIs.');
}
check().catch(error => { console.error(error); process.exitCode = 1; });
