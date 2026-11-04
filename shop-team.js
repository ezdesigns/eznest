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
    const response = await fetch(path, data === undefined ? {} : {
      method: 'POST', headers: {'Content-Type': 'application/json', 'X-EZ-Token': session?.token || ''}, body: JSON.stringify(data)
    });
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
    dialog.querySelector('.tour-brand-row')?.remove();
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
    try { localStorage.setItem('eznest-tour-seen', '1'); localStorage.setItem('eznest-shop-welcome-dismissed', '1'); } catch {}
  }
  function endTour() { rememberTour(); touring = false; finish(); }
  function tour(step = 0) {
    const titles = [['Thanks for downloading', 'Ez Nest.'], ['How it works.', ''], ['Meet', 'OUTPUT.']];
    reset(''); touring = true; dialog.classList.add('team-walkthrough');
    node('span', titles[step][0], heading);
    if (titles[step][1]) node('em', titles[step][1], heading);
    closeButton.setAttribute('aria-label', 'Close walkthrough');
    const brand = node('div', '', null); brand.className = 'tour-brand-row';
    const progress = node('span', `Quick tour · ${step + 1} of 3`, brand); progress.id = 'tour-progress';
    dialog.insertBefore(brand, heading);
    function illustration(src, alt) {
      const image = node('img', '', content); image.className = 'tour-illustration'; image.src = src; image.alt = alt;
      image.width = 600; image.height = 340;
    }
    if (step === 0) {
      node('p', 'Free nesting. Less wasted material.', content).className = 'tour-lead';
      illustration('/onboarding-nest.webp', 'Illustration of shapes nested on a roll of material.');
    } else if (step === 1) {
      const steps = node('ol', '', content); steps.className = 'tour-steps';
      for (const title of ['Upload your print file.', 'Choose your material.', 'Nest, review, and save.']) node('li', title, steps);
    } else {
      node('p', 'We’re building a network for print shops to send work out and bring work in.', content).className = 'tour-lead';
      const link = node('a', 'Explore OUTPUT ↗', content); link.id = 'tour-output-link'; link.href = 'https://output.jeezlabs.io/'; link.target = '_blank'; link.rel = 'noopener noreferrer'; link.referrerPolicy = 'no-referrer';
    }
    const actions = node('div', '', content); actions.className = 'tour-actions';
    if (step > 0) button('Back', () => tour(step - 1), actions).id = 'tour-back';
    if (step < 2) { const skip = button('Skip tour', endTour, actions); skip.className = 'team-text-button tour-skip'; actions.prepend(skip); }
    button(step === 2 ? 'Start nesting' : 'Next', () => step === 2 ? endTour() : tour(step + 1), actions, step !== 2).id = 'tour-next';
    if (step === 2) actions.append(document.getElementById('tour-output-link'));
    heading.tabIndex = -1; heading.focus({preventScroll:true}); dialog.scrollTop = 0;
  }
  function showTour() {
    if (!dialog || !canDismiss()) return;
    tour(); if (!dialog.open) dialog.showModal(); heading.focus({preventScroll:true});
  }
  async function updateSession() { session = await request('/api/session'); label(); }
  function label() {
    const open = document.getElementById('shop-team-open');
    open.replaceChildren();
    const icon = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    icon.setAttribute('viewBox', '0 0 24 24'); icon.setAttribute('width', '20'); icon.setAttribute('height', '20'); icon.setAttribute('aria-hidden', 'true');
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', 'M3 10h18l-2-6H5l-2 6Zm1 0v10h16V10M9 20v-6h6v6M3 10c0 3 4.5 3 4.5 0 0 3 4.5 3 4.5 0 0 3 4.5 3 4.5 0 0 3 4.5 3 4.5 0');
    path.setAttribute('fill', 'none'); path.setAttribute('stroke', 'currentColor'); path.setAttribute('stroke-width', '1.6'); path.setAttribute('stroke-linejoin', 'round');
    icon.append(path); open.append(icon); node('span', session.shopIdentity?.name || 'Your shop', open);
    open.title = session.shopIdentity?.name || 'Your shop';
    open.setAttribute('aria-haspopup', 'dialog');
  }
  async function created() { await updateSession(); finish(); }
  function welcome() {
    reset('Set up your shop');
    const name = input('What’s your print shop called?', 'Your print shop'); name.id = 'team-shop-name';
    name.required = true; name.autocomplete = 'organization';
    node('p', 'Keep your materials together under one shop name. You can invite your team later.', content);
    if (session.pinConfigured) node('p', 'This replaces shared PIN access. Invite current teammates again after creating the shop.', content);
    const create = button('Save shop', async () => {
      name.value = name.value.trim();
      if (!name.reportValidity()) return;
      await request('/api/shop-members/create', {name: name.value}); await created();
    }, content, true); create.id = 'team-create';
    name.addEventListener('keydown', event => {
      if (event.key === 'Enter' && !event.isComposing) { event.preventDefault(); create.click(); }
    });
    button('Not now', () => { try { localStorage.setItem('eznest-shop-welcome-dismissed', '1'); } catch {} finish(); }).className = 'team-text-button';
    const existing = node('div', '', content); existing.className = 'team-existing';
    button('Already have a shop on another PC?', joinAddress, existing).className = 'team-text-button';
    name.focus();
  }
  function joinAddress() {
    reset('Open your shop');
    node('p', 'Ask your shop host for its address. Open it on this shop’s network, then enter your invitation. You will use the host’s stock, not a second copy on this PC.', content);
    const address = input('Shop address', 'http://SHOP-PC:8765'); address.id = 'team-address';
    button('Open shop', () => {
      const raw = address.value.trim();
      const url = new URL(raw.includes('://') ? raw : 'http://' + raw);
      const host = url.hostname.toLowerCase();
      const privateIp = /^(10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)/.test(host) && /^(\d{1,3}\.){3}\d{1,3}$/.test(host);
      const localName = /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.(?:local|lan))?$/.test(host) && host !== 'localhost';
      if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || (!privateIp && !localName) || url.search || url.hash || url.pathname !== '/') throw Error('Enter a shop PC name or private network address, without a code or password.');
      if (!url.port) url.port = '8765';
      url.search = '?view=simple'; location.assign(url.href);
    }, content, true);
    button('Back', welcome);
  }
  function join() {
    reset('Join ' + (session.shopIdentity?.name || 'your shop'));
    node('p', 'Enter the one-time invitation from your shop host. Everyone in this shop uses the same material stock.', content);
    const name = input('Your name'); name.id = 'team-member-name'; name.autocomplete = 'name';
    const code = input('Invitation code', 'XXXXX-XXXXX-XXXXX-XXXXX'); code.id = 'team-code'; code.spellcheck = false;
    button('Join shop', async () => {
      await request('/api/shop-members/join', {name: name.value, code: code.value}); code.value = '';
      await updateSession(); finish();
    }, content, true).id = 'team-join';
  }
  async function manage() {
    reset(session.shopIdentity?.name || 'Your shop');
    node('p', 'Shared material stock. Stock is deducted when usage is confirmed, not just when a layout is previewed.', content);
    node('p', 'Pilot: coordinate one active nesting job at a time. The host PC must stay on. Remote locations are not connected yet.', content);
    if (session.localPC) {
      const shop = await request('/api/shop-members');
      if (session.shopAddress) {
        node('p', 'Teammates open this address on the shop network:', content);
        node('code', session.shopAddress, content);
        button('Create invitation', async () => {
          const invite = await request('/api/shop-members/invite', {});
          let box = document.getElementById('team-invitation');
          if (!box) { box = node('p', '', content); box.id = 'team-invitation'; }
          box.textContent = invite.code + ' · One use · Expires in 15 minutes';
        }, content, true);
        button('Cancel unused invitations', async () => {
          await request('/api/shop-members/cancel-invites', {});
          document.getElementById('team-invitation')?.remove(); message.textContent = 'Unused invitations cancelled.';
        });
      } else {
        node('p', 'This PC is local only. Before inviting people, set up the shared shop host with shop network enabled, then restart Ez Nest. Creating a shop does not open your network.', content);
      }
      node('h3', 'People with access', content);
      if (!shop.members?.length) node('p', 'No teammates have joined yet.', content);
      for (const member of shop.members || []) {
        const row = node('div', '', content); row.className = 'team-person';
        node('span', member.name, row);
        button('Remove access', async () => { await request('/api/shop-members/revoke', {id: member.id}); await manage(); }, row);
      }
    } else {
      node('p', 'Ask the host to manage invitations and people.', content);
      button('Sign out', async () => { await request('/api/logout', {}); location.reload(); });
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
        if (session.localPC) showTour(); else await open();
        return waiting;
      }
      if (replay) showTour();
      return session;
    })();
    return pending;
  }
  return {start, showTour};
})();
