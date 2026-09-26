# Ghost rskIA — AUTOBOT SNIPER multi-marchés (Vercel serverless + MetaAPI + Upstash)
# Marchés : XAUUSD · NAS100 · GBPUSD · BTCUSD — killzone New York (14h00–20h00 Paris).
# Ping externe chaque minute (cron-job.org) → gère les positions en continu +
# cherche des setups sniper : sweep liquidité → CHoCH/BOS M5 → OB frais + FVG,
# flux M15 aligné, ≥4 étoiles, R:R ≥ 1:2. Une position par marché, 2 simultanées max.
#
# Variables d'environnement :
#   ANALYZE_TOKEN            [requis] secret du worker (cron URL ?key=…)
#   GEMINI_KEY               [requis]
#   METAAPI_TOKEN            [requis pour trader]  app.metaapi.cloud
#   METAAPI_ACCOUNT_ID       [requis pour trader]  compte MT5 (Pocket Option accepté)
#   UPSTASH_REDIS_REST_URL   [requis]
#   UPSTASH_REDIS_REST_TOKEN [requis]
# Optionnels : SYMBOLS (défaut "XAUUSD,NAS100,GBPUSD,BTCUSD"), RISK_PCT (1.0),
#   MIN_STARS (4), MIN_RR (2.0), MAX_TRADES_DAY (4), MAX_LOSSES_DAY (2),
#   MAX_SIMULT (2), SESSION_START ("14:00"), SESSION_END ("20:00") heure de Paris,
#   TRADING_ENABLED ("true" = réel ; absent = DRY-RUN), METAAPI_REGION (auto)
import os, json, time, calendar, urllib.request, urllib.error, uuid
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler
from concurrent.futures import ThreadPoolExecutor

TOKEN   = os.environ.get('ANALYZE_TOKEN', '')
KEY     = os.environ.get('GEMINI_KEY', '')
MODEL   = os.environ.get('GEMINI_MODEL', 'gemini-3.6-flash')
MT_TOK  = os.environ.get('METAAPI_TOKEN', '')
MT_ACC  = os.environ.get('METAAPI_ACCOUNT_ID', '')
RU_URL  = os.environ.get('UPSTASH_REDIS_REST_URL', '')
RU_TOK  = os.environ.get('UPSTASH_REDIS_REST_TOKEN', '')
ASSETS  = [s.strip().upper() for s in os.environ.get(
           'SYMBOLS', 'XAUUSD,NAS100,GBPUSD,BTCUSD').split(',') if s.strip()]
RISK_PCT   = float(os.environ.get('RISK_PCT', '1.0'))
MIN_STARS  = int(os.environ.get('MIN_STARS', '4'))
MIN_RR     = float(os.environ.get('MIN_RR', '2.0'))
MAX_TRADES = int(os.environ.get('MAX_TRADES_DAY', '4'))
MAX_LOSSES = int(os.environ.get('MAX_LOSSES_DAY', '2'))
MAX_SIMUL  = int(os.environ.get('MAX_SIMULT', '2'))
LIVE       = os.environ.get('TRADING_ENABLED', '').lower() == 'true'
CAL_URL = 'https://nfs.faireconomy.media/ff_calendar_thisweek.json'
MAGIC = 20260914

def _hm(v, default):
    h, m = (v or default).split(':')
    return int(h) * 60 + int(m)

SESSION = (_hm(os.environ.get('SESSION_START'), '14:00'),
           _hm(os.environ.get('SESSION_END'), '20:00'))

ALIASES = {
    'XAUUSD': ['XAUUSD', 'GOLD', 'XAU/USD', 'XAUUSD.', 'XAUUSDc'],
    'NAS100': ['NAS100', 'USTEC', 'US100', 'NAS100.', 'US100.cash', '#NDX', 'NDX100', 'USATECH'],
    'GBPUSD': ['GBPUSD', 'GBP/USD', 'GBPUSD.', 'GBPUSDc'],
    'BTCUSD': ['BTCUSD', 'BTC/USD', 'BTCUSD.', 'BITCOIN', 'BTCUSDc'],
}

