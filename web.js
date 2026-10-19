'use strict';
const NS = 'http://www.w3.org/2000/svg';
const $ = id => document.getElementById(id);
const PREF = 'eznest-placeholders';
let token = '';
let kits = [];
let current = null;
let busy = false;
let saving = false;
let activeSheet = 0;
let ignoreFileChange = false;
let blockReason = '';

function status(message, failed) {
  const el = $('status');
  el.textContent = message || '';
  el.classList.toggle('error', !!failed);
}

function prefs() {
  try { return JSON.parse(localStorage.getItem(PREF) || '{}'); }
  catch { return {}; }
}

function savePrefs(patch) {
  localStorage.setItem(PREF, JSON.stringify({...prefs(), ...patch}));
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
    seconds: Number($('seconds').value) || 5,
    rotations: $('rotations').value === 'free' ? null : $('rotations').value.split(',').map(Number),
    seed: 42
  };
  if ($('sheet').value.trim()) settings.sheetLength = Number($('sheet').value) * factor;
  if ($('cost').value.trim()) {
    settings.costPerSquareMeter = Number($('cost').value);
    settings.currency = 'USD';
  }
  const name = ($('preset-name').value || $('material').selectedOptions[0].textContent).trim();
  const clean = EZNQueue.validatePreset({name, units: $('unit').value, settings});
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

function unresolved() {
  return kits.some(entry => entry.unresolved);
}

function renderKit() {
  const box = $('kit');
  if (!kits.length) { box.hidden = true; renderActions(); return; }
  const count = kits.reduce((sum, entry) => sum + entry.data.parts.reduce((n, part) => n + (part.quantity || 1), 0), 0) * sets();
  const cuts = cutTotals();
  box.hidden = false;
  $('kit-name').textContent = kits.map(entry => entry.name.replace(/\.(svg|pdf|ai)$/i, '')).join(', ');
  const warnings = kits.flatMap(entry => entry.data.warnings || []);
  $('kit-note').textContent = warnings[0] || '';
  $('kit-note').hidden = !warnings[0];
  const copies = Number($('sets').value) || 1;
  $('pieces').textContent = count + (count === 1 ? ' piece' : ' pieces');
  $('thru').textContent = cuts.thru ? cuts.thru * copies + ' thru' : '0 thru';
  $('kiss').textContent = cuts.kiss ? cuts.kiss * copies + ' kiss' : '0 kiss';
  const fix = unresolved() ? (cuts.contour || 1) * copies : 0;
  $('fix').textContent = fix ? fix + ' to fix' : '0 to fix';
  renderActions();
}

function inputIssue() {
  const width = Number($('width').value);
  const gap = Number($('gap').value);
  const margin = Number($('margin').value);
  const count = Number($('sets').value);
  if (!Number.isFinite(width) || width <= 0) return 'Enter a roll width';
  if (!Number.isFinite(gap) || gap < 0) return 'Check the spacing';
  if (!Number.isFinite(margin) || margin < 0) return 'Check the edge margin';
  if (!Number.isInteger(count) || count < 1 || count > 100) return 'Sets must be from 1 to 100';
  return '';
}

function pieceIssue(state) {
  if (!state?.manifest) return '';
  const expected = (state.manifest.jobs || []).reduce((sum, job) => sum + (job.expected || 0), 0);
  const placed = state.manifest.totalPieces;
  if (expected && placed < expected) return placed + ' of ' + expected + ' pieces · missing pieces';
  if (state.manifest.complete === false) return 'Incomplete layout';
  return '';
}

function setNum(id, value, unit) {
  const node = $(id);
  const num = node.querySelector('.num');
  const unitNode = node.querySelector('.unit');
  if (!num) { node.textContent = value; return; }
  num.textContent = value;
  if (unitNode && unit != null) unitNode.textContent = unit;
}

function lengthOver(state) {
  const raw = $('sheet').value.trim();
  if (!raw || !state?.result) return false;
  const limit = Number(raw) * scale();
  return Number.isFinite(limit) && limit > 0 && state.result.usedLength > limit;
}

function clearReadout() {
  setNum('length', '–', 'ft');
  setNum('waste', '–', '%');
  setNum('sheets', '–');
  $('length').classList.remove('over');
  $('readout').classList.add('pending');
  $('length-exact').textContent = 'of ' + ($('width').value || '–') + ' ' + $('unit').value + ' roll';
  $('cost-line').textContent = '';
  $('checks').textContent = '';
}

