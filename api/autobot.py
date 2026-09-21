# Ghost rskIA — AUTOBOT 100 % cloud (Vercel serverless + MetaAPI + Upstash)
# Boucle déclenchée par un ping externe toutes les minutes (cron-job.org, gratuit).
# Variables d'environnement :
#   ANALYZE_TOKEN            → secret partagé (protège le worker)        [requis]
#   GEMINI_KEY               → clé Gemini (déjà configurée)              [requis]
#   METAAPI_TOKEN            → token MetaAPI (app.metaapi.cloud)         [requis pour trader]
#   METAAPI_ACCOUNT_ID       → id du compte MT5 connecté sur MetaAPI    [requis pour trader]
#   UPSTASH_REDIS_REST_URL   → URL REST Upstash Redis (console.upstash.com, gratuit) [requis]
#   UPSTASH_REDIS_REST_TOKEN → token REST Upstash                        [requis]
# Optionnels : SYMBOL (défaut XAUUSD), RISK_PCT (1.0), MIN_STARS (3), MIN_RR (2.0),
#              MAX_TRADES_DAY (2), MAX_LOSSES_DAY (2), TRADING_ENABLED ('true' = réel,
#              défaut = DRY-RUN qui ne fait que journaliser), METAAPI_REGION (auto)
import os, json, time, calendar, urllib.request, urllib.error, uuid
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler

TOKEN   = os.environ.get('ANALYZE_TOKEN', '')
KEY     = os.environ.get('GEMINI_KEY', '')
MODEL   = os.environ.get('GEMINI_MODEL', 'gemini-3.6-flash')
MT_TOK  = os.environ.get('METAAPI_TOKEN', '')
MT_ACC  = os.environ.get('METAAPI_ACCOUNT_ID', '')
RU_URL  = os.environ.get('UPSTASH_REDIS_REST_URL', '')
RU_TOK  = os.environ.get('UPSTASH_REDIS_REST_TOKEN', '')
SYMBOL  = os.environ.get('SYMBOL', 'XAUUSD')
RISK_PCT    = float(os.environ.get('RISK_PCT', '1.0'))
MIN_STARS   = int(os.environ.get('MIN_STARS', '3'))
MIN_RR      = float(os.environ.get('MIN_RR', '2.0'))
MAX_TRADES  = int(os.environ.get('MAX_TRADES_DAY', '2'))
MAX_LOSSES  = int(os.environ.get('MAX_LOSSES_DAY', '2'))
LIVE        = os.environ.get('TRADING_ENABLED', '').lower() == 'true'
SESSION     = (15 * 60 + 30, 17 * 60 + 30)  # 15h30–17h30 Paris
CAL_URL = 'https://nfs.faireconomy.media/ff_calendar_thisweek.json'
MAGIC = 20260914

# ---------------- utils temps (Paris, DST manuel) ----------------
def paris_now():
    utc = datetime.utcnow()
    y = utc.year
    def last_sun(m):
        cal = calendar.monthcalendar(y, m)
        return datetime(y, m, max(w[calendar.SUNDAY] for w in cal if w[calendar.SUNDAY]), 1)
    dst = last_sun(3) <= utc < last_sun(10)
    return utc + timedelta(hours=2 if dst else 1)

def in_session(now):
    return now.weekday() < 5 and SESSION[0] <= now.hour * 60 + now.minute < SESSION[1]

# ---------------- état (Upstash Redis REST) ----------------
def rdb(cmd, *args):
    if not (RU_URL and RU_TOK):
        return None
    try:
        req = urllib.request.Request(RU_URL, data=json.dumps([cmd] + list(args)).encode(),
                                     headers={'Authorization': f'Bearer {RU_TOK}', 'Content-Type': 'application/json'})
        return json.loads(urllib.request.urlopen(req, timeout=8).read()).get('result')
    except Exception:
        return None

def state():
    s = rdb('GET', 'ghost:state')
    st = json.loads(s) if s else {}
    st.setdefault('log', [])
    return st

def save(st):
    st['log'] = st['log'][-50:]
    st['trades'] = st.get('trades', 0)
    st['losses'] = st.get('losses', 0)
    rdb('SET', 'ghost:state', json.dumps(st))

def log(st, msg):
    st['log'] = st.get('log', [])[-49:] + [f"[{paris_now().strftime('%d/%m %H:%M')}] {msg}"]
    print(msg)

