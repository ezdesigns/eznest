'use strict';
document.getElementById('feedback-form').addEventListener('submit', event => {
  event.preventDefault();
  const form = event.currentTarget;
  if (!form.reportValidity()) return;
  const values = new FormData(form);
  const labels = {tester:'Tester', result:'Result', task:'Task', details:'What happened / expected', file:'File type / size', quantity:'Pieces / quantity', material:'Material / width / spacing', comparison:'Compared with usual method', physical:'Physical print and cut'};
  const kit = document.getElementById('kit-id').textContent;
  const lines = ['EZ Nest tester feedback', 'Kit: ' + kit,
    'App build: ' + document.getElementById('app-build').textContent,
    'Date: ' + new Date().toISOString(), ''];
  for (const [key, label] of Object.entries(labels)) lines.push(label + ': ' + (String(values.get(key) || '').trim() || 'Not provided'), '');
  const blob = new Blob([lines.join('\r\n')], {type:'text/plain;charset=utf-8'});
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url; link.download = 'EZ-Nest-feedback-' + kit + '-' + Date.now() + '.txt';
  document.body.append(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 30000);
  document.getElementById('feedback-status').textContent = 'Download requested. Find the text report in your browser downloads and send it back to the person who gave you the kit.';
});