# ---------------- temps (Paris, DST manuel) ----------------
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
    st.setdefault('open', {})        # {ASSET: {pid, dir, entry, sl, tp, risk, be, since}}
    st.setdefault('cooldown', {})    # {ASSET: horodatage de fin}
    st.setdefault('last_signal', {})
    return st

def save(st):
    st['log'] = st['log'][-50:]
    rdb('SET', 'ghost:state', json.dumps(st))

def log(st, msg):
    st['log'] = st.get('log', [])[-49:] + [f"[{paris_now().strftime('%d/%m %H:%M')}] {msg}"]
    print(msg)

# ---------------- MetaAPI REST ----------------
def mt_base(st):
    reg = os.environ.get('METAAPI_REGION') or st.get('region')
    if reg:
        return f'https://mt-client-api-v1.{reg}.agiliumtrade.ai'
    reg = 'london'
    try:
        req = urllib.request.Request(f'https://mt-provisioning-api-v1.agiliumtrade.ai/users/current/accounts/{MT_ACC}',
                                     headers={'auth-token': MT_TOK})
        reg = json.loads(urllib.request.urlopen(req, timeout=10).read()).get('region') or 'london'
        st['region'] = reg
    except Exception:
        pass
    return f'https://mt-client-api-v1.{reg}.agiliumtrade.ai'

def mt(method, path, body, base):
    url = f'{base}/users/current/accounts/{MT_ACC}{path}'
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={'auth-token': MT_TOK, 'Content-Type': 'application/json'})
    try:
        return json.loads(urllib.request.urlopen(req, timeout=15).read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f'MetaAPI {e.code}: {e.read().decode()[:160]}')

def candles(base, broker_sym, tf, limit):
    return mt('GET', f'/symbols/{broker_sym}/current-candles?timeframe={tf}&limit={limit}', None, base)

def resolve_symbols(st, base):
    """Associe chaque actif au symbole exact du broker (cache 1 jour dans Redis)."""
    cached = st.get('sym_map') or {}
    if cached.get('_day') == paris_now().strftime('%Y-%m-%d'):
        return {k: v for k, v in cached.items() if not k.startswith('_')}
    names = set()
    try:
        for sname in mt('GET', '/symbols', None, base):
            n = sname.get('symbol') or sname.get('name') or ''
            if n:
                names.add(n)
    except Exception:
        names = set()
    low = {n.lower(): n for n in names}
    smap = {}
    for asset in ASSETS:
        found = None
        for alias in ALIASES.get(asset, [asset]):
            if alias.lower() in low:
                found = low[alias.lower()]
                break
        if not found and names:  # recherche souple
            for alias in ALIASES.get(asset, [asset]):
                cand = [n for n in names if alias.lower() in n.lower()]
                if cand:
                    found = sorted(cand, key=len)[0]
                    break
        if not found:  # dernier recours : test direct des alias
            for alias in ALIASES.get(asset, [asset]):
                try:
                    if len(candles(base, alias, '5m', 5) or []) >= 5:
                        found = alias
                        break
                except Exception:
                    continue
        smap[asset] = found
        log(st, f"Symbole {asset} → {found or 'INTROUVABLE (ignoré)'}")
    smap['_day'] = paris_now().strftime('%Y-%m-%d')
    st['sym_map'] = smap
    return {k: v for k, v in smap.items() if not k.startswith('_')}

# ---------------- news ----------------
def news_flagged():
    try:
        events = json.loads(urllib.request.urlopen(CAL_URL, timeout=8).read())
        now = time.time()
        for e in events:
            if e.get('impact') != 'High' or e.get('country') not in ('USD', 'GBP'):
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

