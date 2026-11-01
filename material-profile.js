'use strict';
// Shared material validation; the server remains the authority for stock.
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

function lowStock(values) {
  if (!values || !String(values['available-length'] ?? '').trim()) return '';
  const left = Number(values['available-length']);
  const threshold = String(values['low-stock'] ?? '').trim() ? Number(values['low-stock']) : Number(values['roll-length'] || 0) * 0.1;
  if (!Number.isFinite(left) || left < 0 || !Number.isFinite(threshold) || left > threshold) return '';
  return (left === 0 ? 'Out of stock' : 'Low stock') + ' · ' + left + ' ' + values.unit + ' left';
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

const ROLL_LOOK_ALIKE_CAPITALS = {'А': 'a', 'В': 'b', 'Е': 'e', 'Ё': 'e', 'К': 'k', 'М': 'm', 'Н': 'h', 'О': 'o', 'Р': 'p', 'С': 'c', 'Т': 't', 'У': 'y', 'Х': 'x', 'І': 'i', 'Ї': 'i', 'Ј': 'j', 'Ѕ': 's', 'Ԁ': 'd', 'Ԛ': 'q', 'Ԝ': 'w', 'Ӏ': 'l', 'Α': 'a', 'Β': 'b', 'Ε': 'e', 'Ζ': 'z', 'Η': 'h', 'Ι': 'i', 'Κ': 'k', 'Μ': 'm', 'Ν': 'n', 'Ο': 'o', 'Ρ': 'p', 'Τ': 't', 'Υ': 'y', 'Χ': 'x', 'İ': 'i'};
const ROLL_LOOK_ALIKES = {'а': 'a', 'в': 'b', 'е': 'e', 'ё': 'e', 'к': 'k', 'м': 'm', 'н': 'h', 'о': 'o', 'р': 'p', 'с': 'c', 'т': 't', 'у': 'y', 'х': 'x', 'і': 'i', 'ї': 'i', 'ј': 'j', 'ѕ': 's', 'ԁ': 'd', 'ӏ': 'l', 'ԛ': 'q', 'ԝ': 'w', 'α': 'a', 'ι': 'i', 'κ': 'k', 'ν': 'v', 'ο': 'o', 'ρ': 'p', 'τ': 't', 'υ': 'u', 'χ': 'x', 'ı': 'i', '\u0307': '', 'ς': 'σ', 'ſ': 's', 'ß': 'ss', 'ẞ': 'ss'};
function rollNameKey(text) {
  const clean = String(text || '').normalize('NFKC').replace(/[\p{Cc}\p{Cf}\p{Cs}\p{Co}\p{Cn}]/gu, ch => /\s/.test(ch) ? ' ' : '').replace(/\s+/g, ' ').trim();
  const upper = [...clean].map(ch => ROLL_LOOK_ALIKE_CAPITALS[ch] ?? ch).join('');
  return [...upper.toLowerCase()].map(ch => ROLL_LOOK_ALIKES[ch] ?? ch).join('');
}
