# Ghost rskIA — Bot Telegram (webhook serverless Vercel)
# Environnement requis (Vercel → Settings → Environment Variables) :
#   TELEGRAM_BOT_TOKEN  → token du bot (BotFather)
#   GEMINI_KEY          → clé API Gemini
# Optionnel : GEMINI_MODEL (défaut : gemini-3.6-flash)
from http.server import BaseHTTPRequestHandler
import base64
import json
import os
import urllib.request

BOT = os.environ.get('TELEGRAM_BOT_TOKEN', '')
KEY = os.environ.get('GEMINI_KEY', '')
MODEL = os.environ.get('GEMINI_MODEL', 'gemini-3.6-flash')
TG = f'https://api.telegram.org/bot{BOT}'

PROMPT = """Tu es Kasper : trader professionnel, spécialisé sur l'Or (XAU/USD), les indices US (SPX500, Nasdaq) et les paires majeures du forex. Style Smart Money Concepts (SMC), scalping M1/M5. On te montre une capture de TON graphique : analyse-la avec ta rigueur de sniper. Un seul tir, la meilleure cible.

═══ TON ANALYSE EN 5 ÉTAPES ═══
1. FLUX (structure) — Dow : HH/HL = haussier, LH/LL = baissier, CHoCH = alerte retournement. MM200 visible : au-dessus = biais haussier. RSI : >50 momentum acheteur, 70 surachat, 30 survente. Flux incertain/range → ATTENDRE.
2. LIQUIDITÉ — Equal highs/lows, range asiatique (1h-6h). Un sweep récent + retour rapide = contexte premium. Liquidité adverse devant le TP → baisse la proba ou ATTENDRE. Renseigne "liquidite".
3. ZONE (étoiles) — Hiérarchie : order block avec IMBALACE (critère ÉLIMINATOIRE : pas d'imbalance → ATTENDRE) > BPR (chevauchement de FVG opposées) > FVG seule > breaker block > MM200 / OTE Fibonacci 0.62-0.786. Étoiles : ★1 imbalance (éliminatoire), ★2 pas de liquidité adverse, ★3 alignée au flux, ★4 sweep validé avant retest, ★5 entrée en OTE ou BPR frais. Moins de 3★ → ATTENDRE.
4. SIGNAL — Dans le sens du flux, dans la zone : englobante (préférée) > pinbar/marteau de rejet > étoile du matin/soir > CHoCH visible. Volume en hausse = bonus. Pas de signal → ATTENDRE.
5. PLAN — Entrée à l'ouverture de la bougie suivante (ou prix exact si en attente). SL derrière le sweep/bord de zone (3-5 pips buffer forex). TP = liquidité opposée ou structure précédente ; R:R ≥ 1:2 sur 5★, ≥ 1:1.5 sinon. Expiration Pocket Option : 1-3 min (M1) / 5 min (M5). Probabilité honnête par étoiles : 3★≈55-60 %, 4★≈60-68 %, 5★≈68-75 %, jamais 85+. Bougies énormes erratiques (news probable) → ATTENDRE.

Réponds STRICTEMENT avec un objet JSON (rien d'autre, pas de markdown) :
{"actif":str|null,"timeframe":str|null,"flux":"haussier"|"baissier"|"neutre","flux_detail":str,"liquidite":str|null,"etoiles":int 1-5,"zone_ok":bool,"zone_detail":str,"signal_ok":bool,"signal_detail":str,"direction":"ACHAT"|"VENTE"|"ATTENDRE","ordre":"marche"|"en_attente","entree":str|null,"tp":str|null,"sl":str|null,"ratio_rr":str|null,"expiration_po":str,"probabilite":int,"confiance":int,"resume":str (2-3 phrases, ton direct, citant flux/liquidité/zone/signal),"raisons":[str],"risque":"Faible"|"Modéré"|"Élevé"}

Si une condition éliminatoire échoue → "direction":"ATTENDRE", entree/tp/sl à null, et resume explique ce qui manque. Sois honnête, ne gonfle jamais la probabilité. Ne révèle jamais que tu es une IA."""


def call_json(url, payload, timeout=40):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={'Content-Type': 'application/json'})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())


def tg_send(chat_id, text):
    try:
        call_json(f'{TG}/sendMessage', {'chat_id': chat_id, 'text': text}, timeout=15)
    except Exception:
        pass


