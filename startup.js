(() => {
  'use strict';
  const visit = new URL(location.href), active = visit.searchParams.get('startup') === '1';
  let resolve;
  const revealed = new Promise(done => { resolve = done; });
  let root, rider, lane, gif, observer, frame = 0, last = 0, elapsed = 0, progress = 0;
  let ready = false, failed = false, finished = false, visible = true;
  const still = matchMedia('(prefers-reduced-motion: reduce)');
  function stop() { cancelAnimationFrame(frame); frame = 0; last = 0; }
  function finish() {
    if (finished) return;
    finished = true; stop();
    document.documentElement.removeAttribute('data-starting');
    observer?.disconnect(); observer = null;
    root?.remove(); root = rider = lane = gif = null;
    document.removeEventListener('keydown', blockInput, true);
    for (const name of ['dragover', 'drop']) document.removeEventListener(name, blockInput, true);
    resolve();
  }
  function draw() {
    if (rider) rider.style.transform = `translateX(${Math.max(0, lane.clientWidth - 68) * progress}px) scaleX(-1)`;
  }
  function tick(now) {
    const dt = last ? Math.min((now - last) / 1000, 1 / 30) : 0;
    last = now; elapsed += dt;
    const t = Math.min(1, elapsed / 4.2);
    progress = Math.min(ready ? 1 : .92, t * t * (3 - 2 * t));
    draw(); frame = 0;
    if (progress === 1 && ready) { finish(); return; }
    run();
  }
  function run() {
    if (root && !frame && visible && !document.hidden && !still.matches && !finished) frame = requestAnimationFrame(tick);
  }
  async function motion() {
    stop();
    if (!root || finished) return;
    if (still.matches) {
      try {
        const image = new Image(); image.src = '/startup-nesting.gif'; await image.decode();
        if (finished || !still.matches) return;
        const canvas = document.createElement('canvas'); canvas.width = 800; canvas.height = 800;
        canvas.getContext('2d').drawImage(image, 0, 0); gif.src = canvas.toDataURL();
      } catch { if (gif) gif.hidden = true; }
      if (finished) return;
      progress = ready ? 1 : .5; draw();
      if (ready) finish();
    } else { gif.src = '/startup-nesting.gif'; run(); }
  }
  window.EZNStartup = {
    get state() { return failed ? 'failed' : ready ? 'ready' : 'waiting'; },
    reveal() {
      ready = true;
      if (!active || still.matches) finish();
      else run();
      return revealed;
    },
    fail() { failed = true; finish(); }
  };
  if (!active) { finish(); return; }
  document.documentElement.dataset.starting = '1';
  visit.searchParams.delete('startup');
  history.replaceState(null, '', visit.pathname + visit.search + visit.hash);
  function blockInput(event) {
    if (!finished && (event.type !== 'keydown' || (!event.metaKey && !event.ctrlKey) || event.key === 'Enter')) {
      event.preventDefault(); event.stopImmediatePropagation();
    }
  }
  document.addEventListener('keydown', blockInput, true);
  for (const name of ['dragover', 'drop']) document.addEventListener(name, blockInput, true);
  function mount() {
    if (finished) return;
    root = document.createElement('section'); root.id = 'app-startup'; root.setAttribute('aria-label', 'EZNest loading');
    root.innerHTML = `<div class="startup-content"><div class="startup-scene" aria-hidden="true"><img src="/startup-nesting.gif" alt=""></div><div class="startup-lane" aria-hidden="true"><div class="startup-ground"></div><div class="startup-rider"><img src="/startup-companion.png" alt=""><svg class="startup-board" viewBox="0 0 56 18"><path d="M2 5Q7 9 13 8H44Q50 8 54 3" fill="none" stroke="#242727" stroke-width="3" stroke-linecap="round"/><path d="M14 9L15 14M42 9L41 14" stroke="#242727" stroke-width="2"/><circle cx="15" cy="14" r="3" fill="#3473ed" stroke="#242727" stroke-width="1.4"/><circle cx="41" cy="14" r="3" fill="#3473ed" stroke="#242727" stroke-width="1.4"/></svg></div></div><p class="startup-label" role="status">Loading</p></div>`;
    document.body.prepend(root);
    rider = root.querySelector('.startup-rider'); lane = root.querySelector('.startup-lane'); gif = root.querySelector('.startup-scene img');
    observer = new IntersectionObserver(entries => { visible = entries[entries.length - 1].isIntersecting; if (visible) run(); else stop(); });
    observer.observe(root);
    draw(); motion();
  }
  document.addEventListener('visibilitychange', () => { stop(); run(); });
  still.addEventListener('change', motion);
  window.addEventListener('resize', draw);
  window.addEventListener('pagehide', stop);
  window.addEventListener('pageshow', run);
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount, {once: true});
  else mount();
})();
