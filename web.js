'use strict';
const NS = 'http://www.w3.org/2000/svg';
const $ = id => document.getElementById(id);
let token = '';
let kits = [];
let current = null;
let busy = false;
let saving = false;
let activeSheet = 0;
let ignoreFileChange = false;

function status(message, failed) {
  const el = $('status');
  el.textContent = message || '';
  el.classList.toggle('error', !!failed);
}

async function sha256(data) {
  const digest = await crypto.subtle.digest('SHA-256', data);
  return [...new Uint8Array(digest)].map(byte => byte.toString(16).padStart(2, '0')).join('');
}

async function api(path, data) {
  const response = await fetch(path, {
    method: 'POST',
    headers: {'Content-Type': 'application/json', 'X-EZ-Token': token},
    body: JSON.stringify(data || {})
  });
  const body = await response.json();
  if (!response.ok) throw Error(body.error || 'Request failed.');
  return body;
}

function sets() {
  const count = Number($('sets').value);
  if (!Number.isInteger(count) || count < 1 || count > 100) throw Error('Sets must be a whole number from 1 to 100.');
  return count;
}

function scale() {
  return EZNQueue.unitScale($('unit').value);
}

function preset() {
  const factor = scale();
  const number = id => Number($(id).value) * factor;
  const settings = {
    width: number('width'),
    maxLength: null,
    gap: number('gap'),
    margin: number('margin'),
    seconds: Number($('seconds').value),
    rotations: $('rotations').value === 'free' ? null : $('rotations').value.split(',').map(Number),
    seed: 42
  };
  if ($('sheet').value.trim()) settings.sheetLength = Number($('sheet').value) * factor;
  if ($('cost').value.trim()) {
    settings.costPerSquareMeter = Number($('cost').value);
    settings.currency = 'USD';
  }
  const clean = EZNQueue.validatePreset({name: $('material').value, units: $('unit').value, settings});
  return {id: 'web-roll', ...clean};
}

function profileFor(entries) {
  const pdf = entries.some(entry => entry.data.format === 'pdf');
  if (!pdf) {
    return EZNProfiles.validate({
      name: 'Generic SVG handoff', rip: 'Other / manual', format: 'svg', acceptedFormats: ['svg'],
      colorMode: 'preserve', iccProfile: '', bleedMm: 0, cutSpot: '', cutLayer: '',
      registrationOwner: 'none', finishingSoftware: '', mediaOwner: 'rip', jobLogOwner: 'rip'
    });
  }
  const mapping = EZNCuts.defaults();
  mapping.genericOperation = $('generic-cut').value;
  return EZNProfiles.validate({
    name: 'PDF / CutContour', rip: 'ONYX', format: 'pdf', acceptedFormats: ['pdf', 'ai'],
    colorMode: 'preserve', iccProfile: '', bleedMm: Number($('bleed').value) || 0,
    cutSpot: 'CutContour', cutLayer: 'CutContour', registrationOwner: 'rip',
    finishingSoftware: 'GoProduce', mediaOwner: 'rip', jobLogOwner: 'rip',
    cutMapping: EZNCuts.validate(mapping)
  });
}

function namedCuts(markup) {
  const counts = {thru: 0, kiss: 0, contour: 0};
  const rules = EZNCuts.defaults().rules.filter(rule => rule.match === 'exact' && counts[rule.operation] !== undefined);
  const doc = new DOMParser().parseFromString('<svg xmlns="' + NS + '">' + markup + '</svg>', 'image/svg+xml');
  for (const node of doc.querySelectorAll('[id]')) {
    const rule = rules.find(item => item.name === node.id);
    if (rule) counts[rule.operation] += 1;
  }
  return counts;
}

function cutTotals() {
  const totals = {thru: 0, kiss: 0, contour: 0};
  for (const entry of kits) {
    if (entry.data.format === 'pdf') {
      for (const part of entry.data.parts) for (const key of Object.keys(totals)) totals[key] += part.cutCounts?.[key] || 0;
    } else {
      const counts = namedCuts(entry.data.parts.map(part => part.svg.markup).join(''));
      for (const key of Object.keys(totals)) totals[key] += counts[key];
    }
  }
  return totals;
}

