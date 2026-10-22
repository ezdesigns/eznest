'use strict';
const NS = 'http://www.w3.org/2000/svg';
const $ = id => document.getElementById(id);
const PREF = 'eznest-placeholders';
const PIECE_CAP = 800;
let token = '';
let localSave = false;
let folderView = null;
let browsingFolders = false;
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
let illustratorHandoff = null;
let illustratorLoading = false;
let materialProfiles = {};
let presetEditor = null;
let activeMaterial = 'white-gloss';
const MATERIAL_FIELDS = ['preset-name', 'roll', 'width', 'mark-margin', 'gap', 'margin', 'rotations', 'unit', 'sheet', 'roll-length', 'available-length', 'low-stock', 'auto-bleed', 'bleed', 'cost'];

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
  try { localStorage.setItem(PREF, JSON.stringify({...prefs(), ...patch})); return true; }
  catch { status('This browser could not save your preferences. Check its storage settings.', true); return false; }
}

// Explain effects beside the controls, without adding instructions to the job flow.
function installSettingsHelp() {
  const help = {
    'cut-preset': ['Cut line names', 'Choose the names your print software recognizes. This changes exported cut names; it does not create missing cut lines.'],
    'thru-name': ['Cut through backing', 'The name your print software uses for a full cut. It must match your cutter setup. Changing this name does not set the blade depth.'],
    'kiss-name': ['Cut sticker only', 'The name your print software uses to cut the sticker and leave the backing. It must match your cutter setup.'],
    'generic-cut': ['Unlabelled cut lines', 'Choose how to treat lines named only CutContour in the next file you add. Ask me keeps you in control when the cut type is unclear.'],
    'hot-folder': ['Default print folder', 'The folder selected automatically when you save. Choose My computer to save somewhere else. A folder watched by your print software may start processing saved files.'],
    'printer': ['Printer name', 'A label for your shop setup. Changing it does not connect a printer or change print quality.'],
    'staging-on': ['Keep an extra copy', 'Also save the finished pack in the extra copy folder when you send it.'],
    'staging-folder': ['Extra copy folder', 'Choose where the extra copy is saved. This does not replace the main destination.'],
    'onyx-pc': ['ONYX is on this computer', 'Changes the suggested output folder for this PC. It does not install ONYX or move your files.'],
    'lan': ['Other computers can connect', 'Shows whether this app was started for the shop network. A saved setting cannot open network access. The separate trial stays on this PC.'],
    'updates': ['Look for app updates', 'Checks for newer app versions. Separate shop trials keep update checks off and are updated by opening a new tested build.'],
    'test-channel': ['Include test versions', 'When update checks are enabled, also show releases still being tested. Leave off for normal shop use.'],
    'allow-undo': ['Show Undo send', 'Lets you remove a sent pack while it is still in the output folder. This cannot stop a job that ONYX has already picked up.'],
    'preset-name': ['Material name', 'The name on the material button. Save separate materials when rolls need different widths or spacing.'],
    'unit': ['Units (inches or metric)', 'Shows these dimensions in inches, millimeters or centimeters. Existing values are converted, so the artwork stays the same size.'],
    'roll': ['Roll width', 'The full width of the material. Printable width must fit inside it. Increasing this alone does not make the layout wider.'],
    'width': ['Printable width', 'How much of the roll your printer can use. A smaller width can make the layout longer. Pieces keep their original size.'],
    'gap': ['Space between pieces', 'Space between the outer artwork edges, including existing bleed. More space keeps pieces farther apart and usually uses more material.'],
    'margin': ['Space at roll edges', 'Keeps pieces away from the sides. More space leaves less room for pieces and may make the layout longer.'],
    'roll-length': ['Full roll length', 'The length of a new roll. This is a reference for your material list. Material left on roll is the amount available for this job.'],
    'available-length': ['Material left on roll', 'Limits the batch to this much material. Leave blank if unknown. Update it yourself after printing; the app does not subtract used stock yet.'],
    'low-stock': ['Low-stock alert at', 'Show a red Low stock notice when the saved material left is at or below this length. Leave blank to use 10% of the full roll length, when known. Update material left after printing.'],
    'sheet': ['Longest print section', 'Splits a long layout into sections no longer than this. A lower number can create more sections. Every piece must fit within one section.'],
    'rotations': ['Allowed turns', 'Lets pieces turn to fit closer together. Keep orientation leaves them facing the original direction. Consider material grain and artwork direction.'],
    'mark-margin': ['Room for cutter marks', 'Reserves extra space at the edges, in addition to edge spacing. This does not draw marks; your print software can add them.'],
    'auto-bleed': ['Enlarge artwork at edges', 'Enlarges the artwork slightly around unchanged cut lines. It can change the design near the edges. Leave off for prepared print files and inspect any changed preview.'],
    'bleed': ['Existing color beyond cuts', 'How far the artwork already extends beyond its cut lines, in millimeters. Set this before adding files. It preserves that area during import; it does not create new color.'],
    'cost': ['Material cost per m²', 'Used for a material-cost estimate only. Changing it does not change the layout or charge a customer.'],
    'draw-marks': ['Add cutter marks', 'Draws registration marks in the output. Leave off if ONYX adds its own marks, so you do not get two sets.']
  };
  for (const [setup, main] of Object.entries({'setup-hot': 'hot-folder', 'setup-onyx': 'onyx-pc', 'setup-printer': 'printer', 'setup-thru': 'thru-name', 'setup-kiss': 'kiss-name', 'setup-units': 'unit'})) help[setup] = help[main];
  const tip = document.createElement('div');
  tip.id = 'setting-help'; tip.className = 'setting-help'; tip.role = 'tooltip'; tip.hidden = true;
  document.body.append(tip);
  let active = null, pinned = false, timer = 0;
  function close() {
    clearTimeout(timer);
    if (active) { active.setAttribute('aria-expanded', 'false'); active.removeAttribute('aria-describedby'); }
    active = null; pinned = false; tip.hidden = true;
  }
  function show(button, message) {
    clearTimeout(timer);
    if (active !== button) close();
    active = button; tip.textContent = message; tip.hidden = false;
    button.setAttribute('aria-expanded', 'true'); button.setAttribute('aria-describedby', tip.id);
    const r = button.getBoundingClientRect();
    const box = tip.getBoundingClientRect();
    tip.style.left = Math.max(12, Math.min(r.left, innerWidth - box.width - 12)) + 'px';
    tip.style.top = Math.max(12, r.bottom + box.height + 8 < innerHeight ? r.bottom + 8 : r.top - box.height - 8) + 'px';
  }
  const later = () => { if (!pinned) timer = setTimeout(close, 180); };
  tip.addEventListener('mouseenter', () => clearTimeout(timer));
  tip.addEventListener('mouseleave', later);
  for (const [id, [name, message]] of Object.entries(help)) {
    const input = $(id), original = input.closest('label');
    const field = document.createElement('div');
    for (const attr of original.attributes) field.setAttribute(attr.name, attr.value);
    field.classList.add('setting-field');
    const heading = document.createElement('span'); heading.className = 'setting-heading';
    const label = document.createElement('label'); label.htmlFor = id; label.textContent = name;
    const button = document.createElement('button');
    button.type = 'button'; button.className = 'setting-info'; button.textContent = 'i';
    button.setAttribute('aria-label', 'About ' + name); button.setAttribute('aria-expanded', 'false'); button.setAttribute('aria-controls', tip.id);
    heading.append(label, button);
    for (const child of [...original.childNodes]) {
      if (child.nodeType === Node.TEXT_NODE && child.textContent.trim()) field.append(heading);
      else field.append(child);
    }
    original.replaceWith(field);
    button.addEventListener('mouseenter', () => show(button, message));
    button.addEventListener('mouseleave', later);
    button.addEventListener('focus', () => show(button, message));
    button.addEventListener('blur', () => { if (!pinned) close(); });
    button.addEventListener('click', () => {
      if (active === button && pinned) close();
      else { show(button, message); pinned = true; }
    });
  }
  document.addEventListener('keydown', event => { if (event.key === 'Escape') close(); });
  document.addEventListener('pointerdown', event => { if (!event.target.closest('.setting-info, .setting-help')) close(); });
  document.addEventListener('scroll', close, true);
  window.addEventListener('resize', close);
  $('settings').addEventListener('toggle', close);
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
  return 0; // Prepared artwork keeps its original size and bleed.
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
  if (illustratorHandoff || current?.job?.illustrator) {
    mapping.outputs.thru.layer = 'thru-cut';
    mapping.outputs.kiss.layer = 'kiss cut';
  }
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
  if ($('available-length').value.trim() && Number($('available-length').value) === 0) throw Error('This material is out of stock. Update material left or choose another roll.');
  const factor = scale();
  const number = id => Number($(id).value) * factor;
  const printable = chosenWidthInches() * 25.4;
  const edge = number('margin');
  const mark = $('mark-margin').value.trim() ? number('mark-margin') : 0;
  // The operator's width is the sheet. Mark clearance (and the edge) is reserved
  // inside it, so pieces nest on that width minus the mark margins.
  const settings = {
    width: printable,
    maxLength: $('available-length').value.trim() ? number('available-length') : null,
    gap: number('gap'),
    margin: edge + mark,
    edgeMargin: edge,
    markMargin: mark,
    seconds: Number($('seconds').value) || 30,
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
    colorMode: 'preserve', iccProfile: '', bleedMm: 0,
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
  if (Object.values(state.job?.documentSources || {}).some(source => !source.artworkPreserved)) return 'Re-add the original PDF to preserve its artwork and bleed. This older layout was clipped at import.';
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
  $('preview-tools').hidden = idle;
  $('legend').hidden = idle;
  $('readout').hidden = idle;
  $('export').hidden = idle || confirming;
  $('confirm').hidden = !confirming;
  $('start-over').hidden = idle || confirming;
  $('delivery-receipt').hidden = name !== 'sent';
  $('start-over').textContent = name === 'sent' ? 'Next job' : 'Start over';
  const steps = {drop: 1, nest: 2, blocked: 2, check: 2, confirm: 3, sent: 3};
  for (const node of document.querySelectorAll('[data-workflow-step]')) {
    if (Number(node.dataset.workflowStep) === steps[name]) node.setAttribute('aria-current', 'step');
    else node.removeAttribute('aria-current');
  }
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
  const show = kits.length > 0 && !['drop', 'confirm', 'sent'].includes(document.body.dataset.step);
  $('files').hidden = !show;
  $('add-files').hidden = !show || !!illustratorHandoff || document.body.dataset.step === 'nest';
  $('stop').hidden = document.body.dataset.step !== 'nest';
  $('improve').hidden = document.body.dataset.step !== 'check' || busy || !current || current.released;
  const locked = busy || !!presetEditor || document.body.dataset.step === 'nest';
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
      if (kits.every(item => item.sets === count)) $('sets').value = String(count);
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
  const confirming = document.body.dataset.step === 'confirm';
  syncFiles();
  for (const button of $('materials').querySelectorAll('button')) button.disabled = busy || saving || !!presetEditor || confirming;
  $('confirm-send').disabled = saving || busy || !!presetEditor;
  $('confirm-back').disabled = saving;
  $('start-over').disabled = saving || !!presetEditor;
  $('nest-width').disabled = !!presetEditor || confirming;
  $('sets').disabled = !!presetEditor || confirming;
  $('sets-dec').disabled = !!presetEditor || confirming;
  $('sets-inc').disabled = !!presetEditor || confirming;
  $('file').disabled = !!presetEditor || confirming;
  $('more').disabled = !!presetEditor || confirming;
  $('edit-material').disabled = busy || saving || !!presetEditor || !!illustratorHandoff || confirming;
  const badInput = inputIssue();
  const missing = current && current.result ? pieceIssue(current) : '';
  const cuts = current && current.result ? cutProblem() : null;
  const tooLong = current && current.result && lengthOver(current) ? 'Material is over the sheet length' : '';
  const step = document.body.dataset.step;
  const sent = step === 'sent' && current && current.released;
  $('export').textContent = sent ? 'Save again'
    : 'Review and save';
  $('export').classList.toggle('primary', !sent);
  $('export').classList.toggle('link', !!sent);
  $('start-over').classList.toggle('primary', !!sent);
  $('start-over').classList.toggle('link', !sent);
  $('length').classList.toggle('over', !!(current && current.result && lengthOver(current)));
  $('undo').hidden = !(sent && $('allow-undo').checked && current && current.savedPath);
  if (sent) {
    $('export').disabled = saving || !!presetEditor;
    return;
  }
  const actionable = step !== 'drop' && step !== 'nest';
  const reason = blockReason || missing || (cuts ? cuts.line : '') || tooLong || (actionable ? badInput : '');
  $('export').disabled = busy || saving || !!presetEditor || !!reason || !current || !current.result;
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
  const parts = new Map(state.job.parts.map(part => [part.id, part]));
  const sourcePieces = state.result.placements.reduce((sum, item) => sum + (parts.get(item.id)?.sourcePieceCount || 1), 0);
  const bits = [sourcePieces + (sourcePieces === 1 ? ' piece' : ' pieces')];
  if (sourcePieces > placed) bits.push(placed + ' groups keep artwork together');
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
      node.setAttribute('stroke', '#E6007E');
      node.setAttribute('stroke-dasharray', '8 6');
      node.setAttribute('stroke-width', '3');
    } else if (/thru-cut/i.test(node.id)) {
      node.setAttribute('stroke', '#00B7FF');
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
    // Packing envelopes include bleed; only actual cuts get a coloured overlay.
    // Older cached imports retain their raster cut preview until re-imported.
    for (const cut of part.previewCuts || []) {
      const outline = document.createElementNS(NS, 'path');
      outline.setAttribute('d', cut.d);
      outline.setAttribute('class', 'preview-cut');
      outline.dataset.operation = cut.operation;
      stroke(outline, cut.operation === 'kiss' ? '#E6007E' : '#00B7FF', cut.operation === 'kiss');
      outline.setAttribute('stroke-width', '1');
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
  feet.setAttribute('x', '0');
  feet.setAttribute('y', String(top + sheet.usedLength + scale * 1.3));
  feet.setAttribute('fill', '#111');
  feet.setAttribute('font-size', String(scale));
  feet.setAttribute('font-family', 'Rajdhani, sans-serif');
  feet.setAttribute('text-anchor', 'start');
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
  const h = sheet.usedLength + pad * 2 + 2;
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
  status('');
  $('delivery-receipt').textContent = current?.exportReceipt ? 'Saved to ' + current.exportReceipt.path : current?.savedPath
    ? 'Sent to the hot folder. Check the job in your RIP before printing.'
    : 'Pack downloaded. It has not been sent to a printer. Check your browser downloads.';
  if (current && current.manifest) setSentence(pieceSentence(current), false);
  renderActions();
}

function showBlocked(message) {
  status('');
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
  if (missing) showBlocked(missing);
  else if (state.exportReceipt || (state.deliveryCompleted && state.savedPath)) showSent();
  else if (cuts) showBlocked(cuts.line, cuts.detail);
  else {
    showScreen('check');
    renderActions();
  }
  status(state.note || '');
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
  setNum('sheets', String(live.sheets?.length || 1));
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
  if (presetEditor) return;
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
    job.webOptions = {units: $('unit').value, material: $('material').value, sets: sets(), genericCut: $('generic-cut').value};
    if (illustratorHandoff) {
      if (kits.length !== 1 || kits[0].revision !== illustratorHandoff.documentId) throw Error('Start over before mixing an Illustrator handoff with other jobs.');
      job.illustrator = {id: illustratorHandoff.id};
    }
    job.settings.seed = 42;
    const option = $('material').selectedOptions[0];
    job.media = {
      name: option.dataset.name || roll.name,
      rollWidthMm: $('roll').value.trim() ? Number($('roll').value) * scale() : null,
      printableWidthMm: chosenWidthInches() * 25.4,
      maxPrintableMm: maxPrintableMm(),
      markMarginMm: $('mark-margin').value.trim() ? Number($('mark-margin').value) * scale() : 0,
      printer: $('printer').value.trim() || option.dataset.printer || '',
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
    status('Finding a tighter fit… You can stop and keep the best layout.');
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

async function lock(downloadOnly = false) {
  if (!current || current.released || busy) return current;
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
      stagingFolder: downloadOnly ? '' : stagingPath(),
      downloadOnly
    });
    current.released = true;
    current.sha256 = released.sha256;
    current.savedPath = released.savedPath || '';
    current.deliveryCompleted = released.deliveryCompleted === true;
    showLock(current);
    showSheetId(current);
    return current;
  } finally { renderActions(); }
}

function openConfirm() {
  if (busy || saving || !current || !current.result || $('export').disabled) return;
  status('');
  const jobs = current.job.productionJobs || [];
  const sourceName = jobs[0]?.sourceFile || jobs[0]?.name || 'Print';
  const savedName = current.exportReceipt?.path?.split(/[\\/]/).pop()?.replace(/\.(pdf|zip)$/i, '');
  $('save-name').value = current.downloadName || savedName || cleanPrintName(sourceName.replace(/\.(pdf|ai|svg)$/i, '') + (jobs.length > 1 ? ' and ' + (jobs.length - 1) + ' more' : ''));
  $('save-destination').value = $('hot-folder').value.trim() ? 'folder' : localSave ? 'choose' : 'download';
  $('save-destination').querySelector('[value="folder"]').disabled = !$('hot-folder').value.trim();
  $('save-destination').querySelector('[value="choose"]').hidden = !localSave;
  $('save-destination').querySelector('[value="download"]').hidden = localSave;
  const onePdf = !!current.job.documentSources && (current.result.sheets || [1]).length === 1;
  $('save-format').querySelector('[value="pdf"]').disabled = !onePdf;
  $('save-format').value = onePdf ? 'pdf' : 'pack';
  updateSaveChoice();
  showScreen('confirm');
  showSheetId(current);
  renderActions();
}

function closeConfirm() {
  if (document.body.dataset.step !== 'confirm') return;
  showScreen('check');
  showSheetId(current);
  renderActions();
}

function cleanPrintName(value) {
  let name = String(value).replace(/[<>:"/\\|?*\x00-\x1f]/g, '-').replace(/[. ]+$/g, '').trim().slice(0, 100);
  if (!name || /^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)/i.test(name)) name = 'Print';
  return name;
}

function updateSaveChoice() {
  const mode = $('save-destination').value;
  $('save-name-row').hidden = mode === 'choose';
  $('save-location-note').textContent = mode === 'folder' ? $('hot-folder').value
    : mode === 'choose' ? '' : 'Your browser controls the download location.';
  $('confirm-send').textContent = mode === 'choose' ? 'Save to My Computer…' : mode === 'download' ? 'Download' : 'Save';
}

async function browseExportFolder(path) {
  if (browsingFolders) return;
  const dialog = $('folder-picker');
  if (!dialog.open) dialog.showModal();
  browsingFolders = true;
  $('folder-path').disabled = true;
  $('folder-go').disabled = true;
  $('folder-error').textContent = '';
  $('folder-use').disabled = true;
  try {
    folderView = await api('/api/export/folders', {path});
    $('folder-path').value = folderView.path;
    $('folder-up').disabled = folderView.parent === null;
    $('folder-list').replaceChildren();
    for (const entry of folderView.folders) {
      const button = document.createElement('button');
      button.type = 'button'; button.className = 'folder-entry'; button.textContent = entry.name;
      button.addEventListener('click', () => browseExportFolder(entry.path));
      $('folder-list').append(button);
    }
    if (!folderView.folders.length) $('folder-list').textContent = 'No subfolders';
    $('folder-use').disabled = !folderView.path;
  } catch (error) {
    $('folder-error').textContent = error.message;
  } finally {
    browsingFolders = false;
    $('folder-path').disabled = false;
    $('folder-go').disabled = false;
  }
}

async function exportFile(forceDownload) {
  if (!current || busy || saving) return;
  if (document.body.dataset.step !== 'confirm' && $('export').disabled) return;
  const mode = forceDownload === true ? 'download' : $('save-destination').value;
  const format = $('save-format').value;
  const pdf = format === 'pdf';
  const base = cleanPrintName($('save-name').value.replace(pdf ? /\.pdf$/i : /\.zip$/i, ''));
  const name = base + (pdf ? '.pdf' : '.zip');
  saving = true;
  renderActions();
  try {
    let chosenPath = null;
    if (mode === 'choose') {
      status('Choose a location in the Windows save window.');
      const selection = await api('/api/export/pick', {name: base, format});
      if (selection.cancelled) { status(''); return; }
      chosenPath = selection.path;
    }
    current.downloadName = base;
    if (!current.released) await lock(true);
    if (mode !== 'download') {
      status('Saving…');
      const request = {id: current.id, sha256: current.sha256, name: base, format, destination: mode, path: chosenPath,
        stagingFolder: mode === 'folder' ? stagingPath() : ''};
      let saved = await api('/api/export/save', request);
      if (saved.exists) {
        if (!confirm('Replace the existing file?\n' + saved.path + '\nThe previous version will be kept in the app’s local backups.')) { status(''); return; }
        saved = await api('/api/export/save', {...request, replaceSha256: saved.existingSha256});
        if (saved.exists) throw Error('The file changed. Choose Save again to review the replacement.');
      }
      current.exportReceipt = {path: saved.path, destination: mode, format};
      current.downloadName = saved.path.split(/[\\/]/).pop().replace(/\.(pdf|zip)$/i, '');
      showSent();
      return;
    }
    const response = await fetch('/api/batch/' + current.id);
    if (!response.ok) throw Error('The saved layout could not be downloaded. Try again.');
    let bytes = await response.arrayBuffer();
    const hash = await sha256(bytes);
    if (current.sha256 && hash !== current.sha256) throw Error('The download does not match the locked layout.');
    if (pdf) {
      const printResponse = await fetch('/api/print/' + current.id);
      if (!printResponse.ok) throw Error('Save the complete print pack for this layout.');
      bytes = await printResponse.arrayBuffer();
    }
    const link = document.createElement('a');
    link.href = URL.createObjectURL(new Blob([bytes], {type: pdf ? 'application/pdf' : 'application/zip'}));
    link.download = name;
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(link.href), 1000);
    showSent();
    $('delivery-receipt').textContent = 'Downloaded ' + name;
  } catch (error) {
    status(error.message, true);
  } finally {
    saving = false;
    renderActions();
  }
}

function nextKit() {
  illustratorHandoff = null;
  $('illustrator-load').hidden = false;
  renderMaterialButtons();
  kits = [];
  current = null;
  blockReason = '';
  activeSheet = 0;
  pendingRenest = false;
  renderKit();
  renderFiles();
  showScreen('drop');
  status('');
}

async function stopNest() {
  if (!busy) return;
  pendingRenest = false;
  try { await api('/api/cancel', {keepBest: true}); }
  catch (error) { status(error.message, true); }
}

async function startOver() {
  if (saving) return;
  leaving = true;
  pendingRenest = false;
  if (busy) {
    try { await api('/api/cancel', {}); } catch { /* The next drop starts clean. */ }
  }
  busy = false;
  try { await api('/api/work/discard', {}); }
  catch (error) { leaving = false; status(error.message, true); return; }
  nextKit();
  leaving = false;
}

function convertUnit(next) {
  const previous = $('unit').dataset.current || next;
  const factor = EZNQueue.unitScale(previous) / EZNQueue.unitScale(next);
  for (const id of ['width', 'gap', 'margin', 'sheet', 'mark-margin', 'roll', 'roll-length', 'available-length', 'low-stock']) {
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
  $('material').disabled = !!illustratorHandoff;
  box.replaceChildren();
  for (const option of $('material').options) {
    if (illustratorHandoff && option.value !== 'white-gloss') continue;
    const button = document.createElement('button');
    button.type = 'button';
    button.dataset.value = option.value;
    button.textContent = option.dataset.name || option.textContent.split('·')[0].trim();
    button.setAttribute('aria-pressed', String(option.value === currentValue));
    button.disabled = !!presetEditor || busy || saving;
    button.addEventListener('click', () => {
      chooseMaterial(option.value);
    });
    const item = document.createElement('div');
    item.className = 'material-item';
    item.append(button);
    const stock = lowStock(materialProfiles[option.value]);
    if (stock) {
      const notice = document.createElement('span');
      notice.className = 'stock-alert';
      notice.setAttribute('role', 'status');
      notice.textContent = stock;
      item.append(notice);
    }
    box.append(item);
  }
  const remaining = $('available-length').value.trim();
  $('material-summary').textContent = remaining ? `${Number(remaining)} ${$('unit').value} available` : '';

}

function lowStock(values) {
  if (!values || !String(values['available-length'] ?? '').trim()) return '';
  const left = Number(values['available-length']);
  const threshold = String(values['low-stock'] ?? '').trim() ? Number(values['low-stock']) : Number(values['roll-length'] || 0) * 0.1;
  if (!Number.isFinite(left) || left < 0 || !Number.isFinite(threshold) || left > threshold) return '';
  return (left === 0 ? 'Out of stock' : 'Low stock') + ' · ' + left + ' ' + values.unit + ' left';
}

function materialValues() {
  return {...Object.fromEntries(MATERIAL_FIELDS.map(id => [id, $(id).value])), drawMarks: $('draw-marks').checked};
}

function setMaterialValues(values) {
  for (const id of ['roll-length', 'low-stock']) if (values[id] == null) $(id).value = '';
  for (const id of MATERIAL_FIELDS) if (values[id] != null) $(id).value = values[id];
  $('unit').dataset.current = $('unit').value;
  $('draw-marks').checked = values.drawMarks === true;
  for (const node of document.querySelectorAll('span[data-unit]')) node.textContent = $('unit').value;
}

function validateMaterial(values) {
  if (!values || !['mm', 'cm', 'in'].includes(values.unit)) throw Error('Choose units for this preset.');
  const factor = EZNQueue.unitScale(values.unit);
  const n = id => Number(values[id]) * factor;
  const edge = n('margin'), mark = n('mark-margin');
  if (values['available-length']?.trim() && (!Number.isFinite(n('available-length')) || n('available-length') < 0)) throw Error('Material left must be zero or more, or blank if unknown.');
  const settings = {width: n('width'), maxLength: values['available-length']?.trim() && n('available-length') > 0 ? n('available-length') : null, gap: n('gap'), margin: edge + mark, edgeMargin: edge, markMargin: mark, seconds: 5,
    rotations: values.rotations === 'free' ? null : String(values.rotations).split(',').map(Number), rollWidth: n('roll')};
  if (values.sheet !== '') settings.sheetLength = n('sheet');
  if (values.cost !== '') settings.costPerSquareMeter = Number(values.cost);
  EZNQueue.validatePreset({name: values['preset-name'], units: values.unit, settings});
  if (settings.width > settings.rollWidth) throw Error('Printable width cannot be wider than the roll.');
  if (!['0', '0.0625', '0.125'].includes(values['auto-bleed'])) throw Error('Choose a supported bleed setting.');
  if (!Number.isFinite(Number(values.bleed)) || Number(values.bleed) < 0 || Number(values.bleed) > 25) throw Error('Existing bleed must be from 0 to 25 mm.');
  if (values['roll-length']?.trim() && (!Number.isFinite(n('roll-length')) || n('roll-length') <= 0)) throw Error('Enter a positive full roll length or leave it blank.');
  if (values['roll-length']?.trim() && values['available-length']?.trim() && n('available-length') > n('roll-length')) throw Error('Material left cannot exceed the full roll length.');
  if (values['low-stock']?.trim() && (!Number.isFinite(n('low-stock')) || n('low-stock') < 0)) throw Error('Enter a low-stock alert of zero or more, or leave it blank.');
  if (values['roll-length']?.trim() && values['low-stock']?.trim() && n('low-stock') > n('roll-length')) throw Error('The low-stock alert cannot exceed the full roll length.');
  return {'roll-length': '', 'available-length': '', 'low-stock': '', ...values, 'preset-name': values['preset-name'].trim()};
}

function registerMaterial(id, values) {
  let option = [...$('material').options].find(item => item.value === id);
  if (!option) {
    option = new Option(values['preset-name'], id);
    $('material').insertBefore(option, $('material').querySelector('[value="custom"]'));
  }
  option.textContent = values['preset-name'];
  Object.assign(option.dataset, {name: values['preset-name'], width: values.width, roll: values.roll, unit: values.unit});
  materialProfiles[id] = values;
}

function loadMaterialProfiles(stored) {
  registerMaterial('white-gloss', materialValues());
  const hiddenLegacy = (id, values) => id === 'moto' || values['preset-name'] === 'Design PC test roll';
  const renamed = (id, values) => ({...values, 'preset-name': id === 'holographic' && values['preset-name'] === 'Holographic' ? 'Moto Holographic' : id === 'chrome' && values['preset-name'] === 'Chrome' ? 'Moto Chrome' : values['preset-name']});
  for (const [id, saved] of Object.entries(stored.presets || {})) {
    if (id === 'custom' && !saved.label) continue;
    const values = {...materialValues(), 'preset-name': saved.label?.split(' · ')[0] || 'Saved roll', width: saved.width || '51.5', unit: saved.unit || 'in'};
    if (id === 'white-gloss' && /^White gloss/.test(values['preset-name'])) values['preset-name'] = 'Moto Regular';
    if (hiddenLegacy(id, values)) continue;
    try { registerMaterial(id === 'custom' ? 'saved-custom' : id, validateMaterial(values)); } catch { /* Keep legacy preferences intact if they need correction. */ }
  }
  for (const [id, values] of Object.entries(stored.materialProfiles || {})) {
    if (!/^[a-zA-Z0-9-]{1,80}$/.test(id) || id === 'custom') continue;
    if (hiddenLegacy(id, values)) continue;
    try { registerMaterial(id, validateMaterial(renamed(id, values))); } catch { status('A saved preset needs to be set up again.', true); }
  }
}

function chooseMaterial(id) {
  if (busy || saving || presetEditor || document.body.dataset.step === 'confirm') return;
  if (id === activeMaterial && materialProfiles[id]) return;
  if (id === 'custom' || !materialProfiles[id]) { openPreset(id); return; }
  $('material').value = id;
  applyMaterial();
  requestNest();
}

function openPreset(id) {
  if (busy || saving || presetEditor || illustratorHandoff || document.body.dataset.step === 'confirm') return;
  clearTimeout(nestTimer);
  presetEditor = {id, values: materialValues(), selected: $('material').value, nestWidth: $('nest-width').value};
  if (materialProfiles[id]) setMaterialValues(materialProfiles[id]);
  else {
    $('preset-name').value = id === 'custom' ? '' : [...$('material').options].find(option => option.value === id).textContent;
    for (const field of ['roll-length', 'available-length', 'low-stock']) $(field).value = '';
  }
  $('preset-title').textContent = id === 'custom' ? 'Add material' : 'Edit ' + $('preset-name').value;
  $('preset-error').hidden = true;
  $('preset-editor').hidden = false;
  $('material-advanced').open = false;
  renderMaterialButtons();
  renderActions();
  $('preset-name').focus();
}

function closePreset() {
  if (!presetEditor) return;
  const previous = presetEditor;
  presetEditor = null;
  setMaterialValues(previous.values);
  $('material').value = previous.selected;
  $('nest-width').value = previous.nestWidth;
  $('preset-editor').hidden = true;
  renderMaterialButtons();
  renderActions();
}

function saveMaterial() {
  if (!presetEditor) return;
  try {
    const values = validateMaterial(materialValues());
    const id = presetEditor.id === 'custom' ? 'material-' + crypto.randomUUID() : presetEditor.id;
    if (Object.entries(materialProfiles).some(([key, item]) => key !== id && item['preset-name'].toLowerCase() === values['preset-name'].toLowerCase())) throw Error('A preset with that name already exists. Choose another name.');
    const profiles = {...materialProfiles, [id]: values};
    localStorage.setItem(PREF, JSON.stringify({...prefs(), materialProfiles: profiles, material: id, nestWidth: String(Number(values.width) * EZNQueue.unitScale(values.unit) / 25.4)}));
    registerMaterial(id, values);
    presetEditor = null;
    $('preset-editor').hidden = true;
    $('material').value = id;
    applyMaterial(true);
    status('');
    renderActions();
    requestNest();
  } catch (error) {
    $('preset-error').textContent = error.message;
    $('preset-error').hidden = false;
  }
}

function applyMaterial(quiet) {
  const option = $('material').selectedOptions[0];
  activeMaterial = option.value;
  if (materialProfiles[option.value]) setMaterialValues(materialProfiles[option.value]);
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
  return savePrefs({
    nestWidth: $('nest-width').value,
    material: $('material').value,
    thru: $('thru-name').value,
    kiss: $('kiss-name').value,
    cutPreset: $('cut-preset').value,
    genericCut: $('generic-cut').value,
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
  if (presetEditor) return;
  const width = $('width').value;
  const unit = $('unit').value;
  const match = [...$('material').options].find(option => option.dataset.unit === unit && option.dataset.width === width);
  $('material').value = match ? match.value : 'custom';
  renderMaterialButtons();
  renderActions();
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
  $('hot-default').textContent = path ? 'EZ Designs preset: ' + path : '';
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
  note.textContent = 'Shop network requires starting eznest with --lan.';
}

function applyShop(shop) {
  $('app-version').textContent = shop.version || '';
  $('onyx-pc').checked = shop.onyxPc === true;
  $('lan').checked = shop.runningLan === true;
  $('updates').checked = !shop || shop.updates !== false;
  $('update').hidden = !$('updates').checked;
  $('test-channel').checked = shop.channel === 'test';
  $('output-network').checked = shop.outputNetwork === true;
  if (shop.outputNote) $('output-note').textContent = shop.outputNote;
  if (shop.printer) $('printer').value = shop.printer;
  if (shop.setupComplete && !prefs().thru && shop.thru) $('thru-name').value = shop.thru;
  if (shop.setupComplete && !prefs().kiss && shop.kiss) $('kiss-name').value = shop.kiss;
  matchCutPreset();
  if (shop.setupComplete && shop.units) {
    $('unit').value = shop.units;
    convertUnit(shop.units);
  }
  showLan(shop);
  showRestart(shop);
  showHotDefault(shop.hotFolderDefault);
  showSetup(shop);
  reportLink(shop);
}

function reportLink(shop) {
  const base = (shop && shop.issuesUrl) || $('report').getAttribute('href');
  try {
    const url = new URL(base);
    const version = (shop && shop.version) || $('app-version').textContent || '';
    if (version) url.searchParams.set('version', version);
    $('report').href = url.toString();
  } catch { /* Keep the link that shipped with the page. */ }
}

function showSetup(shop) {
  const panel = $('setup');
  if (!shop || shop.setupComplete) {
    panel.hidden = true;
    return;
  }
  panel.hidden = false;
  if (!$('setup-thru').value) $('setup-thru').value = $('thru-name').value;
  if (!$('setup-kiss').value) $('setup-kiss').value = $('kiss-name').value;
  $('setup-units').value = $('unit').value || 'in';
  if (shop.hotFolder && !$('setup-hot').value) $('setup-hot').value = shop.hotFolder;
  if (shop.printer && !$('setup-printer').value) $('setup-printer').value = shop.printer;
  $('setup-onyx').checked = $('onyx-pc').checked;
}

function applyEzPreset(shop) {
  const preset = (shop && shop.preset) || {};
  $('onyx-pc').checked = $('setup-onyx').checked;
  $('setup-hot').value = $('setup-onyx').checked ? (preset.localHotFolder || '') : (preset.shareHotFolder || '');
  $('setup-printer').value = preset.printer || '';
  $('setup-thru').value = preset.thru || '';
  $('setup-kiss').value = preset.kiss || '';
  $('setup-units').value = preset.units || 'in';
  $('setup-error').hidden = true;
}

async function saveSetup(shop) {
  const previous = $('unit').dataset.current || $('unit').value;
  $('unit').value = $('setup-units').value;
  if ($('unit').value !== previous) convertUnit($('unit').value);
  $('thru-name').value = $('setup-thru').value.trim();
  $('kiss-name').value = $('setup-kiss').value.trim();
  matchCutPreset();
  $('printer').value = $('setup-printer').value.trim();
  $('onyx-pc').checked = $('setup-onyx').checked;
  $('hot-folder').value = $('setup-hot').value.trim();
  const result = await api('/api/setup', shopPayload({
    setupComplete: true,
    printer: $('printer').value,
    units: $('unit').value,
    thru: $('thru-name').value,
    kiss: $('kiss-name').value,
    hotFolder: $('hot-folder').value
  }));
  applyShop(result);
  saveShop();
  await saveHotFolder();
  if ($('hot-error').hidden) {
    $('setup').hidden = true;
    $('setup-error').hidden = true;
  } else {
    $('setup-error').hidden = false;
    $('setup-error').textContent = $('hot-error').textContent;
    $('setup').hidden = false;
  }
}

function shopPayload(extra) {
  return Object.assign({
    lan: $('lan').checked,
    onyxPc: $('onyx-pc').checked,
    updates: $('updates').checked,
    channel: $('test-channel').checked ? 'test' : 'stable',
    outputNetwork: $('output-network').checked
  }, extra || {});
}

async function saveDeploy() {
  const result = await api('/api/shop', shopPayload({
    printer: $('printer').value.trim(),
    units: $('unit').value,
    thru: $('thru-name').value.trim(),
    kiss: $('kiss-name').value.trim()
  }));
  applyShop(result);
  if (result.restart && result.lan) status('Restart eznest to open the shop network.');
  else if (result.restart) status('Shop network turns off after you restart eznest.');
}

async function saveHotFolder() {
  const path = $('hot-folder').value.trim();
  $('hot-error').hidden = true;
  $('hot-error').textContent = '';
  try {
    const result = await api('/api/output/connect', {path});
    $('hot-folder').value = result.path || '';
    saveShop();
    status(result.path ? 'Default print folder saved.' : 'Choose a location when saving.');
    return true;
  } catch (error) {
    $('hot-error').hidden = false;
    $('hot-error').textContent = error.message;
    status(error.message, true);
    return false;
  }
}

async function saveSettings() {
  const button = $('save-settings'), note = $('settings-saved');
  const controls = [...$('settings').querySelectorAll('input, select, button')].map(node => [node, node.disabled]);
  controls.forEach(([node]) => { node.disabled = true; });
  button.disabled = true; note.textContent = 'Saving…'; note.classList.remove('error');
  try {
    cutMapping();
    if (!await saveHotFolder()) throw Error($('hot-error').textContent);
    await saveDeploy();
    if (!saveShop() || !savePrefs({undo: $('allow-undo').checked})) throw Error('This browser could not save your preferences.');
    note.textContent = 'Saved.';
  } catch (error) {
    note.textContent = 'Could not save all settings. ' + error.message;
    note.classList.add('error');
  } finally { controls.forEach(([node, disabled]) => { node.disabled = disabled; }); }
}

async function importPdf(file, operation) {
  const bytes = new Uint8Array(await file.arrayBuffer());
  let binary = '';
  for (let offset = 0; offset < bytes.length; offset += 32768) binary += String.fromCharCode(...bytes.subarray(offset, offset + 32768));
  const mapping = EZNCuts.defaults();
  mapping.rules.push(
    {source: 'layer', match: 'exact', name: 'thru-cut', operation: 'thru'},
    {source: 'layer', match: 'exact', name: 'kiss cut', operation: 'kiss'});
  mapping.genericOperation = operation;
  return api('/api/document/import', {content: btoa(binary), preserveArtwork: true, cutSpot: 'CutContour', cutMapping: EZNCuts.validate(mapping)});
}

async function readEntry(file) {
  const pdf = /\.(pdf|ai)$/i.test(file.name);
  if (!pdf && !/\.svg$/i.test(file.name)) throw Error(file.name + ' is not SVG, PDF, or PDF-compatible AI.');
  if (file.size > (pdf ? 32_000_000 : 8_000_000)) throw Error(file.name + ' is over the ' + (pdf ? '32' : '8') + ' MB limit.');
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
  if (presetEditor) throw Error('Save or cancel the preset before adding files.');
  const files = [...fileList].filter(Boolean);
  if (!files.length || busy || saving) return;
  if (illustratorHandoff && !replace) throw Error('Start over before adding files to another Illustrator attempt.');
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
    if (kits.some(entry => !entry.file)) {
      showBlocked('Add the original files again to choose their cut type. Your saved layout is unchanged.');
      return;
    }
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

function restoreJob(state) {
  const job = state.job;
  if (!job?.productionJobs?.length || job.materialId !== 'web-roll') return;
  kits = job.productionJobs.map(source => {
    const document = job.documentSources?.[source.id];
    const parts = job.parts.filter(part => part.sourceJobId === source.id).map(part => ({
      ...part, id: part.originalPartId, quantity: part.perSet || 1
    }));
    return {...source, origin: 'files', selected: true, status: 'ready', data: {
      ...(document || {}), format: document ? 'pdf' : 'svg',
      svgSource: job.svgSources?.[source.id], parts
    }};
  });
  fileSerial = Math.max(kits.length, ...kits.map(entry => Number(entry.id.match(/-(\d+)$/)?.[1] || 0) + 1));
  const options = job.webOptions || {};
  const settings = job.settings;
  if (['mm', 'in', 'cm'].includes(options.units)) $('unit').value = options.units;
  $('unit').dataset.current = $('unit').value;
  const factor = scale();
  for (const node of document.querySelectorAll('span[data-unit]')) node.textContent = $('unit').value;
  if (options.material && [...$('material').options].some(option => option.value === options.material)) $('material').value = options.material;
  $('preset-name').value = job.materialName || job.media?.name || 'Custom roll';
  $('width').value = (job.media?.maxPrintableMm || settings.width) / factor;
  $('nest-width').value = settings.width / 25.4;
  for (const [id, key] of [['available-length', 'maxLength'], ['gap', 'gap'], ['roll', 'rollWidth'], ['sheet', 'sheetLength'], ['mark-margin', 'markMargin']]) {
    $(id).value = settings[key] == null ? '' : settings[key] / factor;
  }
  $('margin').value = (settings.edgeMargin ?? (settings.margin - (settings.markMargin || 0))) / factor;
  $('seconds').value = Math.max(30, settings.seconds || 30);
  $('rotations').value = settings.rotations == null ? 'free' : settings.rotations.join(',');
  $('auto-bleed').value = (settings.autoBleedMm || 0) / 25.4;
  $('draw-marks').checked = settings.drawRegmarks === true;
  $('cost').value = settings.costPerSquareMeter ?? '';
  $('bleed').value = job.outputProfile?.bleedMm || 0;
  $('sets').value = kits.every(entry => entry.sets === kits[0].sets) ? kits[0].sets : (options.sets || 1);
  const mapping = job.outputProfile?.cutMapping;
  if (mapping?.outputs) {
    $('thru-name').value = mapping.outputs.thru.spot;
    $('kiss-name').value = mapping.outputs.kiss.spot;
    matchCutPreset();
  }
  $('generic-cut').value = options.genericCut || '';
  if (job.illustrator) illustratorHandoff = {...job.illustrator, documentId: kits[0].revision};
  activeMaterial = $('material').value;
  renderMaterialButtons();
  renderFiles();
  showWidth();
}

async function boot() {
  await ensureLibraries();
  const stored = prefs();
  loadMaterialProfiles(stored);
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
  if (['', 'thru', 'kiss', 'contour'].includes(stored.genericCut)) $('generic-cut').value = stored.genericCut;
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
  localSave = session.localSave === true;
  try {
    const folder = await fetchJson('/api/output', 5000);
    if (folder.path) $('hot-folder').value = folder.path;
    else if (stored.hotFolder) $('hot-folder').value = stored.hotFolder;
  } catch { /* The folder status is optional. */ }
  try {
    applyShop(await fetchJson('/api/shop', 5000));
  } catch { /* Shop network settings stay off when the lookup does not answer. */ }
  const state = await fetchJsonRetry('/api/state');
  if (['running', 'ready'].includes(state.status)) restoreJob(state);
  if (state.status === 'running') { busy = true; showScreen('nest'); renderActions(); setTimeout(poll, 300); }
  else if (state.status === 'ready' && state.manifest) showResult(state);
  else { showScreen('drop'); status(''); }
  renderActions();
  refreshUpdate().catch(() => {});
  const handoffId = new URLSearchParams(location.search).get('illustrator');
  if (handoffId) {
    $('illustrator-handoff').hidden = false;
    if (!/^[a-f0-9]{32}$/.test(handoffId)) {
      $('illustrator-note').textContent = 'Invalid Illustrator link. Export again.';
      $('illustrator-load').disabled = true;
    }
  }
  document.body.dataset.ready = '1';
  await autoLoadIllustrator();
}

async function autoLoadIllustrator() {
  const id = new URLSearchParams(location.search).get('illustrator');
  if (!id || !/^[a-f0-9]{32}$/.test(id) || !$('setup').hidden) return;
  // Refreshing a handoff must not replace its reviewed/sent layout or another job.
  if (busy || saving || kits.length || current) {
    $('illustrator-note').textContent = 'A job is already open. Finish it before loading this selection.';
    return;
  }
  await openIllustrator();
}

async function openIllustrator() {
  if (illustratorLoading) return;
  illustratorLoading = true;
  $('illustrator-load').disabled = true;
  $('illustrator-note').textContent = 'Opening your production copy...';
  try { await loadIllustrator(); }
  catch (error) { $('illustrator-note').textContent = error.message + ' Use Load Illustrator selection to retry.'; }
  finally { illustratorLoading = false; $('illustrator-load').disabled = false; }
}

async function loadIllustrator() {
  if (busy || saving) throw Error('Finish the current operation first.');
  if (!$('setup').hidden) throw Error('Finish shop setup first.');
  if ((kits.length || current) && !confirm('Replace the current preview with this Illustrator selection?')) return;
  const id = new URLSearchParams(location.search).get('illustrator');
  const response = await fetch('/api/illustrator/' + encodeURIComponent(id));
  const data = await response.json();
  if (!response.ok) throw Error(data.error);
  nextKit();
  $('material').value = 'white-gloss';
  const regular = $('material').selectedOptions[0];
  regular.dataset.name = 'Regular';
  regular.dataset.width = data.widthIn;
  regular.dataset.roll = Math.max(54, data.widthIn);
  regular.textContent = 'Regular';
  applyMaterial(true);
  $('nest-width').value = data.widthIn;
  $('sets').value = data.sets;
  $('bleed').value = data.bleedMm;
  $('auto-bleed').value = '0';
  $('thru-name').value = 'CutContour_Thru-cut';
  $('kiss-name').value = 'CutContour_Kiss-cut';
  matchCutPreset();
  const bytes = Uint8Array.from(atob(data.content), c => c.charCodeAt(0));
  const file = new File([bytes], 'Illustrator production copy.pdf', {type: 'application/pdf'});
  const entry = await readEntry(file);
  entry.id = 'illustrator-' + data.id;
  illustratorHandoff = {...data, documentId: entry.revision};
  delete illustratorHandoff.content;
  renderMaterialButtons();
  kits = [entry];
  current = null;
  blockReason = '';
  leaving = false;
  renderFiles();
  $('illustrator-note').textContent = 'Choose sets, review every piece, colors and cut paths, then send. Regular material; your saved Illustrator PDF preset was used.';
  $('illustrator-load').hidden = true;
  showScreen('nest');
  requestNest();
}

let updateInfo = {};
let updateWasQueued = false;
let updateVersion = null;
let updateServerPid = null;
function showUpdate(info) {
  updateInfo = info || {};
  if (info?.current && !updateVersion) updateVersion = info.current;
  if (info?.serverPid && !updateServerPid) updateServerPid = info.serverPid;
  updateWasQueued = updateWasQueued || !!info?.queued;
  $('update-cancel').hidden = !info?.queued || !info?.localPC;
  $('update').disabled = !!info?.queued;
  const note = $('update-note');
  $('update').textContent = info?.managedSupported && info?.staged ? 'Install when finished' : info?.applyOnRestart ? 'Install now' : 'Check for update';
  if (info?.updateAvailable && !info.staged) $('update').textContent = 'Download ' + info.latest;
  $('settings').querySelector('summary').title = info?.updateAvailable ? 'Settings - update available' : 'Settings';
  if (info?.managedSupported && info?.staged && !info.localPC) {
    note.hidden = false;
    note.textContent = 'The update is ready. Approve installation on the PC running eznest.';
    $('update').disabled = true;
    return;
  }
  if (info && info.rollback && info.rollback.reason) {
    note.hidden = false;
    note.textContent = info.rollback.reason;
    return;
  }
  if (info && (info.staged || info.applyOnRestart || info.updateAvailable || info.queued || info.managedResult) && info.message) {
    note.hidden = false;
    note.textContent = info.message + (info.releaseNotes && !info.queued ? '\n' + info.releaseNotes.slice(0, 500) : '');
    return;
  }
  note.hidden = true;
  note.textContent = '';
}

async function refreshUpdate(remote) {
  try {
    const notes = await (await fetch('/api/changelog')).json();
    const entries = Array.isArray(notes.entries) ? notes.entries : [];
    const unreleased = entries.find(entry => entry.version === 'Unreleased');
    const current = entries.find(entry => entry.version === notes.version);
    const parts = [unreleased, current].filter(Boolean);
    $('notes-body').textContent = parts.map(entry => entry.body || '').filter(Boolean).join('\n\n');
  } catch { /* What's new stays empty if the changelog is missing. */ }
  try {
    showUpdate(await (await fetch(remote ? '/api/update?refresh=1' : '/api/update')).json());
  } catch { /* The gear still has Update. */ }
}

async function refreshActivity() {
  try {
    const response = await fetch('/api/workload');
    const data = await response.json();
    if (!response.ok) throw Error(data.error);
    const prepared = data.events.prepared || {packs: 0};
    const sent = data.events.sent_to_folder || {packs: 0, pieces: 0, lengthMm: 0, materialM2: 0};
    const removed = data.events.removed_from_folder || {packs: 0};
    $('activity-summary').textContent = `${prepared.packs} packs prepared · ${sent.packs} sent · ${sent.pieces} pieces sent · ${(sent.lengthMm / 304.8).toFixed(1)} ft · ${sent.materialM2.toFixed(2)} m² of material. ${removed.packs} packs removed from the folder.`
      + (data.warning ? ' ' + data.warning : '');
  } catch (error) {
    $('activity-summary').textContent = error.message || 'Local activity is unavailable.';
  }
}

document.addEventListener('DOMContentLoaded', () => {
  installSettingsHelp();
  $('save-settings').addEventListener('click', saveSettings);
  $('settings').addEventListener('input', () => { $('settings-saved').textContent = ''; });
  $('generic-cut').addEventListener('change', saveShop);
  $('illustrator-load').addEventListener('click', openIllustrator);
  $('preview-zoom').addEventListener('change', () => {
    const width = Number($('preview-zoom').value) * 100 + '%';
    for (const id of ['preview', 'live']) $(id).style.width = width;
  });
  $('local-activity').addEventListener('toggle', () => {
    if ($('local-activity').open) refreshActivity();
  });
  $('activity-refresh').addEventListener('click', refreshActivity);
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
  $('material').addEventListener('change', () => { const id = $('material').value; $('material').value = activeMaterial; chooseMaterial(id); });
  $('edit-material').addEventListener('click', () => openPreset($('material').value));
  $('save-material').addEventListener('click', saveMaterial);
  $('cancel-material').addEventListener('click', closePreset);
  $('width').addEventListener('input', () => { watchWidth(); requestNest(); });
  $('nest-width').addEventListener('input', () => { showWidth(); saveShop(); requestNest(); });
  $('nest-width').addEventListener('change', () => { saveShop(); requestNest(); });
  for (const id of ['gap', 'margin', 'sheet', 'mark-margin']) $(id).addEventListener('input', requestNest);
  for (const id of ['width', 'gap', 'margin', 'sheet', 'mark-margin', 'rotations']) $(id).addEventListener('change', requestNest);
  $('cut-preset').addEventListener('change', () => { applyCutPreset(); saveShop(); });
  $('thru-name').addEventListener('input', () => { matchCutPreset(); saveShop(); });
  $('kiss-name').addEventListener('input', () => { matchCutPreset(); saveShop(); });
  $('auto-bleed').addEventListener('change', requestNest);
  $('save-destination').addEventListener('change', updateSaveChoice);
  $('folder-path').addEventListener('input', () => { $('folder-use').disabled = true; });
  $('folder-go').addEventListener('click', () => browseExportFolder($('folder-path').value.trim()));
  $('folder-path').addEventListener('keydown', event => { if (event.key === 'Enter') { event.preventDefault(); event.stopPropagation(); browseExportFolder($('folder-path').value.trim()); } });
  $('folder-up').addEventListener('click', () => browseExportFolder(folderView?.parent ?? ''));
  $('folder-drives').addEventListener('click', () => browseExportFolder(''));
  $('folder-cancel').addEventListener('click', () => $('folder-picker').close());
  $('folder-use').addEventListener('click', async () => {
    $('folder-use').disabled = true;
    $('hot-folder').value = folderView.path;
    if (!await saveHotFolder()) {
      $('folder-error').textContent = $('hot-error').textContent;
      $('folder-use').disabled = false;
      return;
    }
    $('folder-picker').close();
    updateSaveChoice();
  });
  $('browse-output').addEventListener('click', () => {
    browseExportFolder($('hot-folder').value.trim() || undefined);
  });
  $('hot-folder').addEventListener('change', saveHotFolder);
  $('staging-on').addEventListener('change', () => {
    $('staging-row').hidden = !$('staging-on').checked;
    saveShop();
  });
  $('staging-folder').addEventListener('change', saveShop);
  $('lan').addEventListener('change', () => { saveDeploy().catch(error => status(error.message, true)); });
  $('onyx-pc').addEventListener('change', () => { saveDeploy().catch(error => status(error.message, true)); });
  $('updates').addEventListener('change', () => { saveDeploy().catch(error => status(error.message, true)); });
  $('test-channel').addEventListener('change', () => { saveDeploy().catch(error => status(error.message, true)); });
  $('output-network').addEventListener('change', () => { saveDeploy().catch(error => status(error.message, true)); });
  $('printer').addEventListener('change', () => { saveDeploy().catch(error => status(error.message, true)); });
  $('setup-preset').addEventListener('click', async () => {
    try { applyEzPreset(await (await fetch('/api/shop')).json()); }
    catch (error) { status(error.message, true); }
  });
  $('setup-save').addEventListener('click', async () => {
    try { await saveSetup(); await autoLoadIllustrator(); }
    catch (error) {
      $('setup-error').hidden = false;
      $('setup-error').textContent = error.message;
      status(error.message, true);
    }
  });
  $('update').addEventListener('click', async () => {
    if (updateInfo.managedSupported && updateInfo.staged) {
      if (!updateInfo.localPC) return;
      updateWasQueued = true;
      window.location.href = 'eznest-update://install';
      $('update-note').hidden = false;
      $('update-note').textContent = 'Approve the Windows prompt. The helper will wait until work is finished. If no prompt opens, use Update eznest in the Windows Start menu.';
      return;
    }
    const installNow = $('update').textContent === 'Install now';
    try {
      const result = await api('/api/update', {when: installNow ? 'now' : 'restart'});
      status(result.message);
      showUpdate(result);
      if (!result.restarting) await refreshUpdate();
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
  $('update-cancel').addEventListener('click', async () => {
    try { await api('/api/update/cancel', {}); updateWasQueued = false; await refreshUpdate(); }
    catch (error) { status(error.message, true); }
  });
  setInterval(async () => {
    try {
      const response = await fetch('/api/update');
      if (!response.ok) return;
      const info = await response.json();
      if (updateWasQueued && ((info.serverPid && updateServerPid && info.serverPid !== updateServerPid) || (info.current && info.current !== updateVersion))) {
        // Reload only after an approved update, never during ordinary editing.
        location.reload();
        return;
      }
      showUpdate(info);
    } catch {
      if (updateWasQueued) {
        $('update-note').hidden = false;
        $('update-note').textContent = 'Installing the update. This page will reconnect when eznest is ready.';
      }
    }
  }, 5000);
  $('allow-undo').addEventListener('change', () => { savePrefs({undo: $('allow-undo').checked}); renderActions(); });
  $('allow-hold').addEventListener('change', () => savePrefs({hold: $('allow-hold').checked}));
  $('export').addEventListener('click', () => openConfirm());
  $('confirm-send').addEventListener('click', () => exportFile());
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
  $('improve').addEventListener('click', improve);
  $('undo').addEventListener('click', async () => {
    if (!current?.savedPath) return;
    try {
      await api('/api/output/undo', {id: current.id});
      current.savedPath = '';
      current.deliveryCompleted = false;
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
    if ($('folder-picker').open || presetEditor || event.target.closest('input, select, textarea, summary, .setting-info, #settings, #choose-thru, #choose-kiss, #choose-confirm, #confirm-send, #confirm-back, #materials, #sets-dec, #sets-inc, #sheet-tabs, #files, #add-files, #stop, #improve, #update, #setup, #edit-material')) return;
    if (document.body.dataset.step === 'blocked' || $('gate').classList.contains('problem')) { event.preventDefault(); return; }
    if (busy || saving) return;
    if (document.body.dataset.step === 'sent') { event.preventDefault(); startOver(); return; }
    if (document.body.dataset.step === 'confirm') { event.preventDefault(); exportFile(); return; }
    if (document.body.dataset.step === 'check' && current && current.result && !$('export').disabled) { event.preventDefault(); openConfirm(); }
  });
  boot().catch(error => status(error.message, true));
});

