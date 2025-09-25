// Spotlight follow on glass cards
(function(){
  const cards = document.querySelectorAll('.glass-card');
  cards.forEach(card => {
    card.addEventListener('mousemove', (e) => {
      const rect = card.getBoundingClientRect();
      const x = ((e.clientX - rect.left) / rect.width) * 100;
      const y = ((e.clientY - rect.top) / rect.height) * 100;
      card.style.setProperty('--mx', x + '%');
      card.style.setProperty('--my', y + '%');
    }, {passive:true});
  });
})();

// Remove number skeletons shortly after load (data is server-rendered)
(function(){
  window.addEventListener('DOMContentLoaded', () => {
    setTimeout(() => {
      document.querySelectorAll('.skeleton[data-skel="number"]').forEach(el => el.classList.remove('skeleton'));
    }, 250);
  });
})();

// Ripple micro-interaction on cards (no inline JS)
(function(){
  const ROOT_SELECTOR = '.glass-card';
  document.querySelectorAll(ROOT_SELECTOR).forEach(el => el.classList.add('rippleable'));
  document.addEventListener('click', function(e){
    const target = e.target.closest('.rippleable');
    if(!target) return;
    const rect = target.getBoundingClientRect();
    const size = Math.max(rect.width, rect.height);
    const ripple = document.createElement('span');
    ripple.className = 'ripple';
    ripple.style.width = ripple.style.height = size + 'px';
    ripple.style.left = (e.clientX - rect.left - size/2) + 'px';
    ripple.style.top  = (e.clientY - rect.top  - size/2) + 'px';
    target.appendChild(ripple);
    ripple.addEventListener('animationend', () => ripple.remove());
  }, {passive:true});
})();

// Dashboard toast helper
(function(){
  window.showDashToast = function(message, variant){
    const toastEl = document.getElementById('dashToast');
    const bodyEl = document.getElementById('dashToastBody');
    if(!toastEl || !bodyEl) return;
    bodyEl.textContent = message || 'Updated.';
    // reset bg class; default to primary
    toastEl.className = 'toast align-items-center border-0 text-bg-' + (variant || 'primary');
    if (window.bootstrap && bootstrap.Toast){
      const t = bootstrap.Toast.getOrCreateInstance(toastEl, {delay: 2800});
      t.show();
    } else {
      toastEl.style.display = 'block';
      setTimeout(()=> toastEl.style.display='none', 2800);
    }
  };
})();

