'use strict';
// Shared by simple and full workspaces. Invitations never go in URLs or storage.
window.EZNShop = (() => {
  let session, dialog, heading, content, message, done, closeButton;
  let touring = false;
  let stopTourMotion = () => {};
  const node = (tag, text, parent) => {
    const item = document.createElement(tag);
    if (text) item.textContent = text;
    if (parent) parent.append(item);
    return item;
  };
  function svgNode(tag, attrs, parent) {
    const item = document.createElementNS('http://www.w3.org/2000/svg', tag);
    for (const [key, value] of Object.entries(attrs)) item.setAttribute(key, value);
    if (parent) parent.append(item);
    return item;
  }
  function stepIcon(kind, parent) {
    const img = node('img', '', parent); img.className = 'tour-step-icon'; img.alt = '';
    img.src = '/onboarding-' + ({file:'upload', roll:'printer', layout:'computer'}[kind]) + '.webp';
    img.width = 90; img.height = 90;
  }
  function nestingDrawing(parent) {
    // OUTPUT's original ComputerIllustration artwork and screen geometry.
    const svg = svgNode('svg', {viewBox:'0 0 620 250',class:'tour-nesting-drawing',role:'img','aria-label':'A print file arriving on the shop computer, using OUTPUT’s original artwork.'}, parent);
    svgNode('image',{href:'/onboarding-file.webp',x:52,y:83,width:94,height:94,class:'tour-welcome-file tour-nest-piece'},svg);
    const computer = svgNode('g',{transform:'translate(174 0) scale(.25)'},svg);
    svgNode('image',{href:'/onboarding-computer.webp',width:1000,height:1000},computer);
    svgNode('path',{d:'M314 222Q467 223 650 252L643 493Q468 497 313 465Q301 347 314 222Z',fill:'#53c27b',class:'tour-welcome-screen tour-nest-piece'},computer);
    svgNode('image',{href:'/onboarding-stickers.webp',x:438,y:86,width:116,height:116},svg);
    return svg;
  }
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
    stopTourMotion();
    touring = false; dialog.classList.remove('team-walkthrough', 'team-output-tour', 'team-steps-tour');
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
  function finish() { stopTourMotion(); dialog.close(); if (done) { done(session); done = null; } }
  function rememberTour() {
    try { localStorage.setItem('eznest-tour-seen', '1'); localStorage.setItem('eznest-shop-welcome-dismissed', '1'); } catch {}
  }
  function endTour() { rememberTour(); touring = false; finish(); }
  function tour(step = 0) {
    const titles = [['Thanks for downloading', 'Ez Nest.'], ['Your next print', 'in three steps.'], ['Meet', 'OUTPUT.']];
    reset(''); touring = true; dialog.classList.add('team-walkthrough');
    if (step === 2) dialog.classList.add('team-output-tour');
    if (step === 1) dialog.classList.add('team-steps-tour');
    node('span', titles[step][0], heading);
    if (titles[step][1]) node('em', titles[step][1], heading);
    closeButton.setAttribute('aria-label', 'Close walkthrough');
    const brand = node('div', '', null); brand.className = 'tour-brand-row';
    const progress = node('span', `Quick tour · ${step + 1} of 3`, brand); progress.id = 'tour-progress';
    dialog.insertBefore(brand, heading);
    function motionControl(figure, onActive = () => {}, controls) {
      const media = matchMedia('(prefers-reduced-motion: reduce)');
      let playing = !media.matches;
      const toggle = controls ? node('button', '', controls) : null;
      if (toggle) { toggle.type = 'button'; toggle.className = 'tour-story-play'; }
      function sync() {
        const active = playing && !document.hidden;
        figure.dataset.running = String(active);
        onActive(active);
        if (toggle) {
          toggle.textContent = playing ? 'Ⅱ' : '▶';
          toggle.setAttribute('aria-label', playing ? 'Pause examples' : 'Play examples');
          toggle.title = playing ? 'Pause examples' : 'Play examples';
        }
      }
      if (toggle) toggle.onclick = () => { playing = !playing; sync(); };
      const preference = () => { playing = !media.matches; sync(); };
      media.addEventListener('change', preference); document.addEventListener('visibilitychange', sync);
      stopTourMotion = () => {
        playing = false; sync();
        media.removeEventListener('change', preference); document.removeEventListener('visibilitychange', sync);
        stopTourMotion = () => {};
      };
      sync();
    }
    if (step === 0) {
      node('p', 'Arrange your print pieces into a tighter layout and save a file ready to review for printing.', content).className = 'tour-lead';
      node('p', 'Free to use. Built for print shops.', content).className = 'tour-free';
      motionControl(nestingDrawing(content));
    } else if (step === 1) {
      const steps = node('ol', '', content); steps.className = 'tour-steps';
      for (const [icon, title, detail] of [
        ['file', 'Add your print file', 'Use artwork you’ve prepared for printing.'],
        ['roll', 'Choose your roll', 'Its printable width and spacing guide the layout.'],
        ['layout', 'Nest, review, and save', 'Check the pieces and material used before exporting.']
      ]) {
        const row = node('li', '', steps); stepIcon(icon, row); const copy = node('div', '', row);
        node('strong', title, copy); node('span', detail, copy);
      }
    } else {
      node('p', 'Another product from the Ez Nest team, connecting print shops to send work out and bring new work in.', content).className = 'tour-output-intro';
      // Compact adaptation of OUTPUT's landing-demo.ts illustrated stories.
      const stories = [
        {name:'A rush order', job:'200 vinyl stickers by tomorrow', art:'stickers', from:'Your shop', source:'printer', to:'A nearby shop', machine:'printer', captions:['Your machines are booked for two days.', 'OUTPUT finds a shop with time today.', 'Your partner makes the stickers. You keep the customer.']},
        {name:'A bigger job', job:'A 10-foot-wide backdrop', art:'backdrop', from:'Your shop', source:'printer', to:'A partner shop', machine:'printer', captions:['Your 54-inch printer is too narrow.', 'OUTPUT finds a wider printer.', 'Your partner makes the seamless backdrop.']},
        {name:'A distant delivery', job:'200 event stickers in Los Angeles', art:'stickers', from:'Your shop · Austin', source:'printer', to:'A shop · Los Angeles', machine:'printer', captions:['Your customer’s event is across the country.', 'OUTPUT finds a printer near the event.', 'The local shop makes the stickers near your customer.']},
        {name:'Your spare capacity', job:'300 stickers. Room on your printer.', art:'stickers', from:'Another print shop', source:'printer', to:'Your shop', machine:'printer', captions:['Another shop is booked. Your machine has room.', 'OUTPUT matches their job to your open time.', 'You make the job and turn spare capacity into income.']},
        {name:'A smaller run', job:'100 business cards', art:'cards', from:'Your shop', source:'computer', to:'A digital print shop', machine:'press', captions:['You have the design and need a print partner.', 'OUTPUT finds a digital press.', 'Your partner prints and trims the cards.']},
        {name:'A merch order', job:'100 printed T-shirts', art:'tshirts', from:'Your shop', source:'printer', to:'A screen-print shop', machine:'screenpress', captions:['You have the design, but no T-shirt press.', 'OUTPUT finds a shop that prints T-shirts.', 'Your partner prints the shirts. You keep the customer.']}
      ];
      let example = 0, phase = 0, active = false, timer;
      const brief = node('div', '', content); brief.className = 'tour-story-brief';
      const product = node('img', '', brief); product.alt = ''; product.width = 52; product.height = 48;
      const job = node('strong', '', brief); job.id = 'tour-story-job';
      const network = node('div', '', content); network.className = 'tour-network';
      network.setAttribute('role', 'img');
      const shops = [];
      for (const [index, [name, label]] of [['printer', 'Your shop'], ['output', 'OUTPUT'], ['printer', 'Print partner']].entries()) {
        if (index) { const dots = node('div', '', network); dots.className = 'tour-transfer'; for (let n=0;n<3;n++) node('i', '', dots); }
        const shop = node('div', '', network); shop.className = 'tour-network-shop';
        const img = node('img', '', shop); img.src = '/onboarding-' + name + '.webp'; img.alt = ''; img.width = 160; img.height = 160;
        if (name === 'output') node('b', 'OUTPUT', shop).className = 'tour-output-wordmark';
        const labelNode = node('span', label, shop); shops.push({shop, img, label:labelNode});
      }
      const caption = node('p', '', content); caption.className = 'tour-story-caption';
      const selector = node('div', '', content); selector.className = 'tour-story-selector';
      const previous = node('button', '‹', selector); previous.type = 'button'; previous.setAttribute('aria-label', 'Previous example');
      const current = node('span', '', selector); current.id = 'tour-story-example';
      const next = node('button', '›', selector); next.type = 'button'; next.setAttribute('aria-label', 'Next example');
      function renderStory() {
        const story = stories[example];
        product.src = '/onboarding-' + story.art + '.webp'; job.textContent = story.job;
        shops[0].img.src = '/onboarding-' + story.source + '.webp'; shops[0].label.textContent = story.from;
        shops[2].img.src = '/onboarding-' + story.machine + '.webp'; shops[2].label.textContent = story.to;
        shops.forEach((part, index) => { part.shop.dataset.active = String(index === phase); });
        network.dataset.example = String(example); network.dataset.phase = String(phase);
        network.setAttribute('aria-label', 'Illustrated example: ' + story.from + ' connects through OUTPUT to ' + story.to + '.');
        caption.textContent = story.captions[phase]; current.textContent = `${example + 1} / ${stories.length} · ${story.name}`;
      }
      function schedule() {
        clearTimeout(timer);
        if (active) timer = setTimeout(() => {
          if (phase === 2) { example = (example + 1) % stories.length; phase = 0; } else phase++;
          renderStory(); schedule();
        }, 3600);
      }
      function choose(direction) { example = (example + direction + stories.length) % stories.length; phase = 0; renderStory(); schedule(); }
      previous.onclick = () => choose(-1); next.onclick = () => choose(1);
      renderStory();
      motionControl(network, running => { active = running; schedule(); }, selector);
      selector.append(next);
      const link = node('a', 'Explore OUTPUT ↗', content); link.id = 'tour-output-link'; link.href = 'https://output.jeezlabs.io/'; link.target = '_blank'; link.rel = 'noopener noreferrer'; link.referrerPolicy = 'no-referrer';
    }
    const actions = node('div', '', content); actions.className = 'tour-actions';
    if (step > 0) button('Back', () => tour(step - 1), actions).id = 'tour-back';
    if (step < 2) { const skip = button('Skip tour', endTour, actions); skip.className = 'team-text-button tour-skip'; actions.prepend(skip); }
    button(step === 2 ? 'Start nesting' : step === 0 ? 'See how it works' : 'Next', () => step === 2 ? endTour() : tour(step + 1), actions, step !== 2).id = 'tour-next';
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
