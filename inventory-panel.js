'use strict';
window.EZNInventoryPanel = {create(host) {
const $ = id => document.getElementById(id);
document.body.insertAdjacentHTML('beforeend', `<dialog id="stock" aria-labelledby="stock-title">
  <div class="panel">
    <div class="dialog-heading"><div><h2 id="stock-title" class="settings-title">Inventory</h2><p class="hint">Rolls in stock in the shop</p></div><button id="stock-close" class="dialog-close" type="button" aria-label="Close inventory">×</button></div>
    <section id="stock-job" class="stock-job" aria-label="Current job" hidden>
      <h3>This job</h3>
      <p id="stock-job-text"></p>
    </section>
    <svg class="stock-defs" width="0" height="0" aria-hidden="true" focusable="false"><defs>
      <linearGradient id="roll-ok"><stop offset="0" stop-color="#b8b6ae"/><stop offset=".32" stop-color="#f6f5f0"/><stop offset=".7" stop-color="#e4e2da"/><stop offset="1" stop-color="#b8b6ae"/></linearGradient>
      <linearGradient id="roll-low"><stop offset="0" stop-color="#d9a49b"/><stop offset=".32" stop-color="#f8ece9"/><stop offset=".7" stop-color="#efd7d1"/><stop offset="1" stop-color="#d9a49b"/></linearGradient>
    </defs></svg>
    <p id="stock-empty" class="stock-empty" hidden>No materials yet. Add your first roll.</p>
    <ul id="stock-list" class="stock-shelf" role="listbox" aria-label="Rolls in stock" aria-orientation="horizontal"></ul>
    <p id="stock-legend" class="stock-legend" hidden>Tap a roll to see it. Taller roll = wider material. Fatter roll = more left.</p>
    <section id="stock-panel" class="stock-panel" hidden></section>
    <p id="stock-status" role="status" aria-live="polite" class="hint"></p>
    <div class="stock-actions"><button id="stock-add" class="primary" type="button">Add roll</button></div>
  </div>
</dialog>`);
function stockFeet(mm) { return mm == null ? 'unknown' : (mm / 304.8).toFixed(2) + ' ft'; }
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
  const result = host.current?.result;
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
// The same checks as rollJobCheck, as one plain sentence for the details card.
// kind: fits, narrow, short or unmeasured; null when no job is open.
function rollJobStatus(item) {
  const result = host.current?.result;
  if (!result || !(result.width > 0)) return null;
  const p = item.profile;
  const printable = Number(p.width) * EZNQueue.unitScale(p.unit);
  const inches = mm => shelfFmt(Math.round(mm / 25.4 * 10) / 10);
  const feet = mm => shelfFmt(Math.round(mm / 304.8 * 10) / 10);
  if (printable + 0.01 < result.width) return {kind: 'narrow', text: `Too narrow for this job (needs ${inches(result.width)} in, roll is ${inches(printable)} in)`};
  if (item.availableMm == null) return {kind: 'unmeasured', text: 'Enter how much is left to check'};
  if (item.availableMm + 0.5 >= result.usedLength) return {kind: 'fits', text: `Fits this job: needs about ${feet(result.usedLength)} ft, ${feet(item.availableMm)} ft left`};
  return {kind: 'short', text: `Not enough on this roll. Need ${feet(result.usedLength - item.availableMm)} more ft`};
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
function shelfRefFt(extra) { return Math.max(150, ...host.inventory.materials.map(item => shelfRoll(item).full || 0), extra || 0); }
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
  const result = host.current?.result;
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
function shelfAria(m) {
  const parts = [m.name, `${shelfFmt(m.w)} inches wide`, m.left == null ? 'length left not measured' : `${shelfFmt(m.left)} feet${m.full ? ' of ' + shelfFmt(m.full) + ' feet' : ''} left`];
  if (m.low) parts.push('low stock');
  if (m.id === host.selectedId()) parts.push('selected for this job');
  const status = rollJobStatus(m.item);
  if (status) parts.push(status.text);
  return parts.join(', ');
}
// Shelf label: the material name on top, the roll width under it in smaller grey text.
// A name that already ends with the roll width ("Gloss vinyl 54 in") drops it from the
// name line so the width is not shown twice; the full name stays in the tooltip.
function shelfShortName(name, w) {
  const text = String(name || '').trim();
  if (!(w > 0)) return text;
  const match = text.match(/^(.*?\S)[\s,·\-–—]*(\d+(?:\.\d+)?)\s*(?:in|inch|inches|"|”|'')?\.?$/i);
  if (!match || Math.abs(Number(match[2]) - w) > 0.05) return text;
  return match[1].replace(/[\s,·\-–—]+$/, '') || text;
}
function shelfLabel(label, m) {
  label.replaceChildren();
  const full = m.name || 'New roll';
  const name = shelfNode('span', 'stock-name', shelfShortName(full, m.w) || full, label);
  name.title = full;
  shelfNode('span', 'stock-size', m.w > 0 ? `${shelfFmt(m.w)} in` : '\u00a0', label);
}
function shelfNode(tag, cls, text, parent) { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; if (parent) parent.append(e); return e; }
function renderStock() {
  const shelf = $('stock-list');
  shelf.replaceChildren();
  const rolls = host.inventory.materials.map(shelfRoll);
  if (stockSel && !rolls.some(m => m.id === stockSel)) stockSel = null;
  const shown = rolls.slice();
  if (stockForm?.mode === 'add') shown.push(stockForm.draft());
  $('stock-empty').hidden = !host.ready || shown.length > 0;
  $('stock-legend').hidden = !shown.length;
  $('stock-status').textContent = host.ready ? $('stock-status').dataset.note || '' : 'Shop stock is unavailable. Check that the shop computer is running.';
  const result = host.current?.result;
  $('stock-job').hidden = !result;
  if (result) $('stock-job-text').textContent = `Nest needs ${stockFeet(result.usedLength)} of roll at ${Math.round(result.width / 25.4 * 10) / 10} in wide.`;
  $('stock-add').hidden = !!stockForm;
  const refFt = shelfRefFt(stockForm?.draft().full);
  const active = stockForm ? stockForm.id : stockSel;
  shown.forEach((m, index) => {
    const draft = m.id === 'draft';
    const slot = shelfNode('li', 'stock-slot' + (draft ? ' draft' : '') + (m.id === host.selectedId() ? ' in-use' : '') + (m.low ? ' low' : ''), null, shelf);
    slot.dataset.id = m.id;
    slot.setAttribute('role', 'option');
    slot.setAttribute('aria-selected', String(active === m.id));
    slot.setAttribute('aria-label', draft ? 'New roll being added' : shelfAria(m));
    slot.tabIndex = (active ? active === m.id : index === 0) ? 0 : -1;
    if (m.id === host.selectedId()) shelfNode('span', 'stock-pill', 'In use', slot).setAttribute('aria-hidden', 'true');
    // How much is left sits above the roll; the roll's name sits under it, on the shelf.
    const qty = shelfNode('div', 'stock-qty', null, slot);
    qty.setAttribute('aria-hidden', 'true');
    shelfNode('b', m.left == null && !(draft && !(m.w > 0)) ? 'unknown' : null, draft && !(m.w > 0) ? 'New roll' : shelfLeftText(m), qty);
    const svg = svgEl('svg', {'aria-hidden': 'true', class: 'stock-roll'}, slot);
    drawRoll(svg, m, false, refFt);
    if (!draft) shelfMark(svg, rollJobCheck(m.item));
    const label = shelfNode('div', 'stock-label', null, slot);
    label.setAttribute('aria-hidden', 'true');
    shelfLabel(label, m);
    if (!draft) slot.addEventListener('click', () => { if (!stockForm) selectRoll(stockSel === m.id ? null : m.id); });
  });
  if (!stockForm) renderRollPanel();
  fitShelfLabels();
}
// A shelf row whose names all fit on one line drops the second name line, so the width sits
// right under the name; rows with a two-line name keep both lines so widths still line up.
function fitShelfLabels() {
  const rows = new Map();
  for (const slot of $('stock-list').children) {
    slot.classList.remove('one-line');
    const top = slot.offsetTop;
    if (!rows.has(top)) rows.set(top, []);
    rows.get(top).push(slot);
  }
  for (const slots of rows.values()) {
    const wraps = slots.some(slot => {
      const name = slot.querySelector('.stock-name');
      if (!name) return false;
      const range = document.createRange(); range.selectNodeContents(name);
      return new Set([...range.getClientRects()].map(rect => Math.round(rect.top))).size > 1;
    });
    if (!wraps) slots.forEach(slot => slot.classList.add('one-line'));
  }
}
new ResizeObserver(() => fitShelfLabels()).observe($('stock-list'));
function selectRoll(id, focus) {
  stockSel = id;
  for (const slot of $('stock-list').children) slot.setAttribute('aria-selected', String(slot.dataset.id === id));
  renderRollPanel();
  const slot = id ? $('stock-list').querySelector(`[data-id="${id}"]`) : null;
  if (focus && slot) slot.focus({preventScroll: true});
  if (slot) {
    // The shelf has its own scroll area above the docked details card: bring the roll into it.
    revealRoll(id);
    requestAnimationFrame(() => revealRoll(id));
  }
}
function revealRoll(id) {
  const slot = id && stockSel === id ? $('stock-list').querySelector(`[data-id="${id}"]`) : null;
  const shelf = slot && slot.closest('.stock-shelf');
  if (!shelf) return;
  const box = shelf.getBoundingClientRect(), r = slot.getBoundingClientRect();
  if (r.top < box.top) shelf.scrollTop -= box.top - r.top;
  else if (r.bottom > box.bottom) shelf.scrollTop += Math.min(r.bottom - box.bottom, r.top - box.top);
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
  const item = host.inventory.materials.find(entry => entry.id === stockSel);
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
  const status = rollJobStatus(item), inUse = item.id === host.selectedId();
  // No job open: no job line at all.
  if (status) {
    const check = shelfNode('p', 'stock-check', status.text, panel);
    check.dataset.kind = status.kind;
    check.dataset.ok = status.kind === 'fits' ? '1' : status.kind === 'unmeasured' ? 'warn' : '0';
  }
  const actions = shelfNode('div', 'stock-row-actions', null, panel);
  if (inUse) {
    shelfNode('span', 'stock-selected', 'This job uses this roll', actions);
    const other = shelfNode('button', 'link', 'Use a different roll', actions); other.type = 'button';
    other.addEventListener('click', () => { selectRoll(null); $('stock-list').querySelector('.stock-slot:not(.in-use)')?.focus(); });
  } else if (status?.kind !== 'narrow') {
    // A roll that is too narrow can't print this job, so it has no button.
    const use = shelfNode('button', status?.kind === 'fits' || !status ? 'primary' : null, 'Use for this job', actions);
    use.type = 'button'; use.disabled = host.busy;
    use.addEventListener('click', () => { $('stock').close(); host.choose(item.id); });
  }
  const edit = shelfNode('button', 'link', 'Edit', actions); edit.type = 'button';
  edit.addEventListener('click', () => openRollForm('edit', item, status?.kind === 'unmeasured' ? 'roll-f-left' : 'roll-f-name'));
}
// One parser for every Inventory number. Plain digits with an optional decimal point and
// unit; no exponents, no commas. Limits sit inside the shop computer's own limits.
// Same rule as the shop computer: names that only look different count as the same name.
// Same look-alike tables as material_inventory.py: capitals first, then lowercase.
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
  for (const item of host.inventory.materials) shelfNode('option', null, null, names).value = item.profile['preset-name'];
  const error = shelfNode('p', 'stock-form-error', null, fields); error.id = 'roll-form-error'; error.setAttribute('role', 'alert');
  if (stockForm.errors._) error.textContent = stockForm.errors._;
  const actions = shelfNode('div', 'roll-actions', null, form);
  const save = shelfNode('button', 'primary', add ? 'Save roll' : 'Save', actions); save.type = 'submit'; save.disabled = host.busy;
  if (add) { const again = shelfNode('button', 'link', 'Save and add another', actions); again.type = 'button'; again.disabled = host.busy; again.addEventListener('click', () => saveRollForm(true)); }
  const cancel = shelfNode('button', 'link quiet', 'Cancel', actions); cancel.type = 'button'; cancel.addEventListener('click', cancelRollForm);
  if (!add) { const remove = shelfNode('button', 'link danger roll-remove', 'Remove roll', actions); remove.type = 'button'; remove.disabled = host.busy; remove.addEventListener('click', () => removeRoll(stockForm.item)); }
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
    const known = Object.values(host.profiles).find(p => p['preset-name'].toLowerCase() === value.trim().toLowerCase());
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
    slot.querySelector('.stock-qty b').textContent = !(m.w > 0) && stockForm.mode === 'add' ? 'New roll' : shelfLeftText(m);
    shelfLabel(slot.querySelector('.stock-label'), m);
  }
  const cost = parsePrice(stockForm.values.cost).value, costHint = $('roll-f-cost-hint');
  if (costHint) costHint.textContent = cost != null && m.full > 0 && m.w > 0 ? `= $${(cost / (m.w / 12 * m.full)).toFixed(2)} per sq ft` : ROLL_FIELDS[5][4];
}
function rollFormErrors() {
  const v = stockForm.values, e = {};
  const roll = parseInches(v.roll), width = parseInches(v.width), left = parseLength(v.left, stockLenUnit), full = parseLength(v.full, stockLenUnit);
  const price = parsePrice(v.cost);
  if (!v.name.trim()) e.name = 'Enter a material name.';
  else if (!(stockForm.item && rollNameKey(stockForm.item.profile['preset-name']) === rollNameKey(v.name)) && Object.entries(host.profiles).some(([key, p]) => key !== stockForm.id && rollNameKey(p['preset-name']) === rollNameKey(v.name))) e.name = 'A material with this name already exists.';
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
  if (!stockForm || host.busy) return;
  const {e, roll, width, left, full} = rollFormErrors();
  stockForm.errors = e;
  const first = ROLL_FIELDS.find(f => e[f[2]]);
  if (first) { stockForm.focus = first[0]; renderRollForm(); return; }
  const add = stockForm.mode === 'add', item = stockForm.item;
  const base = add ? {...host.defaults(), unit: 'in', 'low-stock': ''} : {...item.profile};
  const per = 25.4 / EZNQueue.unitScale(base.unit), round = n => String(Number(n.toFixed(4)));
  const values = {...base, 'preset-name': stockForm.values.name.normalize('NFKC').replace(/\s+/g, ' ').trim(), roll: round(roll * per), width: round(width * per),
    'available-length': left.ft == null ? '' : round(left.ft * 12 * per), 'roll-length': full.ft == null ? '' : round(full.ft * 12 * per), 'roll-cost': stockForm.values.cost.trim() ? String(parsePrice(stockForm.values.cost).value) : ''};
  if (!add && values['low-stock'] && values['roll-length'] && Number(values['low-stock']) > Number(values['roll-length'])) values['low-stock'] = '';
  host.busy = true;
  try {
    const clean = host.validate(values);
    const id = add ? 'material-' + crypto.randomUUID() : item.id;
    await host.mutate('/api/materials/save', {id, profile: clean, revision: add ? 0 : item.revision});
    host.updated(id);
    const saved = host.inventory.materials.find(entry => entry.id === id);
    const m = saved ? shelfRoll(saved) : null;
    const note = `${add ? 'Added' : 'Saved'} ${clean['preset-name']}.${m ? ' ' + (m.left == null ? 'Length not measured.' : shelfFmt(m.left) + ' ft left.') : ''}`;
    $('stock-status').dataset.note = note;
    host.busy = false;
    if (another) { openRollForm('add', null, 'roll-f-name'); $('stock-status').textContent = note; return; }
    stockForm = null; stockSel = id; renderStock();
    $('stock-list').querySelector(`[data-id="${id}"]`)?.focus();
  } catch (error) {
    stockForm.errors = {_: error.message}; host.busy = false;
    await host.refresh().catch(() => {});
    renderRollForm();
  } finally {
    host.busy = false;
  }
}
function cancelRollForm() {
  const id = stockForm?.mode === 'edit' ? stockForm.id : null;
  stockForm = null; stockSel = id; renderStock();
  (id ? $('stock-list').querySelector(`[data-id="${id}"]`) : $('stock-add'))?.focus();
}
async function removeRoll(item) {
  if (host.busy || !item) return;
  if (!window.confirm(`Remove ${item.profile['preset-name']} from inventory? Its usage history is removed too.`)) return;
  host.busy = true;
  try {
    await host.mutate('/api/materials/remove', {id: item.id, revision: item.revision});
    host.removed(item.id);
    $('stock-status').dataset.note = 'Roll removed.';
    stockForm = null; stockSel = null;
  } catch (error) {
    await host.refresh().catch(() => {});
    $('stock-status').dataset.note = error.message;
  } finally {
    host.busy = false; renderStock();
    if (!stockForm) $('stock-add').focus();
  }
}
async function openStock() {
  await host.refresh().catch(() => {});
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

return {render: renderStock, isEditing: () => !!stockForm};
}};