// Donut chart renderer (no external lib)
(function(){
  const el = document.getElementById('myRecordChart');
  const center = document.getElementById('myRecordCenter');
  const centerSub = document.getElementById('myRecordCenterSub');
  const legend = document.getElementById('myRecordLegend');
  const empty = document.getElementById('my-record-empty');
  const wrap = el ? el.parentElement : null;
  if(!el || !center || !centerSub) return;

  function readColors(){
    const root = document.documentElement;
    const cs = getComputedStyle(root);
    const primaryRgb = (cs.getPropertyValue('--bs-primary-rgb').trim() || '111,66,193');
    // Try a card background var if you have one; else fallback to body bg or white
    const cardBg = cs.getPropertyValue('--card-bg').trim();
    let gapColor = cardBg || getComputedStyle(document.body).backgroundColor || '#fff';
    if(!gapColor) gapColor = '#fff';
    return {
      cWin: `rgba(${primaryRgb},1)`,   cWinDim: `rgba(${primaryRgb},.25)`,
      cLoss: 'rgba(220,53,69,1)',      cLossDim: 'rgba(220,53,69,.25)',
      cTie:  'rgba(108,117,125,1)',    cTieDim:  'rgba(108,117,125,.25)',
      gapColor
    };
  }
  let COLORS = readColors();

  let wins = parseInt(el.dataset.wins || '0', 10) || 0;
  let losses = parseInt(el.dataset.losses || '0', 10) || 0;
  let ties = parseInt(el.dataset.ties || '0', 10) || 0;
  const total = wins + losses + ties;

  if (total === 0) {
    if (legend) legend.classList.add('d-none');
    if (wrap) wrap.style.display = 'none';
    if (empty) empty.style.display = '';
    return;
  } else {
    if (empty) empty.style.display = 'none';
  }
  if (wrap) wrap.style.display = '';

  const pWin = wins / total, pLoss = losses / total, pTie = 1 - pWin - pLoss;
  const winPct = pWin * 100, lossPct = (pWin + pLoss) * 100;

  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

  // animate-in
  const DURATION = 800; const start = performance.now();
  const easeOutCubic = t => 1 - Math.pow(1 - t, 3);
  function frame(now){
    const t = Math.min(1, (now - start) / DURATION); const e = easeOutCubic(t);
    const aWin = pWin * e * 100; const aLoss = (pWin + pLoss * e) * 100;
    el.style.background = `conic-gradient(${COLORS.cWin} 0% ${aWin}%, ${COLORS.cLoss} ${aWin}% ${aLoss}%, ${COLORS.cTie} ${aLoss}% 100%)`;
    center.textContent = String(Math.round(wins * e));
    if(t < 1){
      requestAnimationFrame(frame);
    } else {
      center.textContent = String(wins);
      if (legend) {
        legend.classList.remove('d-none');
        legend.style.removeProperty('display');
      }
      if (wrap)  wrap.classList.remove('skeleton');
      initHover();
      initTooltips();
    }
  }
  requestAnimationFrame(frame);

  function drawNormal(){
    el.style.background = `conic-gradient(${COLORS.cWin} 0% ${winPct}%, ${COLORS.cLoss} ${winPct}% ${lossPct}%, ${COLORS.cTie} ${lossPct}% 100%)`;
  }
  function setSub(key){ centerSub.textContent = key==='win'?'Wins':(key==='loss'?'Losses':'Ties'); }

  function drawEmphasis(key){
    const G = 0.8;
    if(key === 'win'){
      const s = clamp(0 + G, 0, 100), e = clamp(winPct - G, s, 100);
      el.style.background = `conic-gradient(${COLORS.gapColor} 0% ${G}%, ${COLORS.cWin} ${s}% ${e}%, ${COLORS.gapColor} ${e}% ${e+G}%, ${COLORS.cLossDim} ${e+G}% ${lossPct}%, ${COLORS.cTieDim} ${lossPct}% 100%)`;
    } else if(key === 'loss'){
      const s = clamp(winPct + G, 0, 100), e = clamp(lossPct - G, s, 100);
      el.style.background = `conic-gradient(${COLORS.cWinDim} 0% ${winPct}%, ${COLORS.gapColor} ${winPct}% ${winPct+G}%, ${COLORS.cLoss} ${s}% ${e}%, ${COLORS.gapColor} ${e}% ${e+G}%, ${COLORS.cTieDim} ${e+G}% 100%)`;
    } else {
      const s = clamp(lossPct + G, 0, 100), e = clamp(100 - G, s, 100);
      el.style.background = `conic-gradient(${COLORS.cWinDim} 0% ${winPct}%, ${COLORS.cLossDim} ${winPct}% ${lossPct}%, ${COLORS.gapColor} ${lossPct}% ${lossPct+G}%, ${COLORS.cTie} ${s}% ${e}%, ${COLORS.gapColor} ${e}% 100%)`;
    }
  }

  function attachHoverHandlers(node, key){
    node.addEventListener('mouseenter', ()=>{ if(wrap) wrap.classList.add('hovering'); drawEmphasis(key); center.textContent = String(key==='win'?wins:key==='loss'?losses:ties); setSub(key); });
    node.addEventListener('mouseleave', ()=>{ if(wrap) wrap.classList.remove('hovering'); drawNormal(); center.textContent = String(wins); setSub('win'); });
    node.addEventListener('focus',     ()=>{ if(wrap) wrap.classList.add('hovering'); drawEmphasis(key); center.textContent = String(key==='win'?wins:key==='loss'?losses:ties); setSub(key); });
    node.addEventListener('blur',      ()=>{ if(wrap) wrap.classList.remove('hovering'); drawNormal(); center.textContent = String(wins); setSub('win'); });
  }

  function initTooltips(){
    if(!legend) return;
    const totalLocal = total || 1;
    const pct = v => Math.round((v/totalLocal)*100);
    legend.querySelectorAll('.legend-item').forEach(it => {
      const key = it.dataset.key;
      const count = key==='win'?wins:key==='loss'?losses:ties;
      const text = key==='win'?'Wins':(key==='loss'?'Losses':'Ties');
      it.setAttribute('title', `${count} ${text} (${pct(count)}%)`);
      if (window.bootstrap && bootstrap.Tooltip){
        new bootstrap.Tooltip(it, {container: 'body'});
      }
    });
  }

  function initHover(){
    if(legend){
      legend.querySelectorAll('.legend-item').forEach(it => attachHoverHandlers(it, it.dataset.key));
    }
    const arcWin  = document.getElementById('arc-win');
    const arcLoss = document.getElementById('arc-loss');
    const arcTie  = document.getElementById('arc-tie');
    if(arcWin && arcLoss && arcTie){
      const r = 40; const C = 2 * Math.PI * r;
      const lenWin = C * (pWin); const lenLoss = C * (pLoss); const lenTie = C * (pTie);
      arcWin.setAttribute('stroke-dasharray', `${lenWin} ${C - lenWin}`);
      arcWin.setAttribute('stroke-dashoffset', '0');
      arcLoss.setAttribute('stroke-dasharray', `${lenLoss} ${C - lenLoss}`);
      arcLoss.setAttribute('stroke-dashoffset', `-${lenWin}`);
      arcTie.setAttribute('stroke-dasharray', `${lenTie} ${C - lenTie}`);
      arcTie.setAttribute('stroke-dashoffset', `-${lenWin + lenLoss}`);
      arcWin.setAttribute('stroke', 'rgba(0,0,0,0)');
      arcLoss.setAttribute('stroke', 'rgba(0,0,0,0)');
      arcTie.setAttribute('stroke', 'rgba(0,0,0,0)');
      attachHoverHandlers(arcWin,  'win');
      attachHoverHandlers(arcLoss, 'loss');
      attachHoverHandlers(arcTie,  'tie');
    }
  }

  // Recompute colors once CSS is applied
  window.addEventListener('DOMContentLoaded', () => { COLORS = readColors(); });
  // Redraw with new colors on theme change
  document.addEventListener('themeChanged', () => { COLORS = readColors(); drawNormal(); });
})();