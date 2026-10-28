'use strict';
// All lengths are millimeters. Cost is material only, never ink or labor.
(function(root) {
  const finite = n => typeof n === 'number' && Number.isFinite(n);
  function comparison(state, previousLengthFt) {
    const used = state?.result?.usedLength;
    if (!finite(used) || used <= 0) return null;
    const manual = finite(previousLengthFt) && previousLengthFt > 0;
    const baseline = manual ? previousLengthFt * 304.8 : state.nestSavings?.baselineLengthMm ?? state.result?.layoutComparison?.baselineLengthMm;
    if (!finite(baseline) || baseline <= 0) return null;
    const saved = baseline - used;
    const price = state.job?.webOptions?.rollCost;
    const roll = state.job?.webOptions?.fullRollLengthMm;
    return {savedFt: saved / 304.8, percent: saved / baseline * 100,
      savedDollars: finite(price) && price >= 0 && finite(roll) && roll > 0 ? saved / roll * price : null,
      reference: manual ? 'your previous print length' : state.nestSavings ? 'the first fit in this job' : state.result.layoutComparison.reference};
  }
  function signature(state) {
    const job = state?.job;
    if (!job) return '';
    // A prior length is valid only for the same material, width and quantities.
    return JSON.stringify([job.materialName, job.settings?.width, job.settings?.rollWidth,
      (job.parts || []).map(p => [p.documentId || p.sourceJobId, p.pdfPieceId || p.originalPartId || p.id, p.quantity])]);
  }
  function feedback(version, message, state, includeResults) {
    const lines = ['EZ Nest feedback', 'Version: ' + String(version || 'unknown'), '', String(message || '').trim()];
    if (includeResults && state?.result) {
      const r = state.result;
      const metrics = {placedCopies: r.placements?.length, sheetCount: r.sheets?.length || 1,
        printableWidthIn: r.width / 25.4, lengthFt: r.usedLength / 304.8,
        unusedPrintablePercent: (1 - r.utilization) * 100, nestingSeconds: r.elapsed};
      lines.push('', 'Result numbers (shared by choice):');
      for (const [key, value] of Object.entries(metrics)) if (finite(value)) lines.push(key + ': ' + Number(value.toFixed(4)));
    }
    return lines.join('\n');
  }
  const api = {comparison, signature, feedback};
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.EZNResults = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