function cutProblem() {
  if (!unresolved()) return null;
  const names = [];
  let count = 0;
  const copies = Number($('sets').value) || 1;
  for (const entry of kits) {
    if (!entry.unresolved) continue;
    for (const part of entry.data.parts || []) {
      const found = part.cutCounts?.contour || 0;
      if (!found) continue;
      count += found * copies;
      names.push(part.name || part.id);
    }
  }
  if (!count) return {line: 'Cuts have no type', detail: 'Choose thru or kiss. Enter does nothing until this is resolved.'};
  const noun = count === 1 ? 'cut has no type' : 'cuts have no type';
  return {line: count + ' ' + noun, detail: names.join(', ') + ' use plain CutContour.'};
}

function showScreen(name) {
  document.body.dataset.step = name;
  const nesting = name === 'nest';
  const idle = name === 'drop';
  $('empty').hidden = !idle;
  $('sheet-frame').hidden = idle;
  $('legend').hidden = idle || nesting;
  $('gate').hidden = idle;
  $('cancel').hidden = !nesting;
  $('export').hidden = nesting;
  $('download-only').hidden = nesting;
  $('sent-panel').hidden = name !== 'sent';
  $('again').hidden = idle || nesting || !kits.length;
  $('improve').hidden = name !== 'check';
  $('choice').hidden = name !== 'blocked' || !unresolved();
  if (idle) {
    clearReadout();
    $('block-detail').hidden = true;
    $('sheet-tabs').hidden = true;
    $('preview').replaceChildren();
  }
}

function renderActions() {
  const badInput = inputIssue();
  const missing = current && current.result ? pieceIssue(current) : '';
  const cuts = current && current.result ? cutProblem() : null;
  const tooLong = current && current.result && lengthOver(current) ? 'Material is over the sheet length' : '';
  const step = document.body.dataset.step;
  const sent = step === 'sent' && current && current.released;
  $('nest').disabled = busy || saving || !kits.length || !!badInput;
  $('again').disabled = $('nest').disabled;
  $('length').classList.toggle('over', !!(current && current.result && lengthOver(current)));
  if (sent) {
    $('export').disabled = saving;
    $('download-only').disabled = saving;
    $('undo').hidden = !($('allow-undo').checked && current.savedPath);
    return;
  }
  const actionable = step !== 'drop' && step !== 'nest';
  const reason = blockReason || missing || (cuts ? cuts.line : '') || tooLong || (actionable ? badInput : '');
  const blocked = !!reason;
  $('export').disabled = busy || saving || blocked || !current || !current.result;
  $('download-only').disabled = $('export').disabled;
  $('undo').hidden = true;
  if (!actionable) return;
  if (reason) {
    document.body.dataset.step = 'blocked';
    $('gate').hidden = false;
    $('gate').textContent = reason;
    $('gate').className = 'gate problem';
    $('block-detail').hidden = !(cuts && cuts.detail);
    $('block-detail').textContent = cuts ? cuts.detail : '';
    $('choice').hidden = !cuts;
    $('again').hidden = false;
    $('improve').hidden = true;
    return;
  }
  if (current && current.manifest) {
    document.body.dataset.step = 'check';
    const placed = current.manifest.totalPieces;
    $('gate').hidden = false;
    $('gate').textContent = '✓ Ready · ' + placed + ' of ' + placed + ' pieces · cuts OK';
    $('gate').className = 'gate';
    $('block-detail').hidden = true;
    $('choice').hidden = true;
    $('again').hidden = false;
    $('improve').hidden = false;
  }
}