function renderKit() {
  const box = $('kit');
  if (!kits.length) { box.hidden = true; renderBusy(); return; }
  const count = kits.reduce((sum, entry) => sum + entry.data.parts.reduce((n, part) => n + (part.quantity || 1), 0), 0) * sets();
  const cuts = cutTotals();
  box.hidden = false;
  $('kit-name').textContent = kits.map(entry => entry.name.replace(/\.(svg|pdf|ai)$/i, '')).join(', ');
  const warnings = kits.flatMap(entry => entry.data.warnings || []);
  $('kit-note').textContent = warnings[0] || 'Detected pieces stay with their thru-cut and kiss-cut paths.';
  const copies = Number($('sets').value) || 1;
  $('pieces').textContent = count + (count === 1 ? ' piece' : ' pieces');
  $('thru').textContent = cuts.thru ? '✓ ' + cuts.thru * copies + ' thru' : '0 thru';
  $('kiss').textContent = cuts.kiss ? '✓ ' + cuts.kiss * copies + ' kiss' : '0 kiss';
  $('fix').textContent = '0 to fix';
  renderBusy();
}

function renderBusy() {
  $('nest').disabled = busy || saving || !kits.length;
  $('nest').textContent = busy ? 'Nesting…' : (current?.released ? 'Nest a new layout' : 'Nest it');
  $('cancel').hidden = !busy;
  $('sample').disabled = busy || saving;
  $('file').disabled = busy || saving;
  if ($('lock')) $('lock').disabled = busy || saving || !current || !!current.released;
  if ($('export')) $('export').disabled = busy || saving || !current;
  for (const id of ['sets-dec', 'sets-inc']) $(id).disabled = busy || saving;
}

async function readEntry(file, index) {
  const pdf = /\.(pdf|ai)$/i.test(file.name);
  if (!pdf && !/\.svg$/i.test(file.name)) throw Error(file.name + ' is not SVG, PDF, or PDF-compatible AI.');
  if (file.size > (pdf ? 20_000_000 : 8_000_000)) throw Error(file.name + ' is over the ' + (pdf ? '20' : '8') + ' MB limit.');
  let data, revision;
  if (pdf) {
    const bytes = new Uint8Array(await file.arrayBuffer());
    let binary = '';
    for (let offset = 0; offset < bytes.length; offset += 32768) binary += String.fromCharCode(...bytes.subarray(offset, offset + 32768));
    const mapping = EZNCuts.defaults();
    mapping.genericOperation = $('generic-cut').value;
    const bleed = Number($('bleed').value);
    if (!Number.isFinite(bleed) || bleed < 0 || bleed > 25) throw Error('Existing bleed must be from 0 to 25 mm.');
    data = await api('/api/document/import', {content: btoa(binary), bleedMm: bleed, cutSpot: 'CutContour', cutMapping: EZNCuts.validate(mapping)});
    data.reviewed = true;
    revision = data.documentId;
  } else {
    const text = await file.text();
    data = EZNSVG.importSVG(text, file.name);
    data.format = 'svg';
    revision = await sha256(new TextEncoder().encode(text));
  }
  return {
    id: 'web-' + revision.slice(0, 18) + '-' + index, name: file.name, sourceFile: file.name, revision,
    origin: 'files', role: 'required', customer: '', order: '', kit: '', materialId: 'web-roll',
    sets: sets(), selected: true, status: 'ready', data
  };
}

async function importFiles(fileList) {
  const files = [...fileList];
  if (!files.length || busy || saving) return;
  const pdf = files.some(file => /\.(pdf|ai)$/i.test(file.name));
  const svg = files.some(file => /\.svg$/i.test(file.name));
  if (pdf && svg) throw Error('Nest SVG files in one batch and PDF files in another. That keeps the original artwork.');
  status('Reading ' + files.length + (files.length === 1 ? ' file…' : ' files…'));
  const entries = [];
  for (const [index, file] of files.entries()) entries.push(await readEntry(file, index));
  kits = entries;
  renderKit();
  status(kits.length + (kits.length === 1 ? ' file ready.' : ' files ready.') + ' Set the roll, then nest.');
}

