'use strict';
const NS = 'http://www.w3.org/2000/svg';
const $ = id => document.getElementById(id);
const PREF = 'eznest-placeholders';
const PIECE_CAP = 5000;
// Both partner-printing links. Point this at a waitlist page when OUTPUT publishes one.
const OUTPUT_WEBSITE_URL = 'https://output.jeezlabs.io/';
const OUTPUT_WAITLIST_URL = new URL('waitlist', OUTPUT_WEBSITE_URL).href;
let token = '';
let localSave = false;
let folderView = null;
let browsingFolders = false;
let kits = [];
let fileSerial = 0;
let current = null;
let busy = false;
let importing = false;
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
let shopInventory = {materials: [], reservations: []};
let inventoryReady = false;
let inventoryBusy = false;
let inventoryGen = 0; // bumped on every inventory change so an older poll answer is ignored
let presetEditor = null;
let activeMaterial = 'white-gloss';
const MATERIAL_FIELDS = ['preset-name', 'roll', 'width', 'mark-margin', 'gap', 'margin', 'rotations', 'unit', 'sheet', 'print-layout', 'roll-length', 'roll-cost', 'available-length', 'low-stock', 'auto-bleed', 'bleed', 'cost'];

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
    'nesting-effort': ['Nesting effort', 'Quick finds a layout sooner. Best fit spends longer trying arrangements and may use less material. These are search budgets; preparation and checking take extra time. Your artwork, bleed, spacing and allowed turns stay the same. Try tighter fit keeps your best valid result.'],
    'cut-preset': ['Cut naming preset', 'Choose the names your print software recognizes. This changes exported cut names; it does not create missing cut lines.'],
    'thru-name': ['Through-cut name', 'The name your print software uses for a full cut. It must match your cutter setup. Changing this name does not set the blade depth.'],
    'kiss-name': ['Kiss-cut name', 'The name your print software uses to cut the sticker and leave the backing. It must match your cutter setup.'],
    'generic-cut': ['If a cut type is missing', 'Choose how to treat lines named only CutContour in the next file you add. Ask me keeps you in control when the cut type is unclear.'],
    'hot-folder': ['Default print folder', 'The folder selected automatically when you save. Choose My computer to save somewhere else. A folder watched by your print software may start processing saved files.'],
    'printer': ['Printer label (optional)', 'A label for your shop setup. Changing it does not connect a printer or change print quality.'],
    'staging-on': ['Keep an extra copy', 'Also save the finished pack in the extra copy folder when you send it.'],
    'staging-folder': ['Extra copy folder', 'Choose where the extra copy is saved. This does not replace the main destination.'],
    'onyx-pc': ['This PC runs ONYX', 'Changes the suggested output folder for this PC. It does not install ONYX or move your files.'],
    'lan': ['Other computers can connect', 'Shows whether this app was started with --lan. The box is disabled because the startup task controls it. A saved setting cannot open the shop network. The installer applies Shop network only on a fresh install. Change it later by running install-shop.ps1 again with -Lan 1 or -Lan 0 and -StartAtBoot 1, then restart.'],
    'updates': ['Look for app updates', 'Off during beta. Check this box and start Ez Nest with EZ_NEST_UPDATES=1. A download is kept only when its SHA-256 matches. Installing is still a separate click.'],
    'test-channel': ['Include test versions', 'When update checks are enabled, also show releases still being tested. Leave off for normal shop use.'],
    'allow-undo': ['Undo send', 'Lets you remove a sent pack while it is still in the output folder. This cannot stop a job that ONYX has already picked up.'],
    'preset-name': ['Material name', 'The name on the material button. Save separate materials when rolls need different widths or spacing.'],
    'unit': ['Units (inches or metric)', 'Shows these dimensions in inches, millimeters or centimeters. Existing values are converted, so the artwork stays the same size.'],
    'roll': ['Roll width', 'The full width of the material. Printable width must fit inside it. Increasing this alone does not make the layout wider.'],
    'width': ['Printable width', 'How much of the roll your printer can use. A smaller width can make the layout longer. Pieces keep their original size.'],
    'gap': ['Space between pieces', 'Space between the outer artwork edges, including existing bleed. More space keeps pieces farther apart and usually uses more material.'],
    'margin': ['Space at roll edges', 'Keeps pieces away from the sides. More space leaves less room for pieces and may make the layout longer.'],
    'roll-length': ['Full roll length', 'The length of a new roll. This is a reference for your material list. Material left on roll is the amount available for this job.'],
    'roll-cost': ['Full roll cost ($)', 'What you paid for a full roll, in US dollars. Enter its full length and roll width too. Savings divide this cost by the full length. The pack estimate uses the same price spread over the roll area. Ink and labor are not included. Save material to remember this.'],
    'available-length': ['Length left on roll', 'Enter the physical length left, including reserved jobs. Confirmed material use subtracts stock; reservations reduce what is available. Leave blank if unknown.'],
    'low-stock': ['Low-stock alert at', 'Show a red Low stock notice when the saved material left is at or below this length. Leave blank to use 10% of the full roll length, when known. Update material left after printing.'],
    'sheet': ['Longest print section', 'Splits a long layout into sections no longer than this. A lower number can create more sections. Every piece must fit within one section.'],
    'print-layout': ['Print layout', 'Continuous nests all requested pieces onto one long PDF page. Shorter sections use the section length below. Neither changes artwork size or bleed.'],
    'rotations': ['Allowed turns', 'Lets pieces turn to fit closer together. Keep orientation leaves them facing the original direction. Consider material grain and artwork direction.'],
    'mark-margin': ['Room for cutter marks', 'Reserves extra space at the edges, in addition to edge spacing. This does not draw marks; your print software can add them.'],
    'auto-bleed': ['Enlarge artwork at edges', 'Enlarges the artwork slightly around unchanged cut lines. It can change the design near the edges. Leave off for prepared print files and inspect any changed preview.'],
    'bleed': ['Existing color beyond cuts', 'How far the artwork already extends beyond its cut lines, in millimeters. Set this before adding files. It preserves that area during import; it does not create new color.'],
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
    (button.closest('dialog') || document.body).append(tip);
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
  function bindHelp(button, message) {
    button.classList.add('help-label');
    button.setAttribute('aria-expanded', 'false');
    button.setAttribute('aria-controls', tip.id);
    button.addEventListener('mouseenter', () => show(button, message));
    button.addEventListener('mouseleave', later);
    button.addEventListener('focus', () => show(button, message));
    button.addEventListener('blur', () => { if (!pinned) close(); });
    button.addEventListener('click', () => {
      if (active === button && pinned) close();
      else { show(button, message); pinned = true; }
    });
  }
  for (const [id, [name, message]] of Object.entries(help)) {
    const input = $(id);
    if (!input || input.type === 'hidden') continue;
    const original = input.closest('label');
    if (!original) continue;
    input.setAttribute('aria-label', name);
    // The effort heading itself explains the select; avoid repeating its title.
    if (id === 'nesting-effort') {
      bindHelp($('effort-help'), message);
      original.classList.add('effort-field');
      for (const node of [...original.childNodes]) if (node.nodeType === Node.TEXT_NODE) node.textContent = '';
      continue;
    }
    const field = document.createElement('div');
    for (const attr of original.attributes) field.setAttribute(attr.name, attr.value);
    field.classList.add('setting-field');
    const heading = document.createElement('span'); heading.className = 'setting-heading';
    const button = document.createElement('button');
    button.type = 'button'; button.textContent = name;
    button.setAttribute('aria-label', 'About ' + name);
    heading.append(button);
    for (const child of [...original.childNodes]) {
      if (child.nodeType === Node.TEXT_NODE && child.textContent.trim()) field.append(heading);
      else field.append(child);
    }
    original.replaceWith(field);
    bindHelp(button, message);
  }
  document.querySelectorAll('[data-help]').forEach(button => bindHelp(button, button.dataset.help));
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && !tip.hidden) { event.preventDefault(); close(); }
  });
  document.addEventListener('pointerdown', event => { if (!event.target.closest('.help-label, .setting-help')) close(); });
  document.addEventListener('scroll', close, true);
  window.addEventListener('resize', close);
  $('settings').addEventListener('close', close);
  $('material-dialog').addEventListener('close', close);
}

async function sha256(data) {
  const digest = await crypto.subtle.digest('SHA-256', data);
  return [...new Uint8Array(digest)].map(byte => byte.toString(16).padStart(2, '0')).join('');
}

