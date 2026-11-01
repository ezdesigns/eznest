'use strict';
// Full mode uses the same shop ledger and shelf component as simple mode.
let fullInventory = {materials: [], reservations: []};
let fullInventoryReady = false, fullInventoryBusy = false, fullInventoryGeneration = 0;
const defaultRollProfile = {
  'preset-name': '', unit: 'in', roll: '54', width: '51.5', gap: '0.12', margin: '0.25',
  'mark-margin': '0.4', rotations: '0,90,180,270', sheet: '60', 'print-layout': 'sections',
  'auto-bleed': '0', bleed: '0', cost: '', 'roll-length': '', 'roll-cost': '',
  'available-length': '', 'low-stock': '', drawMarks: false
};
async function refreshFullInventory() {
  const generation = ++fullInventoryGeneration;
  try {
    const data = await api('/api/materials');
    if (generation !== fullInventoryGeneration) return;
    fullInventory = data; fullInventoryReady = true;
  } catch (error) { fullInventoryReady = false; throw error; }
}
async function mutateFullInventory(path, payload) {
  ++fullInventoryGeneration;
  try {
    const data = await api(path, payload);
    ++fullInventoryGeneration;
    fullInventory = data; fullInventoryReady = true;
    return data;
  } catch (error) { ++fullInventoryGeneration; throw error; }
}
function chooseStockForQueue(id) {
  if (busy || saving || importing) { status('Finish the current operation before changing material.', true); return; }
  const item = fullInventory.materials.find(row => row.id === id);
  if (!item) return;
  if (item.availableMm === 0) { status('This roll is out of stock. Choose another roll.', true); return; }
  const p = item.profile, factor = EZNQueue.unitScale(p.unit);
  const previous = preferences.presets.find(row => row.inventoryId === id);
  const converted = EZNQueue.validatePreset({name: p['preset-name'], units: p.unit, settings: {
    width: Number(p.width) * factor, maxLength: null, gap: Number(p.gap) * factor,
    margin: (Number(p.margin) + Number(p['mark-margin'])) * factor,
    edgeMargin: Number(p.margin) * factor, markMargin: Number(p['mark-margin']) * factor,
    seconds: previous?.settings.seconds || 5,
    rotations: p.rotations === 'free' ? null : p.rotations.split(',').map(Number),
    rollWidth: Number(p.roll) * factor, continuous: p['print-layout'] === 'continuous',
    ...(p.sheet ? {sheetLength: Number(p.sheet) * factor} : {}),
    ...(pricedMaterial({...p}) == null ? {} : {costPerSquareMeter: pricedMaterial({...p})})
  }});
  const preset = {...converted, id: previous?.id || 'inventory-' + crypto.randomUUID(), inventoryId: id};
  if (previous) preferences.presets[preferences.presets.indexOf(previous)] = preset;
  else preferences.presets.push(preset);
  preferences.active = preset.id;
  for (const entry of activeEntries()) if (entry.selected) entry.materialId = preset.id;
  renderPresets(); invalidate();
  status('Using ' + p['preset-name'] + '. Nest to apply this material.');
}
const fullInventoryPanel = EZNInventoryPanel.create({
  get profiles() { return Object.fromEntries(fullInventory.materials.map(item => [item.id, item.profile])); },
  get inventory() { return fullInventory; }, get ready() { return fullInventoryReady; },
  get busy() { return fullInventoryBusy || busy || saving || importing; },
  set busy(value) { fullInventoryBusy = value; },
  get current() { return current; }, selectedId: () => activePreset().inventoryId || '',
  defaults: () => ({...defaultRollProfile}), validate: validateMaterial,
  refresh: refreshFullInventory, mutate: mutateFullInventory, choose: chooseStockForQueue,
  updated(id) { if (activePreset().inventoryId === id) chooseStockForQueue(id); },
  removed(id) {
    const selected = activePreset().inventoryId === id;
    preferences.presets = preferences.presets.filter(row => row.inventoryId !== id);
    if (selected) preferences.active = preferences.presets[0].id;
    renderPresets(); invalidate();
  }
});