# ---------------- analyse (Gemini, même cerveau que l'app) ----------------
PROMPT = """Tu es un trader SNIPER Smart Money (SMC) sur {symbol}. Graphique M5 (bougies + MM200 orange + volume) + données calculées : {feats}. Contexte M15 : {m15}. Killzone New York.{news}

═══ SETUP SNIPER — LES 4 ÉLÉMENTS SONT OBLIGATOIRES, SINON "ATTENDRE" ═══
1. SWEEP : balayage de liquidité visible (highs/lows asiatiques ou londoniens, equal highs/lows, ou ancien swing) suivi d'un rejet rapide.
2. CHoCH ou BOS M5 : cassure de structure dans le sens du trade APRÈS le sweep.
3. ZONE : retour du prix dans un Order Block frais AVEC imbalance (éliminatoire) — idéalement en confluence FVG. Breaker/BPR acceptés si imbalance nette.
4. ALIGNEMENT : flux M15 ({m15dir}) dans le sens du trade. Contre-tendance M15 → ATTENDRE.

Étoiles : ★1 sweep, ★2 CHoCH/BOS, ★3 OB+imbalance, ★4 confluence FVG/BPR, ★5 OTE 0.62-0.786 ou sweep de la session précédente. Moins de {minstars}★ = ATTENDRE.
PLAN — Entrée "marche" au prix actuel ou "en_attente" dans la zone. SL derrière le sweep (+buffer). TP = liquidité opposée. R:R ≥ {minrr} obligatoire.
Probabilité honnête : 4★≈60-68, 5★≈68-75. Un trade parfait vaut mieux que trois médiocres.
Style : français simple, "resume" ≤ 2 phrases, "detail" < 12 mots.

Réponds STRICTEMENT en JSON : {{"actif":str,"timeframe":"M5","flux":"haussier"|"baissier"|"neutre","flux_detail":str,"liquidite":str|null,"etoiles":int,"zone_ok":bool,"zone_detail":str,"signal_ok":bool,"signal_detail":str,"direction":"ACHAT"|"VENTE"|"ATTENDRE","ordre":"marche"|"en_attente","entree":str|null,"tp":str|null,"sl":str|null,"ratio_rr":str|null,"probabilite":int,"confiance":int,"resume":str,"raisons":[str],"risque":"Faible"|"Modéré"|"Élevé"}}"""

def render_chart(sym, cs_all):
    """PNG bougies + MM200 (Pillow). Retourne le base64 ou None."""
    try:
        from PIL import Image, ImageDraw
        import io, base64
    except Exception:
        return None
    cs = cs_all[-64:]
    W, H, VH = 900, 520, 90
    img = Image.new('RGB', (W, H + VH), (12, 14, 20))
    dr = ImageDraw.Draw(img)
    hi = max(c['high'] for c in cs); lo = min(c['low'] for c in cs)
    span = (hi - lo) or 1e-9
    def Y(p): return int(10 + (hi - p) / span * (H - 40))
    closes = [c['close'] for c in cs]
    ma = [sum(closes[max(0, i - 199):i + 1]) / len(closes[max(0, i - 199):i + 1]) for i in range(len(closes))]
    bw = (W - 70) / len(cs)
    vmax = max((c.get('tickVolume') or 1) for c in cs)
    pts = []
    for i, c in enumerate(cs):
        col = (52, 211, 153) if c['close'] >= c['open'] else (251, 113, 133)
        cx = int(10 + i * bw + bw / 2)
        dr.line([(cx, Y(c['high'])), (cx, Y(c['low']))], fill=col, width=1)
        o, cl_ = Y(c['open']), Y(c['close'])
        dr.rectangle([int(10 + i * bw + 1), min(o, cl_), int(10 + (i + 1) * bw - 1), max(o, cl_) + 1], fill=col)
        vh = int((c.get('tickVolume') or 0) / vmax * (VH - 10))
        dr.rectangle([int(10 + i * bw + 1), H + VH - vh, int(10 + (i + 1) * bw - 1), H + VH], fill=(40, 60, 90))
        pts.append((cx, Y(ma[i])))
    for k in range(1, len(pts)):
        dr.line([pts[k - 1], pts[k]], fill=(251, 146, 60), width=2)
    dr.text((W - 68, 10), f"{hi:.2f}", fill=(130, 147, 169))
    dr.text((W - 68, H - 42), f"{lo:.2f}", fill=(130, 147, 169))
    dr.text((10, H + 4), f"{sym} M5 · MM200 (orange) · killzone NY", fill=(130, 147, 169))
    buf = io.BytesIO(); img.save(buf, 'PNG')
    return base64.b64encode(buf.getvalue()).decode()

