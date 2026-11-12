'use strict';
// Shared by simple and full workspaces. Invitations never go in URLs or storage.
window.EZNShop = (() => {
  let session, dialog, heading, content, message, done, closeButton;
  let touring = false;
  const node = (tag, text, parent) => {
    const item = document.createElement(tag);
    if (text) item.textContent = text;
    if (parent) parent.append(item);
    return item;
  };
  async function request(path, data) {
    let response;
    try {
      response = await fetch(path, data === undefined ? {} : {
        method: 'POST', headers: {'Content-Type': 'application/json', 'X-EZ-Token': session?.token || ''}, body: JSON.stringify(data)
      });
    } catch (error) {
      if (/Failed to fetch|NetworkError|Load failed/i.test(String(error && error.message || error))) {
        throw Error("Can't reach Ez Nest. Check the connection and try again.");
      }
      throw error;
    }
    const result = await response.json();
    if (!response.ok) throw Error(result.error || 'Could not reach your shop. Try again.');
    return result;
  }
  function button(text, action, parent = content, primary = false) {
    const item = node('button', text, parent); item.type = 'button';
    if (primary) item.className = 'primary';
    item.onclick = async () => {
      item.disabled = true; message.textContent = '';
      try { await action(); } catch (error) { message.textContent = error.message; }
      finally { item.disabled = false; }
    };
    return item;
  }
  function input(label, placeholder = '') {
    const box = node('label', label, content), field = node('input', '', box);
    field.maxLength = 80; field.placeholder = placeholder; field.autocomplete = 'off';
    return field;
  }
  function reset(title) {
    touring = false; dialog.classList.remove('team-walkthrough');
    closeButton.setAttribute('aria-label', 'Close shop');
    heading.textContent = title; content.replaceChildren(); message.textContent = '';
    closeButton.hidden = !canDismiss();
  }
  function canDismiss() { return session?.localPC || session?.authenticated; }
  function dismiss() {
    if (!canDismiss()) return;
    if (touring) { endTour(); return; }
    if (session.localPC && !session.shopIdentity?.created) {
      try { localStorage.setItem('eznest-shop-welcome-dismissed', '1'); } catch {}
    }
    finish();
  }
  function finish() { dialog.close(); if (done) { done(session); done = null; } }
  function rememberTour() {
    try { localStorage.setItem('eznest-tour-seen', '1'); } catch {}
  }
  function endTour() {
    rememberTour(); touring = false;
    if (done && session.localPC && !session.shopIdentity?.created) welcome();
    else finish();
  }
  function tour() {
    reset('Thanks for downloading'); touring = true; dialog.classList.add('team-walkthrough');
    heading.append(document.createTextNode(' '));
    node('span', 'Ez Nest', heading).className = 'tour-brand';
    closeButton.setAttribute('aria-label', 'Close welcome');
    const steps = node('ol', '', content); steps.className = 'tour-steps';
    steps.setAttribute('role', 'list');
    const stepIcons = [
      ['Upload your print file', 'onboarding-upload.webp'],
      ['Choose your material', 'onboarding-stickers.webp'],
      ['Nest, review and save', 'onboarding-file.webp']
    ];
    for (const [title, artwork] of stepIcons) {
      const item = node('li', '', steps);
      const icon = node('img', '', item); icon.src = '/' + artwork; icon.alt = ''; icon.width = 36; icon.height = 36;
      node('span', title, item);
    }
    const pitch = node('section', '', content); pitch.className = 'tour-output-pitch';
    const pitchTitle = node('h3', '', pitch);
    node('span', '🤑', pitchTitle).setAttribute('aria-hidden', 'true');
    node('span', 'Want to earn more?', pitchTitle);
    node('p', 'Check out OUTPUT. Take on more jobs without buying more equipment. You keep the customer. Or get paid to print for other shops.', pitch);
    const actions = node('div', '', content); actions.className = 'tour-actions';
    button('Continue', endTour, actions).id = 'tour-next';
    const link = node('a', 'Use OUTPUT', actions); link.id = 'tour-output-link'; link.href = 'https://output.jeezlabs.io/'; link.target = '_blank'; link.rel = 'noopener noreferrer'; link.referrerPolicy = 'no-referrer';
    heading.tabIndex = -1; heading.focus({preventScroll:true}); dialog.scrollTop = 0;
  }
  function showTour() {
    if (!dialog || !canDismiss()) return;
    tour(); if (!dialog.open) dialog.showModal(); heading.focus({preventScroll:true});
  }
  async function updateSession() { session = await request('/api/session'); label(); }
  function label() {
    const shopButton = document.getElementById('shop-team-open');
    const name = session.shopIdentity?.name || 'Your shop';
    shopButton.replaceChildren();
    const icon = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    icon.setAttribute('viewBox', '0 0 24 24'); icon.setAttribute('width', '20'); icon.setAttribute('height', '20'); icon.setAttribute('aria-hidden', 'true');
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', 'M3 10h18l-2-6H5l-2 6Zm1 0v10h16V10M9 20v-6h6v6M3 10c0 3 4.5 3 4.5 0 0 3 4.5 3 4.5 0 0 3 4.5 3 4.5 0 0 3 4.5 3 4.5 0');
    path.setAttribute('fill', 'none'); path.setAttribute('stroke', 'currentColor'); path.setAttribute('stroke-width', '1.6'); path.setAttribute('stroke-linejoin', 'round');
    icon.append(path); shopButton.append(icon); node('span', session.shopIdentity?.name || 'Your shop', shopButton);
    shopButton.title = name;
    shopButton.setAttribute('aria-haspopup', 'dialog');
    shopButton.classList.add('top-button');
  }
  async function created() { await updateSession(); finish(); }
  function welcome() {
    reset('Welcome to Ez Nest');
    node('p', 'Create a shop for your team, or join one with an invite.', content);
    button('Create a shop', () => {
      reset('Create your shop');
      const name = input('Shop name', 'Your shop'); name.id = 'team-shop-name';
      node('p', 'People you invite share this shop’s materials.', content);
      if (session.pinConfigured) node('p', 'People using the old PIN need a new invite.', content);
      button('Create shop', async () => { await request('/api/shop-members/create', {name: name.value}); await created(); }, content, true).id = 'team-create';
      button('Back', welcome); name.focus();
    }, content, true);
    button('Join a shop', joinAddress);
    button('Use this PC for now', dismiss);
  }
  function joinAddress() {
    reset('Join a shop');
    node('p', 'Ask for the shop address. Open it, then enter your invite.', content);
    const address = input('Shop address', 'http://SHOP-PC:8765'); address.id = 'team-address';
    button('Open shop', () => {
      const raw = address.value.trim();
      const url = new URL(raw.includes('://') ? raw : 'http://' + raw);
      const host = url.hostname.toLowerCase();
      const privateIp = /^(10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)/.test(host) && /^(\d{1,3}\.){3}\d{1,3}$/.test(host);
      const localName = /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.(?:local|lan))?$/.test(host) && host !== 'localhost';
      if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || (!privateIp && !localName) || url.search || url.hash || !['/', '/web', '/web/'].includes(url.pathname)) throw Error('Enter a shop PC name or private network address, without a code or password.');
      if (!url.port) url.port = '8765';
      url.pathname = '/';
      url.search = '?view=simple'; location.assign(url.href);
    }, content, true);
    button('Back', welcome);
  }
  function join() {
    reset('Join ' + (session.shopIdentity?.name || 'your shop'));
    if (session.accessRemoved) node('p', 'Your access was removed. Ask for a new invite.', content);
    node('p', 'Join once with your invite. This browser will remember your shop.', content);
    const name = input('Your name'); name.id = 'team-member-name'; name.autocomplete = 'name';
    const code = input('Invite code', 'XXXXX-XXXXX-XXXXX-XXXXX'); code.id = 'team-code'; code.spellcheck = false;
    button('Join shop', async () => {
      await request('/api/shop-members/join', {name: name.value, code: code.value}); code.value = '';
      await updateSession(); finish();
    }, content, true).id = 'team-join';
  }
  async function manage() {
    reset(session.shopIdentity?.name || 'Your shop');
    node('p', 'Everyone in this shop uses the same materials.', content);
    const shop = await request('/api/shop-members');
    node('h3', 'People', content);
    if (!shop.members?.length) node('p', 'No one has joined yet.', content);
    for (const member of shop.members || []) {
      const row = node('div', '', content); row.className = 'team-person';
      node('span', member.name, row);
      if (session.localPC) button('Remove access', async () => { await request('/api/shop-members/revoke', {id: member.id}); await manage(); }, row);
    }
    if (session.localPC) {
      let inviteSlot = null;
      if (session.shopAddress) {
        node('p', 'People open this address:', content);
        node('code', session.shopAddress, content);
        button('Invite someone', async () => {
          const invite = await request('/api/shop-members/invite', {});
          inviteSlot.hidden = false;
          inviteSlot.textContent = invite.code + ' · One use · Expires in 15 minutes';
        }, content, true);
        button('Cancel unused invites', async () => {
          await request('/api/shop-members/cancel-invites', {});
          inviteSlot.hidden = true;
          inviteSlot.textContent = '';
          message.textContent = 'Unused invites cancelled.';
        });
      } else {
        node('p', 'Invites are off until this computer is on the shop network. Turn that on and restart Ez Nest.', content);
      }
      // Keep the invitation in the dialog content before the close control.
      inviteSlot = node('p', '', content);
      inviteSlot.id = 'team-invitation';
      inviteSlot.hidden = true;
    } else {
      node('p', 'Ask the shop computer to invite people.', content);
      button('Log out', async () => { await request('/api/logout', {}); location.reload(); });
    }
  }
  async function open() {
    await updateSession();
    if (!session.localPC && session.shopIdentity?.created && !session.authenticated) join();
    else if (!session.shopIdentity?.created && session.localPC) welcome();
    else if (!session.shopIdentity?.created) {
      reset('Your shop'); node('p', 'Ask the host to create the shop and send you an invitation.', content);
    }
    else await manage();
    if (!dialog.open) dialog.showModal();
  }
  let pending;
  function start() {
    if (pending) return pending;
    pending = (async () => {
      session = await request('/api/session');
      dialog = node('dialog', '', document.body); dialog.id = 'shop-team-dialog';
      dialog.setAttribute('aria-labelledby', 'shop-team-title');
      heading = node('h2', '', dialog); heading.id = 'shop-team-title';
      closeButton = node('button', '×', dialog); closeButton.id = 'shop-team-close'; closeButton.type = 'button';
      closeButton.setAttribute('aria-label', 'Close shop'); closeButton.onclick = dismiss;
      content = node('div', '', dialog); message = node('p', '', dialog); message.setAttribute('role', 'status');
      dialog.addEventListener('cancel', event => {
        event.preventDefault(); dismiss();
      });
      let startedOutside = false;
      function outside(event) {
        const r = dialog.getBoundingClientRect();
        return event.target === dialog && (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom);
      }
      dialog.addEventListener('pointerdown', event => { startedOutside = outside(event); });
      dialog.addEventListener('pointercancel', () => { startedOutside = false; });
      dialog.addEventListener('click', event => { if (startedOutside && outside(event)) dismiss(); startedOutside = false; });
      const parent = document.querySelector('.header-tools, .top-actions') || document.querySelector('header');
      button('Your shop', open, parent).id = 'shop-team-open'; label();
      document.getElementById('shop-team-open').classList.add('top-button');
      parent.prepend(document.getElementById('shop-team-open'));
      let dismissed = false;
      try { dismissed = localStorage.getItem('eznest-shop-welcome-dismissed') === '1'; } catch {}
      const visit = new URL(location.href), replay = visit.searchParams.get('tour') === '1';
      if (replay) { visit.searchParams.delete('tour'); history.replaceState(null, '', visit.pathname + visit.search + visit.hash); }
      if ((session.localPC && !session.shopIdentity?.created && !dismissed) || (!session.localPC && session.shopIdentity?.created && !session.authenticated)) {
        const waiting = new Promise(resolve => { done = resolve; });
        let seen = false;
        try { seen = localStorage.getItem('eznest-tour-seen') === '1'; } catch {}
        await window.EZNStartup?.reveal();
        if (session.localPC && !seen) showTour(); else await open();
        return waiting;
      }
      if (replay) { await window.EZNStartup?.reveal(); showTour(); }
      return session;
    })();
    return pending;
  }
  return {start, showTour};
})();