function sheetList(state) {
  return state.manifest?.sheets?.length ? state.manifest.sheets : [{index: 0, offset: 0, usedLength: state.result.usedLength}];
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

function emphasizeCuts(svg) {
  for (const node of svg.querySelectorAll('[id]')) {
    node.setAttribute('vector-effect', 'non-scaling-stroke');
    if (/kiss-cut/i.test(node.id)) {
      node.setAttribute('stroke', '#00B7FF');
      node.setAttribute('stroke-dasharray', '8 6');
      node.setAttribute('stroke-width', '3');
    } else if (/thru-cut/i.test(node.id)) {
      node.setAttribute('stroke', '#E6007E');
      node.setAttribute('stroke-width', '3');
      node.removeAttribute('stroke-dasharray');
    } else if (/regmark|reg-mark/i.test(node.id)) {
      node.setAttribute('stroke', '#111111');
      node.setAttribute('stroke-width', '3');
      node.removeAttribute('stroke-dasharray');
    }
  }
}

function stroke(node, color, dashed) {
  node.setAttribute('fill', 'none');
  node.setAttribute('stroke', color);
  node.setAttribute('stroke-width', '3');
  node.setAttribute('vector-effect', 'non-scaling-stroke');
  if (dashed) node.setAttribute('stroke-dasharray', '8 6');
  else node.removeAttribute('stroke-dasharray');
}

function documentPreview(state) {
  const out = document.createElementNS(NS, 'svg');
  const parts = new Map(state.job.parts.map(part => [part.id, part]));
  state.result.placements.forEach((placement, index) => {
    const part = parts.get(placement.id);
    const group = document.createElementNS(NS, 'g');
    group.setAttribute('transform', `translate(${placement.x} ${placement.y}) rotate(${placement.rotation})`);
    if (part.preview) {
      const image = document.createElementNS(NS, 'image');
      image.setAttribute('href', part.preview);
      image.setAttribute('width', part.previewWidth);
      image.setAttribute('height', part.previewHeight);
      group.append(image);
    }
    const counts = part.cutCounts || {};
    if (part.points && (counts.thru || counts.kiss)) {
      const outline = document.createElementNS(NS, 'polygon');
      outline.setAttribute('points', part.points.map(point => point.join(',')).join(' '));
      stroke(outline, counts.thru ? '#E6007E' : '#00B7FF', !counts.thru);
      group.append(outline);
    }
    group.dataset.index = String(index + 1);
    out.append(group);
  });
  return out;
}

function addHatch(frame) {
  const defs = document.createElementNS(NS, 'defs');
  const pattern = document.createElementNS(NS, 'pattern');
  pattern.setAttribute('id', 'ez-waste');
  pattern.setAttribute('patternUnits', 'userSpaceOnUse');
  pattern.setAttribute('width', '6');
  pattern.setAttribute('height', '6');
  pattern.setAttribute('patternTransform', 'rotate(45)');
  const backing = document.createElementNS(NS, 'rect');
  backing.setAttribute('width', '6');
  backing.setAttribute('height', '6');
  backing.setAttribute('fill', '#9a9a9a');
  const line = document.createElementNS(NS, 'line');
  line.setAttribute('x1', '0');
  line.setAttribute('y1', '0');
  line.setAttribute('x2', '0');
  line.setAttribute('y2', '6');
  line.setAttribute('stroke', '#7d7d7d');
  line.setAttribute('stroke-width', '2');
  pattern.append(backing, line);
  defs.append(pattern);
  frame.append(defs);
}

function addRuler(frame, sheet, width) {
  const inch = 25.4;
  const scale = Math.max(width, sheet.usedLength) / 42;
  const ruler = document.createElementNS(NS, 'g');
  ruler.setAttribute('id', 'ez-ruler');
  const top = sheet.offset;
  const across = Math.floor(width / inch);
  for (let mark = 0; mark <= across; mark++) {
    const x = mark * inch;
    const tick = document.createElementNS(NS, 'line');
    tick.setAttribute('x1', String(x));
    tick.setAttribute('x2', String(x));
    tick.setAttribute('y1', String(top - (mark % 6 === 0 ? scale * .7 : scale * .35)));
    tick.setAttribute('y2', String(top));
    tick.setAttribute('stroke', '#111');
    tick.setAttribute('stroke-width', String(mark % 6 === 0 ? scale * .08 : scale * .04));
    ruler.append(tick);
    if (mark % 6 === 0 || mark === across) {
      const label = document.createElementNS(NS, 'text');
      label.setAttribute('x', String(x));
      label.setAttribute('y', String(top - scale * .85));
      label.setAttribute('fill', '#111');
      label.setAttribute('font-size', String(scale));
      label.setAttribute('font-family', 'Rajdhani, sans-serif');
      label.setAttribute('text-anchor', mark === 0 ? 'start' : 'middle');
      label.textContent = String(mark) + '"';
      ruler.append(label);
    }
  }
  const down = Math.max(0, Math.floor(sheet.usedLength / inch));
  for (let mark = 0; mark <= down; mark++) {
    const y = top + mark * inch;
    const tick = document.createElementNS(NS, 'line');
    tick.setAttribute('x1', String(-(mark % 6 === 0 ? scale * .7 : scale * .35)));
    tick.setAttribute('x2', '0');
    tick.setAttribute('y1', String(y));
    tick.setAttribute('y2', String(y));
    tick.setAttribute('stroke', '#111');
    tick.setAttribute('stroke-width', String(mark % 6 === 0 ? scale * .08 : scale * .04));
    ruler.append(tick);
  }
  const feet = document.createElementNS(NS, 'text');
  feet.setAttribute('x', String(-scale));
  feet.setAttribute('y', String(top + sheet.usedLength));
  feet.setAttribute('fill', '#111');
  feet.setAttribute('font-size', String(scale));
  feet.setAttribute('font-family', 'Rajdhani, sans-serif');
  feet.setAttribute('text-anchor', 'end');
  feet.textContent = (sheet.usedLength / 304.8).toFixed(2) + ' ft';
  ruler.append(feet);
  frame.append(ruler);
}

function fit(frame, width, height) {
  frame.setAttribute('viewBox', `0 0 ${width} ${height}`);
  frame.style.aspectRatio = width + ' / ' + height;
  frame.removeAttribute('width');
  frame.removeAttribute('height');
}

function badPartIds(state) {
  if (!unresolved() || !state?.job) return [];
  return state.job.parts.filter(part => (part.cutCounts?.contour || 0) > 0).map(part => part.id);
}

function renderSheet(frame, state, index) {
  const result = state.result;
  const sheets = sheetList(state);
  const sheet = sheets[index] || sheets[0];
  const art = state.job.documentSources ? documentPreview(state) : EZNSVG.buildSVG(state.job, result);
  if (!state.job.documentSources) emphasizeCuts(art);
  frame.replaceChildren();
  const pad = Math.max(result.width, sheet.usedLength) / 18;
  const x = -pad;
  const y = sheet.offset - pad;
  const w = result.width + pad + 2;
  const h = sheet.usedLength + pad + 2;
  fit(frame, w, h);
  frame.setAttribute('viewBox', `${x} ${y} ${w} ${h}`);
  addHatch(frame);
  const roll = document.createElementNS(NS, 'rect');
  roll.setAttribute('x', '0');
  roll.setAttribute('y', String(sheet.offset));
  roll.setAttribute('width', result.width);
  roll.setAttribute('height', sheet.usedLength);
  roll.setAttribute('fill', 'url(#ez-waste)');
  roll.setAttribute('stroke', '#111');
  roll.setAttribute('stroke-width', '0.6');
  frame.append(roll);
  addRuler(frame, sheet, result.width);
  for (const child of [...art.children]) frame.append(child);
  const parts = new Map(state.job.parts.map(part => [part.id, part]));
  let number = 1;
  for (const placement of result.placements.filter(item => (item.sheet || 0) === (sheet.index || 0))) {
    if (!badPartIds(state).includes(placement.id)) continue;
    const part = parts.get(placement.id);
    if (!part?.points) continue;
    const halo = document.createElementNS(NS, 'polygon');
    halo.setAttribute('points', part.points.map(point => point.join(',')).join(' '));
    halo.setAttribute('transform', `translate(${placement.x} ${placement.y}) rotate(${placement.rotation})`);
    stroke(halo, '#D92F00', false);
    frame.append(halo);
    const label = document.createElementNS(NS, 'text');
    label.setAttribute('x', String(placement.x));
    label.setAttribute('y', String(placement.y));
    label.setAttribute('fill', '#D92F00');
    label.setAttribute('font-size', String(Math.max(result.width, sheet.usedLength) / 28));
    label.setAttribute('font-family', 'Rajdhani, sans-serif');
    label.textContent = String(number++);
    frame.append(label);
  }
}

function renderLoose(frame) {
  const parts = kits.flatMap(entry => entry.data.parts || []);
  frame.replaceChildren();
  if (!parts.length) { fit(frame, 100, 40); return; }
  let y = 8;
  let width = 40;
  const group = document.createElementNS(NS, 'g');
  parts.forEach((part, index) => {
    if (!part.points) return;
    const xs = part.points.map(point => point[0]);
    const ys = part.points.map(point => point[1]);
    const minX = Math.min(...xs);
    const minY = Math.min(...ys);
    const poly = document.createElementNS(NS, 'polygon');
    poly.setAttribute('points', part.points.map(point => point.join(',')).join(' '));
    poly.setAttribute('transform', `translate(${8 - minX} ${y - minY})`);
    stroke(poly, '#D92F00', false);
    group.append(poly);
    const label = document.createElementNS(NS, 'text');
    label.setAttribute('x', '8');
    label.setAttribute('y', String(y + 8));
    label.setAttribute('fill', '#D92F00');
    label.setAttribute('font-size', '8');
    label.setAttribute('font-family', 'Rajdhani, sans-serif');
    label.textContent = String(index + 1);
    group.append(label);
    width = Math.max(width, Math.max(...xs) - minX + 16);
    y += Math.max(...ys) - minY + 10;
  });
  frame.append(group);
  fit(frame, width, Math.max(40, y));
}

function renderPreview(index) {
  activeSheet = index;
  renderSheet($('preview'), current, index);
  for (const [tabIndex, button] of [...$('sheet-tabs').children].entries()) button.setAttribute('aria-pressed', String(tabIndex === index));
}

function showMetrics(state) {
  const result = state.result;
  setNum('length', (result.usedLength / 304.8).toFixed(1), 'ft');
  const cost = state.manifest.materialCost;
  const costBit = cost ? ' · ≈ $' + Number(cost.total).toFixed(2) : '';
  $('length-exact').textContent = 'of ' + $('width').value + ' ' + $('unit').value + ' roll' + costBit;
  setNum('waste', String(Math.round((1 - result.utilization) * 100)), '%');
  $('cost-line').textContent = Math.round(result.utilization * 100) + '% used';
  const sheets = sheetList(state);
  setNum('sheets', String(sheets.length));
  const summary = placedCuts(state);
  const pieces = state.manifest.totalPieces;
  const bits = [pieces + (pieces === 1 ? ' piece' : ' pieces')];
  if (summary.thru) bits.push(summary.thru + ' thru');
  if (summary.kiss) bits.push(summary.kiss + ' kiss');
  $('checks').textContent = bits.join(' · ');
  $('readout').classList.remove('pending');
  $('length').classList.toggle('over', lengthOver(state));
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
}

function showLock(state) {
  const locked = !!state.released;
  $('layout-id').value = locked ? state.id : '';
  $('layout-hash').value = locked ? (state.sha256 || '') : '';
}

function showSent() {
  showScreen('sent');
  const name = kits.map(entry => entry.name.replace(/\.(svg|pdf|ai)$/i, '')).join(', ') || 'Layout';
  const where = current.savedPath ? current.savedPath : 'Downloaded. No hot folder is set.';
  const sheets = $('sheets').querySelector('.num')?.textContent || '';
  const amount = ($('length').querySelector('.num')?.textContent || '') + ' ' + ($('length').querySelector('.unit')?.textContent || '');
  $('sent-file').textContent = name + ' · ' + sheets + ' sheet · ' + amount.trim() + ' · ' + where;
  $('sent-hold').hidden = !$('allow-hold').checked;
  $('sent-hold').textContent = 'Hold for Operator is on in settings. ONYX still applies its own holds.';
  $('gate').hidden = false;
  $('gate').textContent = 'Sent';
  $('gate').className = 'gate';
  $('empty').hidden = true;
  $('sheet-frame').hidden = false;
  renderActions();
}

function showBlocked(message, detail) {
  blockReason = message || 'Nesting stopped. Change the roll or the file and try again.';
  showScreen('blocked');
  if (!current?.result) {
    setNum('length', '–', 'ft');
    setNum('waste', '–', '%');
    setNum('sheets', '–');
    $('readout').classList.add('pending');
    $('length').classList.remove('over');
    $('checks').textContent = '';
    $('cost-line').textContent = '';
    $('empty').hidden = true;
    $('sheet-frame').hidden = false;
    renderLoose($('preview'));
  }
  renderActions();
  if (detail) {
    $('block-detail').hidden = false;
    $('block-detail').textContent = detail;
  }
}

function showResult(state) {
  current = state;
  blockReason = '';
  showMetrics(state);
  showLock(state);
  renderPreview(Math.min(activeSheet, sheetsIndex(state)));
  const missing = pieceIssue(state);
  const cuts = cutProblem();
  if (state.released) showSent();
  else if (missing) showBlocked(missing);
  else if (cuts) showBlocked(cuts.line, cuts.detail);
  else {
    showScreen('check');
    renderActions();
  }
  status(state.note || (state.released ? 'This locked layout was restored on this computer.' : 'Layout ready.'));
}

function sheetsIndex(state) {
  return Math.max(0, Math.min(activeSheet, sheetList(state).length - 1));
}

function showLive(state) {
  const live = state.live;
  const expected = (state.job?.parts || []).reduce((sum, part) => sum + (part.quantity || 1), 0);
  $('gate').hidden = false;
  $('gate').className = 'gate';
  $('empty').hidden = true;
  $('sheet-frame').hidden = false;
  $('live').hidden = true;
  if (!live || !live.usedLength) {
    setNum('length', '–', 'ft');
    setNum('waste', '–', '%');
    setNum('sheets', '–');
    $('readout').classList.add('pending');
    $('gate').textContent = expected ? 'Nesting… 0 of ' + expected + ' placed' : 'Nesting…';
    return;
  }
  const placed = live.placements?.length || 0;
  setNum('length', (live.usedLength / 304.8).toFixed(1), 'ft');
  setNum('waste', String(Math.round((1 - (live.utilization || 0)) * 100)), '%');
  setNum('sheets', '1');
  $('readout').classList.remove('pending');
  $('length-exact').textContent = 'of ' + $('width').value + ' ' + $('unit').value + ' roll';
  $('cost-line').textContent = Math.round((live.utilization || 0) * 100) + '% used';
  $('checks').textContent = placed + ' of ' + (expected || placed) + ' placed';
  $('gate').textContent = 'Nesting… ' + placed + ' of ' + (expected || placed) + ' placed';
  if (state.job) renderSheet($('preview'), {job: state.job, result: live, manifest: null}, 0);
}

async function poll() {
  if (!busy) return;
  try {
    const state = await (await fetch('/api/state')).json();
    if (state.status === 'running') {
      showScreen('nest');
      showLive(state);
      renderActions();
      setTimeout(poll, 400);
      return;
    }
    busy = false;
    if (state.status === 'ready' && state.manifest) showResult(state);
    else showBlocked(state.error || state.note || 'Nesting stopped. Change the roll or the file and try again.');
  } catch (error) {
    busy = false;
    showBlocked(error.message);
  }
  renderActions();
}

async function nest() {
  if (busy || saving || !kits.length || $('nest').disabled) return;
  try {
    for (const entry of kits) entry.sets = sets();
    const job = EZNQueue.compose(kits, preset(), 'combined');
    job.outputProfile = profileFor(kits);
    job.settings.seed = 42;
    busy = true;
    current = null;
    blockReason = '';
    activeSheet = 0;
    showScreen('nest');
    showLive({job});
    renderActions();
    status('Nesting on ' + $('width').value + ' ' + $('unit').value + '…');
    await api('/api/solve', job);
    setTimeout(poll, 300);
  } catch (error) {
    busy = false;
    showBlocked(error.message);
  }
}

async function improve() {
  if (busy || saving || !current || current.released) return;
  try {
    busy = true;
    showScreen('nest');
    status('Trying a better fit…');
    await api('/api/improve', {id: current.id});
    setTimeout(poll, 300);
  } catch (error) {
    busy = false;
    status(error.message, true);
    renderActions();
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
  renderActions();
  try {
    const artwork = current.job.documentSources ? null : EZNSVG.serialize(EZNSVG.buildSVG(current.job, current.result));
    const released = await api('/api/release', {id: current.id, artwork, map: EZNSVG.serialize(sheetMap(current))});
    current.released = true;
    current.sha256 = released.sha256;
    current.savedPath = released.savedPath || '';
    current.deliveryCompleted = released.deliveryCompleted === true;
    showLock(current);
    return current;
  } finally {
    saving = false;
    renderActions();
  }
}

async function exportFile(forceDownload) {
  if (!current || busy || saving || $('export').disabled) return;
  try {
    if (!current.released) await lock();
    else await api('/api/release', {id: current.id, map: EZNSVG.serialize(sheetMap(current))});
    saving = true;
    const response = await fetch('/api/batch/' + current.id);
    if (!response.ok) throw Error('The locked file is saved, but the download failed. Send again.');
    const bytes = await response.arrayBuffer();
    const hash = await sha256(bytes);
    if (current.sha256 && hash !== current.sha256) throw Error('The download does not match the locked layout.');
    if (forceDownload === true || !current.savedPath) {
      const link = document.createElement('a');
      link.href = URL.createObjectURL(new Blob([bytes], {type: 'application/zip'}));
      link.download = 'eznest-' + current.id.slice(0, 8) + '.zip';
      document.body.append(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(link.href), 1000);
    }
    showSent();
    status(current.savedPath ? 'Sent to the hot folder.' : 'Downloaded eznest-' + current.id.slice(0, 8) + '.zip.');
  } catch (error) {
    showBlocked(error.message);
  } finally {
    saving = false;
    renderActions();
  }
}

function nextKit() {
  kits = [];
  current = null;
  blockReason = '';
  activeSheet = 0;
  renderKit();
  showScreen('drop');
  status('Drop the next kit.');
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
  const option = $('material').selectedOptions[0];
  $('preset-name').value = option.dataset.width ? option.textContent.split('·')[0].trim() : ($('preset-name').value || 'Custom roll');
  if (!option.dataset.width) return;
  $('unit').value = option.dataset.unit || 'in';
  $('unit').dataset.current = $('unit').value;
  $('width').value = option.dataset.width;
  for (const node of document.querySelectorAll('[data-unit]')) node.textContent = $('unit').value;
  savePrefs({material: option.value});
}

function watchWidth() {
  const width = $('width').value;
  const unit = $('unit').value;
  const match = [...$('material').options].find(option => option.dataset.unit === unit && option.dataset.width === width);
  $('material').value = match ? match.value : 'custom';
  renderActions();
}

function rememberPreset() {
  const option = $('material').selectedOptions[0];
  const name = $('preset-name').value.trim();
  if (!name) return;
  if (option.value === 'custom') option.textContent = name;
  else option.textContent = name + ' · ' + ($('width').value || option.dataset.width || '') + ' ' + $('unit').value;
  const stored = prefs();
  stored.presets = stored.presets || {};
  stored.presets[option.value] = {label: option.textContent, width: $('width').value, unit: $('unit').value};
  savePrefs(stored);
}

async function saveHotFolder() {
  const path = $('hot-folder').value.trim();
  try {
    const result = await api('/api/output/connect', {path});
    $('hot-folder').value = result.path || '';
    savePrefs({hotFolder: $('hot-folder').value});
    status(result.path ? 'Hot folder set. Send writes the frozen pack there.' : 'No hot folder. Send downloads the pack.');
  } catch (error) {
    status(error.message, true);
  }
}

async function importPdf(file, operation) {
  const bytes = new Uint8Array(await file.arrayBuffer());
  let binary = '';
  for (let offset = 0; offset < bytes.length; offset += 32768) binary += String.fromCharCode(...bytes.subarray(offset, offset + 32768));
  const mapping = EZNCuts.defaults();
  mapping.genericOperation = operation;
  const bleed = Number($('bleed').value);
  if (!Number.isFinite(bleed) || bleed < 0 || bleed > 25) throw Error('Existing bleed must be from 0 to 25 mm.');
  return api('/api/document/import', {content: btoa(binary), bleedMm: bleed, cutSpot: 'CutContour', cutMapping: EZNCuts.validate(mapping)});
}

async function readEntry(file, index) {
  const pdf = /\.(pdf|ai)$/i.test(file.name);
  if (!pdf && !/\.svg$/i.test(file.name)) throw Error(file.name + ' is not SVG, PDF, or PDF-compatible AI.');
  if (file.size > (pdf ? 20_000_000 : 8_000_000)) throw Error(file.name + ' is over the ' + (pdf ? '20' : '8') + ' MB limit.');
  let data, revision, unresolvedCut = false;
  if (pdf) {
    const chosen = $('generic-cut').value;
    try {
      data = await importPdf(file, chosen);
    } catch (error) {
      if (!chosen && /unspecified cut type/i.test(error.message)) {
        data = await importPdf(file, 'contour');
        unresolvedCut = true;
      } else throw error;
    }
    data.reviewed = true;
    data.format = 'pdf';
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
    sets: sets(), selected: true, status: 'ready', data, file, unresolved: unresolvedCut
  };
}

async function importFiles(fileList) {
  const files = [...fileList].filter(Boolean);
  if (!files.length || busy || saving) return;
  const pdf = files.some(file => /\.(pdf|ai)$/i.test(file.name));
  const svg = files.some(file => /\.svg$/i.test(file.name));
  if (pdf && svg) throw Error('Nest SVG files in one batch and PDF files in another. That keeps the original artwork.');
  status('Reading ' + files.length + (files.length === 1 ? ' file…' : ' files…'));
  const entries = [];
  for (const [index, file] of files.entries()) entries.push(await readEntry(file, index));
  kits = entries;
  current = null;
  blockReason = '';
  renderKit();
  showScreen('drop');
  status(unresolved() ? 'Unnamed cuts need a thru or kiss choice after the nest.' : 'Set the material, then nest.');
}

async function chooseCut(operation) {
  if (busy || saving || !unresolved()) return;
  const files = kits.map(entry => entry.file).filter(Boolean);
  $('generic-cut').value = operation;
  try {
    await importFiles(files);
    $('generic-cut').value = '';
    if (!$('nest').disabled) await nest();
  } catch (error) {
    $('generic-cut').value = '';
    showBlocked(error.message);
  }
}

async function boot() {
  const stored = prefs();
  if (stored.presets) {
    for (const option of $('material').options) {
      const saved = stored.presets[option.value];
      if (!saved) continue;
      option.textContent = saved.label || option.textContent;
      if (saved.width) option.dataset.width = saved.width;
      if (saved.unit) option.dataset.unit = saved.unit;
    }
  }
  $('allow-undo').checked = stored.undo === true;
  $('allow-hold').checked = stored.hold === true;
  const session = await (await fetch('/api/session')).json();
  token = session.token;
  try {
    const folder = await (await fetch('/api/output')).json();
    if (folder.path) $('hot-folder').value = folder.path;
  } catch { /* The folder status is optional. */ }
  const state = await (await fetch('/api/state')).json();
  if (state.status === 'running') { busy = true; showScreen('nest'); renderActions(); setTimeout(poll, 300); }
  else if (state.status === 'ready' && state.manifest) showResult(state);
  else { showScreen('drop'); status('Drop a kit. The nest runs on this computer.'); }
  renderActions();
}

document.addEventListener('DOMContentLoaded', () => {
  $('file').addEventListener('change', async event => {
    if (ignoreFileChange) { ignoreFileChange = false; event.target.value = ''; return; }
    try { await importFiles(event.target.files); }
    catch (error) { showBlocked(error.message); }
    finally { event.target.value = ''; }
  });
  document.addEventListener('dragover', event => { event.preventDefault(); document.body.classList.add('dragging'); });
  document.addEventListener('dragleave', event => { if (!event.relatedTarget) document.body.classList.remove('dragging'); });
  document.addEventListener('drop', async event => {
    event.preventDefault();
    document.body.classList.remove('dragging');
    ignoreFileChange = true;
    try { await importFiles(event.dataTransfer.files); }
    catch (error) { showBlocked(error.message); }
  });
  $('sets-dec').addEventListener('click', () => { $('sets').value = String(Math.max(1, sets() - 1)); renderKit(); });
  $('sets-inc').addEventListener('click', () => { $('sets').value = String(Math.min(100, sets() + 1)); renderKit(); });
  $('sets').addEventListener('change', () => { try { sets(); renderKit(); } catch (error) { $('sets').value = '1'; status(error.message, true); } });
  $('unit').addEventListener('change', () => { convertUnit($('unit').value); watchWidth(); });
  $('material').addEventListener('change', applyMaterial);
  $('width').addEventListener('input', watchWidth);
  $('preset-name').addEventListener('change', rememberPreset);
  $('hot-folder').addEventListener('change', saveHotFolder);
  $('allow-undo').addEventListener('change', () => { savePrefs({undo: $('allow-undo').checked}); renderActions(); });
  $('allow-hold').addEventListener('change', () => { savePrefs({hold: $('allow-hold').checked}); if (current?.released) showSent(); });
  $('nest').addEventListener('click', nest);
  $('cancel').addEventListener('click', async () => {
    try {
      await api('/api/cancel', {keepBest: true});
      busy = false;
      const state = await (await fetch('/api/state')).json();
      if (state.status === 'ready' && state.manifest) showResult(state);
      else showBlocked(state.note || state.error || 'Stopped before a layout was ready.');
    } catch (error) { showBlocked(error.message); }
  });
  $('export').addEventListener('click', () => exportFile(false));
  $('download-only').addEventListener('click', () => exportFile(true));
  $('again').addEventListener('click', nest);
  $('improve').addEventListener('click', improve);
  $('choose-thru').addEventListener('click', () => chooseCut('thru'));
  $('choose-kiss').addEventListener('click', () => chooseCut('kiss'));
  $('next').addEventListener('click', nextKit);
  $('undo').addEventListener('click', async () => {
    if (!current?.savedPath) return;
    try {
      await api('/api/output/undo', {id: current.id});
      current.savedPath = '';
      showResult(current);
      showScreen('check');
      renderActions();
      status('Removed the pack from the hot folder. The locked file is unchanged.');
    } catch (error) { status(error.message, true); }
  });
  document.addEventListener('keydown', event => {
    if (event.repeat || event.altKey || event.ctrlKey || event.metaKey) return;
    if (event.key === ' ' && event.target.id === 'export') { event.preventDefault(); return; }
    if (event.key !== 'Enter') return;
    if (event.target.closest('input, select, textarea, summary, #choose-thru, #choose-kiss, #sets-dec, #sets-inc, #cancel, #sheet-tabs')) return;
    if (document.body.dataset.step === 'blocked' || $('gate').classList.contains('problem')) { event.preventDefault(); return; }
    if (busy || saving) return;
    if (document.body.dataset.step === 'sent') { event.preventDefault(); nextKit(); return; }
    if (document.body.dataset.step === 'check' && current && current.result && !$('export').disabled) { event.preventDefault(); exportFile(); return; }
    if (document.body.dataset.step === 'drop' && !$('nest').disabled) { event.preventDefault(); nest(); }
  });
  boot().catch(error => status(error.message, true));
});