def features(cs):
    cl = [c['close'] for c in cs]
    sma = sum(cl[-200:]) / min(200, len(cl))
    gains, losses = [], []
    for i in range(-15, -1):
        d = cl[i + 1] - cl[i]
        gains.append(max(d, 0)); losses.append(max(-d, 0))
    ag = sum(gains) / 14 or 1e-9; al = sum(losses) / 14 or 1e-9
    rsi = 100 - 100 / (1 + ag / al)
    hh = max(c['high'] for c in cs[-24:]); ll = min(c['low'] for c in cs[-24:])
    return (f"close {cl[-1]:.2f} vs MM200 {sma:.2f} ({'au-dessus' if cl[-1] > sma else 'en dessous'}), "
            f"RSI {rsi:.0f}, range 2h haut {hh:.2f} bas {ll:.2f}")

def m15_context(cs15):
    """Flux M15 simplifié : prix vs MM200 + position dans le range récent."""
    cl = [c['close'] for c in cs15]
    sma = sum(cl[-150:]) / min(150, len(cl))
    hh = max(c['high'] for c in cs15[-16:]); ll = min(c['low'] for c in cs15[-16:])
    pos = (cl[-1] - ll) / ((hh - ll) or 1e-9)
    d = 'haussier' if cl[-1] > sma and pos > 0.5 else ('baissier' if cl[-1] < sma and pos < 0.5 else 'neutre')
    return (f"M15 {d} (close {cl[-1]:.2f} vs MM200 {sma:.2f}, range 4h {ll:.2f}-{hh:.2f})"), d

