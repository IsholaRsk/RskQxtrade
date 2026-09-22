/* Ghost rskIA · Sessions SMC — moteur front-end (marché simulé + SMC + sessions) */
'use strict';

/* ═══════════ 1. ÉTAT LOCAL (persistant, synchronisé au serveur si dispo) ═══════════ */
const LS = 'ghost_sessions_v1';
const DEF = { uid: null, since: null, accounts: [], sessions: [], filleuls: [],
              ref_code: null, referred_by: null, ref_balance: 0, demo_done: 0 };
let S = { ...DEF, ...(JSON.parse(localStorage.getItem(LS) || '{}')) };
const save = () => localStorage.setItem(LS, JSON.stringify(S));

if (!S.uid) {
  const tg = window.Telegram?.WebApp?.initDataUnsafe?.user;
  S.uid = tg ? 'tg_' + tg.id : 'inv_' + Math.random().toString(36).slice(2, 10);
  S.ref_code = S.uid.replace(/^(tg_|inv_)/, '').slice(0, 8);
  S.since = new Date().toISOString().slice(0, 10);
  save();
}
const REF_LINK = `https://t.me/Ghost_rskia_bot?start=${S.ref_code}`;

/* Sync serveur optionnelle (Upstash) — silencieuse si hors-ligne */
const api = (r, opts = {}) =>
  fetch(`/api/gs?r=${r}&uid=${encodeURIComponent(S.uid)}`, {
    method: opts.body ? 'POST' : 'GET',
    headers: { 'Content-Type': 'application/json',
               'X-Telegram-Init': window.Telegram?.WebApp?.initData || '' },
    body: opts.body ? JSON.stringify(opts.body) : undefined
  }).then(r2 => r2.json()).catch(() => ({ offline: true }));

/* Attribution de parrainage (1 fois, via ?ref= ou start_param) */
(() => {
  const ref = new URLSearchParams(location.search).get('ref')
           || window.Telegram?.WebApp?.initDataUnsafe?.start_param;
  if (ref && ref !== S.ref_code && !S.referred_by) {
    S.referred_by = ref; save();
    api('join', { body: { ref } }).catch(() => {});
  }
})();

/* ═══════════ 2. MARCHÉ SIMULÉ (random walk en régimes, seedé par jour) ═══════════ */
const SPECS = {
  'EUR/USD': { p0: 1.0845, vol: 0.00045, pip: 0.0001, pipVal: 10, dec: 5 },
  'GBP/USD': { p0: 1.2720, vol: 0.00055, pip: 0.0001, pipVal: 10, dec: 5 },
  'XAU/USD': { p0: 2384.50, vol: 1.15,    pip: 0.1,    pipVal: 1,  dec: 2 },
  'BTC/USD': { p0: 64800,   vol: 95,      pip: 1,      pipVal: 1,  dec: 0 },
  'USD/JPY': { p0: 156.40,  vol: 0.075,   pip: 0.01,   pipVal: 6.8, dec: 3 }
};
const SYMBOLS = Object.keys(SPECS);

