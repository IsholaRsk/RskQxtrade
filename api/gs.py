# Ghost rskIA · Sessions SMC — API consolidée (Upstash Redis REST)
# Routage par paramètre ?r= (me, session, sessions, trade, trades, trade_close,
# accounts, referral, join, limits). Le frontend fonctionne aussi en local pur :
# cette API ne fait que synchroniser quand les variables Upstash sont présentes.
import os, json, time, hmac, hashlib, urllib.request, urllib.error
from urllib.parse import urlparse, parse_qs
from http.server import BaseHTTPRequestHandler

RU_URL = os.environ.get('UPSTASH_REDIS_REST_URL', '')
RU_TOK = os.environ.get('UPSTASH_REDIS_REST_TOKEN', '')
TG_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '') or os.environ.get('BOT_TOKEN', '')

MAX_SESSIONS_DAY = 3
MAX_TRADES_DAY = 15
MAX_TRADES_SESSION = 5
REF_WITHDRAW_MIN = 2


def rdb(*args):
    if not (RU_URL and RU_TOK):
        raise RuntimeError('redis_off')
    try:
        req = urllib.request.Request(
            RU_URL, data=json.dumps(list(args)).encode(),
            headers={'Authorization': f'Bearer {RU_TOK}', 'Content-Type': 'application/json'})
        return json.loads(urllib.request.urlopen(req, timeout=8).read()).get('result')
    except Exception:
        raise RuntimeError('redis_off')


def jget(key, default):
    v = rdb('GET', key)
    return json.loads(v) if v else default


def jset(key, value):
    rdb('SET', key, json.dumps(value))
    return value


def day_key():
    return time.strftime('%Y-%m-%d', time.gmtime(time.time() + 3600))  # jour Paris approx


def profile(uid):
    p = jget(f'gs:u:{uid}:profile', {})
    p.setdefault('uid', uid)
    p.setdefault('created', time.strftime('%Y-%m-%d'))
    p.setdefault('demo_sessions_done', 0)
    p.setdefault('ref_code', uid.replace('tg_', '')[:8] or uid[:8])
    p.setdefault('referred_by', None)
    p.setdefault('ref_balance', 0.0)
    return p


def check_telegram(init_data):
    """Validation HMAC de l'initData Telegram (si BOT_TOKEN configuré)."""
    if not (TG_TOKEN and init_data):
        return None
    try:
        pairs = dict(p.split('=', 1) for p in init_data.split('&') if '=' in p)
        their_hash = pairs.pop('hash', '')
        check = '\n'.join(f'{k}={pairs[k]}' for k in sorted(pairs))
        secret = hmac.new(b'WebAppData', TG_TOKEN.encode(), hashlib.sha256).digest()
        calc = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
        if calc == their_hash:
            user = json.loads(pairs.get('user', '{}'))
            return user.get('id')
    except Exception:
        return None
    return None


def totals_today(uid):
    n = 0
    for s in jget(f'gs:u:{uid}:sessions', []):
        if s.get('day') == day_key():
            n += len(s.get('trades', []))
    return n