def analyze(sym, cs5, cs15, news_txt):
    feats = features(cs5)
    m15txt, m15dir = m15_context(cs15)
    parts = [{'text': PROMPT.format(symbol=sym, feats=feats, m15=m15txt, m15dir=m15dir,
                                    minstars=MIN_STARS, minrr=MIN_RR, news=news_txt)}]
    b64 = render_chart(sym, cs5)
    if b64:
        parts.append({'inline_data': {'mime_type': 'image/png', 'data': b64}})
    payload = {'contents': [{'role': 'user', 'parts': parts}],
               'generationConfig': {'temperature': 0.15, 'response_mime_type': 'application/json'}}
    req = urllib.request.Request(
        f'https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={KEY}',
        data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
    res = json.loads(urllib.request.urlopen(req, timeout=30).read())
    txt = ''.join(p.get('text', '') for p in res['candidates'][0]['content']['parts'] if not p.get('thought'))
    a, b = txt.find('{'), txt.rfind('}')
    return json.loads(txt[a:b + 1]), m15dir

def num(v):
    try:
        return float(str(v).replace(',', '.').replace('$', '').strip())
    except Exception:
        return None

def parse_rr(v):
    s = str(v or '')
    return num(s.split(':')[-1]) if ':' in s else num(s)

# ---------------- gestion des positions ----------------
def current_price(base, broker_sym):
    return mt('GET', f'/symbols/{broker_sym}/current-price', None, base)

def manage_one(st, base, sym, broker_sym, open_ids):
    """Breakeven à +1R + détection de clôture. Retourne un événement ou None."""
    op = st['open'].get(sym)
    if not op:
        return None
    pid = str(op.get('pid'))
    if pid.startswith('DRY:'):
        cur = current_price(base, broker_sym)
        price = cur.get('bid') if op['dir'] == 'ACHAT' else cur.get('ask')
        age = time.time() - op.get('since', time.time())
        won = None
        if op['dir'] == 'ACHAT':
            if price >= op['tp']: won = True
            elif price <= op['sl']: won = False
        else:
            if price <= op['tp']: won = True
            elif price >= op['sl']: won = False
        if won is None and age > 5400:
            won = None  # timeout 90 min : clôture virtuelle neutre
        elif won is None:
            gained = (price - op['entry']) if op['dir'] == 'ACHAT' else (op['entry'] - price)
            if not op.get('be') and gained >= op['risk']:
                op['be'] = True
            return None
        return close_out(st, sym, won if age <= 5400 else None)
    if pid in open_ids:
        cur = current_price(base, broker_sym)
        price = cur.get('ask') if op['dir'] == 'ACHAT' else cur.get('bid')
        gained = (price - op['entry']) if op['dir'] == 'ACHAT' else (op['entry'] - price)
        if not op.get('be') and gained >= op['risk']:
            if LIVE:
                mt('PUT', f"/positions/{pid}", {'stopLoss': op['entry']}, base)
            log(st, f"Breakeven {sym} #{pid} (SL → {op['entry']})")
            op['be'] = True
        return None
    return close_out(st, sym, None if op.get('be') else _guess_result(st, base, sym, broker_sym, op))

def _guess_result(st, base, sym, broker_sym, op):
    """La position n'existe plus : on estime TP/SL via le prix actuel."""
    try:
        cur = current_price(base, broker_sym)
        price = cur.get('bid') if op['dir'] == 'ACHAT' else cur.get('ask')
        return (price >= op['tp']) if op['dir'] == 'ACHAT' else (price <= op['tp'])
    except Exception:
        return None

def close_out(st, sym, won):
    st['open'].pop(sym, None)
    st['cooldown'][sym] = time.time() + (1800 if won is False else 900)
    if won is True:
        st['wins'] = st.get('wins', 0) + 1
        log(st, f"TP touché {sym} ✅")
    elif won is False:
        st['losses'] = st.get('losses', 0) + 1
        log(st, f"SL touché {sym} ❌ ({st['losses']}/{MAX_LOSSES} pertes)")
    else:
        log(st, f"Position {sym} clôturée (breakeven ou timeout) ➖")
    return {'sym': sym, 'win': won}

# ---------------- ouverture ----------------
def try_trade(st, base, asset, broker_sym, sig, m15dir, infos):
    dirn = str(sig.get('direction', '')).upper()
    stars = int(sig.get('etoiles') or 0)
    rr = parse_rr(sig.get('ratio_rr')) or 0
    entry = num(sig.get('entree')); tp = num(sig.get('tp')); sl = num(sig.get('sl'))
    st['last_signal'][asset] = {k: sig.get(k) for k in ('direction', 'etoiles', 'probabilite', 'resume', 'ratio_rr')}
    if not (dirn in ('ACHAT', 'VENTE') and stars >= MIN_STARS and rr >= MIN_RR and entry and tp and sl):
        if stars >= MIN_STARS - 1 and dirn != 'ATTENDRE':
            log(st, f"Refus {asset} : {stars}★ RR {rr} ({str(sig.get('resume'))[:70]})")
        return None
    if dirn == 'VENTE' and sl < entry:
        sl, tp = tp, sl
    spec = mt('GET', f'/symbols/{broker_sym}/specification', None, base)
    dist = abs(entry - sl)
    tv, ts = float(spec.get('tickValue') or 0), float(spec.get('tickSize') or 0)
    if not (tv and ts and dist):
        raise RuntimeError(f'Spécifications {broker_sym} indisponibles')
    risk_money = infos['equity'] * RISK_PCT / 100
    vol = risk_money / (dist / ts * tv)
    vmin = float(spec.get('minVolume') or 0.01)
    vmax = float(spec.get('maxVolume') or 100)
    vstep = float(spec.get('volumeStep') or 0.01)
    vol = min(vmax, max(vmin, int(vol / vstep) * vstep))
    if vol < vmin:
        log(st, f"{asset} ignoré : volume min = risque trop élevé")
        return None
    action = 'ORDER_TYPE_BUY' if dirn == 'ACHAT' else 'ORDER_TYPE_SELL'
    dec = int(spec.get('digits') or 5)
    if LIVE:
        order = {'actionType': action, 'symbol': broker_sym, 'volume': round(vol, 2),
                 'stopLoss': round(sl, dec), 'takeProfit': round(tp, dec),
                 'comment': 'ghost rskIA sniper', 'clientId': str(uuid.uuid4()), 'magic': MAGIC}
        res = mt('POST', '/trade', order, base)
        pid = res.get('positionId') or res.get('orderId')
        log(st, f"🚀 SNIPER {asset} {dirn} {vol} lot @ {entry} | SL {sl} TP {tp} "
                f"({stars}★, {sig.get('probabilite')}%, M15 {m15dir}) → #{pid}")
    else:
        pid = f'DRY:{asset}'
        log(st, f"DRY-RUN : {asset} {dirn} {vol} lot @ {entry} | SL {sl} TP {tp} ({stars}★)")
    st['open'][asset] = {'pid': pid, 'dir': dirn, 'entry': entry, 'sl': sl,
                         'tp': tp, 'risk': dist, 'be': False, 'since': time.time()}
    st['trades'] += 1
    return {'action': 'traded' if LIVE else 'dry-run', 'sym': asset, 'dir': dirn,
            'vol': vol, 'signal': st['last_signal'][asset]}

def scan_asset(base, asset, broker_sym, news_txt):
    """Analyse un marché ; retourne (asset, sig, m15dir) ou (asset, None, err)."""
    cs5 = candles(base, broker_sym, '5m', 260)
    if not isinstance(cs5, list) or len(cs5) < 60:
        raise RuntimeError(f'bougies M5 insuffisantes sur {broker_sym}')
    cs15 = candles(base, broker_sym, '15m', 200)
    if not isinstance(cs15, list) or len(cs15) < 40:
        cs15 = cs5[::3]
    sig, m15dir = analyze(asset, cs5, cs15, news_txt)
    return asset, sig, m15dir

# ---------------- boucle principale (ping cron) ----------------
def worker(key_ok):
    st = state()
    if not key_ok:
        return {'error': 'Non autorisé'}, 401
    now = paris_now()
    day = now.strftime('%Y-%m-%d')
    if st.get('day') != day:
        st.update({'day': day, 'trades': 0, 'losses': 0, 'wins': 0})
        log(st, 'Nouveau jour — compteurs remis à zéro')
    st['last_run'] = now.strftime('%d/%m %H:%M:%S')

    if not (MT_TOK and MT_ACC and RU_URL):
        return {'action': 'idle', 'raison': 'MetaAPI/Upstash non configurés'}

    base = mt_base(st)
    smap = resolve_symbols(st, base)

    # 1) Gestion continue des positions (même hors killzone)
    events = []
    open_syms = list(st['open'].keys())
    if open_syms:
        try:
            open_ids = {str(p.get('id')) for p in mt('GET', '/positions', None, base)}
        except Exception as e:
            open_ids = set()
            log(st, f'Positions illisibles ({str(e)[:80]})')
        with ThreadPoolExecutor(max_workers=4) as ex:
            for ev in ex.map(lambda a: manage_one(st, base, a, smap.get(a) or a, open_ids), open_syms):
                if ev:
                    events.append(ev)

    # 2) Analyse uniquement dans la killzone New York
    if not in_session(now):
        st['mode'] = 'hors killzone NY'
        save(st)
        out = {'action': 'manage' if open_syms else 'idle',
               'raison': 'hors killzone New York (14h-20h Paris)'}
        if events:
            out['events'] = events
        return out
    if st['trades'] >= MAX_TRADES:
        save(st)
        return {'action': 'idle', 'raison': f'max {MAX_TRADES} trades/jour atteint'}
    if st['losses'] >= MAX_LOSSES:
        save(st)
        return {'action': 'idle', 'raison': f'{MAX_LOSSES} pertes — journée finie'}

    nf = news_flagged()
    news_txt = (f'\nCONTEXTE NEWS : ALERTE {nf} — fenêtre interdite, direction = "ATTENDRE".' if nf else '')
    if nf:
        log(st, f'News {nf} → analyses gelées')
        save(st)
        return {'action': 'idle', 'raison': 'news majeure proche', 'news': nf}

    try:
        info = mt('GET', '/account-information', None, base)
        infos = {'equity': float(info.get('equity') or info.get('balance') or 0)}
    except Exception:
        infos = {'equity': 0}

    # 3) Scan parallèle des 4 marchés éligibles
    cible = []
    for asset in ASSETS:
        bsym = smap.get(asset)
        if not bsym or asset in st['open'] or len(st['open']) + len(cible) >= MAX_SIMUL:
            continue
        if time.time() < float(st['cooldown'].get(asset, 0)):
            continue
        cible.append((asset, bsym))

    results = []
    if cible:
        with ThreadPoolExecutor(max_workers=4) as ex:
            futs = {ex.submit(scan_asset, base, a, b, news_txt): a for a, b in cible}
            for f in futs:
                try:
                    results.append(f.result(timeout=45))
                except Exception as e:
                    log(st, f'Scan {futs[f]} impossible : {str(e)[:90]}')

    # 4) Classement des candidats → on tire les meilleurs setups d'abord
    candidats = []
    for asset, sig, m15dir in results:
        if not sig:
            continue
        stars = int(sig.get('etoiles') or 0)
        dirn = str(sig.get('direction', '')).upper()
        ok_dir = (dirn in ('ACHAT', 'VENTE') and
                  (m15dir == 'neutre' or
                   (dirn == 'ACHAT' and m15dir == 'haussier') or
                   (dirn == 'VENTE' and m15dir == 'baissier')))
        if ok_dir and stars >= MIN_STARS:
            candidats.append((stars, int(sig.get('confiance') or sig.get('probabilite') or 0), asset, sig, m15dir))
        else:
            st['last_signal'][asset] = {k: sig.get(k) for k in ('direction', 'etoiles', 'probabilite', 'resume')}
            if stars >= MIN_STARS - 1 and dirn != 'ATTENDRE':
                log(st, f"Refus {asset} : {'flux M15 opposé' if not ok_dir else f'{stars}★'} — {str(sig.get('resume'))[:60]}")
    candidats.sort(key=lambda x: (x[0], x[1]), reverse=True)

    pris = []
    for stars, _conf, asset, sig, m15dir in candidats:
        slots = min(MAX_TRADES - st['trades'], MAX_SIMUL - len(st['open']))
        if slots <= 0:
            break
        r = try_trade(st, base, asset, smap[asset], sig, m15dir, infos)
        if r:
            pris.append(r)

    save(st)
    return {'action': 'scan', 'marchés': [a for a, _ in cible],
            'candidats': [c[2] for c in candidats], 'trades': pris,
            'events': events, 'mode': 'LIVE' if LIVE else 'DRY-RUN'}


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
        self._json({'status': 'Ghost rskIA AUTOBOT SNIPER',
                    'configuré': {'token': bool(TOKEN), 'gemini': bool(KEY),
                                  'metaapi': bool(MT_TOK and MT_ACC), 'redis': bool(RU_URL)},
                    'mode': 'LIVE' if LIVE else 'DRY-RUN (sûr)',
                    'marchés': ASSETS,
                    'killzone': f"{SESSION[0]//60:02d}h{SESSION[0]%60:02d}-{SESSION[1]//60:02d}h{SESSION[1]%60:02d} Paris (New York)",
                    'précision': f'≥{MIN_STARS}★ + flux M15 + R:R ≥ 1:{MIN_RR:g}',
                    'symboles_résolus': {k: v for k, v in (st.get('sym_map') or {}).items() if not k.startswith('_')},
                    'positions': list(st.get('open', {}).keys()),
                    'trades_jour': st.get('trades', 0), 'pertes_jour': st.get('losses', 0),
                    'dernier_run': st.get('last_run'), 'derniers_signaux': st.get('last_signal', {}),
                    'log': st.get('log', [])[-10:]})

    def do_POST(self):
        return self._run()

    def _run(self):
        try:
            if not TOKEN:
                return self._json({'error': 'ANALYZE_TOKEN non configuré côté serveur'}, 500)
            if not self._key_ok():
                return self._json({'error': 'Non autorisé'}, 401)
            res = worker(True)
            out, code = res if isinstance(res, tuple) else (res, 200)
            return self._json(out, code)
        except Exception as e:
            import traceback
            try:
                st = state(); log(st, f'ERREUR : {str(e)[:180]}'); save(st)
            except Exception:
                pass
            return self._json({'error': str(e)[:300], 'debug_tb': traceback.format_exc()[-700:]}, 500)
