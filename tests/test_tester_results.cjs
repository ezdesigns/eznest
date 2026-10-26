const assert = require('node:assert/strict');
const {comparison, signature, feedback} = require('../tester-results.js');
const state = {id: 'private-id', savedPath: 'S:/Customer Secret',
  job: {materialName: 'private material', settings: {width: 1300, rollWidth: 1370},
    parts: [{id: 'private-piece', name: 'Secret customer', quantity: 7}],
    webOptions: {rollCost: 300, fullRollLengthMm: 30480}},
  result: {usedLength: 3048, width: 1300, placements: Array(7).fill({id:'private-piece'}), utilization: .8, elapsed: 30},
  nestSavings: {baselineLengthMm: 3657.6}};
assert.equal(comparison(state, 15).savedFt, 5);
assert.equal(comparison(state, 15).savedDollars, 15);
assert.ok(Math.abs(comparison(state).savedFt - 2) < 1e-10);
assert.ok(Math.abs(comparison(state, 8).savedFt + 2) < 1e-10);
assert.equal(comparison({...state, nestSavings: null}), null);
assert.equal(comparison({...state, job: {}}, 15).savedDollars, null);
assert.notEqual(signature(state), signature({...state, job: {...state.job, parts: [{...state.job.parts[0], quantity: 8}]}}));
assert.notEqual(signature(state), signature({...state, job: {...state.job, settings: {...state.job.settings, width: 900}}}));
const basic = feedback('1.2.3', 'Make preview larger', state, false);
assert.ok(basic.includes('1.2.3'));
assert.ok(!basic.includes('lengthFt'));
const opted = feedback('1.2.3', 'Make preview larger', state, true);
assert.ok(opted.includes('lengthFt: 10'));
assert.ok(opted.includes('placedCopies: 7'));
for (const text of [basic, opted]) for (const secret of ['private', 'Secret', 'S:/', 'rollCost']) assert.ok(!text.includes(secret));
console.log('Tester results: savings, quantities and feedback privacy passed');
