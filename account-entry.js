/* Shared by the two workspaces. OUTPUT owns Privy sign-in and authorizes this
 * computer with its existing one-time code. Opening that page is not sign-in. */
(() => {
  'use strict';
  document.documentElement.dataset.accountPending = 'true';
  let pending, session, shop, dialog, content, error, close, control, busy = false;
  const node = (tag, text, attrs = {}) => {
    const el = document.createElement(tag);
    if (text) el.textContent = text;
    for (const [key, value] of Object.entries(attrs)) el.setAttribute(key, value);
    return el;
  };
  async function request(path, data) {
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch(path, {cache: 'no-store', signal: controller.signal,
        ...(data === undefined ? {} : {method: 'POST', headers: {'Content-Type': 'application/json', 'X-EZ-Token': session?.token || ''}, body: JSON.stringify(data)})});
      const result = await response.json();
      if (!response.ok) throw Error(typeof result.error === 'string' ? result.error : 'Please try again.');
      return result;
    } finally { clearTimeout(timer); }
  }
  function build() {
    if (dialog) return;
    dialog = node('dialog', '', {id: 'account-entry', 'aria-labelledby': 'account-entry-title'});
    const head = node('div', '', {class: 'account-entry-head'});
    head.append(node('span', 'EZNest', {class: 'account-entry-brand'}));
    close = node('button', '×', {type: 'button', 'aria-label': 'Close account'});
    close.onclick = () => { if (session?.account?.ready && shop?.setupComplete) dialog.close(); };
    head.append(close); content = node('div'); error = node('p', '', {role: 'alert', class: 'account-entry-error'});
    dialog.append(head, content, error); document.body.append(dialog);
    dialog.addEventListener('cancel', event => { if (!session?.account?.ready || !shop?.setupComplete || busy) event.preventDefault(); });
    control = node('button', 'Account', {type: 'button', id: 'account-open'});
    control.onclick = () => { pending = undefined; ensure(true).catch(showError); };
    (document.querySelector('.header-tools') || document.querySelector('#top-actions') || document.querySelector('header')).append(control);
  }
  function showError(failure) {
    error.textContent = failure.name === 'AbortError' ? 'The connection timed out. Try again.' : failure.message;
  }
  function page(step, title, note) {
    content.replaceChildren(node('p', step, {class: 'account-entry-step'}), node('h1', title, {id: 'account-entry-title'}), node('p', note));
    error.textContent = ''; close.hidden = !session?.account?.ready || !shop?.setupComplete;
    if (!dialog.open) dialog.showModal();
  }
  function button(text, action, primary = true) {
    const el = node('button', text, {type: 'button', ...(primary ? {class: 'primary'} : {})});
    el.onclick = action; return el;
  }
  function loginLink() {
    // The server builds this from its configured, allowlisted OUTPUT origin.
    const value = session?.account?.connectUrl;
    let url;
    try { url = new URL(value); } catch { return node('p', 'OUTPUT sign-in is unavailable.'); }
    if (url.protocol !== 'https:' || url.username || url.password || url.pathname !== '/workspace' || url.search !== '?tools=eznest' || url.hash) return node('p', 'OUTPUT sign-in is unavailable.');
    return node('a', 'Sign in with OUTPUT', {id: 'account-sign-in', class: 'button primary', href: url.href, target: '_blank', rel: 'noopener noreferrer'});
  }
  function welcome(resolve) {
    page('01 / Welcome', 'Your work starts here.', 'Nest print-ready artwork, keep track of materials, and prepare files for your print software.');
    const list = node('ol', '', {class: 'account-entry-steps'});
    for (const text of ['Sign in with your OUTPUT account', 'Set up this computer', 'Start nesting — online or offline']) list.append(node('li', text));
    content.append(list, button('Continue', () => connect(resolve)), node('p', 'Your artwork and inventory stay on this computer.', {class: 'account-entry-note'}));
  }
  function connect(resolve) {
    page('02 / Account', 'One account for OUTPUT and EZNest.', 'Use the same Privy sign-in as OUTPUT. In OUTPUT, add this computer, then enter its one-time code here.');
    if (!session.localPC) {
      content.append(node('p', 'Finish sign-in on the shop computer first.'), button('Check again', () => refresh(resolve).catch(showError)));
      return;
    }
    content.append(loginLink(), node('p', 'Return to this window after signing in. Opening OUTPUT alone does not connect this computer.', {class: 'account-entry-note'}));
    const form = node('form'), label = node('label', 'Computer code from OUTPUT');
    const input = node('input', '', {id: 'account-code', autocomplete: 'off', spellcheck: 'false', autocapitalize: 'characters', maxlength: '64', placeholder: 'XXXXX-XXXXX', required: ''});
    label.append(input);
    const submit = node('button', 'Connect this computer', {type: 'submit', class: 'primary'});
    form.append(label, submit);
    form.onsubmit = async event => {
      event.preventDefault(); if (busy) return;
      busy = true; submit.disabled = true; error.textContent = '';
      try {
        const code = input.value; input.value = '';
        await request('/api/telemetry/output/pair', {code});
        await refresh(resolve);
      } catch (failure) {
        // A lost HTTP response must not make the user redeem a spent code.
        // The service may already have persisted successful authorization.
        try {
          const latest = await request('/api/session');
          if (latest.account?.ready) { await refresh(resolve); return; }
        } catch { /* A manual status check is also available below. */ }
        showError(failure);
      }
      finally { busy = false; submit.disabled = false; }
    };
    content.append(form, button('Check connection', async () => {
      try {
        await refresh(resolve);
        if (!session.account?.ready) error.textContent = 'This computer is not connected yet. Complete sign-in in OUTPUT and enter its computer code.';
      } catch (failure) { showError(failure); }
    }, false), node('p', 'Connecting sends this computer’s name and installation ID to OUTPUT. Activity and capacity sharing stay off until you enable them.', {class: 'account-entry-note'}));
  }
  function setup(resolve) {
    page('03 / This computer', 'Make it yours.', 'Choose your working units and label this computer’s printer. These settings stay local.');
    const form = node('form'), fields = {};
    function field(key, title, fallback, limit) {
      const label = node('label', title), input = node('input', '', {maxlength: String(limit)});
      input.value = shop[key] || fallback; fields[key] = input; label.append(input); return label;
    }
    form.append(field('printer', 'Printer label (optional)', '', 120));
    const label = node('label', 'Working units'), units = node('select', '', {id: 'account-units'});
    for (const [value, text] of [['mm', 'Millimeters'], ['in', 'Inches'], ['cm', 'Centimeters']]) units.append(node('option', text, {value}));
    units.value = shop.units || 'mm'; label.append(units); form.append(label);
    const details = node('details'), summary = node('summary', 'Cutting setup');
    details.append(summary, field('thru', 'Through-cut spot', 'CutContour_Thru-cut', 80), field('kiss', 'Kiss-cut spot', 'CutContour_Kiss-cut', 80), node('p', 'Confirm these names in your print software before production.', {class: 'account-entry-note'}));
    const submit = node('button', 'Save and start nesting', {type: 'submit', class: 'primary'});
    form.append(details, submit);
    form.onsubmit = async event => {
      event.preventDefault(); if (busy) return;
      busy = true; submit.disabled = true; error.textContent = '';
      try {
        shop = await request('/api/setup', {printer: fields.printer.value.trim(), units: units.value,
          thru: fields.thru.value.trim(), kiss: fields.kiss.value.trim(), hotFolder: shop.hotFolder || '', onyxPc: shop.onyxPc === true});
        finish(resolve);
      } catch (failure) { showError(failure); }
      finally { busy = false; submit.disabled = false; }
    };
    content.append(form);
  }
  function finish(resolve) {
    document.documentElement.removeAttribute('data-account-pending');
    control.textContent = session.account.devMode ? 'Account · development' : 'Account · connected';
    dialog.close(); resolve({session, shop});
  }
  function account(resolve) {
    page('Account', 'Connected through OUTPUT.', 'This computer can nest offline. Opening OUTPUT uses the same Privy account flow. Artwork and inventory remain local.');
    content.append(loginLink(), button('Disconnect this computer', async () => {
      if (!window.confirm('Disconnect this computer? You will need to sign in through OUTPUT and enter a new code before nesting again. Your local files and inventory are kept.')) return;
      try { await request('/api/telemetry/output/disconnect', {}); await refresh(resolve); }
      catch (failure) { showError(failure); }
    }, false));
    document.documentElement.removeAttribute('data-account-pending'); resolve({session, shop});
  }
  async function refresh(resolve, reopen = false) {
    session = await request('/api/session');
    if (!session.account?.ready) { document.documentElement.dataset.accountPending = 'true'; connect(resolve); return; }
    // LAN browsers still enter their shop PIN in the existing workspace boot.
    // /api/shop is host-only, and must never be queried before that PIN flow.
    if (!session.localPC) { shop = {setupComplete: true}; finish(resolve); return; }
    shop = await request('/api/shop');
    if (session.localPC && !session.account.devMode && !shop.setupComplete) setup(resolve);
    else if (reopen) account(resolve);
    else finish(resolve);
  }
  function ensure(reopen = false) {
    if (pending && !reopen) return pending;
    build();
    pending = new Promise(resolve => {
      request('/api/session').then(async info => {
        session = info;
        if (info.account?.ready) await refresh(resolve, reopen);
        else { document.documentElement.dataset.accountPending = 'true'; welcome(resolve); }
      }).catch(failure => {
        page('Connection', 'Connect to the local service.', 'EZNest could not load the account status. Your work is kept on this computer.');
        content.append(button('Try again', () => refresh(resolve).catch(showError))); showError(failure);
      });
    });
    return pending;
  }
  window.EZNAccountEntry = {ensure};
})();