function mulberry(seed) {
  return () => {
    seed |= 0; seed = (seed + 0x6D2B79F5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function genCandles(symbol, n = 160, startIdx = 0) {
  const spec = SPECS[symbol];
  const rng = mulberry([...symbol + new Date().toISOString().slice(0, 10)]
    .reduce((a, c) => a * 31 + c.charCodeAt(0), 7) + startIdx);
  const out = []; let p = spec.p0 * (1 + (rng() - 0.5) * 0.01);
  for (let i = 0; i < n; i++) {
    const regime = Math.sin((i + startIdx) / 23) * 0.6 + (rng() - 0.5) * 0.8;
    const o = p;
    const drift = regime * spec.vol * 0.9;
    const c = o + drift + (rng() - 0.5) * spec.vol * 2;
    const h = Math.max(o, c) + rng() * spec.vol * 0.9;
    const l = Math.min(o, c) - rng() * spec.vol * 0.9;
    out.push({ o, h, l, c, v: 50 + rng() * 450 });
    p = c;
  }
  return out;
}

/* ═══════════ 3. DÉTECTEUR SMC (structure, OB, FVG, sweep) ═══════════ */
function swings(cs, k = 2) {
  const hi = [], lo = [];
  for (let i = k; i < cs.length - k; i++) {
    const seg = cs.slice(i - k, i + k + 1);
    if (cs[i].h === Math.max(...seg.map(c => c.h))) hi.push({ i, p: cs[i].h });
    if (cs[i].l === Math.min(...seg.map(c => c.l))) lo.push({ i, p: cs[i].l });
  }
  return { hi, lo };
}

function smcScan(cs) {
  const sw = swings(cs), last = cs[cs.length - 1];
  const sh = sw.hi.slice(-3), sl = sw.lo.slice(-3);
  let structure = 'range', bos = null, choch = null;
  if (sh.length >= 2 && sl.length >= 2) {
    const hh = sh[sh.length - 1].p > sh[sh.length - 2].p;
    const hl = sl[sl.length - 1].p > sl[sl.length - 2].p;
    const lh = sh[sh.length - 1].p < sh[sh.length - 2].p;
    const ll = sl[sl.length - 1].p < sl[sl.length - 2].p;
    if (hh && hl) structure = 'haussier'; else if (lh && ll) structure = 'baissier';
    if (sh.length >= 2 && last.c > sh[sh.length - 1].p && structure !== 'baissier') bos = 'BOS haussier';
    if (sl.length >= 2 && last.c < sl[sl.length - 1].p && structure !== 'haussier') bos = 'BOS baissier';
    if (structure === 'haussier' && sl.length && last.c < sl[sl.length - 1].p) choch = 'CHoCH baissier';
    if (structure === 'baissier' && sh.length && last.c > sh[sh.length - 1].p) choch = 'CHoCH haussier';
  }
  /* Order block : dernière bougie inverse avant impulsion cassant la structure */
  let ob = null;
  for (let i = cs.length - 3; i > Math.max(0, cs.length - 40); i--) {
    const body = Math.abs(cs[i + 1].c - cs[i + 1].o);
    const avg = cs.slice(Math.max(0, i - 8), i + 1).reduce((a, c) => a + Math.abs(c.c - c.o), 0) / 9;
    if (body > avg * 1.6) {
      const bull = cs[i + 1].c > cs[i + 1].o, prev = cs[i];
      if (bull && prev.c < prev.o) { ob = { type: 'OB haussier', lo: prev.l, hi: Math.max(prev.o, prev.c), dir: 'BUY' }; break; }
      if (!bull && prev.c > prev.o) { ob = { type: 'OB baissier', hi: prev.h, lo: Math.min(prev.o, prev.c), dir: 'SELL' }; break; }
    }
  }
  /* FVG : vide entre mèches de i-1 et i+1 */
  let fvg = null;
  for (let i = cs.length - 2; i > Math.max(1, cs.length - 25); i--) {
    if (cs[i + 1].l > cs[i - 1].h) { fvg = { type: 'FVG haussier', lo: cs[i - 1].h, hi: cs[i + 1].l, dir: 'BUY' }; break; }
    if (cs[i + 1].h < cs[i - 1].l) { fvg = { type: 'FVG baissier', hi: cs[i - 1].l, lo: cs[i + 1].h, dir: 'SELL' }; break; }
  }
  /* Sweep : mèche au-delà du dernier swing puis clôture à l'intérieur */
  let sweep = null;
  if (sh.length && last.h > sh[sh.length - 1].p && last.c < sh[sh.length - 1].p) sweep = 'Sweep des highs';
  if (sl.length && last.l < sl[sl.length - 1].p && last.c > sl[sl.length - 1].p) sweep = 'Sweep des lows';

  /* Setup : prix rentré dans la zone OB + confluence FVG + sens structure */
  let signal = null;
  if (ob && structure === (ob.dir === 'BUY' ? 'haussier' : 'baissier')) {
    const inZone = last.c >= ob.lo && last.c <= ob.hi * 1.0005;
    const conf = fvg && fvg.dir === ob.dir;
    if (inZone && (conf || sweep)) {
      signal = { dir: ob.dir, ob: ob.type, fvg: fvg?.type || null, sweep,
                 reason: `${ob.type} · ${conf ? 'confluence FVG' : 'après ' + (sweep || 'sweep')}` };
    }
  }
  return { structure, bos, choch, ob, fvg, sweep, signal, price: last.c };
}

/* ═══════════ 4. SESSIONS & TRADES ═══════════ */
const DAY = new Date().toISOString().slice(0, 10);
const todaySessions = () => S.sessions.filter(s => s.day === DAY);
const todayTrades = () => todaySessions().reduce((a, s) => a + s.trades.length, 0);
const active = () => S.sessions.find(s => s.status === 'active');

let LV = { cs: [], tick: 0, timer: null };
const CANDLE_MS = 4000;

function launchSession(cfg) {
  const s = { id: 's' + Date.now(), day: DAY, ...cfg, mode: 'demo', status: 'active',
              opened_at: new Date().toTimeString().slice(0, 5), trades: [], pnl_total: 0 };
  S.sessions.push(s); save();
  api('session', { body: s });
  return s;
}

function openTrade(s, sig) {
  const spec = SPECS[s.symbol];
  const entry = sig.price;
  const sl = sig.dir === 'BUY' ? entry - s.slPts * spec.pip : entry + s.slPts * spec.pip;
  const tp = sig.dir === 'BUY' ? entry + s.tpPts * spec.pip : entry - s.tpPts * spec.pip;
  const t = { id: 't' + Date.now(), direction: sig.dir, entry, sl, tp, lot: s.lot,
              status: 'open', pnl: 0,
              smc: { structure: sig.structure, bos: sig.bos, choch: sig.choch,
                     ob: sig.signal.ob, fvg: sig.signal.fvg, sweep: sig.signal.sweep,
                     reason: sig.signal.reason } };
  s.trades.push(t); save();
  api('trade', { body: { session_id: s.id, direction: t.direction, entry, sl, tp, lot: t.lot } });
  toast(`${sig.dir === 'BUY' ? 'ACHAT' : 'VENTE'} ouvert · ${sig.signal.reason}`, 'ok');
  return t;
}

function closeTrade(s, t, price, won) {
  const spec = SPECS[s.symbol];
  const pts = Math.abs(price - t.entry) / spec.pip;
  t.pnl = +(won ? pts * spec.pipVal * t.lot : -pts * spec.pipVal * t.lot).toFixed(2);
  t.status = won ? 'tp' : 'sl'; t.exit = price;
  t.closed_at = new Date().toTimeString().slice(0, 5);
  if (!s.trades.some(x => x.status === 'open') && s.trades.length >= s.maxTrades) {
    s.status = 'terminee';
    s.pnl_total = +s.trades.reduce((a, x) => a + x.pnl, 0).toFixed(2);
    S.demo_done = Math.min(S.demo_done + 1, 999);
    toast(`Session terminée · PnL ${s.pnl_total >= 0 ? '+' : ''}${s.pnl_total} $`, s.pnl_total >= 0 ? 'ok' : 'ko');
  } else {
    toast(`${won ? 'TP' : 'SL'} touché sur ${s.symbol} (${t.pnl >= 0 ? '+' : ''}${t.pnl} $)`, won ? 'ok' : 'ko');
  }
  save();
  api('trade_close', { body: { session_id: s.id, trade_id: t.id, result: t.status, exit: price, pnl: t.pnl } });
}

/* Boucle live : nouvelle bougie toutes les 4 s, gestion TP/SL puis recherche d'entrée */
function liveTick() {
  const s = active(); if (!s) return;
  const spec = SPECS[s.symbol];
  LV.tick++;
  const last = LV.cs[LV.cs.length - 1];
  if (LV.tick % 4 === 1) {                       // prolonge la bougie en cours
    last.c += (Math.random() - 0.5) * spec.vol * 0.8;
    last.h = Math.max(last.h, last.c); last.l = Math.min(last.l, last.c);
  } else if (LV.tick % 4 === 0) {                // clôture et nouvelle bougie
    LV.cs.push({ o: last.c, h: last.c * 1.0001, l: last.c * 0.9999, c: last.c, v: 80 + Math.random() * 400 });
    if (LV.cs.length > 220) LV.cs.shift();
  }
  /* TP / SL */
  for (const t of s.trades.filter(x => x.status === 'open')) {
    if (t.direction === 'BUY') {
      if (last.l <= t.sl) closeTrade(s, t, t.sl, false);
      else if (last.h >= t.tp) closeTrade(s, t, t.tp, true);
    } else {
      if (last.h >= t.sl) closeTrade(s, t, t.sl, false);
      else if (last.l <= t.tp) closeTrade(s, t, t.tp, true);
    }
  }
  /* Nouveau signal si aucun trade ouvert et session non pleine */
  if (s.status === 'active' && !s.trades.some(t => t.status === 'open') && s.trades.length < s.maxTrades) {
    const sig = smcScan(LV.cs.slice(0, -1));
    if (sig.signal) openTrade(s, sig);
    LV.lastCtx = sig;
  }
  renderLive();
}

/* ═══════════ 5. GRAPHIQUE ═══════════ */
function drawChart() {
  const cv = document.getElementById('chart'), ctx = cv.getContext('2d');
  const cs = LV.cs.slice(-70); if (!cs.length) return;
  const W = cv.width, H = cv.height, VH = 60;
  ctx.clearRect(0, 0, W, H + VH);
  const hi = Math.max(...cs.map(c => c.h)), lo = Math.min(...cs.map(c => c.l));
  const span = (hi - lo) || 1e-9;
  const Y = p => 12 + (hi - p) / span * (H - 24);
  const bw = W / cs.length;
  cs.forEach((c, i) => {
    const up = c.c >= c.o, x = i * bw;
    ctx.strokeStyle = ctx.fillStyle = up ? '#34d399' : '#fb7185';
    ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(x + bw / 2, Y(c.h)); ctx.lineTo(x + bw / 2, Y(c.l)); ctx.stroke();
    const yo = Y(c.o), yc = Y(c.c);
    ctx.fillRect(x + 1, Math.min(yo, yc), Math.max(bw - 2, 1), Math.max(Math.abs(yc - yo), 1));
    const vmax = 500, vh = c.v / vmax * (VH - 8);
    ctx.fillStyle = 'rgba(70,95,140,.5)';
    ctx.fillRect(x + 1, H + VH - vh, Math.max(bw - 2, 1), vh);
  });
  /* niveaux SL/TP des trades ouverts */
  const s = active();
  if (s) for (const t of s.trades.filter(x => x.status === 'open')) {
    ctx.setLineDash([5, 4]); ctx.lineWidth = 1;
    ctx.strokeStyle = '#fb7185'; ctx.beginPath(); ctx.moveTo(0, Y(t.sl)); ctx.lineTo(W, Y(t.sl)); ctx.stroke();
    ctx.strokeStyle = '#34d399'; ctx.beginPath(); ctx.moveTo(0, Y(t.tp)); ctx.lineTo(W, Y(t.tp)); ctx.stroke();
    ctx.strokeStyle = '#67e8f9'; ctx.beginPath(); ctx.moveTo(0, Y(t.entry)); ctx.lineTo(W, Y(t.entry)); ctx.stroke();
    ctx.setLineDash([]);
  }
  ctx.fillStyle = '#8a93b1'; ctx.font = '11px system-ui';
  ctx.fillText(hi.toFixed(SPECS[active()?.symbol || 'XAU/USD'].dec), W - 58, 14);
  ctx.fillText(lo.toFixed(SPECS[active()?.symbol || 'XAU/USD'].dec), W - 58, H - 6);
}

/* ═══════════ 6. RENDU UI ═══════════ */
const $ = id => document.getElementById(id);
const f2 = n => (n >= 0 ? '+' : '') + Number(n).toFixed(2);

function toast(msg, kind = '') {
  const d = document.createElement('div');
  d.className = `toast ${kind}`; d.textContent = msg;
  document.body.appendChild(d);
  setTimeout(() => d.remove(), 2600);
}

function renderStats() {
  const cal = Math.min(S.demo_done, 3);
  $('stats').innerHTML = [
    [`${cal}/3`, 'Calibration<br>sessions'],
    [`${todayTrades()}/15`, "Trades<br>aujourd'hui"],
    [`${todaySessions().length}/3`, "Sessions<br>aujourd'hui"],
    ['Démo', 'Mode']
  ].map(([b, s]) => `<div class="stat"><b>${b}</b><span>${s}</span></div>`).join('');
  $('pf-cal').textContent = `${cal}/3 sessions démo`;
}

function renderAccounts() {
  const sel = $('f-account');
  if (!S.accounts.length) {
    sel.innerHTML = '<option>— Aucun compte —</option>';
    $('no-account').style.display = 'block';
    $('btn-launch').disabled = true;
  } else {
    sel.innerHTML = S.accounts.map(a => `<option value="${a.id}">${a.label} · ${a.login}</option>`).join('');
    $('no-account').style.display = 'none';
    $('btn-launch').disabled = false;
  }
  $('pf-accs').innerHTML = S.accounts.length
    ? S.accounts.map(a => `<div class="acc"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#67e8f9" stroke-width="2"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 10h18"/></svg><div><b>${a.label}</b><div class="note">${a.login} · ${a.server} · démo locale</div></div></div>`).join('')
    : '<div class="empty">Aucun compte enregistré.</div>';
}

function renderLive() {
  const s = active();
  $('lv-empty').classList.toggle('hidden', !!s);
  $('btn-stop').style.display = s ? 'block' : 'none';
  if (!s) { $('lv-trades').innerHTML = ''; $('lv-context').innerHTML = ''; return; }
  $('lv-title').textContent = `${s.symbol} · ${s.tf}`;
  $('lv-status').textContent = 'En cours';
  $('lv-count').textContent = `${s.trades.filter(t => t.status !== 'open').length}/${s.maxTrades} trades`;
  drawChart();
  const ctx = LV.lastCtx;
  $('lv-context').innerHTML = ctx ? [
    ctx.structure && `<span class="badge ob">${ctx.structure}</span>`,
    (ctx.bos || ctx.choch) && `<span class="badge">${ctx.bos || ctx.choch}</span>`,
    ctx.ob && `<span class="badge ob">${ctx.ob.type}</span>`,
    ctx.fvg && `<span class="badge fvg">${ctx.fvg.type}</span>`,
    ctx.sweep && `<span class="badge sw">${ctx.sweep}</span>`
  ].filter(Boolean).join('') : '';
  const spec = SPECS[s.symbol];
  $('lv-trades').innerHTML = s.trades.length ? s.trades.map(t => {
    let pnl = t.pnl;
    if (t.status === 'open' && LV.cs.length) {
      const cur = LV.cs[LV.cs.length - 1].c;
      const dir = t.direction === 'BUY' ? 1 : -1;
      pnl = +(((cur - t.entry) / spec.pip) * dir * spec.pipVal * t.lot).toFixed(2);
    }
    const tag = t.status === 'open' ? '<span class="badge sw">ouvert</span>'
              : t.status === 'tp' ? '<span class="badge ob">TP</span>' : '<span class="badge">SL</span>';
    return `<div class="trade">
      <span class="dir ${t.direction}">${t.direction === 'BUY' ? 'ACHAT' : 'VENTE'}</span>
      <div><b>${t.entry.toFixed(spec.dec)}</b><div class="note">SL ${t.sl.toFixed(spec.dec)} · TP ${t.tp.toFixed(spec.dec)}</div>
      <div class="note">${t.smc?.reason || ''}</div></div>
      ${tag}<span class="pnl ${pnl >= 0 ? 'up' : 'dn'}">${f2(pnl)} $</span></div>`;
  }).reverse().join('') : '<div class="empty">En attente d\'un setup SMC…</div>';
}

function renderHistory() {
  const done = S.sessions.filter(s => s.status === 'terminee');
  const wins = done.filter(s => s.pnl_total > 0).length;
  const tot = done.reduce((a, s) => a + s.pnl_total, 0);
  $('hi-stats').innerHTML = `
    <div class="stat"><b>${done.length}</b><span>Sessions terminées</span></div>
    <div class="stat" style="margin-top:0"><b class="${tot >= 0 ? '' : ''}" style="color:${tot >= 0 ? 'var(--ok)' : 'var(--ko)'}">${f2(tot)} $</b><span>PnL cumulé (démo)</span></div>`;
  $('hi-list').innerHTML = done.length ? done.map(s => {
    const spec = SPECS[s.symbol];
    return `<div class="trade" style="display:block">
      <div style="display:flex;align-items:center;gap:8px">
        <b>${s.symbol}</b><span class="badge">${s.tf}</span>
        <span class="badge">${s.trades.length} trades</span>
        <span class="badge">${s.day}</span>
        <span class="pnl ${s.pnl_total >= 0 ? 'up' : 'dn'}" style="margin-left:auto">${f2(s.pnl_total)} $</span>
      </div>
      <div style="margin-top:8px">${s.trades.map(t =>
        `<div class="note" style="padding:3px 0">${t.direction === 'BUY' ? 'ACHAT' : 'VENTE'} @ ${t.entry.toFixed(spec.dec)} → ${t.status === 'tp' ? 'TP' : 'SL'} · <b style="color:${t.pnl >= 0 ? 'var(--ok)' : 'var(--ko)'}">${f2(t.pnl)} $</b></div>`
      ).join('')}</div></div>`;
  }).reverse().join('') : '<div class="empty">Aucune session pour le moment.</div>';
}

function renderRef() {
  $('ref-link').value = REF_LINK;
  const qual = S.filleuls.filter(f => f.qualified).length;
  $('ref-stats').innerHTML = [
    [S.filleuls.length, 'Filleuls'], [qual, 'Qualifiés'], [f2(S.ref_balance) + ' $', 'Solde']
  ].map(([b, s]) => `<div class="stat"><b>${b}</b><span>${s}</span></div>`).join('');
  $('ref-list').innerHTML = S.filleuls.length
    ? S.filleuls.map(f => `<div class="acc">${f.uid} <span class="badge ${f.qualified ? 'ob' : ''}" style="margin-left:auto">${f.qualified ? 'qualifié' : 'inscrit'}</span></div>`).join('')
    : '<div class="empty">Aucun filleul pour le moment.</div>';
}

function renderProfile() {
  $('pf-uid').textContent = S.uid.startsWith('tg_') ? `Telegram #${S.uid.slice(3)}` : `Invité ${S.uid.slice(4)}`;
  $('pf-since').textContent = S.since;
  const ok = '<svg viewBox="0 0 24 24" fill="none" stroke="var(--ok)" stroke-width="2.5" stroke-linecap="round"><path d="M20 6 9 17l-5-5"/></svg>';
  const wait = '<svg viewBox="0 0 24 24" fill="none" stroke="var(--muted)" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="9"/></svg>';
  const items = [
    [`${Math.min(S.demo_done, 3)} sessions démo terminées`, S.demo_done >= 3],
    ['Plafonds de risque respectés', true],
    ['Compte réel débloqué (bientôt)', false]
  ];
  $('pf-checklist').innerHTML = '<label style="margin-top:14px">Checklist calibration</label>' +
    items.map(([t, okk]) => `<div class="check">${okk ? ok : wait}<span>${t}</span></div>`).join('');
}

function renderAll() {
  renderStats(); renderAccounts(); renderLive(); renderHistory(); renderRef(); renderProfile();
}

/* ═══════════ 7. ÉVÉNEMENTS ═══════════ */
document.querySelectorAll('nav button').forEach(b => b.addEventListener('click', () => {
  document.querySelectorAll('nav button').forEach(x => x.classList.remove('on'));
  b.classList.add('on');
  document.querySelectorAll('section').forEach(x => x.classList.add('hidden'));
  $('tab-' + b.dataset.tab).classList.remove('hidden');
  renderAll();
}));

let selSymbol = 'XAU/USD';
$('f-symbol').innerHTML = SYMBOLS.map(sym =>
  `<div class="chip ${sym === selSymbol ? 'on' : ''}" data-v="${sym}">${sym}</div>`).join('');
$('f-symbol').querySelectorAll('.chip').forEach(c => c.addEventListener('click', () => {
  $('f-symbol').querySelectorAll('.chip').forEach(x => x.classList.remove('on'));
  c.classList.add('on'); selSymbol = c.dataset.v;
}));

let selTF = 'M5';
$('f-tf').querySelectorAll('div').forEach(c => c.addEventListener('click', () => {
  $('f-tf').querySelectorAll('div').forEach(x => x.classList.remove('on'));
  c.classList.add('on'); selTF = c.dataset.v;
}));

$('btn-analyze').addEventListener('click', () => {
  const cs = genCandles(selSymbol, 160, Math.floor(Math.random() * 40));
  const r = smcScan(cs);
  const spec = SPECS[selSymbol];
  const row = (k, v) => `<div class="kpi"><span>${k}</span><b>${v || '—'}</b></div>`;
  $('analysis').innerHTML = `
    ${row('Structure', r.structure)}
    ${row('Signal récent', r.choch || r.bos || 'aucun')}
    ${row('Zone (OB)', r.ob ? r.ob.type : null)}
    ${row('Confluence', r.fvg ? r.fvg.type : null)}
    ${row('Liquidité', r.sweep)}
    ${r.signal
      ? `<div style="margin:10px 0;padding:11px;border-radius:12px;background:linear-gradient(135deg,rgba(37,99,235,.25),rgba(34,197,94,.18));border:1px solid rgba(6,182,212,.4)">
          <b style="color:${r.signal.dir === 'BUY' ? 'var(--ok)' : 'var(--ko)'}">${r.signal.dir === 'BUY' ? 'Setup ACHAT' : 'Setup VENTE'}</b>
          <div class="note" style="margin-top:4px">${r.signal.reason} · prix ${cs[cs.length - 1].c.toFixed(spec.dec)}</div></div>`
      : '<p class="note" style="margin-top:8px">Pas de setup propre — discipline : on attend la zone.</p>'}`;
  $('analysis').classList.remove('hidden');
});

$('btn-launch').addEventListener('click', () => {
  if (active()) return toast('Une session est déjà en cours.', 'ko');
  if (todaySessions().length >= 3) return toast('Plafond atteint : 3 sessions par jour.', 'ko');
  const cfg = {
    account: $('f-account').value, symbol: selSymbol, tf: selTF,
    lot: Math.max(0.01, parseFloat($('f-lot').value) || 0.01),
    maxTrades: Math.min(5, Math.max(1, parseInt($('f-max').value) || 3)),
    slPts: Math.max(5, parseFloat($('f-sl').value) || 20),
    tpPts: Math.max(5, parseFloat($('f-tp').value) || 40)
  };
  const s = launchSession(cfg);
  LV.cs = genCandles(s.symbol, 160, Math.floor(Math.random() * 60));
  LV.tick = 0; LV.lastCtx = null;
  clearInterval(LV.timer);
  LV.timer = setInterval(liveTick, CANDLE_MS / 4);
  toast(`Session ${s.symbol} ${s.tf} lancée (démo) — analyse en cours…`, 'ok');
  document.querySelector('nav button[data-tab="live"]').click();
});

$('btn-stop').addEventListener('click', () => {
  const s = active(); if (!s) return;
  for (const t of s.trades.filter(x => x.status === 'open')) {
    const cur = LV.cs[LV.cs.length - 1].c;
    const spec = SPECS[s.symbol];
    const dir = t.direction === 'BUY' ? 1 : -1;
    t.pnl = +(((cur - t.entry) / spec.pip) * dir * spec.pipVal * t.lot).toFixed(2);
    t.status = Math.abs(cur - t.tp) < Math.abs(cur - t.sl) && dir * (cur - t.entry) > 0 ? 'tp' : 'sl';
    t.exit = cur;
  }
  s.status = 'terminee';
  s.pnl_total = +s.trades.reduce((a, x) => a + x.pnl, 0).toFixed(2);
  if (s.trades.length) S.demo_done = Math.min(S.demo_done + 1, 999);
  save(); clearInterval(LV.timer);
  toast(`Session arrêtée · PnL ${f2(s.pnl_total)} $`, s.pnl_total >= 0 ? 'ok' : 'ko');
  renderAll();
});

$('btn-addacc').addEventListener('click', () => {
  const label = $('a-name').value.trim(), login = $('a-login').value.trim(), server = $('a-server').value.trim();
  if (!label || !login) return toast('Nom et login requis.', 'ko');
  const acc = { id: 'a' + Date.now(), label, login, server: server || '—', kind: 'demo_local' };
  S.accounts.push(acc); save();
  api('account', { body: acc });
  $('a-name').value = $('a-login').value = $('a-server').value = '';
  toast('Compte enregistré en démo locale.', 'ok');
  renderAccounts();
});

$('btn-copy').addEventListener('click', () => {
  $('ref-link').select();
  navigator.clipboard?.writeText(REF_LINK).then(() => toast('Lien copié !', 'ok'))
    .catch(() => document.execCommand('copy'));
});

/* ═══════════ 8. INIT ═══════════ */
window.Telegram?.WebApp?.ready?.();
window.Telegram?.WebApp?.expand?.();
renderAll();
/* Rattrape une session active après rechargement */
if (active()) {
  const s = active();
  LV.cs = genCandles(s.symbol, 160, Math.floor(Math.random() * 60));
  clearInterval(LV.timer);
  LV.timer = setInterval(liveTick, CANDLE_MS / 4);
}
/* Synchro initiale silencieuse */
api('me').then(r => {
  if (!r.offline && r.profile) {
    S.demo_done = Math.max(S.demo_done, r.profile.demo_sessions_done || 0);
    if (r.filleuls) S.ref_balance = r.filleuls.balance || 0;
    save(); renderAll();
  }
}).catch(() => {});
