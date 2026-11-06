(() => {
  'use strict';
  const visit = new URL(location.href), active = visit.searchParams.get('startup') === '1';
  const duration = 5, holdAt = 4.6;
  let resolve;
  const revealed = new Promise(done => { resolve = done; });
  let root, rider, lane, video, observer, frame = 0, last = 0, lastMedia = 0, stalled = 0, progress = 0;
  let ready = false, failed = false, finished = false, visible = true, held = false, visualDone = false, ending = false, playRequested = false;
  const still = matchMedia('(prefers-reduced-motion: reduce)');
  function stop() { cancelAnimationFrame(frame); frame = 0; last = 0; ending = false; video?.pause(); }
  function finish() {
    if (finished) return;
    finished = true; stop();
    document.documentElement.removeAttribute('data-starting');
    observer?.disconnect(); observer = null;
    if (video) { video.onerror = null; video.onended = null; video.removeAttribute('src'); video.load(); }
    root?.remove(); root = rider = lane = video = null;
    document.removeEventListener('keydown', blockInput, true);
    for (const name of ['dragover', 'drop']) document.removeEventListener(name, blockInput, true);
    resolve();
  }
  function draw() {
    if (rider) rider.style.transform = `translateX(${Math.max(0, lane.clientWidth - 68) * progress}px) scaleX(-1)`;
  }
  function revealEnd() {
    if (!ready || !visualDone || finished || ending) return;
    cancelAnimationFrame(frame);
    progress = 1; draw(); ending = true;
    // Paint the last nesting frame and the rider at the right edge before reveal.
    frame = requestAnimationFrame(() => { frame = requestAnimationFrame(finish); });
  }
  function posterOnly() {
    stop();
    if (video) { video.onerror = null; video.removeAttribute('src'); video.load(); }
    visualDone = true; held = false; progress = ready ? 1 : .5; draw();
    if (ready) finish();
  }
  function tick(now) {
    frame = 0;
    if (!video || finished || ending) return;
    const time = video.currentTime;
    stalled = time > lastMedia + .001 ? 0 : stalled + (last ? (now - last) / 1000 : 0);
    last = now; lastMedia = time;
    if (!ready && time >= holdAt) {
      video.pause(); held = true;
      if (time > holdAt + .05) video.currentTime = holdAt;
      progress = Math.min(time, holdAt) / duration; draw(); last = 0; return;
    }
    progress = Math.min(1, time / duration); draw();
    if (video.ended) { visualDone = true; revealEnd(); return; }
    if (stalled >= 8) { posterOnly(); return; }
    run();
  }
  function run() {
    if (!root || finished || ending || !visible || document.hidden || still.matches) return;
    if (visualDone) { revealEnd(); return; }
    if (held && !ready) return;
    if (held) { held = false; stalled = 0; last = 0; }
    if (video.paused && !playRequested) {
      playRequested = true;
      video.play().catch(error => { if (!finished && error.name !== 'AbortError') posterOnly(); }).finally(() => { playRequested = false; });
    }
    if (!frame) frame = requestAnimationFrame(tick);
  }
  function motion() {
    stop();
    if (!root || finished) return;
    if (still.matches) posterOnly();
    else {
      visualDone = false; held = false; stalled = 0; lastMedia = 0;
      video.src = '/startup-nesting.mp4'; video.onerror = posterOnly;
      run();
    }
  }
  window.EZNStartup = {
    get state() { return failed ? 'failed' : ready ? 'ready' : 'waiting'; },
    reveal() { ready = true; if (!active || still.matches) finish(); else run(); return revealed; },
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
    root.innerHTML = `<div class="startup-content"><div class="startup-scene" aria-hidden="true"><video poster="/startup-nesting-poster.png" muted playsinline preload="auto"></video></div><div class="startup-lane" aria-hidden="true"><div class="startup-ground"></div><div class="startup-rider"><img src="/startup-companion.png" alt=""><svg class="startup-board" viewBox="0 0 56 18"><path d="M2 5Q7 9 13 8H44Q50 8 54 3" fill="none" stroke="#242727" stroke-width="3" stroke-linecap="round"/><path d="M14 9L15 14M42 9L41 14" stroke="#242727" stroke-width="2"/><circle cx="15" cy="14" r="3" fill="#3473ed" stroke="#242727" stroke-width="1.4"/><circle cx="41" cy="14" r="3" fill="#3473ed" stroke="#242727" stroke-width="1.4"/></svg></div></div><p class="startup-label" role="status">Loading</p></div>`;
    document.body.prepend(root);
    rider = root.querySelector('.startup-rider'); lane = root.querySelector('.startup-lane'); video = root.querySelector('video'); video.muted = true;
    video.onended = () => { if (!ready) { held = true; video.currentTime = holdAt; progress = holdAt / duration; draw(); } else { visualDone = true; revealEnd(); } };
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