def route(r, q, body, uid):
    if r == 'me':
        p = profile(uid)
        sessions = jget(f'gs:u:{uid}:sessions', [])
        files = jget(f'gs:u:{uid}:filleuls', [])
        return {'profile': p,
                'calibration': {'ok': p['demo_sessions_done'] >= 3,
                                'badge': f"{min(p['demo_sessions_done'], 3)}/3 sessions démo"},
                'sessions_today': sum(1 for s in sessions if s.get('day') == day_key()),
                'trades_today': totals_today(uid),
                'filleuls': {'total': len(files), 'qualified': sum(1 for f in files if f.get('qualified')),
                             'balance': p.get('ref_balance', 0.0),
                             'can_withdraw': sum(1 for f in files if f.get('qualified')) >= REF_WITHDRAW_MIN}}

    if r == 'limits':
        sessions = jget(f'gs:u:{uid}:sessions', [])
        return {'sessions_today': sum(1 for s in sessions if s.get('day') == day_key()),
                'trades_today': totals_today(uid),
                'max_sessions': MAX_SESSIONS_DAY, 'max_trades': MAX_TRADES_DAY,
                'max_trades_session': MAX_TRADES_SESSION}

    if r == 'sessions':
        return {'sessions': jget(f'gs:u:{uid}:sessions', [])[-50:]}

    if r == 'session':  # POST — créer une session
        sessions = jget(f'gs:u:{uid}:sessions', [])
        today = sum(1 for s in sessions if s.get('day') == day_key())
        if today >= MAX_SESSIONS_DAY:
            return ({'error': 'Plafond atteint : 3 sessions par jour.'}, 400)
        max_tr = min(int(body.get('max_trades') or 5), MAX_TRADES_SESSION)
        s = {'id': body.get('id') or f's{int(time.time() * 1000)}',
             'day': day_key(),
             'symbol': str(body.get('symbol', 'XAU/USD'))[:12],
             'tf': str(body.get('tf', 'M5'))[:4],
             'lot': float(body.get('lot') or 0.01),
             'max_trades': max_tr, 'sl_pts': float(body.get('sl_pts') or 20),
             'tp_pts': float(body.get('tp_pts') or 40),
             'mode': 'demo', 'status': 'active',
             'opened_at': time.strftime('%H:%M', time.gmtime(time.time() + 3600)),
             'trades': [], 'pnl_total': 0.0}
        sessions.append(s)
        jset(f'gs:u:{uid}:sessions', sessions)
        return {'session': s}

    if r == 'trade':  # POST — ouvrir un trade dans une session
        sessions = jget(f'gs:u:{uid}:sessions', [])
        sid = str(body.get('session_id'))
        s = next((x for x in sessions if x['id'] == sid), None)
        if not s or s.get('status') != 'active':
            return ({'error': 'Session introuvable ou terminée.'}, 400)
        if totals_today(uid) >= MAX_TRADES_DAY:
            return ({'error': 'Plafond atteint : 15 trades par jour.'}, 400)
        if len(s['trades']) >= s.get('max_trades', MAX_TRADES_SESSION):
            s['status'] = 'terminee'
            jset(f'gs:u:{uid}:sessions', sessions)
            return ({'error': 'Session complète (max trades).'}, 400)
        t = {'id': f't{int(time.time() * 1000)}',
             'direction': 'BUY' if str(body.get('direction', '')).upper() in ('BUY', 'ACHAT') else 'SELL',
             'entry': float(body.get('entry')), 'sl': float(body.get('sl')),
             'tp': float(body.get('tp')), 'lot': float(body.get('lot') or s['lot']),
             'status': 'open', 'pnl': 0.0,
             'smc': {k: body.get('smc', {}).get(k) for k in ('structure', 'bos', 'choch', 'ob', 'fvg', 'sweep', 'reason')}}
        s['trades'].append(t)
        jset(f'gs:u:{uid}:sessions', sessions)
        return {'trade': t}

    if r == 'trade_close':  # POST — clôturer
        sessions = jget(f'gs:u:{uid}:sessions', [])
        sid, tid = str(body.get('session_id')), str(body.get('trade_id'))
        s = next((x for x in sessions if x['id'] == sid), None)
        if not s:
            return ({'error': 'Session introuvable.'}, 400)
        t = next((x for x in s['trades'] if x['id'] == tid), None)
        if not t:
            return ({'error': 'Trade introuvable.'}, 400)
        won = body.get('result') == 'tp'
        t.update({'status': 'tp' if won else 'sl', 'exit': float(body.get('exit') or 0),
                  'pnl': round(float(body.get('pnl') or 0), 2),
                  'closed_at': time.strftime('%H:%M', time.gmtime(time.time() + 3600))})
        opened = [x for x in s['trades'] if x['status'] != 'open']
        s['pnl_total'] = round(sum(x['pnl'] for x in opened), 2)
        if len(s['trades']) >= s.get('max_trades', MAX_TRADES_SESSION) and not any(x['status'] == 'open' for x in s['trades']):
            s['status'] = 'terminee'
            p = profile(uid)
            p['demo_sessions_done'] = p.get('demo_sessions_done', 0) + 1
            jset(f'gs:u:{uid}:profile', p)
        jset(f'gs:u:{uid}:sessions', sessions)
        return {'trade': t, 'pnl_total': s['pnl_total'], 'session_status': s['status']}

    if r == 'accounts':
        return {'accounts': jget(f'gs:u:{uid}:accs', [])}

    if r == 'account':  # POST
        accs = jget(f'gs:u:{uid}:accs', [])
        a = {'id': f'a{int(time.time() * 1000)}', 'label': str(body.get('label', 'Compte MT5'))[:40],
             'login': str(body.get('login', ''))[:32], 'server': str(body.get('server', ''))[:60],
             'kind': 'demo_local'}
        accs.append(a)
        jset(f'gs:u:{uid}:accs', accs)
        return {'account': a}

    if r == 'referral':
        p = profile(uid)
        files = jget(f'gs:u:{uid}:filleuls', [])
        return {'code': p['ref_code'],
                'link': f"https://t.me/Ghost_rskia_bot?start={p['ref_code']}",
                'filleuls': files, 'balance': p.get('ref_balance', 0.0),
                'can_withdraw': sum(1 for f in files if f.get('qualified')) >= REF_WITHDRAW_MIN}

    if r == 'join':  # POST {ref}
        code = str(body.get('ref', ''))[:16]
        if not code:
            return ({'error': 'Code invalide.'}, 400)
        owner = rdb('GET', f'gs:ref:{code}')
        p = profile(uid)
        if owner and owner != uid and not p.get('referred_by'):
            p['referred_by'] = code
            jset(f'gs:u:{uid}:profile', p)
            files = jget(f'gs:u:{owner}:filleuls', [])
            files.append({'uid': uid[:16], 'qualified': False,
                          'since': time.strftime('%Y-%m-%d')})
            jset(f'gs:u:{owner}:filleuls', files)
            return {'ok': True, 'referred_by': code}
        jset(f'gs:ref:{p["ref_code"]}', uid)
        return {'ok': False}

    return ({'error': 'route inconnue'}, 404)


