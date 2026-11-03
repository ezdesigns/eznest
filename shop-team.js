'use strict';
// Shared by simple and full workspaces. Invitations never go in URLs or storage.
window.EZNShop = (() => {
  let session, dialog, heading, content, message, done;
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
  function reset(title) { heading.textContent = title; content.replaceChildren(); message.textContent = ''; }
  function finish() { dialog.close(); if (done) { done(session); done = null; } }
  async function updateSession() { session = await request('/api/session'); label(); }
  function label() {
    const shopButton = document.getElementById('shop-team-open');
    shopButton.textContent = session.shopIdentity?.name || 'Your shop';
    const parent = shopButton.parentElement;
    let invite = document.getElementById('shop-invite-open');
    const show = !!(session.localPC && session.shopIdentity?.created);
    if (show && !invite && parent) {
      invite = button('Invite', open, parent);
      invite.id = 'shop-invite-open';
      invite.className = 'top-button';
      const logout = document.getElementById('logout');
      if (logout && logout.parentElement === parent) parent.insertBefore(invite, logout);
    } else if (!show && invite) invite.remove();
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
    button('Use this PC for now', finish);
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
      if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || (!privateIp && !localName) || url.search || url.hash || url.pathname !== '/') throw Error('Enter a shop PC name or private network address, without a code or password.');
      if (!url.port) url.port = '8765';
      url.search = '?view=simple'; location.assign(url.href);
    }, content, true);
    button('Back', welcome);
  }
  function join() {
    reset('Join ' + (session.shopIdentity?.name || 'your shop'));
    if (session.accessRemoved) node('p', 'Your access was removed. Ask for a new invite.', content);
    node('p', 'Enter your name and the invite from your shop.', content);
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
    if (session.localPC) {
      const shop = await request('/api/shop-members');
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
      node('h3', 'People', content);
      if (!shop.members?.length) node('p', 'No one has joined yet.', content);
      for (const member of shop.members || []) {
        const row = node('div', '', content); row.className = 'team-person';
        node('span', member.name, row);
        button('Remove access', async () => { await request('/api/shop-members/revoke', {id: member.id}); await manage(); }, row);
      }
      // The code sits above Done. Appending it when the invite is created would put it below.
      inviteSlot = node('p', '', content);
      inviteSlot.id = 'team-invitation';
      inviteSlot.hidden = true;
    } else {
      node('p', 'Ask the shop computer to invite people.', content);
      button('Log out', async () => { await request('/api/logout', {}); location.reload(); });
    }
    button('Done', finish);
  }
  async function open() {
    await updateSession();
    if (!session.localPC && session.shopIdentity?.created && !session.authenticated) join();
    else if (!session.shopIdentity?.created && session.localPC) welcome();
    else if (!session.shopIdentity?.created) {
      reset('Your shop'); node('p', 'Ask the host to create the shop and send you an invitation.', content); button('Done', finish);
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
      content = node('div', '', dialog); message = node('p', '', dialog); message.setAttribute('role', 'status');
      dialog.addEventListener('cancel', event => {
        if (!session.localPC && !session.authenticated) event.preventDefault(); else finish();
      });
      const parent = document.querySelector('.header-tools, .top-actions') || document.querySelector('header');
      const shopButton = button('Your shop', open, parent);
      shopButton.id = 'shop-team-open';
      const logout = document.getElementById('logout');
      if (logout && logout.parentElement === parent) parent.insertBefore(shopButton, logout);
      label();
      if ((session.localPC && !session.shopIdentity?.created) || (!session.localPC && session.shopIdentity?.created && !session.authenticated)) {
        const waiting = new Promise(resolve => { done = resolve; }); await open(); return waiting;
      }
      return session;
    })();
    return pending;
  }
  return {start};
})();
