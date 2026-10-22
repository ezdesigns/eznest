'use strict';
const NS = 'http://www.w3.org/2000/svg';
const $ = id => document.getElementById(id);
const PREF = 'eznest-placeholders';
const PIECE_CAP = 800;
let token = '';
let kits = [];
let fileSerial = 0;
let current = null;
let busy = false;
let saving = false;
let activeSheet = 0;
let ignoreFileChange = false;
let blockReason = '';
let pendingRenest = false;
let leaving = false;
let nestTimer = 0;

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

function fetchJson(path, ms) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), ms);
  return fetch(path, {signal: controller.signal}).then(response => {
    clearTimeout(timer);
    if (!response.ok) throw Error('Request failed.');
    return response.json();
  }, error => {
    clearTimeout(timer);
    throw error;
  });
}

async function fetchJsonRetry(path) {
  let last = Error('Request failed.');
  for (let attempt = 0; attempt < 3; attempt++) {
    try { return await fetchJson(path, 4000); }
    catch (error) { last = error; }
  }
  throw last;
}

function stylesApplied() {
  return getComputedStyle(document.documentElement).getPropertyValue('--alarm').toLowerCase().includes('d92f00');
}

function loadStylesheet() {
  return new Promise((resolve, reject) => {
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = '/web.css?ts=' + Date.now();
    const timer = setTimeout(() => { link.remove(); reject(Error('The shop stylesheet did not load.')); }, 4000);
    link.onload = () => { clearTimeout(timer); resolve(); };
    link.onerror = () => { clearTimeout(timer); link.remove(); reject(Error('The shop stylesheet did not load.')); };
    document.head.appendChild(link);
  });
}

function loadScript(src) {
  return new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = src + '?ts=' + Date.now();
    const timer = setTimeout(() => { script.remove(); reject(Error(src + ' did not load.')); }, 4000);
    script.onload = () => { clearTimeout(timer); resolve(); };
    script.onerror = () => { clearTimeout(timer); script.remove(); reject(Error(src + ' did not load.')); };
    document.head.appendChild(script);
  });
}

async function ensureLibraries() {
  const need = [['EZNQueue', '/queue-core.js'], ['EZNCuts', '/cut-mapping.js'], ['EZNProfiles', '/shop-profiles.js']];
  for (const [name, src] of need) {
    for (let attempt = 0; attempt < 3 && typeof window[name] === 'undefined'; attempt++) {
      try { await loadScript(src); }
      catch { /* Ask for the script again. */ }
    }
    if (typeof window[name] === 'undefined') throw Error(name + ' did not load.');
  }
}

async function ensureStyles() {
  if (stylesApplied()) return;
  for (let attempt = 0; attempt < 3 && !stylesApplied(); attempt++) {
    try { await loadStylesheet(); }
    catch { /* Ask for the stylesheet again. */ }
  }
  if (!stylesApplied()) throw Error('The shop stylesheet did not load.');
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
  if (!Number.isInteger(count) || count < 1 || count > PIECE_CAP) throw Error('Sets must be a whole number from 1 to ' + PIECE_CAP + '.');
  return count;
}

function scale() {
  return EZNQueue.unitScale($('unit').value);
}

const CUT_PRESETS = {
  ln: {thru: 'LNThru-cut', kiss: 'LNKiss-cut'},
  output: {thru: 'CutContour_Thru-cut', kiss: 'CutContour_Kiss-cut'}
};
const HOT_FOLDER_LABEL = 'EPSON SureColor S80600 ONYX Input';

function autoBleedMm() {
  const inches = Number($('auto-bleed').value);
  if (!Number.isFinite(inches) || inches < 0) return 0;
  return inches * 25.4;
}

function cutNames() {
  const thru = $('thru-name').value.trim();
  const kiss = $('kiss-name').value.trim();
  if (!thru || !kiss || thru.length > 80 || kiss.length > 80) throw Error('Enter thru and kiss spot names.');
  return {thru, kiss};
}

function cutMapping() {
  const mapping = EZNCuts.defaults();
  const names = cutNames();
  mapping.genericOperation = $('generic-cut').value;
  mapping.outputs.thru.spot = names.thru;
  mapping.outputs.thru.layer = names.thru;
  mapping.outputs.kiss.spot = names.kiss;
  mapping.outputs.kiss.layer = names.kiss;
  return EZNCuts.validate(mapping);
}

function chosenWidthInches() {
  return Number($('nest-width').value);
}

function maxPrintableMm() {
  const option = $('material').selectedOptions[0];
  if (option && option.dataset.width) {
    return Number(option.dataset.width) * EZNQueue.unitScale(option.dataset.unit || 'in');
  }
  const width = Number($('width').value);
  return Number.isFinite(width) ? width * scale() : NaN;
}

function marginsMm() {
  const factor = scale();
  const edge = Number($('margin').value) * factor;
  const mark = $('mark-margin').value.trim() ? Number($('mark-margin').value) * factor : 0;
  return {edge, mark, total: edge + mark};
}

function rotatedSpan(points, degrees) {
  const rad = degrees * Math.PI / 180;
  const c = Math.cos(rad);
  const s = Math.sin(rad);
  let minX = Infinity;
  let maxX = -Infinity;
  for (const point of points) {
    const x = point[0] * c - point[1] * s;
    if (x < minX) minX = x;
    if (x > maxX) maxX = x;
  }
  return maxX - minX;
}

function widestPieceMm() {
  const angles = $('rotations').value === 'free'
    ? Array.from({length: 36}, (_, index) => index * 5)
    : $('rotations').value.split(',').map(Number);
  let widest = 0;
  for (const entry of kits) {
    for (const part of entry.data?.parts || []) {
      if (!part.points || part.points.length < 2) continue;
      let best = Infinity;
      for (const angle of angles) best = Math.min(best, rotatedSpan(part.points, angle));
      if (best > widest) widest = best;
    }
  }
  return widest;
}