class handler(BaseHTTPRequestHandler):

    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        data = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, X-Telegram-Init')
        self.end_headers()
        self.wfile.write(data)

    def _uid(self, q):
        tg = check_telegram(self.headers.get('X-Telegram-Init', ''))
        if tg:
            return f'tg_{tg}'
        return str((q.get('uid') or [''])[0])[:64] or 'guest'

    def do_OPTIONS(self):
        self._json({})

    def do_GET(self):
        q = parse_qs(urlparse(self.path).query)
        r = (q.get('r') or ['me'])[0]
        try:
            out = route(r, q, {}, self._uid(q))
            if isinstance(out, tuple):
                return self._json(out[0], out[1])
            return self._json(out)
        except RuntimeError:
            return self._json({'offline': True, 'hint': 'Upstash non configuré — mode local.'})
        except Exception as e:
            return self._json({'error': str(e)[:200]}, 500)

    def do_POST(self):
        try:
            size = int(self.headers.get('Content-Length') or 0)
            body = json.loads(self.rfile.read(size) or b'{}')
        except Exception:
            body = {}
        q = parse_qs(urlparse(self.path).query)
        r = (q.get('r') or [''])[0]
        uid = self._uid(q) or str(body.get('uid', 'guest'))[:64]
        try:
            out = route(r, q, body, uid)
            if isinstance(out, tuple):
                return self._json(out[0], out[1])
            return self._json(out)
        except RuntimeError:
            return self._json({'offline': True, 'hint': 'Upstash non configuré — mode local.'})
        except Exception as e:
            return self._json({'error': str(e)[:200]}, 500)