function placedCuts(state) {
  const summary = state.manifest?.cutSummary;
  if (summary && (summary.thru || summary.kiss || summary.contour)) return summary;
  const totals = {thru: 0, kiss: 0, contour: 0};
  const parts = new Map((state.job.parts || []).map(part => [part.id, part]));
  for (const placement of state.result.placements) {
    const markup = parts.get(placement.id)?.svg?.markup;
    if (!markup) continue;
    const counts = namedCuts(markup);
    for (const key of Object.keys(totals)) totals[key] += counts[key];
  }
  return totals;
}

function sheetList(state) {
  return state.manifest?.sheets?.length ? state.manifest.sheets : [{index: 0, offset: 0, usedLength: state.result.usedLength}];
}

function emphasizeCuts(svg) {
  for (const node of svg.querySelectorAll('[id]')) {
    if (/kiss-cut/i.test(node.id)) {
      node.setAttribute('stroke', '#D92F00');
      node.setAttribute('stroke-dasharray', '1.6 1.1');
      node.setAttribute('stroke-width', '0.7');
    } else if (/thru-cut/i.test(node.id)) {
      node.setAttribute('stroke', '#182a25');
      node.setAttribute('stroke-width', '0.7');
      node.removeAttribute('stroke-dasharray');
    }
  }
}

function documentPreview(state) {
  const out = document.createElementNS(NS, 'svg');
  const parts = new Map(state.job.parts.map(part => [part.id, part]));
  state.result.placements.forEach((placement, index) => {
    const part = parts.get(placement.id);
    const group = document.createElementNS(NS, 'g');
    group.setAttribute('id', 'ez-part-' + (index + 1));
    group.setAttribute('transform', `translate(${placement.x} ${placement.y}) rotate(${placement.rotation})`);
    if (part.preview) {
      const image = document.createElementNS(NS, 'image');
      image.setAttribute('href', part.preview);
      image.setAttribute('width', part.previewWidth);
      image.setAttribute('height', part.previewHeight);
      group.append(image);
    }
    out.append(group);
  });
  return out;
}

function renderPreview(index) {
  activeSheet = index;
  const result = current.result;
  const sheets = sheetList(current);
  const sheet = sheets[index] || sheets[0];
  const art = current.job.documentSources ? documentPreview(current) : EZNSVG.buildSVG(current.job, result);
  if (!current.job.documentSources) emphasizeCuts(art);
  const frame = $('preview');
  frame.replaceChildren();
  frame.setAttribute('viewBox', `-2 ${sheet.offset - 2} ${result.width + 4} ${sheet.usedLength + 4}`);
  // A 54 in roll with a short nest would otherwise draw as a thin strip.
  // Scale from the sheet's short side so pieces stay large enough to see, and scroll the rest.
  const shortSide = Math.min(result.width, sheet.usedLength);
  const pixelsPerMm = Math.min(6, Math.max(1.6, 240 / shortSide));
  frame.setAttribute('width', String((result.width + 4) * pixelsPerMm));
  frame.setAttribute('height', String((sheet.usedLength + 4) * pixelsPerMm));
  const background = document.createElementNS(NS, 'rect');
  background.setAttribute('x', '0');
  background.setAttribute('y', String(sheet.offset));
  background.setAttribute('width', result.width);
  background.setAttribute('height', sheet.usedLength);
  background.setAttribute('fill', '#ffffff');
  background.setAttribute('stroke', '#c8c8c4');
  frame.append(background);
  for (const child of [...art.children]) frame.append(child);
  for (const [tabIndex, button] of [...$('sheet-tabs').children].entries()) button.setAttribute('aria-pressed', String(tabIndex === index));
}

function showLock(state) {
  const locked = !!state.released;
  $('locked').hidden = !locked;
  $('layout-id').value = locked ? state.id : '';
  $('layout-hash').value = locked ? (state.sha256 || '') : '';
  $('export').textContent = locked ? 'Export again' : 'Export print file';
  $('out-title').textContent = locked ? 'Layout locked' : 'Sheet ready';
}