function widthLabel() {
  const width = chosenWidthInches();
  if (!Number.isFinite(width) || width <= 0) return 'on — wide';
  return 'on ' + String(Number(width.toFixed(4))) + '" wide';
}

function showWidth() {
  const node = $('used-width');
  if (node) node.textContent = widthLabel();
}

function shortProblem(message) {
  const text = message || '';
  if (/too large|wider than/i.test(text)) return 'A piece is wider than this width';
  if (/one sheet|sheet length|maximum sheet/i.test(text)) return 'Material is over the sheet length';
  return text;
}

function preset() {
  const factor = scale();
  const number = id => Number($(id).value) * factor;
  const printable = chosenWidthInches() * 25.4;
  const edge = number('margin');
  const mark = $('mark-margin').value.trim() ? number('mark-margin') : 0;
  // The operator's width is the sheet. Mark clearance (and the edge) is reserved
  // inside it, so pieces nest on that width minus the mark margins.
  const settings = {
    width: printable,
    maxLength: null,
    gap: number('gap'),
    margin: edge + mark,
    edgeMargin: edge,
    markMargin: mark,
    seconds: Number($('seconds').value) || 5,
    rotations: $('rotations').value === 'free' ? null : $('rotations').value.split(',').map(Number),
    seed: 42,
    autoBleedMm: autoBleedMm(),
    drawRegmarks: $('draw-marks').checked === true
  };
  if ($('roll').value.trim()) settings.rollWidth = number('roll');
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
  const mapping = cutMapping();
  if (!pdf) {
    return EZNProfiles.validate({
      name: 'Generic SVG handoff', rip: 'Other / manual', format: 'svg', acceptedFormats: ['svg'],
      colorMode: 'preserve', iccProfile: '', bleedMm: 0, cutSpot: '', cutLayer: '',
      registrationOwner: 'none', finishingSoftware: '', mediaOwner: 'rip', jobLogOwner: 'rip',
      cutMapping: mapping
    });
  }
  return EZNProfiles.validate({
    name: 'PDF / CutContour', rip: 'ONYX', format: 'pdf', acceptedFormats: ['pdf', 'ai'],
    colorMode: 'preserve', iccProfile: '', bleedMm: Number($('bleed').value) || 0,
    cutSpot: 'CutContour', cutLayer: 'CutContour', registrationOwner: 'rip',
    finishingSoftware: 'GoProduce', mediaOwner: 'rip', jobLogOwner: 'rip',
    cutMapping: mapping
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

function mappedOperation(source, name) {
  const thru = $('thru-name').value.trim();
  const kiss = $('kiss-name').value.trim();
  if (name === thru) return 'thru';
  if (name === kiss) return 'kiss';
  const rules = EZNCuts.defaults().rules.filter(rule => rule.source === source);
  const matches = rules.filter(rule => rule.match === 'exact' ? rule.name === name : name.startsWith(rule.name));
  const exact = matches.filter(rule => rule.match === 'exact');
  const chosen = exact.length ? exact : matches;
  if (chosen.length) return chosen[0].operation;
  const other = EZNCuts.defaults().rules.find(rule => rule.source !== source && rule.match === 'exact' && rule.name === name);
  return other ? other.operation : '';
}

function unknownRefs() {
  const found = [];
  for (const entry of kits) {
    for (const part of entry.data?.parts || []) {
      for (const ref of part.cutRefs || []) {
        const operation = mappedOperation(ref.source, ref.name);
        if (operation === 'thru' || operation === 'kiss' || operation === 'regmark') continue;
        found.push(ref);
      }
    }
  }
  return found;
}

function unresolved() {
  return unknownRefs().length > 0;
}

function renderKit() {
  renderActions();
}

function inputIssue() {
  const chosen = chosenWidthInches();
  const chosenMm = chosen * 25.4;
  const maxMm = maxPrintableMm();
  const {edge, mark, total} = marginsMm();
  const gap = Number($('gap').value);
  const count = Number($('sets').value);
  if (!Number.isFinite(chosen) || chosen <= 0) return 'Width must be greater than 0';
  if (!Number.isFinite(maxMm) || maxMm <= 0) return 'Enter a printable width';
  if (!Number.isFinite(gap) || gap < 0) return 'Check the spacing';
  if (!Number.isFinite(edge) || edge < 0) return 'Check the edge margin';
  if (!Number.isFinite(mark) || mark < 0) return 'Check the mark margin';
  if (chosenMm > maxMm + 0.05) return "Width is over this material's printable width";
  if (total * 2 >= chosenMm) return 'Mark margins leave no room on this width';
  const widest = widestPieceMm();
  if (widest > chosenMm - total * 2 + 0.2) return 'A piece is wider than this width';
  return quantityIssue() || (Number.isInteger(count) && count >= 1 && count <= PIECE_CAP ? '' : 'Sets must be from 1 to ' + PIECE_CAP);
}

function quantityIssue() {
  if (!kits.length) return '';
  let total = 0;
  for (const entry of kits) {
    if (!Number.isInteger(entry.sets) || entry.sets < 1 || entry.sets > PIECE_CAP) return 'Quantity must be from 1 to ' + PIECE_CAP;
    const per = (entry.data?.parts || []).reduce((sum, part) => sum + (part.quantity || 1), 0);
    total += per * entry.sets;
  }
  if (total > PIECE_CAP) return 'This batch holds ' + PIECE_CAP + ' pieces';
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
  if (!Number.isFinite(limit) || limit <= 0) return false;
  const sheets = state.result.sheets;
  if (sheets && sheets.length) return sheets.some(sheet => sheet.usedLength > limit + 0.05);
  return state.result.usedLength > limit;
}

function clearReadout() {
  setNum('length', '–', 'ft');
  setNum('waste', '–', '%');
  setNum('sheets', '–');
  $('length').classList.remove('over');
  $('readout').classList.add('pending');
  $('checks').textContent = '';
}

function setSentence(text, problem) {
  $('checks').textContent = text || '';
  $('gate').className = problem ? 'gate problem' : 'gate';
  $('gate').hidden = !text;
}

function plainContour() {
  const refs = unknownRefs();
  return refs.length > 0 && refs.every(ref => ref.name === 'CutContour');
}

function cutProblem() {
  const refs = unknownRefs();
  if (!refs.length) return null;
  if (plainContour()) return {line: 'Plain CutContour found: Kiss or Thru?', plain: true};
  const ref = refs.find(item => item.name !== 'CutContour' && item.source === 'layer')
    || refs.find(item => item.name !== 'CutContour')
    || refs[0];
  const kind = ref.source === 'layer' ? 'layer' : 'spot';
  return {line: 'Unknown cut ' + kind + ' "' + ref.name + '". Rename to thru or kiss.'};
}

function showSheetId(state) {
  const node = $('sheet-id');
  const id = state && state.id ? String(state.id) : '';
  node.textContent = id;
  node.hidden = !id;
}

function showScreen(name) {
  document.body.dataset.step = name;
  const idle = name === 'drop';
  const confirming = name === 'confirm';
  $('drop-screen').hidden = !idle;
  $('sheet-frame').hidden = idle;
  $('legend').hidden = idle;
  $('readout').hidden = idle;
  $('export').hidden = idle || confirming;
  $('confirm').hidden = !confirming;
  $('start-over').hidden = idle;
  $('choice').hidden = name !== 'blocked' || !unresolved();
  if ($('choice').hidden) $('choose-confirm').hidden = true;
  if (idle) showSheetId(null);
  syncFiles();
  if (idle) {
    clearReadout();
    $('sheet-tabs').hidden = true;
    $('preview').replaceChildren();
    setSentence('', false);
  }
}

function syncFiles() {
  const show = kits.length > 0 && document.body.dataset.step !== 'drop';
  $('files').hidden = !show;
  $('add-files').hidden = !show || document.body.dataset.step === 'nest';
  $('stop').hidden = document.body.dataset.step !== 'nest';
  const locked = busy || document.body.dataset.step === 'nest';
  for (const node of $('files').querySelectorAll('input, button')) node.disabled = locked;
}

function renderFiles() {
  const list = $('files');
  list.replaceChildren();
  for (const entry of kits) {
    const row = document.createElement('li');
    const name = document.createElement('span');
    name.className = 'file-name';
    name.textContent = entry.name;
    const qty = document.createElement('input');
    qty.type = 'number';
    qty.min = '1';
    qty.max = String(PIECE_CAP);
    qty.step = '1';
    qty.value = String(entry.sets);
    qty.setAttribute('aria-label', 'Quantity for ' + entry.name);
    const commitQty = () => {
      const count = Number(qty.value);
      if (!Number.isInteger(count) || count < 1 || count > PIECE_CAP) {
        if (document.activeElement !== qty) qty.value = String(entry.sets);
        return;
      }
      if (count === entry.sets) return;
      entry.sets = count;
      requestNest();
    };
    qty.addEventListener('input', commitQty);
    qty.addEventListener('change', () => {
      if (!Number.isInteger(Number(qty.value)) || Number(qty.value) < 1) qty.value = String(entry.sets);
      commitQty();
    });
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'link';
    remove.textContent = 'Remove';
    remove.setAttribute('aria-label', 'Remove ' + entry.name);
    remove.addEventListener('click', () => removeFile(entry.id));
    row.append(name, qty, remove);
    list.append(row);
  }
  syncFiles();
}

function removeFile(id) {
  if (saving) return;
  kits = kits.filter(entry => entry.id !== id);
  if (!kits.length) { startOver(); return; }
  renderFiles();
  requestNest();
}

function applySetsToFiles() {
  let count = Number($('sets').value);
  if (!Number.isInteger(count) || count < 1 || count > PIECE_CAP) {
    $('sets').value = '1';
    count = 1;
    status('Sets must be from 1 to ' + PIECE_CAP + '.', true);
  }
  for (const entry of kits) entry.sets = count;
  if (kits.length) renderFiles();
}

function renderActions() {
  const badInput = inputIssue();
  const missing = current && current.result ? pieceIssue(current) : '';
  const cuts = current && current.result ? cutProblem() : null;
  const tooLong = current && current.result && lengthOver(current) ? 'Material is over the sheet length' : '';
  const step = document.body.dataset.step;
  const sent = step === 'sent' && current && current.released;
  $('length').classList.toggle('over', !!(current && current.result && lengthOver(current)));
  $('undo').hidden = !(sent && $('allow-undo').checked && current && current.savedPath);
  if (sent) {
    $('export').disabled = saving;
    return;
  }
  const actionable = step !== 'drop' && step !== 'nest';
  const reason = blockReason || missing || (cuts ? cuts.line : '') || tooLong || (actionable ? badInput : '');
  $('export').disabled = busy || saving || !!reason || !current || !current.result;
  if (step === 'confirm') {
    $('export').hidden = true;
    $('confirm').hidden = false;
    $('choice').hidden = true;
    $('choose-confirm').hidden = true;
    return;
  }
  if (!actionable) return;
  if (reason) {
    document.body.dataset.step = 'blocked';
    const plain = !!(cuts && cuts.plain && reason === cuts.line);
    setSentence(reason, !plain);
    if (plain) {
      if ($('choose-confirm').hidden) cutChoice = 'kiss';
      $('choice').hidden = false;
      $('choose-confirm').hidden = false;
      $('choose-kiss').setAttribute('aria-pressed', cutChoice === 'kiss' ? 'true' : 'false');
      $('choose-thru').setAttribute('aria-pressed', cutChoice === 'thru' ? 'true' : 'false');
    } else if (cuts) {
      $('choice').hidden = false;
      $('choose-confirm').hidden = true;
      $('choose-kiss').setAttribute('aria-pressed', 'false');
      $('choose-thru').setAttribute('aria-pressed', 'false');
    } else {
      $('choice').hidden = true;
      $('choose-confirm').hidden = true;
    }
    return;
  }
  if (current && current.manifest) {
    document.body.dataset.step = 'check';
    setSentence(pieceSentence(current), false);
    $('choice').hidden = true;
    $('choose-confirm').hidden = true;
  }
}

function pieceSentence(state) {
  const summary = placedCuts(state);
  const placed = state.manifest.totalPieces;
  const bits = [placed + (placed === 1 ? ' piece' : ' pieces')];
  if (summary.thru) bits.push(summary.thru + ' thru');
  if (summary.kiss) bits.push(summary.kiss + ' kiss');
  return bits.join(' · ') + ' · cuts OK';
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
  if (!state.job.documentSources) {
    applyAutoBleed(art, state.job, result);
    emphasizeCuts(art);
  }
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
  setNum('waste', String(Math.round((1 - result.utilization) * 100)), '%');
  const sheets = sheetList(state);
  setNum('sheets', String(sheets.length));
  $('readout').classList.remove('pending');
  showWidth();
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
  if (current && current.manifest) setSentence(pieceSentence(current), false);
  renderActions();
}

function showBlocked(message) {
  blockReason = shortProblem(message) || 'Nesting stopped. Change the width or the file and try again.';
  showScreen('blocked');
  showWidth();
  if (!current?.result) {
    setNum('length', '–', 'ft');
    setNum('waste', '–', '%');
    setNum('sheets', '–');
    $('readout').classList.add('pending');
    $('length').classList.remove('over');
    $('sheet-frame').hidden = false;
    renderLoose($('preview'));
  }
  renderActions();
}

function showResult(state) {
  current = state;
  blockReason = '';
  document.body.dataset.nestWidth = state.result ? String(state.result.width) : '';
  showMetrics(state);
  showLock(state);
  showSheetId(state);
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
  $('sheet-frame').hidden = false;
  $('live').hidden = true;
  if (!live || !live.usedLength) {
    setNum('length', '–', 'ft');
    setNum('waste', '–', '%');
    setNum('sheets', '–');
    $('readout').classList.add('pending');
    setSentence('Nesting…', false);
    return;
  }
  const placed = live.placements?.length || 0;
  setNum('length', (live.usedLength / 304.8).toFixed(1), 'ft');
  setNum('waste', String(Math.round((1 - (live.utilization || 0)) * 100)), '%');
  setNum('sheets', '1');
  $('readout').classList.remove('pending');
  showWidth();
  setSentence('Nesting… ' + placed + ' of ' + (expected || placed), false);
  if (state.job) renderSheet($('preview'), {job: state.job, result: live, manifest: null}, 0);
}

async function poll() {
  if (!busy) return;
  try {
    const state = await fetchJson('/api/state', 4000);
    if (leaving || !kits.length) { busy = false; if (!kits.length) showScreen('drop'); return; }
    if (state.status === 'running') {
      showScreen('nest');
      showLive(state);
      renderActions();
      setTimeout(poll, 400);
      return;
    }
    busy = false;
    if (pendingRenest && kits.length && !leaving) {
      pendingRenest = false;
      nest();
      return;
    }
    if (state.status === 'ready' && state.manifest) showResult(state);
    else showBlocked(state.error || state.note || 'That file does not fit this roll.');
  } catch (error) {
    if (error && error.name === 'AbortError' && busy && !leaving) { setTimeout(poll, 300); return; }
    busy = false;
    if (pendingRenest && kits.length && !leaving) { pendingRenest = false; nest(); return; }
    showBlocked(error.message);
  }
  renderActions();
}

function requestNest() {
  clearTimeout(nestTimer);
  nestTimer = setTimeout(() => {
    if (leaving || saving || !kits.length) return;
    if (busy) { pendingRenest = true; return; }
    nest();
  }, 150);
}

async function nest() {
  if (busy || saving || !kits.length) return;
  if (inputIssue()) { showBlocked(inputIssue()); return; }
  try {
    const roll = preset();
    const job = EZNQueue.compose(kits, roll, 'combined');
    job.outputProfile = profileFor(kits);
    job.settings.seed = 42;
    const option = $('material').selectedOptions[0];
    job.media = {
      name: option.dataset.name || roll.name,
      rollWidthMm: $('roll').value.trim() ? Number($('roll').value) * scale() : null,
      printableWidthMm: chosenWidthInches() * 25.4,
      maxPrintableMm: maxPrintableMm(),
      markMarginMm: $('mark-margin').value.trim() ? Number($('mark-margin').value) * scale() : 0,
      printer: option.dataset.printer || '',
      quickSet: option.dataset.quickset || '',
      hotFolderLabel: HOT_FOLDER_LABEL
    };
    busy = true;
    current = null;
    showSheetId(null);
    blockReason = '';
    activeSheet = 0;
    showScreen('nest');
    showLive({job});
    renderActions();
    status('Nesting on ' + $('nest-width').value + ' in…');
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

function applyAutoBleed(svg, job, result) {
  const mm = autoBleedMm();
  if (!(mm > 0)) return svg;
  result.placements.forEach((placement, index) => {
    const part = job.parts.find(item => item.id === placement.id);
    const artwork = svg.querySelector('#ez-part-' + (index + 1));
    const node = artwork?.querySelector('[data-ezn-boundary="true"]');
    if (!node || node.closest('defs')) return;
    // A source viewBox or nested transform can make one source unit many mm.
    // Imported points already include those transforms. Draw their bleed in
    // output millimeters, cancelling the source-parent transform while keeping
    // its clipping and opacity ancestry. The original artwork/cut is untouched.
    let fill = null;
    for (let ancestor = node; ancestor && ancestor !== svg; ancestor = ancestor.parentElement) {
      if (ancestor.hasAttribute('fill')) { fill = ancestor.getAttribute('fill'); break; }
    }
    if (!fill || fill === 'none' || fill === 'transparent' || /^url\(/i.test(fill)) return;
    if (node.hasAttribute('clip-path')) throw Error('SVG auto bleed cannot preserve this boundary clip. Turn auto bleed off or export a PDF.');
    let parent = svg.createSVGMatrix();
    for (let ancestor = node.parentElement; ancestor && ancestor !== svg; ancestor = ancestor.parentElement) {
      const local = ancestor.transform?.baseVal.consolidate()?.matrix;
      if (local) parent = local.multiply(parent);
    }
    let inverse;
    try { inverse = parent.inverse(); }
    catch (_) { throw Error('SVG auto bleed cannot use this transform. Turn auto bleed off or export a PDF.'); }
    const values = [inverse.a, inverse.b, inverse.c, inverse.d, inverse.e, inverse.f];
    if (!values.every(Number.isFinite)) throw Error('SVG auto bleed cannot use this transform. Turn auto bleed off or export a PDF.');
    const bleed = document.createElementNS(NS, 'polygon');
    bleed.setAttribute('data-ezn-bleed', '1');
    bleed.setAttribute('points', part.points.map(point => point.join(',')).join(' '));
    bleed.setAttribute('transform', `matrix(${values.join(' ')}) translate(${placement.x} ${placement.y}) rotate(${placement.rotation})`);
    bleed.setAttribute('fill', fill);
    bleed.setAttribute('stroke', fill);
    bleed.setAttribute('stroke-width', String(2 * mm));
    bleed.setAttribute('stroke-linejoin', 'round');
    bleed.setAttribute('stroke-dasharray', 'none');
    bleed.setAttribute('stroke-opacity', '1');
    for (const name of ['fill-opacity', 'opacity', 'color']) {
      if (node.hasAttribute(name)) bleed.setAttribute(name, node.getAttribute(name));
    }
    node.parentNode.insertBefore(bleed, node);
  });
  return svg;
}

async function lock() {
  if (!current || current.released || busy || saving) return current;
  saving = true;
  renderActions();
  try {
    let artwork = null;
    if (!current.job.documentSources) {
      const art = EZNSVG.buildSVG(current.job, current.result);
      applyAutoBleed(art, current.job, current.result);
      artwork = EZNSVG.serialize(art);
    }
    const released = await api('/api/release', {
      id: current.id,
      artwork,
      map: EZNSVG.serialize(sheetMap(current)),
      autoBleedMm: autoBleedMm(),
      drawRegmarks: $('draw-marks').checked === true,
      cutMapping: cutMapping(),
      stagingFolder: stagingPath()
    });
    current.released = true;
    current.sha256 = released.sha256;
    current.savedPath = released.savedPath || '';
    current.deliveryCompleted = released.deliveryCompleted === true;
    showLock(current);
    showSheetId(current);
    return current;
  } finally {
    saving = false;
    renderActions();
  }
}

function sheetSummary() {
  const option = $('material').selectedOptions[0];
  const material = (option.dataset.name || option.textContent || 'Material').trim();
  const width = String(Number(Number($('nest-width').value).toFixed(4)));
  const length = (current.result.usedLength / 25.4).toFixed(1);
  const pieces = current.manifest ? current.manifest.totalPieces : 0;
  return [
    material,
    width + ' in wide',
    length + ' in long',
    pieces + (pieces === 1 ? ' piece' : ' pieces'),
    current.id
  ].join('\n');
}

function openConfirm() {
  if (busy || saving || !current || !current.result || $('export').disabled) return;
  $('confirm-summary').textContent = sheetSummary();
  showScreen('confirm');
  showSheetId(current);
}

function closeConfirm() {
  if (document.body.dataset.step !== 'confirm') return;
  showScreen('check');
  showSheetId(current);
  renderActions();
}

async function exportFile(forceDownload) {
  if (!current || busy || saving) return;
  if (document.body.dataset.step !== 'confirm' && $('export').disabled) return;
  try {
    if (!current.released) await lock();
    else await api('/api/release', {
      id: current.id,
      map: EZNSVG.serialize(sheetMap(current)),
      stagingFolder: stagingPath()
    });
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
  pendingRenest = false;
  renderKit();
  renderFiles();
  showScreen('drop');
  status('Drop your files.');
}

async function stopNest() {
  if (!busy) return;
  pendingRenest = false;
  try { await api('/api/cancel', {keepBest: true}); }
  catch (error) { status(error.message, true); }
}

async function startOver() {
  leaving = true;
  pendingRenest = false;
  if (busy) {
    try { await api('/api/cancel', {}); } catch { /* The next drop starts clean. */ }
  }
  busy = false;
  nextKit();
  leaving = false;
}

function convertUnit(next) {
  const previous = $('unit').dataset.current || next;
  const factor = EZNQueue.unitScale(previous) / EZNQueue.unitScale(next);
  for (const id of ['width', 'gap', 'margin', 'sheet', 'mark-margin', 'roll']) {
    if (!$(id).value.trim()) continue;
    $(id).value = String(Number((Number($(id).value) * factor).toFixed(4)));
  }
  $('unit').dataset.current = next;
  for (const node of document.querySelectorAll('span[data-unit]')) node.textContent = next;
}

function stagingPath() {
  if (!$('staging-on').checked) return '';
  return $('staging-folder').value.trim();
}

function renderMaterialButtons() {
  const box = $('materials');
  const currentValue = $('material').value;
  box.replaceChildren();
  for (const option of $('material').options) {
    const button = document.createElement('button');
    button.type = 'button';
    button.dataset.value = option.value;
    button.textContent = option.dataset.name || option.textContent.split('·')[0].trim();
    button.setAttribute('aria-pressed', String(option.value === currentValue));
    button.addEventListener('click', () => {
      if ($('material').value === option.value) return;
      $('material').value = option.value;
      applyMaterial();
      requestNest();
    });
    box.append(button);
  }
}

function applyMaterial(quiet) {
  const option = $('material').selectedOptions[0];
  const named = option.dataset.name || (option.dataset.width ? option.textContent.split('·')[0].trim() : '');
  $('preset-name').value = named || ($('preset-name').value || 'Custom roll');
  if (option.dataset.width) {
    $('unit').value = option.dataset.unit || 'in';
    $('unit').dataset.current = $('unit').value;
    $('width').value = option.dataset.width;
    $('nest-width').value = String(Number((Number(option.dataset.width) * EZNQueue.unitScale(option.dataset.unit || 'in') / 25.4).toFixed(4)));
    $('roll').value = option.dataset.roll || option.dataset.width;
    for (const node of document.querySelectorAll('span[data-unit]')) node.textContent = $('unit').value;
  }
  renderMaterialButtons();
  if (!quiet) saveShop();
}

function saveShop() {
  savePrefs({
    nestWidth: $('nest-width').value,
    material: $('material').value,
    thru: $('thru-name').value,
    kiss: $('kiss-name').value,
    cutPreset: $('cut-preset').value,
    hotFolder: $('hot-folder').value,
    stagingOn: $('staging-on').checked,
    stagingFolder: $('staging-folder').value
  });
}

function applyCutPreset() {
  const names = CUT_PRESETS[$('cut-preset').value];
  if (!names) return;
  $('thru-name').value = names.thru;
  $('kiss-name').value = names.kiss;
}

function matchCutPreset() {
  const thru = $('thru-name').value.trim();
  const kiss = $('kiss-name').value.trim();
  const match = Object.entries(CUT_PRESETS).find(([, names]) => names.thru === thru && names.kiss === kiss);
  $('cut-preset').value = match ? match[0] : 'custom';
}

function watchWidth() {
  const width = $('width').value;
  const unit = $('unit').value;
  const match = [...$('material').options].find(option => option.dataset.unit === unit && option.dataset.width === width);
  $('material').value = match ? match.value : 'custom';
  renderMaterialButtons();
  renderActions();
}

function rememberPreset() {
  const option = $('material').selectedOptions[0];
  const name = $('preset-name').value.trim();
  if (!name) return;
  if (option.value === 'custom') option.textContent = name;
  else option.textContent = name + ' · ' + ($('width').value || option.dataset.width || '') + ' ' + $('unit').value;
  renderMaterialButtons();
  const stored = prefs();
  stored.presets = stored.presets || {};
  stored.presets[option.value] = {label: option.textContent, width: $('width').value, unit: $('unit').value};
  savePrefs(stored);
}

function showLan(shop) {
  const on = $('lan').checked;
  $('lan-note').hidden = !on;
  $('lan-note').textContent = (shop && shop.warning) || 'Anyone on the shop LAN can Send to ONYX. Do not share this network with guest WiFi.';
  const bits = [];
  if (shop && shop.url) bits.push(shop.url);
  if (shop && shop.addresses && shop.addresses.length) bits.push(shop.addresses[0]);
  $('lan-address').textContent = bits.filter(Boolean).join(' · ');
  $('lan-address').hidden = !on;
}

function showHotDefault(path) {
  $('hot-default').textContent = path ? 'Default ' + path : '';
  if (!$('hot-folder').value && path) $('hot-folder').placeholder = path;
}

function showRestart(shop) {
  const note = $('lan-restart');
  if (!shop || !shop.restart) {
    note.hidden = true;
    note.textContent = '';
    return;
  }
  note.hidden = false;
  note.textContent = shop.lan ? 'Restart eznest to open the shop network.' : 'Shop network turns off after you restart eznest.';
}

function applyShop(shop) {
  $('app-version').textContent = shop.version || '';
  $('onyx-pc').checked = shop.onyxPc === true;
  $('lan').checked = shop.lan === true;
  $('updates').checked = !shop || shop.updates !== false;
  $('update').hidden = !$('updates').checked;
  showLan(shop);
  showRestart(shop);
  showHotDefault(shop.hotFolderDefault);
}

async function saveDeploy() {
  const result = await api('/api/shop', {lan: $('lan').checked, onyxPc: $('onyx-pc').checked, updates: $('updates').checked});
  applyShop(result);
  if (result.restart && result.lan) status('Restart eznest to open the shop network.');
  else if (result.restart) status('Shop network turns off after you restart eznest.');
}

async function saveHotFolder() {
  const path = $('hot-folder').value.trim();
  try {
    const result = await api('/api/output/connect', {path});
    $('hot-folder').value = result.path || '';
    saveShop();
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

async function readEntry(file) {
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
      } else if (/\.ai$/i.test(file.name)) throw Error('Save as PDF');
      else throw error;
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
    id: 'web-' + revision.slice(0, 12) + '-' + (fileSerial++), name: file.name, sourceFile: file.name, revision,
    origin: 'files', role: 'required', customer: '', order: '', kit: '', materialId: 'web-roll',
    sets: sets(), selected: true, status: 'ready', data, file, unresolved: unresolvedCut
  };
}

async function importFiles(fileList, replace) {
  const files = [...fileList].filter(Boolean);
  if (!files.length || busy || saving) return;
  const incomingPdf = files.some(file => /\.(pdf|ai)$/i.test(file.name));
  const incomingSvg = files.some(file => /\.svg$/i.test(file.name));
  const havePdf = !replace && kits.some(entry => entry.data?.format === 'pdf');
  const haveSvg = !replace && kits.some(entry => entry.data?.format === 'svg');
  if ((incomingPdf && incomingSvg) || (incomingPdf && haveSvg) || (incomingSvg && havePdf)) {
    throw Error('Nest SVG files in one batch and PDF files in another. That keeps the original artwork.');
  }
  status('Reading ' + files.length + (files.length === 1 ? ' file…' : ' files…'));
  const entries = [];
  for (const file of files) entries.push(await readEntry(file));
  kits = replace ? entries : kits.concat(entries);
  current = null;
  blockReason = '';
  leaving = false;
  renderFiles();
  showScreen('nest');
  status('Nesting…');
  requestNest();
}

function renameCut(markup, from, to) {
  const renamed = markup
    .replaceAll('data-name="' + from + '"', 'data-name="' + to + '"')
    .replaceAll('id="' + from + '"', 'id="' + to + '"');
  if (renamed !== markup) return renamed;
  const doc = new DOMParser().parseFromString('<svg xmlns="' + NS + '">' + markup + '</svg>', 'image/svg+xml');
  const group = doc.createElementNS(NS, 'g');
  group.setAttribute('id', to);
  group.setAttribute('data-name', to);
  while (doc.documentElement.firstChild) group.appendChild(doc.documentElement.firstChild);
  return new XMLSerializer().serializeToString(group).replace(/ xmlns="[^"]*"/, '');
}

let cutChoice = 'kiss';

function selectCut(operation) {
  if (busy || saving || !unresolved()) return;
  if (!plainContour()) {
    chooseCut(operation);
    return;
  }
  cutChoice = operation === 'thru' ? 'thru' : 'kiss';
  $('choose-kiss').setAttribute('aria-pressed', cutChoice === 'kiss' ? 'true' : 'false');
  $('choose-thru').setAttribute('aria-pressed', cutChoice === 'thru' ? 'true' : 'false');
}

function confirmCut() {
  if (busy || saving || !plainContour()) return;
  chooseCut(cutChoice === 'thru' ? 'thru' : 'kiss');
}

async function chooseCut(operation) {
  if (busy || saving || !unresolved()) return;
  const output = operation === 'kiss' ? $('kiss-name').value.trim() : $('thru-name').value.trim();
  if (kits.some(entry => entry.data?.format === 'pdf')) {
    const files = kits.map(entry => entry.file).filter(Boolean);
    $('generic-cut').value = operation;
    try {
      await importFiles(files, true);
    } catch (error) {
      showBlocked(error.message);
    } finally {
      $('generic-cut').value = '';
    }
    return;
  }
  for (const entry of kits) {
    for (const part of entry.data?.parts || []) {
      const unknowns = (part.cutRefs || []).filter(ref => !['thru', 'kiss', 'regmark'].includes(mappedOperation(ref.source, ref.name)));
      if (part.svg && part.svg.markup) {
        let markup = part.svg.markup;
        for (const ref of unknowns) markup = renameCut(markup, ref.name, output);
        part.svg.markup = markup;
      }
      if (!unknowns.length) continue;
      part.cutRefs = (part.cutRefs || []).filter(ref => !unknowns.includes(ref));
      part.cutRefs.push({source: 'spot', name: output});
    }
    entry.unresolved = false;
  }
  blockReason = '';
  requestNest();
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
  if (stored.material && [...$('material').options].some(option => option.value === stored.material)) {
    $('material').value = stored.material;
    applyMaterial(true);
  }
  if (stored.nestWidth) {
    $('nest-width').value = stored.nestWidth;
    showWidth();
  }
  if (stored.thru) $('thru-name').value = stored.thru;
  if (stored.kiss) $('kiss-name').value = stored.kiss;
  if (stored.thru || stored.kiss) matchCutPreset();
  $('staging-on').checked = stored.stagingOn === true;
  if (stored.stagingFolder) $('staging-folder').value = stored.stagingFolder;
  $('staging-row').hidden = !$('staging-on').checked;
  renderMaterialButtons();
  $('allow-undo').checked = stored.undo === true;
  $('allow-hold').checked = stored.hold === true;
  await ensureLibraries();
  await ensureStyles();
  const session = await fetchJsonRetry('/api/session');
  token = session.token;
  try {
    const folder = await fetchJson('/api/output', 5000);
    if (folder.path) $('hot-folder').value = folder.path;
    else if (stored.hotFolder) $('hot-folder').value = stored.hotFolder;
  } catch { /* The folder status is optional. */ }
  try {
    applyShop(await fetchJson('/api/shop', 5000));
  } catch { /* Shop network settings stay off when the lookup does not answer. */ }
  const state = await fetchJsonRetry('/api/state');
  if (state.status === 'running') { busy = true; showScreen('nest'); renderActions(); setTimeout(poll, 300); }
  else if (state.status === 'ready' && state.manifest) showResult(state);
  else { showScreen('drop'); status('Drop your files.'); }
  renderActions();
  document.body.dataset.ready = '1';
  refreshUpdate().catch(() => {});
}

function showUpdate(info) {
  const note = $('update-note');
  $('update').textContent = info && info.applyOnRestart ? 'Install now' : 'Update';
  if (info && info.rollback) {
    note.hidden = false;
    note.textContent = info.rollback.reason || info.message || '';
    return;
  }
  if (info && (info.applyOnRestart || info.updateAvailable) && info.message) {
    note.hidden = false;
    note.textContent = info.message;
    return;
  }
  note.hidden = true;
  note.textContent = '';
}

async function refreshUpdate(remote) {
  const version = $('app-version').textContent || '';
  $('report').href = 'https://github.com/ezdesigns/eznest/issues/new?' + new URLSearchParams({
    template: 'tester-problem.yml',
    title: 'Problem in eznest ' + (version || '1.0.0-rc.1'),
    version: version
  });
  try {
    const notes = await (await fetch('/api/changelog')).json();
    const entries = Array.isArray(notes.entries) ? notes.entries : [];
    const current = entries.find(entry => entry.version === notes.version) || entries[0];
    $('notes-body').textContent = current && current.body ? current.body : '';
  } catch { /* What's new stays empty if the changelog is missing. */ }
  showUpdate(await (await fetch(remote ? '/api/update?refresh=1' : '/api/update')).json());
}

document.addEventListener('DOMContentLoaded', () => {
  renderMaterialButtons();
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
  $('sets-dec').addEventListener('click', () => {
    $('sets').value = String(Math.max(1, (Number($('sets').value) || 1) - 1));
    applySetsToFiles();
    requestNest();
  });
  $('sets-inc').addEventListener('click', () => {
    $('sets').value = String(Math.min(PIECE_CAP, (Number($('sets').value) || 1) + 1));
    applySetsToFiles();
    requestNest();
  });
  const renestFromSets = () => {
    applySetsToFiles();
    requestNest();
  };
  $('sets').addEventListener('input', renestFromSets);
  $('sets').addEventListener('change', renestFromSets);
  $('unit').addEventListener('change', () => { convertUnit($('unit').value); watchWidth(); requestNest(); });
  $('material').addEventListener('change', () => { applyMaterial(); requestNest(); });
  $('width').addEventListener('input', () => { watchWidth(); requestNest(); });
  $('nest-width').addEventListener('input', () => { showWidth(); saveShop(); requestNest(); });
  $('nest-width').addEventListener('change', () => { saveShop(); requestNest(); });
  for (const id of ['gap', 'margin', 'sheet', 'mark-margin']) $(id).addEventListener('input', requestNest);
  for (const id of ['width', 'gap', 'margin', 'sheet', 'mark-margin', 'rotations']) $(id).addEventListener('change', requestNest);
  $('cut-preset').addEventListener('change', () => { applyCutPreset(); saveShop(); });
  $('thru-name').addEventListener('input', () => { matchCutPreset(); saveShop(); });
  $('kiss-name').addEventListener('input', () => { matchCutPreset(); saveShop(); });
  $('auto-bleed').addEventListener('change', requestNest);
  $('preset-name').addEventListener('change', rememberPreset);
  $('settings').addEventListener('toggle', () => { if ($('settings').open) refreshUpdate(true).catch(() => {}); });
  $('hot-folder').addEventListener('change', saveHotFolder);
  $('staging-on').addEventListener('change', () => {
    $('staging-row').hidden = !$('staging-on').checked;
    saveShop();
  });
  $('staging-folder').addEventListener('change', saveShop);
  $('lan').addEventListener('change', () => { saveDeploy().catch(error => status(error.message, true)); });
  $('onyx-pc').addEventListener('change', () => { saveDeploy().catch(error => status(error.message, true)); });
  $('updates').addEventListener('change', () => { saveDeploy().catch(error => status(error.message, true)); });
  $('update').addEventListener('click', async () => {
    const installNow = $('update').textContent === 'Install now';
    try {
      const result = await api('/api/update', {when: installNow ? 'now' : 'restart'});
      status(result.message);
      showUpdate(result);
      if (result.restarting) {
        $('update-note').hidden = false;
        $('update-note').textContent = result.message;
      }
    } catch (error) {
      const offline = /Failed to fetch|NetworkError/i.test(String(error.message || error));
      if (installNow && offline) {
        status('eznest is restarting to install the update.');
        return;
      }
      status(error.message, true);
    }
  });
  $('allow-undo').addEventListener('change', () => { savePrefs({undo: $('allow-undo').checked}); renderActions(); });
  $('allow-hold').addEventListener('change', () => savePrefs({hold: $('allow-hold').checked}));
  $('export').addEventListener('click', () => openConfirm());
  $('confirm-send').addEventListener('click', () => exportFile(false));
  $('confirm-back').addEventListener('click', closeConfirm);
  $('choose-thru').addEventListener('click', () => selectCut('thru'));
  $('choose-kiss').addEventListener('click', () => selectCut('kiss'));
  $('choose-confirm').addEventListener('click', confirmCut);
  $('start-over').addEventListener('click', startOver);
  $('more').addEventListener('change', async event => {
    try { await importFiles(event.target.files); }
    catch (error) { showBlocked(error.message); }
    finally { event.target.value = ''; }
  });
  $('stop').addEventListener('click', stopNest);
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
    if (event.target.closest('input, select, textarea, summary, #choose-thru, #choose-kiss, #choose-confirm, #confirm-send, #confirm-back, #materials, #sets-dec, #sets-inc, #sheet-tabs, #files, #add-files, #stop, #update')) return;
    if (document.body.dataset.step === 'blocked' || $('gate').classList.contains('problem')) { event.preventDefault(); return; }
    if (busy || saving) return;
    if (document.body.dataset.step === 'sent') { event.preventDefault(); startOver(); return; }
    if (document.body.dataset.step === 'confirm') { event.preventDefault(); exportFile(); return; }
    if (document.body.dataset.step === 'check' && current && current.result && !$('export').disabled) { event.preventDefault(); openConfirm(); }
  });
  boot().catch(error => status(error.message, true));
});