function fetchJson(path, ms) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), ms);
  return fetch(path, {signal: controller.signal}).then(async response => {
    clearTimeout(timer);
    if (!response.ok) {
      throw Error('Request failed.');
    }
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
  const need = [['EZNQueue', '/queue-core.js'], ['EZNCuts', '/cut-mapping.js'], ['EZNProfiles', '/shop-profiles.js'], ['EZNResults', '/tester-results.js']];
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

function withToken(headers) {
  const copy = Object.assign({}, headers);
  if (token) copy['X-EZ-Token'] = token;
  return copy;
}

async function api(path, data, file) {
  const response = await fetch(path, {
    method: 'POST',
    headers: file ? withToken({'Content-Type': 'application/pdf', 'X-EZ-Import': encodeURIComponent(JSON.stringify(data || {}))}) : withToken({'Content-Type': 'application/json'}),
    body: file || JSON.stringify(data || {})
  });
  const body = await response.json();
  if (!response.ok) {
    const error = Error(body.error || 'Request failed.');
    error.code = body.code;
    if (path === '/api/document/import' || path === '/api/document/import-file') {
      error.guideReview = body.guideReview; error.cutReview = body.cutReview;
    }
    throw error;
  }
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
const HOT_FOLDER_LABEL = 'Example RIP Input';

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

// Savings use full roll cost divided by full length. The pack estimate uses that
// same purchase spread over roll width × full length. A saved per-m² price is
// kept only when those three values cannot produce one.
function derivedCostPerSquareMeter(values) {
  if (!values || !['mm', 'cm', 'in'].includes(values.unit)) return null;
  const priceText = String(values['roll-cost'] ?? '').trim();
  const widthText = String(values.roll ?? '').trim();
  const lengthText = String(values['roll-length'] ?? '').trim();
  if (!priceText || !widthText || !lengthText) return null;
  const price = Number(priceText), width = Number(widthText), length = Number(lengthText);
  if (!Number.isFinite(price) || price < 0 || !Number.isFinite(width) || width <= 0 || !Number.isFinite(length) || length <= 0) return null;
  const millimeters = EZNQueue.unitScale(values.unit);
  const area = (width * millimeters / 1000) * (length * millimeters / 1000);
  return area > 0 ? price / area : null;
}

function pricedMaterial(values) {
  const derived = derivedCostPerSquareMeter(values);
  if (derived != null) {
    const usable = derived <= 1000000;
    values.cost = usable ? String(derived) : '';
    return usable ? derived : null;
  }
  const legacy = String(values.cost ?? '').trim();
  const price = Number(legacy);
  if (!legacy || !Number.isFinite(price) || price < 0 || price > 1000000) {
    values.cost = '';
    return null;
  }
  values.cost = legacy;
  return price;
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
  settings.continuous = $('print-layout').value === 'continuous';
  if (settings.continuous) settings.sheetLength = 5000;
  const form = materialValues();
  const price = pricedMaterial(form);
  $('cost').value = form.cost;
  if (price != null) {
    settings.costPerSquareMeter = price;
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
  if (state?.job?.settings?.continuous) return state.result?.usedLength > 5000;
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
  $('piece-count').textContent = '';
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
  const configuring = name === 'configure';
  const empty = idle || configuring || (!current?.result && name === 'blocked');
  const confirming = name === 'confirm';
  $('drop-screen').hidden = !empty;
  $('upload-title').textContent = kits.length ? 'Files ready to nest' : 'Upload your print here';
  $('upload-hint').textContent = kits.length ? 'Choose material and effort, then Nest. Click here to add files.' : 'Click to choose files or drop them here';
  $('job-empty').hidden = kits.length > 0;
  $('sheet-frame').hidden = empty;
  $('preview-tools').hidden = empty;
  $('legend').hidden = empty;
  $('piece-review').hidden = empty || name === 'nest' || !current?.result;
  $('nest-savings').hidden = empty || name === 'nest' || !(EZNResults.comparison(current)?.savedFt >= .005);
  $('readout').hidden = empty;
  $('export').hidden = empty || confirming || name === 'nest';
  $('start-nesting').hidden = !!current?.result || !['drop', 'configure', 'blocked'].includes(name);
  $('nest-row').hidden = $('start-nesting').hidden;
  $('start-over-idle').disabled = kits.length === 0;
  if (empty) $('sheet-tabs').hidden = true;
  $('confirm').hidden = !confirming;
  $('start-over').hidden = idle || confirming || !$('nest-row').hidden;
  $('delivery-receipt').hidden = name !== 'sent';
  $('saved-heading').hidden = name !== 'sent';
  $('start-over').textContent = name === 'sent' ? 'Next job' : 'Start over';
  const steps = {drop: 1, nest: 2, blocked: 2, check: 2, confirm: 3, sent: 3};
  for (const node of document.querySelectorAll('[data-workflow-step]')) {
    if (Number(node.dataset.workflowStep) === steps[name]) node.setAttribute('aria-current', 'step');
    else node.removeAttribute('aria-current');
  }
  $('choice').hidden = name !== 'blocked' || !unresolved();
  if ($('choice').hidden) $('choose-confirm').hidden = true;
  if (idle) showSheetId(null);
  syncWelcome();
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
  $('copies-summary').textContent = kits.some(entry => entry.sets !== 1) ? kits.map(entry => entry.sets + '×').join(', ') : '';
  $('start-nesting').disabled = busy || importing || saving || !!presetEditor || !kits.length || !!inputIssue();
  $('add-files').hidden = !show || !!illustratorHandoff || document.body.dataset.step === 'nest';
  $('stop').hidden = document.body.dataset.step !== 'nest';
  $('improve').hidden = document.body.dataset.step !== 'check' || busy || !current || current.released;
  $('improve').disabled = importing || saving;
  const locked = busy || importing || !!presetEditor || document.body.dataset.step === 'nest';
  $('nesting-effort').disabled = locked || saving || !!current?.released || ['confirm', 'sent'].includes(document.body.dataset.step);
  for (const node of $('files').querySelectorAll('input, button')) node.disabled = locked;
}

function renderFiles() {
  const list = $('files');
  $('copies-label').textContent = kits.length > 1 ? 'Copies of every file' : 'Copies';
  list.replaceChildren();
  for (const entry of kits) {
    const row = document.createElement('li');
    const name = document.createElement('span');
    name.className = 'file-name';
    name.textContent = entry.name;
    const quantity = document.createElement('label'); quantity.className = 'file-copies';
    const quantityLabel = document.createElement('span'); quantityLabel.textContent = 'Copies of this file';
    const qty = document.createElement('input');
    qty.type = 'number';
    qty.min = '1';
    qty.max = String(PIECE_CAP);
    qty.step = '1';
    qty.value = String(entry.sets);
    qty.setAttribute('aria-label', 'Quantity for ' + entry.name);
    const countNote = document.createElement('span'); countNote.className = 'file-count';
    const perFile = (entry.data?.parts || []).reduce((sum, part) => sum + (part.quantity || 1) * (part.sourcePieceCount || 1), 0);
    const showCount = () => { countNote.textContent = `${perFile.toLocaleString()} pieces × ${entry.sets.toLocaleString()} = ${(perFile * entry.sets).toLocaleString()} total`; };
    showCount();
    const commitQty = () => {
      const count = Number(qty.value);
      if (!Number.isInteger(count) || count < 1 || count > PIECE_CAP) {
        if (document.activeElement !== qty) qty.value = String(entry.sets);
        return;
      }
      if (count === entry.sets) return;
      entry.sets = count;
      showCount();
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
    quantity.append(quantityLabel, qty);
    row.append(name, remove, quantity, countNote);
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
  document.body.dataset.saving = String(saving);
  $('confirm').setAttribute('aria-busy', String(saving));
  if (saving) $('confirm-send').textContent = 'Preparing file…';
  else updateSaveChoice();
  const confirming = document.body.dataset.step === 'confirm';
  syncFiles();
  $('material').disabled = busy || saving || !!presetEditor || !!illustratorHandoff || confirming;
  $('confirm-send').disabled = saving || busy || !!presetEditor;
  $('confirm-back').disabled = saving;
  for (const id of ['save-name','save-format','save-destination']) $(id).disabled = saving;
  $('start-over').disabled = saving || !!presetEditor;
  $('nest-width').disabled = busy || saving || !!presetEditor || confirming;
  $('sets').disabled = busy || saving || !!presetEditor || confirming;
  $('sets-dec').disabled = busy || saving || !!presetEditor || confirming;
  $('sets-inc').disabled = busy || saving || !!presetEditor || confirming;
  $('file').disabled = busy || saving || !!presetEditor || confirming;
  $('more').disabled = busy || saving || !!presetEditor || confirming;
  $('edit-material').disabled = busy || saving || !!presetEditor || !!illustratorHandoff || confirming;
  if (importing) {
    for (const id of ['material', 'confirm-send', 'start-over', 'nest-width', 'sets', 'sets-dec', 'sets-inc', 'file', 'more', 'edit-material', 'improve', 'export']) $(id).disabled = true;
    return;
  }
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
  if (step === 'configure' || (step === 'blocked' && !current?.result)) {
    $('export').hidden = true; $('export').disabled = true;
    $('start-nesting').hidden = !kits.length;
    setSentence(badInput || blockReason, true);
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
    $('job-checks').textContent = pieceSentence(current);
    $('gate').hidden = true;
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
  const excluded = Object.values(state.job.documentSources || {}).reduce((sum, source) => sum + (source.excludedGuideCount || 0), 0);
  if (excluded) bits.push(excluded + ' guides excluded');
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

function renderPieceReview() {
  const cards = $('piece-cards');
  cards.replaceChildren();
  if (!$('piece-review').open || !current?.result) return;
  const counts = new Map();
  for (const placement of current.result.placements) counts.set(placement.id, (counts.get(placement.id) || 0) + 1);
  const sources = new Map((current.job.productionJobs || []).map(source => [source.id, source.name]));
  current.job.parts.forEach((part, index) => {
    const card = document.createElement('article'); card.className = 'piece-card';
    const title = document.createElement('strong'); title.textContent = part.name || 'Piece ' + (index + 1);
    const quantity = document.createElement('span'); quantity.className = 'piece-quantity';
    quantity.textContent = (counts.get(part.id) || 0) + ' of ' + part.quantity + ' copies';
    const image = document.createElement('img'); image.loading = 'lazy'; image.alt = 'Artwork for piece ' + (index + 1);
    try {
      const points = part.points;
      const x = Math.min(...points.map(p => p[0])), y = Math.min(...points.map(p => p[1]));
      const w = Math.max(...points.map(p => p[0])) - x, h = Math.max(...points.map(p => p[1])) - y;
      const result = {width: w, usedLength: h, placements: [{id: part.id, x: 0, y: 0, rotation: 0}]};
      const art = current.job.documentSources ? documentPreview({job: current.job, result}) : EZNSVG.buildSVG(current.job, result);
      if (!current.job.documentSources) emphasizeCuts(art);
      art.setAttribute('xmlns', NS); art.setAttribute('viewBox', `${x - 1} ${y - 1} ${w + 2} ${h + 2}`);
      art.setAttribute('width', '180'); art.setAttribute('height', '120');
      image.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(new XMLSerializer().serializeToString(art));
    } catch { image.alt = 'Preview unavailable — check this piece in the layout'; }
    const source = document.createElement('span'); source.className = 'piece-source'; source.textContent = sources.get(part.sourceJobId) || '';
    const cuts = part.cutCounts || namedCuts(part.svg?.markup || '');
    const detail = document.createElement('span'); detail.className = 'piece-detail';
    const bits = [];
    if ((part.sourcePieceCount || 1) > 1) { if (!part.name) title.textContent = 'Piece ' + (index + 1); bits.push(part.sourcePieceCount + ' pieces kept together'); }
    if (cuts.thru) bits.push(cuts.thru + ' thru');
    if (cuts.kiss) bits.push(cuts.kiss + ' kiss');
    if (cuts.contour) bits.push(cuts.contour + ' cuts need a type');
    if (!cuts.thru && !cuts.kiss && !cuts.contour) bits.push('Check cut lines');
    detail.textContent = bits.join(' · ');
    const more = document.createElement('details'), summary = document.createElement('summary');
    summary.textContent = 'Details'; more.append(summary, quantity, detail, source);
    card.append(image, title, more); cards.append(card);
  });
}

function showNestSavings(state) {
  const comparison = EZNResults.comparison(state);
  $('nest-savings').hidden = !(comparison?.savedFt >= .005);
  if ($('nest-savings').hidden) return;
  $('nest-savings').dataset.saving = 'positive';
  $('savings-label').textContent = `${comparison.percent.toFixed(1)}% less material`;
  $('savings-value').textContent = comparison.savedDollars == null ? `${comparison.savedFt.toFixed(2)} ft saved` : `$${comparison.savedDollars.toFixed(2)} saved`;
  $('savings-context').textContent = `${comparison.savedDollars == null ? '' : comparison.savedFt.toFixed(2) + ' ft · '}vs. ${comparison.reference}${comparison.savedDollars == null ? '' : ' · material only'}`;
}

function feedbackText() {
  return EZNResults.feedback($('app-version').textContent, $('feedback-message').value, current, $('feedback-numbers').checked);
}

function updateFeedbackPreview() { $('feedback-preview').textContent = feedbackText(); }

function setNestingEffort(seconds) {
  const value = [5, 30, 90].includes(Number(seconds)) ? Number(seconds) : 30;
  $('nesting-effort').value = String(value);
  $('seconds').value = String(value);
  $('effort-summary').textContent = $('nesting-effort').selectedOptions[0].textContent;
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
  const scale = width / 42;
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
  // Keep the selected section's global coordinates, but exclude other sections.
  // ViewBox padding alone can expose the next section below this one's edge.
  const sectionResult = {...result, placements: result.placements.filter(item => (item.sheet || 0) === (sheet.index || 0))};
  const art = state.job.documentSources ? documentPreview({...state, result: sectionResult}) : EZNSVG.buildSVG(state.job, sectionResult);
  if (!state.job.documentSources) {
    applyAutoBleed(art, state.job, sectionResult);
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
  const parts = new Map(state.job.parts.map(part => [part.id, part]));
  const count = result.placements.reduce((sum, item) => sum + (parts.get(item.id)?.sourcePieceCount || 1), 0);
  $('result-heading').hidden = true;
  $('piece-count').textContent = `${count.toLocaleString()} ${count === 1 ? 'piece' : 'pieces'}`;
  $('piece-review-title').textContent = `Check ${count.toLocaleString()} ${count === 1 ? 'piece' : 'pieces'}`;
  $('piece-review-count').textContent = (state.job.productionJobs || []).map(source => {
    const copies = source.sets || 1;
    const perFile = state.job.parts.filter(part => part.sourceJobId === source.id)
      .reduce((sum, part) => sum + part.quantity * (part.sourcePieceCount || 1), 0) / copies;
    return `${perFile.toLocaleString()} ${perFile === 1 ? 'piece' : 'pieces'} × ${copies.toLocaleString()} ${copies === 1 ? 'copy' : 'copies'}`;
  }).join(' + ');
  const coverage = Math.max(0, Math.min(100, result.utilization * 100));
  $('coverage-label').textContent = `${Math.round(coverage)}% occupied by pieces`;
  $('coverage-bar').style.width = coverage + '%';
  setNum('length', (result.usedLength / 304.8).toFixed(2), 'ft');
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
  if (current && current.manifest) { $('job-checks').textContent = pieceSentence(current); setSentence('', false); }
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
  showNestSavings(state);
  renderPieceReview();
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
  status(state.nestSavings && ['Found a better layout.', 'Kept your best layout; this search did not improve it.'].includes(state.note) ? '' : (state.note || ''));
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
      requestNest();
      return;
    }
    if (state.status === 'ready' && state.manifest) showResult(state);
    else showBlocked(state.error || state.note || 'That file does not fit this roll.');
  } catch (error) {
    if (error && error.name === 'AbortError' && busy && !leaving) { setTimeout(poll, 300); return; }
    busy = false;
    if (pendingRenest && kits.length && !leaving) { pendingRenest = false; requestNest(); return; }
    showBlocked(error.message);
  }
  renderActions();
}

function requestNest() {
  clearTimeout(nestTimer);
  if (presetEditor || leaving || saving || !kits.length) return;
  if (busy || importing) { pendingRenest = true; return; }
  // A changed job has no saveable result until the operator starts a new search.
  current = null;
  blockReason = '';
  showScreen('configure');
  showSheetId(null);
  $('job-checks').textContent = '';
  status('');
  renderActions();
}

async function nest() {
  if (busy || importing || saving || !kits.length) return;
  try {
    await refreshInventory().catch(() => {});
    const sharedStock = shopInventory.materials.find(item => item.id === $('material').value);
    if (inventoryReady && sharedStock) $('available-length').value = sharedStock.availableMm == null ? '' : String(sharedStock.availableMm / scale());
    if (inputIssue()) { showBlocked(inputIssue()); return; }
    const roll = preset();
    const job = EZNQueue.compose(kits, roll, 'combined');
    if (inventoryReady && shopInventory.materials.some(item => item.id === $('material').value)) job.inventoryMaterialId = $('material').value;
    job.outputProfile = profileFor(kits);
    job.webOptions = {units: $('unit').value, material: $('material').value, sets: sets(), genericCut: $('generic-cut').value,
      sectionLengthMm: $('sheet').value.trim() ? Number($('sheet').value) * scale() : null,
      rollCost: $('roll-cost').value.trim() ? Number($('roll-cost').value) : null,
      fullRollLengthMm: $('roll-length').value.trim() ? Number($('roll-length').value) * scale() : null};
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
  if (busy || importing || saving || !current || current.released) return;
  try {
    busy = true;
    showScreen('nest');
    status('Trying a better fit…');
    await api('/api/improve', {id: current.id, seconds: Number($('nesting-effort').value)});
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
  $('save-summary').textContent = `${current.manifest.totalPieces.toLocaleString()} pieces · ${(current.result.usedLength / 304.8).toFixed(2)} ft · ${onePdf ? 'one PDF page' : sheetList(current).length + ' print sections'} · ${current.job.materialName}`;
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
    status(pdf ? 'Preparing your PDF with the original artwork and cut lines…' : 'Preparing your print pack…');
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
  $('sets').value = '1';
  $('job-options').open = false;
  $('job-checks').textContent = '';
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
  if (saving || importing) return;
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
  const selected = $('material').value;
  $('material').disabled = !!illustratorHandoff || !!presetEditor || busy || saving || document.body.dataset.step === 'confirm';
  for (const option of $('material').options) {
    option.hidden = !!illustratorHandoff && option.value !== 'white-gloss';
    const stock = lowStock(materialProfiles[option.value]);
    option.textContent = (option.dataset.name || option.textContent.split(' · ')[0]) + (stock ? ' · ' + stock.split(' · ')[0] : '');
  }
  const box = $('materials');
  box.replaceChildren();
  const stock = lowStock(materialProfiles[selected]);
  if (stock) {
    const notice = document.createElement('div');
    notice.className = 'stock-alert'; notice.setAttribute('role', 'status');
    notice.textContent = stock; box.append(notice);
  }
  const remaining = $('available-length').value.trim();
  const shared = shopInventory.materials.find(item => item.id === selected);
  $('material-summary').textContent = shared ? `${stockFeet(shared.availableMm)} available · ${stockFeet(shared.reservedMm)} reserved` : remaining && !stock ? `${Number(remaining)} ${$('unit').value} available · this browser only` : '';
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
  $('print-layout').value = values['print-layout'] || 'sections';
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
  if (!['continuous','sections'].includes(values['print-layout'] || 'sections')) throw Error('Choose a print layout.');
  const price = pricedMaterial(values);
  if (price != null) settings.costPerSquareMeter = price;
  EZNQueue.validatePreset({name: values['preset-name'], units: values.unit, settings});
  if (settings.width > settings.rollWidth) throw Error('Printable width cannot be wider than the roll.');
  if (!['0', '0.0625', '0.125'].includes(values['auto-bleed'])) throw Error('Choose a supported bleed setting.');
  if (!Number.isFinite(Number(values.bleed)) || Number(values.bleed) < 0 || Number(values.bleed) > 25) throw Error('Existing bleed must be from 0 to 25 mm.');
  if (values['roll-length']?.trim() && (!Number.isFinite(n('roll-length')) || n('roll-length') <= 0)) throw Error('Enter a positive full roll length or leave it blank.');
  if (values['roll-cost']?.trim() && (!Number.isFinite(Number(values['roll-cost'])) || Number(values['roll-cost']) < 0 || !(n('roll-length') > 0))) throw Error('Enter a full roll length and a cost of zero or more to estimate savings.');
  if (values['roll-length']?.trim() && values['available-length']?.trim() && n('available-length') > n('roll-length')) throw Error('Material left cannot exceed the full roll length.');
  if (values['low-stock']?.trim() && (!Number.isFinite(n('low-stock')) || n('low-stock') < 0)) throw Error('Enter a low-stock alert of zero or more, or leave it blank.');
  if (values['roll-length']?.trim() && values['low-stock']?.trim() && n('low-stock') > n('roll-length')) throw Error('The low-stock alert cannot exceed the full roll length.');
  return {'roll-length': '', 'roll-cost': '', 'available-length': '', 'low-stock': '', ...values, 'preset-name': values['preset-name'].trim()};
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

async function openPreset(id) {
  if (busy || saving || presetEditor || illustratorHandoff || document.body.dataset.step === 'confirm') return;
  await refreshInventory().catch(() => {});
  if (presetEditor || busy || saving) return;
  clearTimeout(nestTimer);
  presetEditor = {id, values: materialValues(), selected: $('material').value, nestWidth: $('nest-width').value};
  presetEditor.revision = shopInventory.materials.find(item => item.id === id)?.revision || 0;
  if (materialProfiles[id]) setMaterialValues(materialProfiles[id]);
  else {
    $('preset-name').value = id === 'custom' ? '' : [...$('material').options].find(option => option.value === id).textContent;
    for (const field of ['roll-length', 'available-length', 'low-stock']) $(field).value = '';
  }
  const shared = shopInventory.materials.find(item => item.id === id);
  if (shared) $('available-length').value = shared.onHandMm == null ? '' : stockInput(shared.onHandMm, shared.profile.unit);
  presetEditor.savedValues = materialValues();
  $('inventory-status').textContent = inventoryReady ? '' : 'Shop stock is unavailable. Reconnect to update it.';
  $('material-usage').open = false;
  renderInventory();
  $('preset-title').textContent = id === 'custom' ? 'Add material' : 'Edit ' + $('preset-name').value;
  $('preset-error').hidden = true;
  $('preset-editor').hidden = false;
  $('material-dialog').showModal();
  $('preset-name').focus();
  $('material-advanced').open = false;
  renderMaterialButtons();
  renderActions();
}

function closePreset() {
  if (!presetEditor || $('save-material').disabled || inventoryBusy) return;
  const previous = presetEditor;
  presetEditor = null;
  setMaterialValues(previous.values);
  $('material').value = previous.selected;
  $('nest-width').value = previous.nestWidth;
  $('preset-editor').hidden = true;
  $('material-dialog').close();
  renderMaterialButtons();
  renderActions();
}

async function saveMaterial() {
  if (!presetEditor || inventoryBusy) return;
  $('save-material').disabled = true;
  try {
    const entered = materialValues();
    const shared = shopInventory.materials.find(item => item.id === presetEditor.id);
    if (shared && entered.unit === presetEditor.savedValues.unit && entered['available-length'] === presetEditor.savedValues['available-length']) {
      entered['available-length'] = shared.onHandMm == null ? '' : String(shared.onHandMm / EZNQueue.unitScale(entered.unit));
    }
    const values = validateMaterial(entered);
    const id = presetEditor.id === 'custom' ? 'material-' + crypto.randomUUID() : presetEditor.id;
    if (Object.entries(materialProfiles).some(([key, item]) => key !== id && item['preset-name'].toLowerCase() === values['preset-name'].toLowerCase())) throw Error('A preset with that name already exists. Choose another name.');
    await mutateInventory('/api/materials/save', {id, profile: values, revision: presetEditor.revision});
    savePrefs({material: id, nestWidth: String(Number(values.width) * EZNQueue.unitScale(values.unit) / 25.4)});
    presetEditor = null;
    $('preset-editor').hidden = true;
    $('material-dialog').close();
    $('material').value = id;
    applyMaterial(true);
    status('');
    renderActions();
    requestNest();
  } catch (error) {
    $('preset-error').textContent = error.message;
    $('preset-error').hidden = false;
    refreshInventory().catch(() => {});
  } finally {
    $('save-material').disabled = false;
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
  $('lan-access').hidden = !on;
  $('lan-note').hidden = !on;
  $('lan-note').textContent = (shop && shop.warning) || 'Shop computers need the shop PIN before they can nest or send. Anyone on the shop LAN can Send to ONYX after that PIN. Do not share this network with guest WiFi.';
  const bits = [];
  if (shop && shop.url) bits.push(shop.url);
  if (shop && shop.addresses && shop.addresses.length) bits.push(shop.addresses[0]);
  $('lan-address').textContent = bits.filter(Boolean).join(' · ');
  $('lan-address').hidden = !on;
}

function showHotDefault(path) {
  $('hot-default').textContent = path ? 'Example shop preset: ' + path : '';
  if (!$('hot-folder').value && path) $('hot-folder').placeholder = path;
}

function outputUrlField() {
  const input = $('output-url');
  if (!input || input.disabled) return null;
  const value = input.value.trim();
  if (!value) return '';
  try {
    const url = new URL(value);
    if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash || (url.pathname && url.pathname !== '/')) return null;
    return url.origin;
  } catch {
    return null;
  }
}

function showOutputService(shop) {
  const input = $('output-url');
  if (!input || !shop) return;
  const locked = shop.outputUrlSource === 'environment';
  input.disabled = locked;
  if (document.activeElement !== input) input.value = shop.outputUrl || '';
  const destination = $('output-destination');
  if (destination) destination.textContent = shop.outputTelemetryUrl || 'https://output.jeezlabs.io/api/shop/telemetry';
  const note = $('output-url-note');
  if (note) {
    note.textContent = locked
      ? 'EZ_NEST_OUTPUT_URL is set for this run and overrides the saved address. Activity sharing stays off until you agree. Connecting to OUTPUT is optional.'
      : 'Leave blank for https://output.jeezlabs.io. Change it only on this computer. Another address has to match EZ_NEST_OUTPUT_URL, set when Ez Nest starts. Activity sharing stays off until you agree. Connecting to OUTPUT is optional.';
  }
}

function showRestart(shop) {
  const note = $('lan-restart');
  if (shop && shop.lanWaiting) {
    note.hidden = false;
    note.textContent = 'Shop network is waiting for a shop PIN. Set the PIN on this computer, then restart eznest.';
    return;
  }
  if (!shop || !shop.restart) {
    note.hidden = true;
    note.textContent = '';
    return;
  }
  note.hidden = false;
  note.textContent = 'Shop network requires starting eznest with --lan.';
}

function applyShop(shop) {
  $('app-version').textContent = (shop.version || '') + (shop.buildId ? ' · build ' + shop.buildId : '');
  $('onyx-pc').checked = shop.onyxPc === true;
  $('lan').checked = shop.runningLan === true;
  $('updates').checked = !!(shop && shop.updates === true);
  showOutputService(shop);
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
  renderCutLineNote();
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
  // First run: no setup card. Save the prefilled defaults; every field stays in Settings.
  panel.hidden = true;
  if (!$('setup-thru').value) $('setup-thru').value = $('thru-name').value;
  if (!$('setup-kiss').value) $('setup-kiss').value = $('kiss-name').value;
  $('setup-units').value = $('unit').value || 'in';
  if (shop.hotFolder && !$('setup-hot').value) $('setup-hot').value = shop.hotFolder;
  if (shop.printer && !$('setup-printer').value) $('setup-printer').value = shop.printer;
  $('setup-onyx').checked = $('onyx-pc').checked;
  if (shop.localPC === false || setupSaving) return;
  setupSaving = true;
  saveSetup(shop).catch(() => {}).finally(() => { setupSaving = false; renderCutLineNote(); });
}
let setupSaving = false;
function renderCutLineNote() {
  const short = name => String(name || '').replace(/^CutContour_/i, '') || 'not set';
  $('cut-line-names').textContent = short($('thru-name').value) + ', ' + short($('kiss-name').value);
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
  if ($('hot-folder').value.trim()) await saveHotFolder();
  else $('hot-error').hidden = true;
  if ($('hot-error').hidden) {
    $('setup').hidden = true;
    $('setup-error').hidden = true;
  } else {
    // A bad saved folder is reported in Settings; it never blocks nesting.
    $('setup').hidden = true;
  }
}

function shopPayload(extra) {
  const payload = Object.assign({
    lan: $('lan').checked,
    onyxPc: $('onyx-pc').checked,
    updates: $('updates').checked,
    channel: $('test-channel').checked ? 'test' : 'stable',
    outputNetwork: $('output-network').checked
  }, extra || {});
  const outputUrl = outputUrlField();
  if (outputUrl !== null) payload.outputUrl = outputUrl;
  return payload;
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

function reviewCutOutlines(file, review) {
  const dialog = $('cut-review'), pages = $('cut-review-pages'), choice = $('cut-review-operation');
  $('cut-review-file').textContent = file.name;
  $('cut-review-summary').textContent = review.count.toLocaleString() + ' closed outlines have no cut name. Check the highlighted lines, then choose how they should cut.';
  choice.value = ''; $('cut-review-accept').disabled = true;
  pages.replaceChildren();
  for (const preview of review.pages) {
    const section = document.createElement('section'), svg = document.createElementNS(NS, 'svg');
    const title = document.createElement('h3'); title.textContent = 'Page ' + preview.page;
    svg.setAttribute('viewBox', preview.viewBox.join(' '));
    svg.setAttribute('role', 'img'); svg.setAttribute('aria-label', 'Artwork with proposed cut outlines highlighted');
    const image = document.createElementNS(NS, 'image');
    ['x', 'y', 'width', 'height'].forEach((key, index) => image.setAttribute(key, preview.viewBox[index]));
    image.setAttribute('href', preview.image); svg.append(image);
    for (const outline of preview.paths) {
      const path = document.createElementNS(NS, 'path'); path.setAttribute('d', outline.d);
      path.setAttribute('vector-effect', 'non-scaling-stroke'); svg.append(path);
    }
    const viewport = document.createElement('div'); viewport.className = 'cut-review-viewport'; viewport.append(svg);
    const label = document.createElement('label'); label.textContent = 'Zoom';
    const zoom = document.createElement('input'); zoom.type = 'range'; zoom.min = 1; zoom.max = 8; zoom.step = .5; zoom.value = 1;
    zoom.setAttribute('aria-label', 'Zoom page ' + preview.page);
    zoom.oninput = () => { svg.style.width = (zoom.value * 100) + '%'; svg.style.height = (zoom.value * 320) + 'px'; };
    label.append(zoom); section.append(title, viewport, label); pages.append(section);
  }
  return new Promise(resolve => {
    const finish = accepted => {
      const operation = choice.value;
      if (accepted && !['kiss', 'thru'].includes(operation)) return;
      dialog.removeEventListener('cancel', cancel); choice.onchange = null;
      $('cut-review-cancel').onclick = null; $('cut-review-accept').onclick = null;
      dialog.close(); pages.replaceChildren();
      resolve(accepted ? {id:review.id, sourceHash:review.sourceHash, operation} : null);
    };
    const cancel = event => { event.preventDefault(); finish(false); };
    choice.onchange = () => { $('cut-review-accept').disabled = !choice.value; pages.dataset.operation = choice.value; };
    pages.dataset.operation = '';
    dialog.addEventListener('cancel', cancel);
    $('cut-review-cancel').onclick = () => finish(false);
    $('cut-review-accept').onclick = () => finish(true);
    dialog.showModal(); $('cut-review-cancel').focus();
  });
}

function reviewGuides(file, review) {
  const dialog = $('guide-review');
  $('guide-file').textContent = file.name;
  const count = review.lines.length;
  $('guide-summary').textContent = count + ' dashed lines may be guides. Exclude them only if they are not intended cuts or perforations.';
  const pages = $('guide-pages'); pages.replaceChildren();
  for (const preview of review.pages) {
    const section = document.createElement('section');
    const title = document.createElement('h3'); title.textContent = 'Page ' + preview.page;
    const svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('viewBox', preview.viewBox.join(' '));
    svg.setAttribute('role', 'img'); svg.setAttribute('aria-label', 'Cut outlines with possible guides highlighted');
    // Draw highlighted candidates last so crossings stay visible.
    for (const outline of [...preview.paths].sort((a,b) => Number(a.guide)-Number(b.guide))) {
      const path = document.createElementNS(NS, 'path'); path.setAttribute('d', outline.d);
      path.setAttribute('class', outline.guide ? 'possible-guide' : 'review-cut');
      path.setAttribute('vector-effect', 'non-scaling-stroke'); svg.append(path);
    }
    const note = document.createElement('p'); note.className = 'hint';
    note.textContent = review.lines.filter(line => line.page === preview.page).map(line => (line.lengthMm / 25.4).toFixed(2) + ' in').join(' · ');
    section.append(title, svg, note); pages.append(section);
  }
  $('guide-exclude').textContent = 'Exclude ' + count + ' lines and continue';
  return new Promise(resolve => {
    const finish = accepted => {
      dialog.removeEventListener('cancel', cancel);
      $('guide-cancel').onclick = null; $('guide-exclude').onclick = null;
      dialog.close(); pages.replaceChildren();
      resolve(accepted ? {id: review.id, sourceHash: review.sourceHash, excludedIds: review.lines.map(line => line.id)} : null);
    };
    const cancel = event => { event.preventDefault(); finish(false); };
    dialog.addEventListener('cancel', cancel);
    $('guide-cancel').onclick = () => finish(false);
    $('guide-exclude').onclick = () => finish(true);
    dialog.showModal(); $('guide-cancel').focus();
  });
}

function showImportError(error) {
  // A rejected new file must not invalidate a previously checked layout.
  if (current?.result) showResult(current);
  else if (!kits.length) { showScreen('drop'); renderActions(); }
  status(error.message, !error.importCancelled);
}

async function importPdf(file, operation) {
  const mapping = EZNCuts.defaults();
  mapping.rules.push(
    {source: 'layer', match: 'exact', name: 'thru-cut', operation: 'thru'},
    {source: 'layer', match: 'exact', name: 'kiss cut', operation: 'kiss'});
  mapping.genericOperation = operation;
  const request = {preserveArtwork: true, cutSpot: 'CutContour', cutMapping: EZNCuts.validate(mapping)};
  try { return await api('/api/document/import-file', request, file); }
  catch (error) {
    if (error.cutReview) {
      const approval = await reviewCutOutlines(file, error.cutReview);
      if (!approval) { const cancelled = Error('File not added. Cut review cancelled.'); cancelled.importCancelled = true; throw cancelled; }
      status('Preparing the reviewed stickers…');
      return api('/api/document/import-file', {...request, cutApproval: approval}, file);
    }
    if (!error.guideReview) throw error;
    const approval = await reviewGuides(file, error.guideReview);
    if (!approval) { const cancelled = Error('File not added. Guide review cancelled.'); cancelled.importCancelled = true; throw cancelled; }
    status('Reading file with the reviewed guides excluded…');
    return api('/api/document/import-file', {...request, guideApproval: approval}, file);
  }
}

async function readEntry(file) {
  const pdf = /\.(pdf|ai)$/i.test(file.name);
  if (!pdf && !/\.svg$/i.test(file.name)) throw Error(file.name + ' is not SVG, PDF, or PDF-compatible AI.');
  if (file.size > (pdf ? 2_000_000_000 : 8_000_000)) throw Error(file.name + ' is over the ' + (pdf ? '2 GB' : '8 MB') + ' limit.');
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
    id: 'web-' + revision.slice(0, 12) + '-' + (fileSerial++), name: file.name, sourceFile: file.name, revision,
    origin: 'files', role: 'required', customer: '', order: '', kit: '', materialId: 'web-roll',
    sets: 1, selected: true, status: 'ready', data, file, unresolved: unresolvedCut
  };
}

async function importFiles(fileList, replace) {
  if (presetEditor) throw Error('Save or cancel the preset before adding files.');
  const files = [...fileList].filter(Boolean);
  if (!files.length || busy || importing || saving) return;
  if (illustratorHandoff && !replace) throw Error('Start over before adding files to another Illustrator attempt.');
  const incomingPdf = files.some(file => /\.(pdf|ai)$/i.test(file.name));
  const incomingSvg = files.some(file => /\.svg$/i.test(file.name));
  const havePdf = !replace && kits.some(entry => entry.data?.format === 'pdf');
  const haveSvg = !replace && kits.some(entry => entry.data?.format === 'svg');
  if ((incomingPdf && incomingSvg) || (incomingPdf && haveSvg) || (incomingSvg && havePdf)) {
    throw Error('Nest SVG files in one batch and PDF files in another. That keeps the original artwork.');
  }
  importing = true;
  renderActions();
  status('Reading ' + files.length + (files.length === 1 ? ' file…' : ' files…'));
  const entries = [];
  try {
    for (const file of files) {
      try { entries.push(await readEntry(file)); }
      catch (error) {
        if (!error.importCancelled) error.message = file.name + ': ' + error.message + (files.length > 1 ? ' No files from this selection were added.' : '');
        throw error;
      }
    }
  } finally {
    importing = false;
    renderActions();
    if (pendingRenest) { pendingRenest = false; requestNest(); }
  }
  kits = replace ? entries : kits.concat(entries);
  current = null;
  blockReason = '';
  leaving = false;
  renderFiles();
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
      showImportError(error);
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
  $('print-layout').value = job.settings?.continuous ? 'continuous' : 'sections';
  const settings = job.settings;
  if (['mm', 'in', 'cm'].includes(options.units)) $('unit').value = options.units;
  $('unit').dataset.current = $('unit').value;
  const factor = scale();
  $('roll-cost').value = options.rollCost ?? '';
  $('roll-length').value = options.fullRollLengthMm == null ? '' : options.fullRollLengthMm / factor;
  for (const node of document.querySelectorAll('span[data-unit]')) node.textContent = $('unit').value;
  if (options.material && [...$('material').options].some(option => option.value === options.material)) $('material').value = options.material;
  $('preset-name').value = job.materialName || job.media?.name || 'Custom roll';
  $('width').value = (job.media?.maxPrintableMm || settings.width) / factor;
  $('nest-width').value = settings.width / 25.4;
  for (const [id, key] of [['available-length', 'maxLength'], ['gap', 'gap'], ['roll', 'rollWidth'], ['sheet', 'sheetLength'], ['mark-margin', 'markMargin']]) {
    $(id).value = settings[key] == null ? '' : settings[key] / factor;
  }
  if (settings.continuous && options.sectionLengthMm != null) $('sheet').value = options.sectionLengthMm / factor;
  $('margin').value = (settings.edgeMargin ?? (settings.margin - (settings.markMargin || 0))) / factor;
  setNestingEffort(prefs().nestingSeconds ?? settings.seconds);
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

let outputSharing = null;
function renderOutputSharing(info) {
  outputSharing = info;
  const source = info.connection;
  const paired = source === 'paired';
  const launch = source === 'environment' || source === 'environment-invalid';
  $('output-connect-shop').hidden = !paired;
  $('output-connect-shop').textContent = !paired ? '' : (info.shopName ? 'Connected to ' + info.shopName + '.' : 'Connected to OUTPUT');
  $('output-pair-form').hidden = paired || launch || source === 'disabled';
  $('output-disconnect').hidden = !paired;
  $('output-pair').disabled = $('output-pair-form').hidden || info.paused;
  $('output-disconnect').disabled = !paired || info.paused;
  const connectStatus = $('output-connect-status');
  connectStatus.classList.remove('error');
  if (info.paused) connectStatus.textContent = 'Sharing is paused during installation or recovery.';
  else if (launch) connectStatus.textContent = 'This computer uses OUTPUT launch settings. A pairing code is not used while those settings are present.';
  else if (source === 'disabled') connectStatus.textContent = 'OUTPUT delivery is turned off for this run.';
  else if (paired && info.requiresConsent) connectStatus.textContent = 'Review the sharing details below, then choose Enable sharing.';
  else if (paired) connectStatus.textContent = '';
  else connectStatus.textContent = 'Not connected. Nesting, saving, and stock work without OUTPUT.';
  $('telemetry-agree').checked = false;
  $('telemetry-agree').disabled = !info.configured || info.enabled || info.paused;
  $('telemetry-enable').disabled = true;
  $('telemetry-stop').disabled = !info.enabled || info.paused;
  $('telemetry-kinds').textContent = info.eventTypes.join(', ');
  $('telemetry-bands').textContent = 'Measurement range widths (null means unknown; 0 means zero): ' + Object.entries(info.bands).map(([key, step]) => key + ': ' + step).join('; ') + '.';
  const bands = Object.fromEntries(Object.entries(info.bands).map(([key, step]) => [key, `[${step},${step * 2})`]));
  $('telemetry-preview').textContent = JSON.stringify({schema: info.schema, requestId: '00000000-0000-5000-8000-000000000001', kind: 'nest.created', instanceId: info.instanceId, nestId: '00000000000000000000000000000001', occurredAt: '2026-01-01T00:00:00.000000Z', appVersion: info.appVersion, materialClass: 'moto_regular', bands}, null, 2);
  $('telemetry-status').textContent = info.paused ? 'Sharing paused during installation or recovery. Refresh after the host restarts to change sharing settings.' : !info.configured ? 'Off. Connect this computer to OUTPUT, then review the fields below.' : info.enabled ? `Sharing new activity. ${info.pendingEvents} pending. ${info.withheldEvents} invalid observations kept only on this host. ${info.lastError || (info.lastDeliveredAt ? 'Last receipt: ' + info.lastDeliveredAt : 'No confirmed delivery yet.')}` : 'Off. Activity sharing stays off until you agree. The account connection stays in place.';
}
async function refreshOutputSharing() {
  try {
    const response = await fetch('/api/telemetry/output', {headers: {'X-EZ-Token': token}});
    if (!response.ok) throw Error('Review and manage OUTPUT sharing on the host computer.');
    renderOutputSharing(await response.json());
  } catch (error) {
    outputSharing = null;
    $('telemetry-agree').disabled = $('telemetry-enable').disabled = $('telemetry-stop').disabled = true;
    $('telemetry-status').textContent = error.message;
  }
}
async function connectOutput() {
  const input = $('output-pair-code');
  const status = $('output-connect-status');
  const code = input.value.trim();
  if (!code) {
    status.textContent = 'Paste the pairing code from OUTPUT.';
    status.classList.add('error');
    return;
  }
  $('output-pair').disabled = true;
  try {
    const response = await fetch('/api/telemetry/output/pair', {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-EZ-Token': token},
      body: JSON.stringify({code})
    });
    const body = await response.json();
    if (!response.ok) {
      const failure = Error(body.error || 'Could not connect to OUTPUT.');
      failure.reason = body.reason;
      throw failure;
    }
    input.value = '';
    renderOutputSharing(body);
    refreshOutputLink().catch(() => {});
    if (body.requiresConsent && !$('telemetry-agree').disabled) $('telemetry-agree').focus();
  } catch (error) {
    if (['invalid_code', 'expired', 'consumed', 'limit', 'replay', 'unexpected', 'rejected'].includes(error.reason)) input.value = '';
    await refreshOutputSharing().catch(() => {});
    status.textContent = error.message;
    status.classList.add('error');
  }
}
async function disconnectOutput() {
  if (!window.confirm('Disconnect this computer from OUTPUT? Nesting, saving, and stock keep working on this computer.')) return;
  $('output-disconnect').disabled = true;
  try {
    renderOutputSharing(await api('/api/telemetry/output/disconnect', {}));
    await refreshOutputLink();
  } catch (error) {
    $('output-connect-status').textContent = error.message;
    $('output-connect-status').classList.add('error');
    refreshOutputSharing().catch(() => {});
  }
}
async function changeOutputSharing(enable) {
  if (enable && (!outputSharing || outputSharing.paused || !$('telemetry-agree').checked)) return;
  $('telemetry-enable').disabled = $('telemetry-stop').disabled = true;
  try {
    const data = enable ? {revision: outputSharing.revision, version: outputSharing.consentVersion, configurationId: outputSharing.configurationId, confirmed: true} : {};
    renderOutputSharing(await api('/api/telemetry/output/' + (enable ? 'consent' : 'revoke'), data));
  } catch (error) {
    $('telemetry-status').textContent = error.message + ' Refresh sharing status before trying again.';
    outputSharing = null;
    $('telemetry-agree').checked = false;
    $('telemetry-agree').disabled = true;
  }
}

async function boot() {
  closeSettingsFolds();
  await ensureLibraries();
  const stored = prefs();
  setNestingEffort(stored.nestingSeconds);
  loadMaterialProfiles(stored);
  if (stored.material && [...$('material').options].some(option => option.value === stored.material)) {
    $('material').value = stored.material;
    applyMaterial(true);
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
  let session = await fetchJsonRetry('/api/session');
  token = session.token || '';
  localSave = session.localSave === true;
  renderOutputLink(session.outputLink, session.localPC);
  if (session.localPC && session.pinWeak) {
    await requireHostPinReset();
    session = await fetchJsonRetry('/api/session');
  }
  if (session.localPC && $('shop-pin')) {
    $('shop-pin').hidden = false;
    showPinNotices(session);
  } else if (!session.localPC && !session.authenticated) {
    await requireShopPin(session);
    $('logout').hidden = false;
  } else if (!session.localPC) {
    $('logout').hidden = false;
  }
  await refreshInventory().catch(() => {});
  if (inventoryReady && shopInventory.materials.some(item => item.id === stored.material)) $('material').value = stored.material;
  if (inventoryReady && shopInventory.materials.some(item => item.id === $('material').value)) applyMaterial(true);
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
  setInterval(() => { if (!document.hidden && !inventoryBusy && !stockForm && !document.querySelector('dialog[open]')) refreshInventory().catch(() => {}); }, 10000);
}

function showOutputBanner(session) {
  const banner = $('output-banner');
  if (!banner) return;
  const text = session && session.outputConnection && session.outputConnection.banner;
  banner.hidden = !text;
  banner.textContent = text || '';
}

function requireHostPinReset() {
  const gate = $('pin-gate');
  const note = $('pin-note');
  const input = $('pin-input');
  const submit = $('pin-submit');
  const error = $('pin-error');
  $('pin-title').textContent = 'Replace the shop PIN';
  note.textContent = 'This PIN is from before the current rule. Designer computers can keep using it until you save a new one here. Use 8 to 12 digits, or a passphrase of at least 10 characters with a letter.';
  input.hidden = false;
  input.value = '';
  submit.hidden = false;
  submit.textContent = 'Save new PIN';
  submit.disabled = false;
  error.hidden = true;
  gate.addEventListener('cancel', event => event.preventDefault());
  gate.showModal();
  input.focus();
  return new Promise(resolve => {
    $('pin-form').onsubmit = async event => {
      event.preventDefault();
      submit.disabled = true;
      try {
        await api('/api/pin', {pin: input.value});
        input.value = '';
        gate.close();
        resolve();
      } catch (err) {
        error.hidden = false;
        error.textContent = err.message;
        submit.disabled = false;
      }
    };
  });
}

function showPinNotices(session) {
  const box = $('pin-alert');
  const text = $('pin-alert-text');
  const ack = $('pin-alert-ack');
  if (!box || !session || !session.localPC) return;
  const parts = [];
  if (session.pinAlert && session.pinAlert.active) {
    parts.push('Shop PIN failures are arriving from the network (' + session.pinAlert.failures + ' since you last reviewed them). This does not lock anyone out. Each address still waits longer after repeated tries.');
  }
  if (session.pinWeak) parts.push('This shop PIN was saved before the current rule. Set a new one: 8 to 12 digits, or a passphrase of at least 10 characters with a letter.');
  box.hidden = parts.length === 0;
  text.textContent = parts.join(' ');
  ack.hidden = !(session.pinAlert && session.pinAlert.active);
}

function requireShopPin(session) {
  const gate = $('pin-gate');
  const note = $('pin-note');
  const input = $('pin-input');
  const submit = $('pin-submit');
  const error = $('pin-error');
  error.hidden = true;
  error.textContent = '';
  if (!session.pinConfigured) {
    note.textContent = 'Ask the person at the shop computer to set a PIN, then refresh this page.';
    input.hidden = true;
    submit.hidden = true;
    gate.showModal();
    return new Promise(() => {});
  }
  note.textContent = session.pinWeak
    ? 'This PIN still works. The shop computer must replace it. You can keep nesting until then. You stay signed in on this browser until you log out, stay idle for an hour, or eight hours pass.'
    : 'Enter the shop PIN or passphrase from the computer that runs Ez Nest. You stay signed in on this browser until you log out, stay idle for an hour, or eight hours pass.';
  input.hidden = false;
  submit.hidden = false;
  gate.showModal();
  input.focus();
  return new Promise(resolve => {
    $('pin-form').onsubmit = async event => {
      event.preventDefault();
      submit.disabled = true;
      try {
        const response = await fetch('/api/login', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({pin: input.value})
        });
        const body = await response.json().catch(() => ({}));
        if (!response.ok) throw Error(body.error || 'Could not sign in.');
        input.value = '';
        gate.close();
        resolve();
      } catch (err) {
        error.hidden = false;
        error.textContent = err.message;
        submit.disabled = false;
      }
    };
  });
}

function stockInput(mm, unit) { return String(Number((mm / EZNQueue.unitScale(unit)).toFixed(3))); }

function stockFeet(mm) { return mm == null ? 'unknown' : (mm / 304.8).toFixed(2) + ' ft'; }

function acceptInventory(data) {
  const changed = JSON.stringify(data) !== JSON.stringify(shopInventory);
  if (changed) $('inventory-status').textContent = '';
  shopInventory = data;
  inventoryReady = true;
  for (const item of data.materials) {
    const values = {...item.profile, 'available-length': item.availableMm == null ? '' : String(item.availableMm / EZNQueue.unitScale(item.profile.unit))};
    registerMaterial(item.id, values);
  }
  renderMaterialButtons();
  renderInventory();
  if (changed && $('stock')?.open) renderStock();
}

async function mutateInventory(path, payload) {
  inventoryGen++;
  try {
    const data = await api(path, payload);
    inventoryGen++;
    acceptInventory(data);
    return data;
  } catch (error) { inventoryGen++; throw error; }
}

async function refreshInventory() {
  const gen = inventoryGen;
  try {
    const data = await fetchJson('/api/materials', 5000);
    // A save or remove happened after this request started: its answer is newer.
    if (gen !== inventoryGen) return;
    acceptInventory(data);
  }
  catch (error) {
    inventoryReady = false;
    $('inventory-status').textContent = 'Shop stock is unavailable. Reconnect before reserving or confirming usage.';
    renderInventory();
    throw error;
  }
}

function materialStockDirty() {
  return !!presetEditor && JSON.stringify(materialValues()) !== JSON.stringify(presetEditor.savedValues);
}

function renderInventory() {
  for (const field of $('preset-editor').querySelectorAll('.fields, #material-advanced')) field.inert = inventoryBusy;
  const id = presetEditor?.id;
  const material = shopInventory.materials.find(item => item.id === id);
  const dirty = materialStockDirty();
  const box = $('inventory-materials'); box.replaceChildren();
  if (material) {
    for (const [label, value] of [['On roll', material.onHandMm], ['Reserved', material.reservedMm], ['Available', material.availableMm]]) {
      const metric = document.createElement('div');
      const name = document.createElement('span'); name.textContent = label;
      const amount = document.createElement('strong'); amount.textContent = stockFeet(value);
      metric.append(name, amount); box.append(metric);
    }
  }
  box.hidden = !material;
  const matches = !!material && current?.job?.inventoryMaterialId === id;
  const prior = shopInventory.reservations.find(row => row.id === current?.id && row.material === id);
  const reserve = $('inventory-reserve');
  reserve.hidden = !matches || !current?.result;
  reserve.disabled = !inventoryReady || inventoryBusy || busy || saving || dirty || !!prior || !!pieceIssue(current) || !!cutProblem();
  reserve.textContent = prior ? (prior.status === 'reserved' ? 'Reserved for this job' : prior.status === 'used' ? 'Material use recorded' : 'Reservation released') : 'Reserve for this job';
  $('inventory-job-note').textContent = dirty && material ? 'Save your changes before updating usage.' : current?.result && !matches && id === $('material').value ? 'Save this material, then nest again to reserve stock for this job.' : '';
  const history = shopInventory.reservations.filter(row => row.material === id);
  $('material-usage').hidden = !history.length;
  const rows = $('inventory-reservations'); rows.replaceChildren();
  for (const row of history) {
    const card = document.createElement('section'); card.className = 'inventory-row';
    const text = document.createElement('p');
    text.textContent = `${stockFeet(row.length)} · ${row.status === 'used' ? 'Used' : row.status === 'cancelled' ? 'Released' : 'Reserved'} · job ${row.id.slice(0, 8)}`;
    card.append(text);
    if (row.status === 'reserved') {
      for (const [action, label] of [['use','Confirm material used'], ['cancel','Release reservation']]) {
        const button = document.createElement('button'); button.type = 'button'; button.className = 'link'; button.textContent = label;
        button.disabled = !inventoryReady || inventoryBusy || dirty;
        button.addEventListener('click', () => inventoryAction('/api/materials/transition', {id: row.id, action})); card.append(button);
      }
    }
    rows.append(card);
  }
}

async function inventoryAction(path, payload) {
  if (inventoryBusy || !presetEditor || materialStockDirty()) return;
  inventoryBusy = true; $('save-material').disabled = true; renderInventory();
  try {
    await mutateInventory(path, payload);
    const updated = shopInventory.materials.find(item => item.id === presetEditor.id);
    if (updated) {
      presetEditor.revision = updated.revision;
      setMaterialValues({...updated.profile, 'available-length': updated.onHandMm == null ? '' : stockInput(updated.onHandMm, updated.profile.unit)});
      presetEditor.savedValues = materialValues();
      presetEditor.values['available-length'] = updated.availableMm == null ? '' : String(updated.availableMm / EZNQueue.unitScale(presetEditor.values.unit));
    }
    if (path.endsWith('/reserve')) $('material-usage').open = true;
    $('inventory-status').textContent = payload.action === 'use' ? 'Material use recorded. Stock updated.' : payload.action === 'cancel' ? 'Reservation released. Stock is available again.' : 'Material reserved. Physical stock is unchanged until you confirm usage.';
  } catch (error) {
    await refreshInventory().catch(() => {});
    $('inventory-status').textContent = error.message;
  } finally { inventoryBusy = false; $('save-material').disabled = false; renderInventory(); }
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
  $('illustrator-note').textContent = 'Choose nesting effort, then Start nesting. Review colors and cuts before saving. Your saved Illustrator PDF preset was used.';
  $('illustrator-load').hidden = true;
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
  $('update').disabled = !!info?.queued || !!info?.busy;
  const note = $('update-note');
  $('update').textContent = info?.managedSupported && info?.staged ? 'Install when finished' : info?.applyOnRestart ? 'Install now' : 'Check for update';
  if (info?.updateAvailable && !info.staged) $('update').textContent = 'Download ' + info.latest;
  if (info?.platform === 'macos' && info?.staged) $('update').textContent = 'Open Mac installer';
  if (info?.busy) $('update').textContent = 'Checking update…';
  $('settings-open').title = info?.updateAvailable ? 'Settings - update available' : 'Settings';
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
  if (info && (info.staged || info.applyOnRestart || info.updateAvailable || info.queued || info.managedResult || info.busy || info.error) && info.message) {
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

// Only dismiss a backdrop click that started and ended outside the dialog.
// Dragging from an input to the backdrop must not discard material edits.
function dismissOnBackdrop(dialog, dismiss) {
  let startedOutside = false;
  const outside = event => {
    const r = dialog.getBoundingClientRect();
    return event.target === dialog && (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom);
  };
  dialog.addEventListener('pointerdown', event => { startedOutside = outside(event); });
  dialog.addEventListener('click', event => {
    if (startedOutside && outside(event)) dismiss();
    startedOutside = false;
  });
  dialog.addEventListener('pointercancel', () => { startedOutside = false; });
}

function closeSettingsFolds() {
  for (const id of ['settings-cuts', 'settings-delivery', 'settings-updates']) {
    const node = $(id);
    if (node) node.open = false;
  }
}

function syncWelcome() {
  $('feedback-welcome').hidden = !!prefs().feedbackWelcomed || kits.length > 0 || !!current;
}

document.addEventListener('DOMContentLoaded', () => {
  closeSettingsFolds();
  $('inventory-open').addEventListener('click', () => openPreset($('material').value));
  $('preset-editor').addEventListener('input', renderInventory);
  $('preset-editor').addEventListener('change', renderInventory);
  $('inventory-reserve').addEventListener('click', () => inventoryAction('/api/materials/reserve', {id: current?.id}));
  installSettingsHelp();
  $('settings-open').addEventListener('click', () => {
    const dialog = $('settings');
    if (!dialog.open) dialog.showModal();
    $('hot-folder').focus();
  });
  $('settings-close').addEventListener('click', () => $('settings').close());
  $('settings-telemetry').addEventListener('toggle', () => { if ($('settings-telemetry').open) refreshOutputSharing(); });
  $('telemetry-refresh').addEventListener('click', refreshOutputSharing);
  $('telemetry-agree').addEventListener('change', () => { $('telemetry-enable').disabled = !outputSharing || !outputSharing.configured || outputSharing.enabled || outputSharing.paused || !$('telemetry-agree').checked; });
  $('output-pair').addEventListener('click', connectOutput);
  $('output-disconnect').addEventListener('click', disconnectOutput);
  $('output-pair-code').addEventListener('keydown', event => {
    if (event.key === 'Enter') { event.preventDefault(); connectOutput(); }
  });
  $('telemetry-enable').addEventListener('click', () => changeOutputSharing(true));
  $('telemetry-stop').addEventListener('click', () => changeOutputSharing(false));
  dismissOnBackdrop($('settings'), () => { if (!$('save-settings').disabled) $('settings').close(); });
  $('max-output-waitlist').href = OUTPUT_WAITLIST_URL;
  $('max-output-learn').href = OUTPUT_WEBSITE_URL;
  const choiceRow = document.querySelector('.output-modes');
  if (choiceRow && !window.matchMedia('(prefers-reduced-motion: reduce)').matches && 'IntersectionObserver' in window) {
    const watchChoices = new IntersectionObserver(entries => {
      if (!entries.some(entry => entry.isIntersecting)) return;
      requestAnimationFrame(() => requestAnimationFrame(() => choiceRow.classList.add('choice-seen')));
      watchChoices.disconnect();
    });
    watchChoices.observe($('layout-options'));
  }
  $('max-output').addEventListener('click', () => {
    const dialog = $('max-output-dialog');
    if (!dialog.open) dialog.showModal();
    $('max-output-close').focus();
  });
  $('max-output-close').addEventListener('click', () => $('max-output-dialog').close());
  dismissOnBackdrop($('max-output-dialog'), () => $('max-output-dialog').close());
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
    catch (error) { showImportError(error); }
    finally { event.target.value = ''; }
  });
  document.addEventListener('dragover', event => { event.preventDefault(); document.body.classList.add('dragging'); });
  document.addEventListener('dragleave', event => { if (!event.relatedTarget) document.body.classList.remove('dragging'); });
  document.addEventListener('drop', async event => {
    event.preventDefault();
    document.body.classList.remove('dragging');
    ignoreFileChange = true;
    try { await importFiles(event.dataTransfer.files); }
    catch (error) { showImportError(error); }
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
  $('material-close').addEventListener('click', closePreset);
  dismissOnBackdrop($('material-dialog'), closePreset);
  $('material-dialog').addEventListener('cancel', event => { event.preventDefault(); closePreset(); });
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
  $('shop-pin-save').addEventListener('click', () => {
    const input = $('shop-pin-input');
    const error = $('shop-pin-error');
    api('/api/pin', {pin: input.value}).then(() => {
      input.value = '';
      error.hidden = true;
      status('Shop PIN saved on this computer.');
      return fetchJson('/api/session').then(showPinNotices);
    }).catch(err => {
      error.hidden = false;
      error.textContent = err.message;
    });
  });
  $('pin-alert-ack').addEventListener('click', () => {
    api('/api/pin/alert/ack', {}).then(() => fetchJson('/api/session').then(showPinNotices)).catch(err => status(err.message, true));
  });
  $('logout').addEventListener('click', () => {
    fetch('/api/logout', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'}).finally(() => location.reload());
  });
  $('lan').addEventListener('change', () => { saveDeploy().catch(error => status(error.message, true)); });
  $('onyx-pc').addEventListener('change', () => { saveDeploy().catch(error => status(error.message, true)); });
  $('updates').addEventListener('change', () => { saveDeploy().catch(error => status(error.message, true)); });
  if ($('output-url')) $('output-url').addEventListener('change', () => {
    if (outputUrlField() === null) {
      status('OUTPUT address must be an https URL with no path or password.', true);
      return;
    }
    saveDeploy().catch(error => status(error.message, true));
  });
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
      $('update-note').textContent = updateInfo.platform === 'macos'
        ? 'Approve the Mac installer prompt. Finish or discard any unsent job first. If no installer opens, reopen Ez Nest and try again.'
        : 'Approve the Windows prompt. The helper will wait until work is finished. If no prompt opens, use Update eznest in the Windows Start menu.';
      return;
    }
    const installNow = $('update').textContent === 'Install now';
    try {
      const result = await api('/api/update', {when: installNow ? 'now' : 'restart'});
      // Mac verification/download continues in the background. Keep its
      // progress in Settings without replacing the current job's status.
      if (result.platform !== 'macos') status(result.message);
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
  $('start-over-idle').addEventListener('click', startOver);
  $('more').addEventListener('change', async event => {
    try { await importFiles(event.target.files); }
    catch (error) { showImportError(error); }
    finally { event.target.value = ''; }
  });
  $('stop').addEventListener('click', stopNest);
  $('improve').addEventListener('click', improve);
  $('piece-review').addEventListener('toggle', renderPieceReview);
  const dismissWelcome = () => { $('feedback-welcome').hidden = true; savePrefs({feedbackWelcomed: true}); };
  syncWelcome();
  $('feedback-dismiss').addEventListener('click', dismissWelcome);
  $('in-house').addEventListener('click', () => $('nesting-effort').focus());
  $('start-nesting').addEventListener('click', () => { dismissWelcome(); nest(); });
  $('feedback-open').addEventListener('click', () => {
    dismissWelcome();
    $('feedback-numbers').checked = false;
    $('feedback-version').textContent = 'App version: ' + $('app-version').textContent;
    updateFeedbackPreview();
    const dialog = $('feedback-dialog');
    if (!dialog.open) dialog.showModal();
    $('feedback-message').focus();
  });
  $('feedback-close').addEventListener('click', () => $('feedback-dialog').close());
  $('feedback-message').addEventListener('input', updateFeedbackPreview);
  $('feedback-numbers').addEventListener('change', updateFeedbackPreview);
  $('feedback-download').addEventListener('click', () => {
    const url = URL.createObjectURL(new Blob([feedbackText()], {type: 'text/plain;charset=utf-8'}));
    const link = document.createElement('a'); link.href = url; link.download = 'EZ-Nest-feedback.txt'; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
  $('feedback-send').addEventListener('click', () => {
    const url = new URL($('report').href);
    url.searchParams.delete('template'); url.searchParams.set('title', 'Tester feedback'); url.searchParams.set('body', feedbackText());
    window.open(url.toString(), '_blank', 'noopener,noreferrer');
  });
  $('nesting-effort').addEventListener('change', () => {
    setNestingEffort($('nesting-effort').value);
    savePrefs({nestingSeconds: Number($('nesting-effort').value)});
    // Changing effort affects the next search. It never discards a reviewed fit.
  });
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
    if ($('settings').open || $('stock').open || $('max-output-dialog').open || importing || $('guide-review').open || $('feedback-dialog').open || $('folder-picker').open || presetEditor || event.target.closest('input, select, textarea, summary, .help-label, #settings, #settings-open, #top-actions, #stock, #in-house, #max-output, #nest-savings, #feedback-open, #feedback-dismiss, #start-nesting, #choose-thru, #choose-kiss, #choose-confirm, #confirm-send, #confirm-back, #materials, #sets-dec, #sets-inc, #sheet-tabs, #files, #add-files, #stop, #improve, #update, #setup, #edit-material')) return;
    if (document.body.dataset.step === 'blocked' || $('gate').classList.contains('problem')) { event.preventDefault(); return; }
    if (busy || saving) return;
    if (document.body.dataset.step === 'sent') { event.preventDefault(); startOver(); return; }
    if (document.body.dataset.step === 'confirm') { event.preventDefault(); exportFile(); return; }
    if (document.body.dataset.step === 'check' && current && current.result && !$('export').disabled) { event.preventDefault(); openConfirm(); }
  });
  boot().catch(error => status(error.message, true));
});


// --- OUTPUT link control (header). Connecting is optional; nothing here blocks nesting.
let outputLink = null;
let outputLinkLocal = true;
function agoText(seconds) {
  if (seconds == null) return '';
  if (seconds < 90) return 'just now';
  if (seconds < 5400) return Math.round(seconds / 60) + ' min ago';
  if (seconds < 172800) return Math.round(seconds / 3600) + ' h ago';
  return Math.round(seconds / 86400) + ' days ago';
}
function renderOutputLink(info, local) {
  outputLink = info || null;
  if (local !== undefined) outputLinkLocal = local !== false;
  const root = $('output-link');
  if (!root) return;
  const state = info?.state || 'unpaired';
  const paired = state === 'connected' || state === 'stale';
  root.dataset.state = state;
  root.hidden = !info;
  if (info?.connectUrl) $('output-link-open').href = info.connectUrl;
  $('output-link-connect').hidden = paired || !$('output-link-form').hidden;
  $('output-link-connect').textContent = state === 'revoked' ? 'Reconnect to OUTPUT' : 'Connect to OUTPUT';
  $('output-link-connect').disabled = !info?.canPair;
  $('output-link-connect').title = info?.canPair ? '' : 'Connect from the shop computer.';
  $('output-link-status').hidden = !paired;
  const name = info?.shopName ? ' · ' + info.shopName : '';
  $('output-link-label').textContent = state === 'stale' ? 'Last seen ' + (agoText(info.secondsSinceCheckIn) || 'not yet') : 'Connected' + name;
  $('output-link-detail').textContent = state === 'stale'
    ? (info.secondsSinceCheckIn == null ? 'OUTPUT has not heard from this computer yet.' : 'Last check-in ' + agoText(info.secondsSinceCheckIn) + '. Nesting keeps working.')
    : 'Connected' + name + '. Last check-in ' + (agoText(info?.secondsSinceCheckIn) || 'not yet') + '.';
  for (const id of ['output-link-reconnect', 'output-link-disconnect']) $(id).disabled = !info?.canPair;
  const dot = $('output-dot');
  if (dot) {
    const live = state === 'connected' && info?.secondsSinceCheckIn != null;
    dot.classList.toggle('connected', live);
    const label = live ? 'Connected to OUTPUT' + name : paired ? $('output-link-label').textContent : 'Connect to OUTPUT';
    dot.title = label; dot.setAttribute('aria-label', label);
  }
}
async function refreshOutputLink() {
  const session = await fetchJson('/api/session', 5000);
  renderOutputLink(session.outputLink, session.localPC);
}
function closeOutputLinkMenu() {
  $('output-link-menu').hidden = true;
  $('output-link-status').setAttribute('aria-expanded', 'false');
}
function openOutputLinkForm() {
  closeOutputLinkMenu();
  const url = outputLink?.connectUrl;
  if (url) window.open(url, '_blank', 'noopener,noreferrer');
  $('output-link-form').hidden = false;
  $('output-link-connect').hidden = true;
  $('output-link-error').hidden = true;
  $('output-link-code').value = '';
  $('output-link-code').focus();
}
function closeOutputLinkForm() {
  $('output-link-form').hidden = true;
  $('output-link-code').value = '';
  renderOutputLink(outputLink);
}
async function submitOutputLink(event) {
  event.preventDefault();
  const code = $('output-link-code').value.trim();
  const error = $('output-link-error');
  if (!code) { error.textContent = 'Paste the pairing code from OUTPUT.'; error.hidden = false; return; }
  $('output-link-submit').disabled = true;
  try {
    const body = await api('/api/telemetry/output/pair', {code});
    $('output-link-code').value = '';
    $('output-link-form').hidden = true;
    renderOutputSharing(body);
    await refreshOutputLink();
  } catch (failure) {
    $('output-link-code').value = '';
    error.textContent = failure.message;
    error.hidden = false;
  } finally {
    $('output-link-submit').disabled = false;
  }
}
async function checkOutputLink() {
  $('output-link-check').disabled = true;
  $('output-link-detail').textContent = 'Checking…';
  try {
    await api('/api/telemetry/output/check-in', {});
    await refreshOutputLink();
    if (outputLink?.state === 'stale') $('output-link-detail').textContent = 'OUTPUT did not answer. Nesting keeps working. Try again later.';
  } catch (failure) {
    $('output-link-detail').textContent = failure.message;
  } finally {
    $('output-link-check').disabled = false;
  }
}
async function disconnectOutputLink() {
  closeOutputLinkMenu();
  if (!window.confirm('Disconnect this computer from OUTPUT? Nesting, saving, and stock keep working on this computer.')) return;
  try {
    renderOutputSharing(await api('/api/telemetry/output/disconnect', {}));
  } catch (failure) {
    status(failure.message, true);
  }
  await refreshOutputLink().catch(() => {});
}
$('output-link-connect').addEventListener('click', openOutputLinkForm);
$('output-link-reconnect').addEventListener('click', openOutputLinkForm);
$('output-link-cancel').addEventListener('click', closeOutputLinkForm);
$('output-link-form').addEventListener('submit', submitOutputLink);
$('output-link-check').addEventListener('click', checkOutputLink);
$('output-link-disconnect').addEventListener('click', disconnectOutputLink);
$('output-link-status').addEventListener('click', () => {
  const open = $('output-link-menu').hidden;
  $('output-link-menu').hidden = !open;
  $('output-link-status').setAttribute('aria-expanded', String(open));
  if (open) $('output-link-check').focus();
});
document.addEventListener('click', event => { if (!event.target.closest('#output-link')) closeOutputLinkMenu(); });
document.addEventListener('keydown', event => {
  if (event.key !== 'Escape') return;
  if (!$('output-link-menu').hidden) { closeOutputLinkMenu(); $('output-link-status').focus(); }
  else if (!$('output-link-form').hidden && event.target.closest('#output-link-form')) closeOutputLinkForm();
});

// --- Inventory (Stock) dialog. Reads and writes the shared shop inventory.
function rollWidthText(item) {
  const p = item.profile;
  return `${Number(p.roll)} ${p.unit} roll · ${Number(p.width)} ${p.unit} printable`;
}
function rollLowText(item) {
  return lowStock({...item.profile, 'available-length': item.availableMm == null ? '' : String(item.availableMm / EZNQueue.unitScale(item.profile.unit))});
}
function rollCostPerSqFt(item) {
  const p = item.profile;
  const cost = Number(p['roll-cost']), length = Number(p['roll-length']), roll = Number(p.roll);
  if (!String(p['roll-cost'] || '').trim() || !(cost > 0) || !(length > 0) || !(roll > 0)) return '';
  const scale = EZNQueue.unitScale(p.unit) / 304.8;
  return '$' + (cost / (roll * scale * length * scale)).toFixed(2) + ' per sq ft';
}
function rollJobCheck(item) {
  const result = current?.result;
  if (!result || !(result.width > 0)) return null;
  const p = item.profile;
  const printable = Number(p.width) * EZNQueue.unitScale(p.unit);
  const jobIn = String(Math.round(result.width / 25.4 * 10) / 10);
  const lines = [];
  let ok = true;
  const rollIn = String(Math.round(printable / 25.4 * 10) / 10);
  if (printable + 0.01 < result.width) return {ok: false, lines: [`Too narrow: job is ${jobIn} in wide, this roll prints ${rollIn} in`]};
  lines.push(`Width fits: job ${jobIn} in on ${rollIn} in printable`);
  if (item.availableMm == null) lines.push('Length left unknown. Enter how much is left to check.');
  else if (item.availableMm + 0.5 >= result.usedLength) lines.push('Enough for this job · ' + stockFeet(result.usedLength) + ' needed');
  else { ok = false; lines.push('Not enough. Need ' + stockFeet(result.usedLength - item.availableMm) + ' more'); }
  return {ok, lines};
}
// Shelf view: each roll stands upright. Taller = wider material, thicker = more length left.
// Drawing sizes are a picture only, not a measurement. Geometry goes through setAttribute/CSSOM (CSP safe).
const SVGNS = 'http://www.w3.org/2000/svg';
const SHELF_CORE = 1.5, SHELF_WRAP = 0.011, SHELF_REF_W = 64, SHELF_TILT = 0.3;
let stockSel = null, stockForm = null, stockLenUnit = 'ft';
function shelfRadius(ft) { return Math.sqrt(SHELF_CORE * SHELF_CORE + Math.max(0, ft) * 12 * SHELF_WRAP / Math.PI); }
function shelfFmt(v) { const s = v < 10 ? v.toFixed(2) : v.toFixed(1); return s.includes('.') ? s.replace(/\.?0+$/, '') : s; }
function shelfRoll(item) {
  const p = item.profile, scale = EZNQueue.unitScale(p.unit);
  const full = Number(p['roll-length']);
  return {id: item.id, name: p['preset-name'], w: Number(p.roll) * scale / 25.4, pw: Number(p.width) * scale / 25.4,
    left: item.onHandMm == null ? null : item.onHandMm / 304.8, full: String(p['roll-length'] || '').trim() && full > 0 ? full * scale / 304.8 : null,
    low: !!rollLowText(item), item};
}
function shelfRefFt(extra) { return Math.max(150, ...shopInventory.materials.map(item => shelfRoll(item).full || 0), extra || 0); }
function svgEl(tag, attrs, parent) { const e = document.createElementNS(SVGNS, tag); for (const k in attrs) if (attrs[k] !== '' && attrs[k] != null) e.setAttribute(k, attrs[k]); if (parent) parent.append(e); return e; }
function shelfWall(cx, r, top, base) { return `M${cx - r},${top}L${cx - r},${base}A${r},${r * SHELF_TILT} 0 0 0 ${cx + r},${base}L${cx + r},${top}A${r},${r * SHELF_TILT} 0 0 1 ${cx - r},${top}Z`; }
function shelfScale(big) {
  const small = matchMedia('(max-width: 600px)').matches;
  if (big) { const H = small ? 160 : 210, W = small ? 260 : 190, ppi = (H - 44) / SHELF_REF_W; return {W, H, ppi, r0: ppi * 18.4, base: H - 10, cx: W / 2}; }
  const W = small ? 72 : 88, H = small ? 124 : 140, ppi = (H - 34) / SHELF_REF_W;
  return {W, H, ppi, r0: ppi * 18.4, base: H - 6, cx: W / 2};
}
function drawRoll(svg, m, big, refFt) {
  svg.replaceChildren();
  const S = shelfScale(big);
  for (const [k, v] of Object.entries({width: S.W, height: S.H, viewBox: `0 0 ${S.W} ${S.H}`})) svg.setAttribute(k, v);
  if (big) svgEl('line', {x1: 6, x2: S.W - 6, y1: S.base + .5, y2: S.base + .5, stroke: '#8d8d86', 'stroke-width': 2}, svg);
  const ref = shelfRadius(refFt), rc = S.r0 * SHELF_CORE / ref, cx = S.cx;
  if (!(m.w > 0)) {
    const r = S.r0 * .7, t = S.base - 54 * S.ppi;
    svgEl('path', {d: shelfWall(cx, r, t, S.base), fill: 'none', stroke: '#c9c9c2', 'stroke-dasharray': '5 4'}, svg);
    svgEl('ellipse', {cx, cy: t, rx: r, ry: r * SHELF_TILT, fill: 'none', stroke: '#c9c9c2', 'stroke-dasharray': '5 4'}, svg);
    return {r: 0};
  }
  const top = S.base - Math.min(m.w, SHELF_REF_W * 1.1) * S.ppi;
  const unknown = m.left == null, length = unknown ? (m.full || 150) : m.left, r = S.r0 * shelfRadius(length) / ref;
  if (!unknown) svgEl('ellipse', {cx: cx + r * .25, cy: S.base + 1, rx: r * 1.35, ry: Math.max(2, r * SHELF_TILT * .9), fill: '#1c1c1c', opacity: .1}, svg);
  if (big && m.full && !unknown && m.full > m.left) {
    const rf = S.r0 * shelfRadius(m.full) / ref;
    svgEl('path', {d: shelfWall(cx, rf, top, S.base), fill: 'none', stroke: '#8d8d86', 'stroke-dasharray': '4 3'}, svg);
    svgEl('ellipse', {cx, cy: top, rx: rf, ry: rf * SHELF_TILT, fill: '#fff', stroke: '#8d8d86', 'stroke-dasharray': '4 3'}, svg);
  }
  const body = svgEl('g', {class: 'roll-body'}, svg);
  svgEl('path', {d: shelfWall(cx, r, top, S.base), fill: unknown ? 'none' : m.low ? 'url(#roll-low)' : 'url(#roll-ok)'}, body);
  svgEl('ellipse', {cx, cy: top, rx: r, ry: r * SHELF_TILT, fill: unknown ? '#fff' : m.low ? '#f6e4df' : '#ecebe4', stroke: unknown ? '#8d8d86' : '#9c9a92', 'stroke-width': .8, 'stroke-dasharray': unknown ? '3 3' : ''}, body);
  svgEl('ellipse', {cx, cy: top, rx: rc, ry: rc * SHELF_TILT, fill: '#d4d2ca', stroke: '#8d8d86', 'stroke-width': .8}, body);
  svgEl('ellipse', {cx, cy: top, rx: rc * .62, ry: rc * .62 * SHELF_TILT, fill: '#4a4741'}, body);
  svgEl('path', {d: shelfWall(cx, r, top, S.base), fill: 'none', stroke: unknown ? '#8d8d86' : m.low ? '#b42318' : '#6f6e68', 'stroke-width': m.low ? 2 : 1, 'stroke-dasharray': unknown ? '4 3' : '', 'stroke-linejoin': 'round'}, body);
  const result = current?.result;
  if (!big && result?.width > 0 && m.pw * 25.4 + 0.01 < result.width) {
    const y = S.base - result.width / 25.4 * S.ppi;
    svgEl('line', {x1: cx - S.r0 - 6, x2: cx + S.r0 + 6, y1: y, y2: y, stroke: '#b42318', 'stroke-width': 1.6, 'stroke-dasharray': '4 3'}, svg);
  }
  return {r, body};
}
function shelfMark(svg, check) {
  if (!check) return;
  const S = shelfScale(false), x = S.W - 9, y = 12, warn = check.ok && check.lines.some(line => /unknown/.test(line));
  const kind = !check.ok ? 'bad' : warn ? 'warn' : 'ok', color = {bad: '#b42318', ok: '#15803d', warn: '#8a6100'}[kind];
  svgEl('circle', {cx: x, cy: y, r: 7.5, fill: kind === 'bad' ? color : '#fff', stroke: color, 'stroke-width': 1.4}, svg);
  svgEl('path', {d: kind === 'ok' ? `M${x - 3.5},${y}l2.5,2.5l4.5,-5` : kind === 'bad' ? `M${x},${y - 4}v4.5M${x},${y + 2.6}v.6` : `M${x - 2.4},${y - 2}a2.4,2.4 0 1 1 3.2,2.2c-.8,.4-.8,1-.8,1.6M${x},${y + 3.4}v.4`,
    fill: 'none', stroke: kind === 'bad' ? '#fff' : color, 'stroke-width': 1.7, 'stroke-linecap': 'round'}, svg);
}
function shelfLeftText(m) { return m.left == null ? 'Not measured' : shelfFmt(m.left) + ' ft'; }
function shelfJobLine(check) {
  if (!check) return null;
  const line = !check.ok ? check.lines.find(text => /Too narrow|Not enough/.test(text)) || check.lines[0] : check.lines[check.lines.length - 1];
  return {ok: check.ok && !/unknown/.test(line), warn: check.ok && /unknown/.test(line), text: line};
}
function shelfAria(m) {
  const parts = [m.name, `${shelfFmt(m.w)} inch roll`, m.left == null ? 'length left not measured' : `${shelfFmt(m.left)} feet${m.full ? ' of ' + shelfFmt(m.full) + ' feet' : ''} left`];
  if (m.low) parts.push('low stock');
  if (m.id === $('material').value) parts.push('selected for this job');
  const line = shelfJobLine(rollJobCheck(m.item));
  if (line) parts.push('job check: ' + line.text);
  return parts.join(', ');
}
function shelfNode(tag, cls, text, parent) { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; if (parent) parent.append(e); return e; }
function renderStock() {
  const host = $('stock-list');
  host.replaceChildren();
  const rolls = shopInventory.materials.map(shelfRoll);
  if (stockSel && !rolls.some(m => m.id === stockSel)) stockSel = null;
  const shown = rolls.slice();
  if (stockForm?.mode === 'add') shown.push(stockForm.draft());
  $('stock-empty').hidden = !inventoryReady || shown.length > 0;
  $('stock-legend').hidden = !shown.length;
  $('stock-status').textContent = inventoryReady ? $('stock-status').dataset.note || '' : 'Shop stock is unavailable. Check that the shop computer is running.';
  const result = current?.result;
  $('stock-job').hidden = !result;
  if (result) $('stock-job-text').textContent = `Nest needs ${stockFeet(result.usedLength)} of roll at ${Math.round(result.width / 25.4 * 10) / 10} in wide.`;
  $('stock-add').hidden = !!stockForm;
  const refFt = shelfRefFt(stockForm?.draft().full);
  const active = stockForm ? stockForm.id : stockSel;
  shown.forEach((m, index) => {
    const draft = m.id === 'draft';
    const slot = shelfNode('li', 'stock-slot' + (draft ? ' draft' : '') + (m.id === $('material').value ? ' in-use' : '') + (m.low ? ' low' : ''), null, host);
    slot.dataset.id = m.id;
    slot.setAttribute('role', 'option');
    slot.setAttribute('aria-selected', String(active === m.id));
    slot.setAttribute('aria-label', draft ? 'New roll being added' : shelfAria(m));
    slot.tabIndex = (active ? active === m.id : index === 0) ? 0 : -1;
    if (m.id === $('material').value) shelfNode('span', 'stock-pill', 'In use', slot).setAttribute('aria-hidden', 'true');
    const svg = svgEl('svg', {'aria-hidden': 'true', class: 'stock-roll'}, slot);
    drawRoll(svg, m, false, refFt);
    if (!draft) shelfMark(svg, rollJobCheck(m.item));
    const label = shelfNode('div', 'stock-label', null, slot);
    shelfNode('b', m.left == null && !(draft && !(m.w > 0)) ? 'unknown' : null, draft && !(m.w > 0) ? 'New roll' : shelfLeftText(m), label);
    const nameLine = shelfNode('span', null, m.name || 'New roll', label);
    if (m.name) nameLine.title = m.name;
    if (!draft) slot.addEventListener('click', () => { if (!stockForm) selectRoll(stockSel === m.id ? null : m.id); });
  });
  if (!stockForm) renderRollPanel();
}
function selectRoll(id, focus) {
  stockSel = id;
  for (const slot of $('stock-list').children) slot.setAttribute('aria-selected', String(slot.dataset.id === id));
  renderRollPanel();
  const slot = id ? $('stock-list').querySelector(`[data-id="${id}"]`) : null;
  if (focus && slot) slot.focus({preventScroll: true});
  if (slot) {
    // The details card sits at the bottom of the dialog; keep the tapped roll above it.
    slot.style.scrollMarginBottom = ($('stock-panel').offsetHeight + 16) + 'px';
    slot.style.scrollMarginTop = '16px';
    slot.scrollIntoView({block: 'nearest'});
  }
}
function stockColumns() { const list = $('stock-list'), first = list.firstElementChild; return first ? Math.max(1, Math.round(list.clientWidth / first.getBoundingClientRect().width)) : 1; }
$('stock-list').addEventListener('keydown', event => {
  const slots = [...$('stock-list').children], index = slots.indexOf(document.activeElement);
  if (index < 0) return;
  let next = index;
  const cols = stockColumns();
  switch (event.key) {
    case 'ArrowRight': next++; break; case 'ArrowLeft': next--; break;
    case 'ArrowDown': next += cols; break; case 'ArrowUp': next -= cols; break;
    case 'Home': next = 0; break; case 'End': next = slots.length - 1; break;
    case 'Enter': case ' ': event.preventDefault(); if (!stockForm && slots[index].dataset.id !== 'draft') selectRoll(slots[index].dataset.id); return;
    default: return;
  }
  event.preventDefault();
  next = Math.max(0, Math.min(slots.length - 1, next));
  slots.forEach(slot => { slot.tabIndex = -1; });
  slots[next].tabIndex = 0; slots[next].focus();
});
function closeButton(parent, label, handler) {
  const button = shelfNode('button', 'stock-x', null, parent); button.type = 'button'; button.setAttribute('aria-label', label);
  const svg = svgEl('svg', {width: 18, height: 18, viewBox: '0 0 18 18', 'aria-hidden': 'true'}, button);
  svgEl('path', {d: 'M4.5 4.5l9 9M13.5 4.5l-9 9', stroke: 'currentColor', 'stroke-width': 1.6, 'stroke-linecap': 'round', fill: 'none'}, svg);
  button.addEventListener('click', handler);
  return button;
}
function renderRollPanel() {
  const panel = $('stock-panel'); panel.replaceChildren();
  const item = shopInventory.materials.find(entry => entry.id === stockSel);
  panel.hidden = !item;
  if (!item) return;
  const m = shelfRoll(item);
  panel.setAttribute('aria-label', 'Details for ' + m.name);
  const head = shelfNode('div', 'stock-panel-head', null, panel), title = shelfNode('div', null, null, head);
  shelfNode('h3', null, m.name, title);
  shelfNode('p', 'stock-sub', `${shelfFmt(m.w)} in wide roll · prints ${shelfFmt(m.pw)} in`, title);
  closeButton(head, 'Close details', () => { const id = stockSel; selectRoll(null); $('stock-list').querySelector(`[data-id="${id}"]`)?.focus(); });
  const left = shelfNode('div', 'stock-left', null, panel);
  const count = shelfNode('button', 'stock-len', shelfLeftText(m), left); count.type = 'button';
  count.setAttribute('aria-label', (m.left == null ? 'Length left not measured' : `Length left ${shelfFmt(m.left)} feet`) + '. Change it');
  count.addEventListener('click', () => openRollForm('edit', item, 'roll-f-left'));
  if (m.left != null && m.full) shelfNode('span', null, `of ${shelfFmt(m.full)} ft left`, left);
  else if (m.left != null) shelfNode('span', null, 'left', left);
  if (m.low) shelfNode('span', 'stock-low', rollLowText(item).startsWith('Out') ? 'Out of stock' : 'Low stock', left);
  const cost = rollCostPerSqFt(item);
  if (cost) shelfNode('p', 'stock-sub', cost, panel);
  const line = shelfJobLine(rollJobCheck(item));
  if (line) shelfNode('p', 'stock-check', line.text, panel).dataset.ok = line.ok ? '1' : line.warn ? 'warn' : '0';
  const actions = shelfNode('div', 'stock-row-actions', null, panel);
  if (item.id === $('material').value) shelfNode('span', 'stock-selected', 'This job uses this roll', actions);
  else {
    const use = shelfNode('button', null, 'Use for this job', actions); use.type = 'button'; use.disabled = inventoryBusy;
    use.addEventListener('click', () => { $('stock').close(); chooseMaterial(item.id); });
  }
  const edit = shelfNode('button', 'link', 'Edit', actions); edit.type = 'button';
  edit.addEventListener('click', () => openRollForm('edit', item, 'roll-f-name'));
}
// One parser for every Inventory number. Plain digits with an optional decimal point and
// unit; no exponents, no commas. Limits sit inside the shop computer's own limits.
// Same rule as the shop computer: names that only look different count as the same name.
function rollNameKey(text) {
  return String(text || '').normalize('NFKC').replace(/[\u0000-\u0008\u000b-\u001f\u007f-\u009f\u00ad\u061c\u180e\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff]/g, '').replace(/\s+/g, ' ').trim().toLowerCase();
}
const ROLL_LIMITS = {inches: [0.4, 196], feet: [0, 100000], price: [0, 1000000]};
function parseRollNumber(text, units) {
  const value = String(text || '').trim().toLowerCase();
  if (!value) return {empty: true};
  const match = value.match(/^(\d{1,9}(?:\.\d{0,4})?|\.\d{1,4})\s*([a-z'"]+)?$/);
  if (!match) return {bad: true};
  const number = Number(match[1]);
  if (!Number.isFinite(number)) return {bad: true};
  let unit = null;
  if (match[2]) { unit = units?.[match[2]]; if (!unit) return {bad: true}; }
  return {number, unit};
}
const LENGTH_UNITS = {ft: 'ft', feet: 'ft', foot: 'ft', "'": 'ft', in: 'in', inch: 'in', inches: 'in', '"': 'in'};
// Lengths: feet by default; "150 ft", "1800 in", 12' and 6" all work.
function parseLength(text, unit) {
  const read = parseRollNumber(text, LENGTH_UNITS);
  if (read.empty || read.bad) return read;
  const given = read.unit || unit, ft = read.number / (given === 'in' ? 12 : 1);
  if (ft > ROLL_LIMITS.feet[1] || (ft > 0 && ft < 0.01)) return {bad: true};
  return {ft, given, typed: !!read.unit};
}
function parseInches(text) {
  const read = parseRollNumber(text, {in: 'in', inch: 'in', inches: 'in', '"': 'in'});
  if (read.empty || read.bad || read.number < ROLL_LIMITS.inches[0] || read.number > ROLL_LIMITS.inches[1]) return null;
  return read.number;
}
function parsePrice(text) {
  const read = parseRollNumber(String(text || '').trim().replace(/^\$\s*/, ''), null);
  if (read.empty || read.bad) return read;
  return read.number > ROLL_LIMITS.price[1] ? {bad: true} : {value: read.number};
}
const ROLL_FIELDS = [
  ['roll-f-name', 'Material', 'name', null, 'For example: Gloss vinyl'],
  ['roll-f-roll', 'Roll width', 'roll', 'in', 'Measure across the roll.'],
  ['roll-f-width', 'Width you can print on', 'width', 'in', 'How wide the printer can print on it.'],
  ['roll-f-left', 'Length left on roll', 'left', 'len', 'Leave blank if you have not measured it.'],
  ['roll-f-full', 'Length of a new roll', 'full', 'len', 'Optional. How long a brand-new roll is.'],
  ['roll-f-cost', 'Price you paid for a new roll ($)', 'cost', null, 'Optional. Shows cost per square foot.'],
];
function openRollForm(mode, item, focus) {
  const m = item ? shelfRoll(item) : null;
  const values = m ? {name: m.name, roll: shelfFmt(m.w), width: shelfFmt(m.pw), left: m.left == null ? '' : shelfFmt(m.left), full: m.full == null ? '' : shelfFmt(m.full), cost: item.profile['roll-cost'] || ''}
    : {name: '', roll: '', width: '', left: '', full: '', cost: ''};
  stockLenUnit = 'ft';
  stockForm = {mode, id: item ? item.id : 'draft', item, values, touched: {width: mode === 'edit', full: mode === 'edit'}, errors: {}, focus: focus || 'roll-f-name',
    draft() {
      const v = this.values, roll = parseInches(v.roll), width = parseInches(v.width), left = parseLength(v.left, stockLenUnit), full = parseLength(v.full, stockLenUnit);
      const low = left.ft != null && full.ft > 0 && left.ft <= full.ft * 0.1;
      return {id: this.id, name: v.name.trim(), w: roll > 0 ? roll : null, pw: width > 0 ? width : roll || 0, left: left.ft ?? null, full: full.ft > 0 ? full.ft : null, low: this.mode === 'edit' && this.item ? (left.ft != null && shelfRoll(this.item).low && left.ft === shelfRoll(this.item).left) || low : low};
    }};
  stockSel = null;
  renderStock();
  renderRollForm();
}
function renderRollForm() {
  const panel = $('stock-panel'); panel.replaceChildren(); panel.hidden = false;
  const add = stockForm.mode === 'add';
  panel.setAttribute('aria-label', add ? 'Add a roll' : 'Edit roll');
  const head = shelfNode('div', 'stock-panel-head', null, panel);
  shelfNode('h3', null, add ? 'Add a roll' : 'Edit roll', head);
  closeButton(head, 'Cancel', cancelRollForm);
  const form = shelfNode('form', 'roll-form', null, panel); form.noValidate = true;
  form.addEventListener('submit', event => { event.preventDefault(); saveRollForm(false); });
  const preview = shelfNode('div', 'roll-preview', null, form); preview.setAttribute('aria-hidden', 'true');
  svgEl('svg', {id: 'roll-preview-svg'}, preview);
  shelfNode('p', 'stock-sub', null, preview).id = 'roll-preview-cap';
  const fields = shelfNode('div', 'roll-fields', null, form);
  const unitToggle = shelfNode('div', 'roll-units', null, fields); unitToggle.setAttribute('role', 'group'); unitToggle.setAttribute('aria-label', 'Length units');
  shelfNode('span', null, 'Lengths in', unitToggle);
  for (const [unit, text] of [['ft', 'feet'], ['in', 'inches']]) {
    const b = shelfNode('button', null, text, unitToggle); b.type = 'button'; b.dataset.unit = unit; b.setAttribute('aria-pressed', String(stockLenUnit === unit));
    b.addEventListener('click', () => {
      if (stockLenUnit === unit) return;
      for (const key of ['left', 'full']) { const parsed = parseLength(stockForm.values[key], stockLenUnit); if (parsed.ft != null) { stockForm.values[key] = shelfFmt(unit === 'in' ? parsed.ft * 12 : parsed.ft); const input = $('roll-f-' + key); if (input) input.value = stockForm.values[key]; } }
      stockLenUnit = unit;
      for (const other of unitToggle.querySelectorAll('button')) other.setAttribute('aria-pressed', String(other.dataset.unit === unit));
      for (const span of fields.querySelectorAll('[data-len-unit]')) span.textContent = unit;
      rollFormLive();
    });
  }
  const pairs = [[0], [1, 2], [3, 4], [5]];
  for (const group of pairs) {
    const row = shelfNode('div', group.length > 1 ? 'roll-row' : null, null, fields);
    for (const index of group) rollField(row, ROLL_FIELDS[index]);
  }
  const names = shelfNode('datalist', null, null, fields); names.id = 'roll-names';
  for (const option of $('material').options) if (option.value !== 'custom') shelfNode('option', null, null, names).value = option.dataset.name || option.textContent;
  const error = shelfNode('p', 'stock-form-error', null, fields); error.id = 'roll-form-error'; error.setAttribute('role', 'alert');
  if (stockForm.errors._) error.textContent = stockForm.errors._;
  const actions = shelfNode('div', 'roll-actions', null, form);
  const save = shelfNode('button', 'primary', add ? 'Save roll' : 'Save', actions); save.type = 'submit'; save.disabled = inventoryBusy;
  if (add) { const again = shelfNode('button', 'link', 'Save and add another', actions); again.type = 'button'; again.disabled = inventoryBusy; again.addEventListener('click', () => saveRollForm(true)); }
  const cancel = shelfNode('button', 'link quiet', 'Cancel', actions); cancel.type = 'button'; cancel.addEventListener('click', cancelRollForm);
  if (!add) { const remove = shelfNode('button', 'link danger roll-remove', 'Remove roll', actions); remove.type = 'button'; remove.disabled = inventoryBusy; remove.addEventListener('click', () => removeRoll(stockForm.item)); }
  rollFormLive();
  const target = $(stockForm.focus);
  if (target) setTimeout(() => { target.focus(); target.select?.(); }, 0);
}
function rollField(parent, [id, label, key, unit, help]) {
  const wrap = shelfNode('label', 'roll-field', null, parent); wrap.htmlFor = id;
  shelfNode('span', 'roll-label', label, wrap);
  const box = shelfNode('span', 'measure', null, wrap);
  const input = shelfNode('input', null, null, box);
  Object.assign(input, {id, name: key, value: stockForm.values[key], autocomplete: 'off', type: 'text'});
  if (key === 'name') { input.maxLength = 80; input.setAttribute('list', 'roll-names'); }
  else input.inputMode = 'decimal';
  if (unit === 'in') shelfNode('span', null, 'in', box);
  if (unit === 'len') shelfNode('span', null, stockLenUnit, box).dataset.lenUnit = '1';
  const hint = shelfNode('span', 'hint', help, wrap); hint.id = id + '-hint';
  input.setAttribute('aria-describedby', hint.id);
  if (stockForm.errors[key]) {
    input.setAttribute('aria-invalid', 'true'); box.classList.add('invalid');
    const err = shelfNode('span', 'roll-error', stockForm.errors[key], wrap); err.id = id + '-error';
    input.setAttribute('aria-describedby', err.id + ' ' + hint.id);
  }
  input.addEventListener('input', () => rollFormInput(key, input.value, input));
  return wrap;
}
function rollFormInput(key, value, input) {
  const form = stockForm; if (!form) return;
  form.values[key] = value;
  if (form.errors[key]) { delete form.errors[key]; input.removeAttribute('aria-invalid'); input.parentElement.classList.remove('invalid'); $(input.id + '-error')?.remove(); input.setAttribute('aria-describedby', input.id + '-hint'); }
  if (key === 'width') form.touched.width = true;
  if (key === 'full') form.touched.full = true;
  if (key === 'roll' && !form.touched.width) { form.values.width = value; $('roll-f-width').value = value; }
  if (key === 'left' && !form.touched.full && form.mode === 'add') { form.values.full = value; $('roll-f-full').value = value; }
  // "1800 in" typed while the form is in feet: the suffix shows what was typed.
  for (const field of ['left', 'full']) {
    const read = parseLength(form.values[field], stockLenUnit), span = $('roll-f-' + field)?.parentElement.querySelector('[data-len-unit]');
    if (span) span.textContent = read.typed ? read.given : stockLenUnit;
  }
  if (key === 'name' && form.mode === 'add') {
    const known = Object.values(materialProfiles).find(p => p['preset-name'].toLowerCase() === value.trim().toLowerCase());
    if (known && !form.values.roll) {
      const scale = EZNQueue.unitScale(known.unit) / 25.4;
      form.values.roll = shelfFmt(Number(known.roll) * scale); $('roll-f-roll').value = form.values.roll;
      if (!form.touched.width) { form.values.width = shelfFmt(Number(known.width) * scale); $('roll-f-width').value = form.values.width; }
    }
  }
  rollFormLive();
}
function rollFormLive() {
  const m = stockForm.draft(), refFt = shelfRefFt(m.full);
  drawRoll($('roll-preview-svg'), m, true, refFt);
  $('roll-preview-cap').textContent = !(m.w > 0) ? 'Type a width to see the roll' : `${shelfFmt(m.w)} in wide · ${m.left == null ? 'length not measured' : shelfFmt(m.left) + ' ft' + (m.full ? ' of ' + shelfFmt(m.full) + ' ft' : '')}`;
  const slot = $('stock-list').querySelector(`[data-id="${stockForm.id}"]`);
  if (slot) {
    drawRoll(slot.querySelector('svg'), m, false, refFt);
    slot.querySelector('.stock-label b').textContent = !(m.w > 0) && stockForm.mode === 'add' ? 'New roll' : shelfLeftText(m);
    slot.querySelector('.stock-label span').textContent = m.name || 'New roll';
  }
  const cost = parsePrice(stockForm.values.cost).value, costHint = $('roll-f-cost-hint');
  if (costHint) costHint.textContent = cost != null && m.full > 0 && m.w > 0 ? `= $${(cost / (m.w / 12 * m.full)).toFixed(2)} per sq ft` : ROLL_FIELDS[5][4];
}
function rollFormErrors() {
  const v = stockForm.values, e = {};
  const roll = parseInches(v.roll), width = parseInches(v.width), left = parseLength(v.left, stockLenUnit), full = parseLength(v.full, stockLenUnit);
  const price = parsePrice(v.cost);
  if (!v.name.trim()) e.name = 'Enter a material name.';
  else if (Object.entries(materialProfiles).some(([key, p]) => key !== stockForm.id && rollNameKey(p['preset-name']) === rollNameKey(v.name))) e.name = 'A preset with that name already exists. Choose another name.';
  if (roll == null) e.roll = 'Roll width looks wrong. Enter inches, like 54.';
  if (width == null) e.width = 'Width you can print on looks wrong. Enter inches, like 51.5.';
  else if (!e.roll && width > roll) e.width = 'This can\'t be wider than the roll itself.';
  if (left.bad) e.left = 'Length left looks wrong. Enter a number like 150, or leave it blank.';
  if (full.bad || full.ft === 0) e.full = 'Length of a new roll looks wrong. Enter a number like 150, or leave it blank.';
  if (price.bad) e.cost = 'Roll price looks wrong. Enter a number like 8.50.';
  else if (!price.empty && !(full.ft > 0)) e.cost = 'Enter the length of a new roll too, so the price per square foot can be worked out.';
  if (!e.left && !e.full && left.ft != null && full.ft != null && left.ft > full.ft + 1e-9) e.left = 'There can\'t be more left than a new roll holds.';
  return {e, roll, width, left, full};
}
async function saveRollForm(another) {
  if (!stockForm || inventoryBusy) return;
  const {e, roll, width, left, full} = rollFormErrors();
  stockForm.errors = e;
  const first = ROLL_FIELDS.find(f => e[f[2]]);
  if (first) { stockForm.focus = first[0]; renderRollForm(); return; }
  const add = stockForm.mode === 'add', item = stockForm.item;
  const base = add ? {...materialValues(), unit: 'in', 'low-stock': ''} : {...item.profile};
  const per = 25.4 / EZNQueue.unitScale(base.unit), round = n => String(Number(n.toFixed(4)));
  const values = {...base, 'preset-name': stockForm.values.name.normalize('NFKC').replace(/\s+/g, ' ').trim(), roll: round(roll * per), width: round(width * per),
    'available-length': left.ft == null ? '' : round(left.ft * 12 * per), 'roll-length': full.ft == null ? '' : round(full.ft * 12 * per), 'roll-cost': stockForm.values.cost.trim() ? String(parsePrice(stockForm.values.cost).value) : ''};
  if (!add && values['low-stock'] && values['roll-length'] && Number(values['low-stock']) > Number(values['roll-length'])) values['low-stock'] = '';
  inventoryBusy = true;
  try {
    const clean = validateMaterial(values);
    const id = add ? 'material-' + crypto.randomUUID() : item.id;
    await mutateInventory('/api/materials/save', {id, profile: clean, revision: add ? 0 : item.revision});
    if (id === $('material').value) applyMaterial(true);
    const saved = shopInventory.materials.find(entry => entry.id === id);
    const m = saved ? shelfRoll(saved) : null;
    const note = `${add ? 'Added' : 'Saved'} ${clean['preset-name']}.${m ? ' ' + (m.left == null ? 'Length not measured.' : shelfFmt(m.left) + ' ft left.') : ''}`;
    $('stock-status').dataset.note = note;
    inventoryBusy = false;
    if (another) { openRollForm('add', null, 'roll-f-name'); $('stock-status').textContent = note; return; }
    stockForm = null; stockSel = id; renderStock();
    $('stock-list').querySelector(`[data-id="${id}"]`)?.focus();
  } catch (error) {
    stockForm.errors = {_: error.message}; inventoryBusy = false;
    await refreshInventory().catch(() => {});
    renderRollForm();
  } finally {
    inventoryBusy = false;
  }
}
function cancelRollForm() {
  const id = stockForm?.mode === 'edit' ? stockForm.id : null;
  stockForm = null; stockSel = id; renderStock();
  (id ? $('stock-list').querySelector(`[data-id="${id}"]`) : $('stock-add'))?.focus();
}
async function removeRoll(item) {
  if (inventoryBusy || !item) return;
  if (!window.confirm(`Remove ${item.profile['preset-name']} from inventory? Its usage history is removed too.`)) return;
  inventoryBusy = true;
  try {
    await mutateInventory('/api/materials/remove', {id: item.id, revision: item.revision});
    const option = [...$('material').options].find(entry => entry.value === item.id);
    const wasSelected = $('material').value === item.id;
    if (option) option.remove();
    delete materialProfiles[item.id];
    if (wasSelected) { $('material').selectedIndex = 0; applyMaterial(true); }
    renderMaterialButtons();
    $('stock-status').dataset.note = 'Roll removed.';
    stockForm = null; stockSel = null;
  } catch (error) {
    await refreshInventory().catch(() => {});
    $('stock-status').dataset.note = error.message;
  } finally {
    inventoryBusy = false; renderStock();
    if (!stockForm) $('stock-add').focus();
  }
}
async function openStock() {
  await refreshInventory().catch(() => {});
  stockForm = null; stockSel = null; $('stock-status').dataset.note = '';
  renderStock();
  if (!$('stock').open) $('stock').showModal();
  $('stock-close').focus();
}
$('stock').addEventListener('cancel', event => {
  if (stockForm) { event.preventDefault(); cancelRollForm(); }
  else if (stockSel) { event.preventDefault(); const id = stockSel; selectRoll(null); $('stock-list').querySelector(`[data-id="${id}"]`)?.focus(); }
});
$('stock-open').addEventListener('click', openStock);
$('stock-close').addEventListener('click', () => $('stock').close());
$('stock-add').addEventListener('click', () => openRollForm('add', null, 'roll-f-name'));

for (const id of ['thru-name', 'kiss-name']) $(id).addEventListener('input', renderCutLineNote);
renderCutLineNote();

// Header status circle: click reuses the existing connect flow (or the connected menu).
$('output-dot')?.addEventListener('click', event => { event.stopPropagation(); ($('output-link-status').hidden ? $('output-link-connect') : $('output-link-status')).click(); });