# ---------------- MetaAPI REST ----------------
def mt_base(st):
    reg = os.environ.get('METAAPI_REGION') or st.get('region')
    if reg:
        return f'https://mt-client-api-v1.{reg}.agiliumtrade.ai', reg
    try:
        req = urllib.request.Request(f'https://mt-provisioning-api-v1.agiliumtrade.ai/users/current/accounts/{MT_ACC}',
                                     headers={'auth-token': MT_TOK})
        j = json.loads(urllib.request.urlopen(req, timeout=10).read())
        reg = j.get('region') or 'london'
        st['region'] = reg
    except Exception:
        reg = os.environ.get('METAAPI_REGION', 'london')
    return f'https://mt-client-api-v1.{reg}.agiliumtrade.ai', reg

def mt(method, path, body, base):
    url = f'{base}/users/current/accounts/{MT_ACC}{path}'
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={'auth-token': MT_TOK, 'Content-Type': 'application/json'})
    try:
        return json.loads(urllib.request.urlopen(req, timeout=15).read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f'MetaAPI {e.code}: {e.read().decode()[:160]}')

# ---------------- news ----------------
def news_flagged():
    try:
        events = json.loads(urllib.request.urlopen(CAL_URL, timeout=8).read())
        now = time.time()
        for e in events:
            if e.get('impact') != 'High':
                continue
            try:
                d = e['date']
                ts = time.mktime(time.strptime(d[:19], '%Y-%m-%dT%H:%M:%S'))
                sign = 1 if d[19] == '-' else -1
                ts += sign * (int(d[20:22]) * 3600 + int(d[23:25]) * 60)
            except Exception:
                continue
            if -900 <= (ts - now) <= 3600:
                return f"{e.get('country')} «{e.get('title')}»"
    except Exception:
        pass
    return ''

# ---------------- prompt IA (même cerveau que l'app/bot) ----------------
PROMPT = """Tu es un scalper professionnel Smart Money (SMC). On te donne un graphique M5 de {symbol} (rendu serveur, MM200 rouge + bougies + volume) avec indicateurs calculés : {feats}. Analyse comme si tu plaçais ton propre argent. UN seul trade de qualité — ou aucun.

═══ 4 FILTRES + 1 PLAN, DANS CET ORDRE (un échec = ATTENDRE) ═══
FILTRE 1 · FLUX — HH/HL haussier, LH/LL baissier, CHoCH = alerte. Prix vs MM200. RSI >50 momentum acheteur, >70 surachat, <30 survente. Range illisible → ATTENDRE.
FILTRE 2 · LIQUIDITÉ — Equal highs/lows et range asiatique = poches de stops. Sweep récent + retour rapide = contexte premium. Liquidité adverse avant le TP → ATTENDRE ou probabilité réduite.
FILTRE 3 · ZONE — Order block frais AVEC imbalance (ÉLIMINATOIRE) > BPR > FVG > breaker > MM200/OTE 0.62-0.786. Étoiles : ★1 imbalance (obligatoire), ★2 pas de liquidité adverse, ★3 sens du flux, ★4 sweep validé, ★5 OTE/BPR. <3★ → ATTENDRE.
FILTRE 4 · SIGNAL — Englobante > pinbar/marteau > étoile matin/soir > CHoCH, dans la zone, dans le sens du flux. Pas de signal → ATTENDRE.
LE PLAN — Entrée "marche" ou "en_attente" au prix exact. SL derrière le sweep/zone (+buffer). TP = liquidité opposée ; R:R ≥ {minrr} OBLIGATOIRE sinon ATTENDRE. Probabilité honnête : 3★≈55-60, 4★≈60-68, 5★≈68-75.
Actifs optimisés : XAU/USD, SPX500, Nasdaq, EUR/USD, GBP/USD.{news}
Style : français simple, "resume" 1-2 phrases max, "detail" < 12 mots.

Réponds STRICTEMENT en JSON : {{"actif":str,"timeframe":"M5","flux":"haussier"|"baissier"|"neutre","flux_detail":str,"liquidite":str|null,"etoiles":int,"zone_ok":bool,"zone_detail":str,"signal_ok":bool,"signal_detail":str,"direction":"ACHAT"|"VENTE"|"ATTENDRE","ordre":"marche"|"en_attente","entree":str|null,"tp":str|null,"sl":str|null,"ratio_rr":str|null,"probabilite":int,"confiance":int,"resume":str,"raisons":[str],"risque":"Faible"|"Modéré"|"Élevé"}}"""