function showResult(state) {
  current = state;
  const result = state.result;
  const sheets = sheetList(state);
  const feet = result.usedLength / 304.8;
  $('output').hidden = false;
  $('length').textContent = feet.toFixed(2) + ' ft';
  $('length-exact').textContent = result.usedLength.toFixed(1) + ' mm on a ' + result.width.toFixed(1) + ' mm roll';
  $('waste').textContent = ((1 - result.utilization) * 100).toFixed(1) + '%';
  $('sheets').textContent = String(sheets.length);
  const summary = placedCuts(state);
  const pieces = state.manifest.totalPieces;
  $('checks').textContent = pieces + (pieces === 1 ? ' piece' : ' pieces') + (summary.thru ? ' · ' + summary.thru + ' thru' : '') + (summary.kiss ? ' · ' + summary.kiss + ' kiss' : '');
  const cost = state.manifest.materialCost;
  $('cost-line').textContent = cost ? '≈ ' + cost.currency + ' ' + cost.total.toFixed(2) + ' material' : '';
  const tabs = $('sheet-tabs');
  tabs.replaceChildren();
  tabs.hidden = sheets.length < 2;
  sheets.forEach((sheet, index) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = 'Sheet ' + (index + 1);
    button.addEventListener('click', () => renderPreview(index));
    tabs.append(button);
  });
  showLock(state);
  renderPreview(Math.min(activeSheet, sheets.length - 1));
  renderBusy();
}

async function poll() {
  if (!busy) return;
  try {
    const state = await (await fetch('/api/state')).json();
    if (state.status === 'running') { setTimeout(poll, 400); return; }
    busy = false;
    if (state.status === 'ready' && state.manifest) {
      showResult(state);
      status(state.note || 'Layout ready. Lock it when this nest is the one you want to print.');
    } else status(state.error || 'Nesting stopped. Change the roll or the file and try again.', state.status === 'error');
  } catch (error) {
    busy = false;
    status(error.message, true);
  }
  renderBusy();
}

async function nest() {
  if (busy || saving || !kits.length) return;
  try {
    for (const entry of kits) entry.sets = sets();
    const job = EZNQueue.compose(kits, preset(), 'combined');
    job.outputProfile = profileFor(kits);
    job.settings.seed = 42;
    busy = true;
    current = null;
    $('output').hidden = true;
    renderBusy();
    status('Nesting on ' + $('width').value + ' ' + $('unit').value + '…');
    await api('/api/solve', job);
    setTimeout(poll, 300);
  } catch (error) {
    busy = false;
    renderBusy();
    status(error.message, true);
  }
}

function sheetMap(state) {
  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('xmlns', NS);
  svg.setAttribute('width', state.result.width + 'mm');
  svg.setAttribute('height', state.result.usedLength + 'mm');
  svg.setAttribute('viewBox', `0 0 ${state.result.width} ${state.result.usedLength}`);
  const parts = new Map(state.job.parts.map(part => [part.id, part]));
  for (const placement of state.result.placements) {
    const part = parts.get(placement.id);
    const shape = document.createElementNS(NS, 'polygon');
    shape.setAttribute('points', part.points.map(point => point.join(',')).join(' '));
    shape.setAttribute('transform', `translate(${placement.x} ${placement.y}) rotate(${placement.rotation})`);
    shape.setAttribute('fill', 'none');
    shape.setAttribute('stroke', '#182a25');
    shape.setAttribute('stroke-width', '0.4');
    svg.append(shape);
  }
  return svg;
}

async function lock() {
  if (!current || current.released || busy || saving) return current;
  saving = true;
  renderBusy();
  try {
    const artwork = current.job.documentSources ? null : EZNSVG.serialize(EZNSVG.buildSVG(current.job, current.result));
    const released = await api('/api/release', {id: current.id, artwork, map: EZNSVG.serialize(sheetMap(current))});
    current.released = true;
    current.sha256 = released.sha256;
    current.deliveryCompleted = released.deliveryCompleted === true;
    showLock(current);
    status('Locked ' + released.id.slice(0, 8) + '. Exporting again returns this same file.');
    return current;
  } finally {
    saving = false;
    renderBusy();
  }
}