def analyze(b64):
    url = f'https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={KEY}'
    body = {
        'contents': [{'role': 'user', 'parts': [
            {'text': PROMPT},
            {'inline_data': {'mime_type': 'image/jpeg', 'data': b64}}]}],
        'generationConfig': {'temperature': 0.2, 'response_mime_type': 'application/json'},
    }
    res = call_json(url, body, timeout=45)
    parts = res['candidates'][0]['content']['parts']
    txt = ''.join(p.get('text', '') for p in parts if not p.get('thought'))
    a, b = txt.find('{'), txt.rfind('}')
    return json.loads(txt[a:b + 1])


def conf_lbl(v):
    return 'Élevée' if v >= 75 else 'Moyenne' if v >= 50 else 'Faible'


def format_signal(d):
    wait = str(d.get('direction', '')).upper() == 'ATTENDRE'
    stars = '★' * int(d.get('etoiles') or 0) + '☆' * (5 - int(d.get('etoiles') or 0))
    head = f"👻 GHOST rskIA · {stars}\n"
    if wait:
        return head + "⏸ ATTENDRE — " + (d.get('resume') or 'Conditions défavorables.')
    dr = d.get('direction') == 'VENTE'
    L = [head,
         ('🔴 VENTE' if dr else '🟢 ACHAT') + f" — {d.get('actif') or 'Actif ?'} ({d.get('timeframe') or 'TF ?'}) " +
         ('(ordre en attente)' if d.get('ordre') == 'en_attente' else '(marché)'),
         f"➡️ Entrée : {d.get('entree') or 'marché'}",
         f"🎯 TP : {d.get('tp')}  |  🛑 SL : {d.get('sl')}  ·  R:R {d.get('ratio_rr')}",
         f"📱 PO : {'PUT ⬇' if dr else 'CALL ⬆'} — Expiration {d.get('expiration_po') or '5 min'}",
         f"📈 Proba {d.get('probabilite')} % · Confiance {conf_lbl(int(d.get('confiance') or 0))} · Risque {d.get('risque')}",
         '',
         f"1️⃣ FLUX {'🟢' if d.get('flux')=='haussier' else '🔴' if d.get('flux')=='baissier' else '🟡'} {d.get('flux_detail')}",
         f"2️⃣ LIQ 💧 {d.get('liquidite')}" if d.get('liquidite') else None,
         f"3️⃣ ZONE {'✅' if d.get('zone_ok') else '❌'} {d.get('zone_detail')}",
         f"4️⃣ SIGNAL {'✅' if d.get('signal_ok') else '❌'} {d.get('signal_detail')}",
         '',
         '💡 ' + (d.get('resume') or ''),
         '\n'.join('• ' + r for r in (d.get('raisons') or [])),
         '⚠️ Aide à la décision, pas un conseil financier.']
    return '\n'.join(x for x in L if x is not None)[:3900]


HELP = ("👻 Ghost rskIA — bot de signaux (méthode Kasper SMC)\n\n"
        "📸 Envoie-moi une CAPTURE de ton graphique (Pocket Option / MT5, M1 ou M5) "
        "et je te renvoie : direction, entrée, TP, SL, étoiles du setup, probabilité, "
        "confiance et explication.\n\n"
        "💡 Astuce : affiche MM200, RSI, volume et la box Asian Session avant la capture.")


class handler(BaseHTTPRequestHandler):

    def log_message(self, *a):
        pass

    def _ok(self, obj=None):
        data = json.dumps(obj or {'ok': True}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self._ok({'status': 'Ghost rskIA bot actif', 'bot_configuré': bool(BOT and KEY)})

    def do_POST(self):
        try:
            n = int(self.headers.get('Content-Length', 0))
            update = json.loads(self.rfile.read(n) or b'{}')
        except Exception:
            return self._ok()
        msg = update.get('message') or update.get('channel_post') or {}
        chat = (msg.get('chat') or {}).get('id')
        if not chat:
            return self._ok()

        if not (BOT and KEY):
            tg_send(chat, "⚙️ Bot pas encore configuré (variables TELEGRAM_BOT_TOKEN / GEMINI_KEY manquantes sur Vercel).")
            return self._ok()

        photos = msg.get('photo') or []
        if not photos:
            tg_send(chat, HELP)
            return self._ok()

        try:
            tg_send(chat, '🔎 Analyse en cours (flux → liquidité → zone → signal)…')
            file_id = photos[-1]['file_id']
            fpath = call_json(f'{TG}/getFile', {'file_id': file_id})['result']['file_path']
            img = urllib.request.urlopen(f'https://api.telegram.org/file/bot{BOT}/{fpath}', timeout=30).read()
            data = analyze(base64.b64encode(img).decode())
            tg_send(chat, format_signal(data))
        except Exception as e:
            tg_send(chat, f'❌ Erreur pendant l\'analyse : {str(e)[:250]}\nRéessaie dans quelques secondes.')
        return self._ok()