def render_chart(candles):
    """Rend un PNG (bougies + MM200 + volume) avec Pillow ; None si Pillow absent."""
    try:
        from PIL import Image, ImageDraw
    except Exception:
        return None, None
    cs = candles[-60:]
    W, H, VH = 900, 520, 90
    img = Image.new('RGB', (W, H + VH), (12, 14, 20))
    dr = ImageDraw.Draw(img)
    hi = max(c['high'] for c in cs); lo = min(c['low'] for c in cs)
    span = (hi - lo) or 1e-9
    cl = [c['close'] for c in cs]
    ma = [sum(cl[max(0, i - 199):i + 1]) / len(cl[max(0, i - 199):i + 1]) for i in range(len(cl))]
    def Y(p): return int(10 + (hi - p) / span * (H - 40))
    bw = (W - 70) / len(cs)
    x = 10
    vmax = max((c.get('tickVolume') or 1) for c in cs)
    pts = []
    for i, c in enumerate(cs):
        up = c['close'] >= c['open']
        col = (52, 211, 153) if up else (251, 113, 133)
        cx = int(x + i * bw + bw / 2)
        dr.line([(cx, Y(c['high'])), (cx, Y(c['low']))], fill=col, width=1)
        o, cl_ = Y(c['open']), Y(c['close'])
        dr.rectangle([int(x + i * bw + 1), min(o, cl_), int(x + (i + 1) * bw - 1), max(o, cl_) + 1], fill=col)
        vh = int((c.get('tickVolume') or 0) / vmax * (VH - 10))
        dr.rectangle([int(x + i * bw + 1), H + VH - vh, int(x + (i + 1) * bw - 1), H + VH], fill=(40, 60, 90))
        pts.append((cx, Y(ma[i] if i + len(candles) - len(cs) < 200 else c['close'])))
    for k in range(1, len(pts)):  # MM200 en rouge/or
        dr.line([pts[k - 1], pts[k]], fill=(251, 146, 60), width=2)
    dr.text((W - 68, 10), f"{hi:.2f}", fill=(130, 147, 169))
    dr.text((W - 68, H - 42), f"{lo:.2f}", fill=(130, 147, 169))
    dr.text((10, H + 4), f"{SYMBOL} M5 · MM200 (or) · {len(cs)} bougies", fill=(130, 147, 169))
    import io, base64
    buf = io.BytesIO(); img.save(buf, 'PNG')
    return base64.b64encode(buf.getvalue()).decode(), img

def features(candles):
    cl = [c['close'] for c in candles]
    sma = sum(cl[-200:]) / min(200, len(cl))
    # RSI 14
    gains, losses = [], []
    for i in range(-15, -1):
        d = cl[i + 1] - cl[i]
        gains.append(max(d, 0)); losses.append(max(-d, 0))
    ag = sum(gains) / 14 or 1e-9; al = sum(losses) / 14 or 1e-9
    rsi = 100 - 100 / (1 + ag / al)
    hh = max(c['high'] for c in candles[-24:]); ll = min(c['low'] for c in candles[-24:])
    return f"close {cl[-1]:.2f} vs MM200 {sma:.2f} ({'au-dessus' if cl[-1] > sma else 'en dessous'}), RSI {rsi:.0f}, range 2h haut {hh:.2f} bas {ll:.2f}"