async function exportFile() {
  if (!current || busy || saving) return;
  try {
    if (!current.released) await lock();
    else await api('/api/release', {id: current.id, map: EZNSVG.serialize(sheetMap(current))});
    saving = true;
    renderBusy();
    const response = await fetch('/api/batch/' + current.id);
    if (!response.ok) throw Error('The locked file is saved, but the download failed. Export again.');
    const bytes = await response.arrayBuffer();
    const hash = await sha256(bytes);
    if (current.sha256 && hash !== current.sha256) throw Error('The download does not match the locked layout.');
    const link = document.createElement('a');
    link.href = URL.createObjectURL(new Blob([bytes], {type: 'application/zip'}));
    link.download = 'eznest-' + current.id.slice(0, 8) + '.zip';
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(link.href), 1000);
    status('Downloaded eznest-' + current.id.slice(0, 8) + '.zip.');
  } catch (error) {
    status(error.message, true);
  } finally {
    saving = false;
    renderBusy();
  }
}

function convertUnit(next) {
  const previous = $('unit').dataset.current || next;
  const factor = EZNQueue.unitScale(previous) / EZNQueue.unitScale(next);
  for (const id of ['width', 'gap', 'margin', 'sheet']) {
    if (!$(id).value.trim()) continue;
    $(id).value = String(Number((Number($(id).value) * factor).toFixed(4)));
  }
  $('unit').dataset.current = next;
  for (const node of document.querySelectorAll('[data-unit]')) node.textContent = next;
}

function applyMaterial() {
  if ($('material').value === '54 in roll') { $('unit').value = 'in'; convertUnit('in'); $('width').value = '54'; }
  if ($('material').value === '53 in roll') { $('unit').value = 'in'; convertUnit('in'); $('width').value = '53'; }
}

function watchWidth() {
  const width = $('width').value;
  $('material').value = $('unit').value === 'in' && width === '54' ? '54 in roll' : $('unit').value === 'in' && width === '53' ? '53 in roll' : 'Custom roll';
}

async function boot() {
  const session = await (await fetch('/api/session')).json();
  token = session.token;
  const state = await (await fetch('/api/state')).json();
  if (state.status === 'running') { busy = true; status('Nesting…'); renderBusy(); setTimeout(poll, 300); }
  else if (state.status === 'ready' && state.manifest) {
    showResult(state);
    status(state.released ? 'This locked layout was restored on this computer.' : 'Restored the last layout. Lock it to keep this file.');
  } else status('Drop a kit. The nest runs on this computer.');
  renderBusy();
}

document.addEventListener('DOMContentLoaded', () => {
  $('file').addEventListener('change', async event => {
    if (ignoreFileChange) { ignoreFileChange = false; event.target.value = ''; return; }
    try { await importFiles(event.target.files); } catch (error) { status(error.message, true); }
    finally { event.target.value = ''; }
  });
  $('sample').addEventListener('click', async () => {
    try {
      const response = await fetch('/sample-artwork.svg');
      if (!response.ok) throw Error('The sample artwork is missing.');
      const text = await response.text();
      await importFiles([new File([text], 'sample-artwork.svg', {type: 'image/svg+xml'})]);
    } catch (error) { status(error.message, true); }
  });
  document.addEventListener('dragover', event => { event.preventDefault(); document.body.classList.add('dragging'); });
  document.addEventListener('dragleave', event => { if (!event.relatedTarget) document.body.classList.remove('dragging'); });
  document.addEventListener('drop', async event => {
    event.preventDefault();
    document.body.classList.remove('dragging');
    ignoreFileChange = true;
    try { await importFiles(event.dataTransfer.files); } catch (error) { status(error.message, true); }
  });
  $('sets-dec').addEventListener('click', () => { $('sets').value = String(Math.max(1, sets() - 1)); renderKit(); });
  $('sets-inc').addEventListener('click', () => { $('sets').value = String(Math.min(100, sets() + 1)); renderKit(); });
  $('sets').addEventListener('change', () => { try { sets(); renderKit(); } catch (error) { $('sets').value = '1'; status(error.message, true); } });
  $('unit').addEventListener('change', () => convertUnit($('unit').value));
  $('material').addEventListener('change', applyMaterial);
  $('width').addEventListener('change', watchWidth);
  $('nest').addEventListener('click', nest);
  $('cancel').addEventListener('click', async () => { try { await api('/api/cancel', {}); } catch (error) { status(error.message, true); } });
  $('lock').addEventListener('click', () => lock().catch(error => status(error.message, true)));
  $('export').addEventListener('click', exportFile);
  boot().catch(error => status(error.message, true));
});