def analyze(candles, minrr, news_txt):
    b64, _ = render_chart(candles)
    parts = [{'text': PROMPT.format(symbol=SYMBOL, feats=features(candles), minrr=minrr, news=news_txt)}]
    if b64:
        parts.append({'inline_data': {'mime_type': 'image/png', 'data': b64}})
    payload = {'contents': [{'role': 'user', 'parts': parts}],
               'generationConfig': {'temperature': 0.2, 'response_mime_type': 'application/json'}}
    req = urllib.request.Request(
        f'https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={KEY}',
        data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
    res = json.loads(urllib.request.urlopen(req, timeout=45).read())
    txt = ''.join(p.get('text', '') for p in res['candidates'][0]['content']['parts'] if not p.get('thought'))
    a, b = txt.find('{'), txt.rfind('}')
    return json.loads(txt[a:b + 1])

def num(v):
    try:
        return float(str(v).replace(',', '.').replace('$', '').strip())
    except Exception:
        return None

def parse_rr(v):
    s = str(v or '')
    return num(s.split(':')[-1]) if ':' in s else num(s)

# ---------------- boucle principale ----------------
def worker(key_ok):
    st = state()
    if not key_ok:
        return {'error': 'Non autorisé'}, 401
    now = paris_now()
    day = now.strftime('%Y-%m-%d')
    if st.get('day') != day:
        st.update({'day': day, 'trades': 0, 'losses': 0})
        log(st, 'Nouveau jour — compteurs remis à zéro')
    st['last_run'] = now.strftime('%d/%m %H:%M:%S')

    if not in_session(now):
        st['mode'] = 'hors-session'
        save(st)
        return {'action': 'idle', 'raison': 'hors créneau 15h30-17h30 Paris'}
    if not (MT_TOK and MT_ACC and RU_URL):
        return {'action': 'idle', 'raison': 'MetaAPI/Upstash non configurés'}
    if st['trades'] >= MAX_TRADES:
        save(st); return {'action': 'idle', 'raison': f'max {MAX_TRADES} trades/jour atteint'}
    if st['losses'] >= MAX_LOSSES:
        save(st); return {'action': 'idle', 'raison': f'{MAX_LOSSES} pertes aujourd\'hui — journée finie'}

    base, _ = mt_base(st)
    # ---- gestion du trade ouvert (breakeven + détection clôture) ----
    op = st.get('open')
    positions = mt('GET', '/positions', None, base)
    open_ids = {str(p.get('id')) for p in positions}
    if op:
        if str(op.get('pid')) in open_ids:
            p = next(p for p in positions if str(p.get('id')) == str(op['pid']))
            cur = mt('GET', f'/symbols/{SYMBOL}/current-price', None, base)
            price = cur['ask'] if op['dir'] == 'ACHAT' else cur['bid']
            gained = (price - op['entry']) if op['dir'] == 'ACHAT' else (op['entry'] - price)
            if not op.get('be') and gained >= op['risk']:
                if LIVE:
                    mt('PUT', f"/positions/{op['pid']}", {'stopLoss': op['entry']}, base)
                    log(st, f"Breakeven posé sur #{op['pid']} (SL → entrée {op['entry']})")
                else:
                    log(st, f"DRY-RUN : breakeven serait posé sur #{op['pid']}")
                op['be'] = True
        else:
            cur = mt('GET', f'/symbols/{SYMBOL}/current-price', None, base)
            price = cur['bid'] if op['dir'] == 'ACHAT' else cur['ask']
            win = (price >= op['tp']) if op['dir'] == 'ACHAT' else (price <= op['tp'])
            if op.get('be'):
                win = None  # sorti au breakeven : ni win ni loss
            if win is True:
                log(st, f"TP touché sur #{op['pid']} ✅")
            elif win is False:
                st['losses'] += 1
                log(st, f"SL touché sur #{op['pid']} ❌ ({st['losses']}/{MAX_LOSSES})")
            else:
                log(st, f"Trade #{op['pid']} clôturé au breakeven ➖")
            st['open'] = None
            save(st)
            return {'action': 'closed', 'win': win}
        save(st)
        return {'action': 'managing', 'position': op['dir'], 'be': op.get('be', False)}

    # ---- aucun trade ouvert : on analyse ----
    candles = mt('GET', f'/symbols/{SYMBOL}/current-candles?timeframe=5m&limit=260', None, base)
    if not isinstance(candles, list) or len(candles) < 60:
        raise RuntimeError('Bougies insuffisantes reçues de MetaAPI')
    nf = news_flagged()
    news_txt = f'\nCONTEXTE NEWS : ALERTE {nf} — fenêtre interdite, direction = "ATTENDRE".' if nf else ''
    if nf:
        log(st, f'News {nf} → pas d\'analyse (fenêtre interdite)')
        save(st)
        return {'action': 'idle', 'raison': 'news majeure proche', 'news': nf}

    sig = analyze(candles, MIN_RR, news_txt)
    st['last_signal'] = {k: sig.get(k) for k in ('direction', 'etoiles', 'probabilite', 'resume', 'ratio_rr')}
    dirn = str(sig.get('direction', '')).upper()
    stars = int(sig.get('etoiles') or 0)
    rr = parse_rr(sig.get('ratio_rr')) or 0
    entry = num(sig.get('entree')); tp = num(sig.get('tp')); sl = num(sig.get('sl'))
    ok = (dirn in ('ACHAT', 'VENTE') and stars >= MIN_STARS and rr >= MIN_RR and entry and tp and sl)
    if not ok:
        log(st, f"Pas de tir : {dirn} {stars}★ RR {rr} — {str(sig.get('resume'))[:90]}")
        save(st)
        return {'action': 'skip', 'signal': st['last_signal']}

    info = mt('GET', '/account-information', None, base)
    spec = mt('GET', f'/symbols/{SYMBOL}/specification', None, base)
    equity = float(info.get('equity') or info.get('balance') or 0)
    risk_money = equity * RISK_PCT / 100
    dist = abs(entry - sl)
    tv, ts = float(spec.get('tickValue') or 0), float(spec.get('tickSize') or 0)
    if not (equity and tv and ts and dist):
        raise RuntimeError('Données de sizing indisponibles (spec/account)')
    loss_per_lot = dist / ts * tv
    vol = risk_money / loss_per_lot
    vmin = float(spec.get('minVolume') or 0.01); vmax = float(spec.get('maxVolume') or 100)
    vstep = float(spec.get('volumeStep') or 0.01)
    vol = min(vmax, max(vmin, int(vol / vstep) * vstep))
    if vol < vmin:
        save(st); return {'action': 'skip', 'raison': 'volume min = risque trop élevé'}
    if dirn == 'VENTE' and sl < entry:
        sl, tp = tp, sl  # sécurité si l'IA a inversé
    action = 'ORDER_TYPE_BUY' if dirn == 'ACHAT' else 'ORDER_TYPE_SELL'
    order = {'actionType': action, 'symbol': SYMBOL, 'volume': round(vol, 2),
             'stopLoss': round(sl, 5), 'takeProfit': round(tp, 5),
             'comment': 'ghost rskIA', 'clientId': str(uuid.uuid4()), 'magic': MAGIC}
    if LIVE:
        res = mt('POST', '/trade', order, base)
        pid = res.get('positionId') or res.get('orderId')
        st['open'] = {'pid': pid, 'dir': dirn, 'entry': entry, 'sl': sl, 'tp': tp, 'risk': dist, 'be': False}
        st['trades'] += 1
        log(st, f"🚀 {dirn} {vol} lot @ {entry} | SL {sl} TP {tp} ({stars}★, proba {sig.get('probabilite')}%) → ticket {pid}")
        save(st)
        return {'action': 'traded', 'vol': vol, 'signal': st['last_signal'], 'metaapi': res}
    else:
        st['open'] = {'pid': 'DRY', 'dir': dirn, 'entry': entry, 'sl': sl, 'tp': tp, 'risk': dist, 'be': False}
        st['trades'] += 1
        log(st, f"DRY-RUN : {dirn} {vol} lot @ {entry} | SL {sl} TP {tp} ({stars}★)")
        save(st)
        return {'action': 'dry-run', 'vol': vol, 'signal': st['last_signal']}


class handler(BaseHTTPRequestHandler):

    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        data = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(data)

    def _key_ok(self):
        from urllib.parse import urlparse, parse_qs
        q = parse_qs(urlparse(self.path).query)
        supplied = (self.headers.get('x-ghost-token') or (q.get('key') or [''])[0])
        return bool(TOKEN) and supplied == TOKEN

    def do_GET(self):
        if self._key_ok():
            return self._run()
        st = state()
        self._json({'status': 'Ghost rskIA AUTOBOT',
                    'configuré': {'token': bool(TOKEN), 'gemini': bool(KEY), 'metaapi': bool(MT_TOK and MT_ACC), 'redis': bool(RU_URL)},
                    'mode': 'LIVE' if LIVE else 'DRY-RUN (sûr)',
                    'session': '15h30-17h30 Paris · lun-ven', 'symbole': SYMBOL,
                    'trades_jour': st.get('trades', 0), 'pertes_jour': st.get('losses', 0),
                    'dernier_run': st.get('last_run'), 'dernier_signal': st.get('last_signal'),
                    'log': st.get('log', [])[-10:]})

    def do_POST(self):
        return self._run()

    def _run(self):
        try:
            if not TOKEN:
                return self._json({'error': 'ANALYZE_TOKEN non configuré côté serveur'}, 500)
            tok = self._key_ok()
            if not tok:
                return self._json({'error': 'Non autorisé'}, 401)
            res = worker(tok)
            out, code = res if isinstance(res, tuple) else (res, 200)
            return self._json(out, code)
        except Exception as e:
            import traceback
            tb = traceback.format_exc()[-800:]
            try:
                st = state(); log(st, f'ERREUR : {str(e)[:180]}'); save(st)
            except Exception:
                pass
            return self._json({'error': str(e)[:300], 'debug_tb': tb}, 500)
