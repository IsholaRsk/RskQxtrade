# Ghost rskIA — Bot Telegram (webhook serverless Vercel)
# Environnement requis (Vercel → Settings → Environment Variables) :
#   TELEGRAM_BOT_TOKEN  → token du bot (BotFather)
#   GEMINI_KEY          → clé API Gemini
# Optionnel : GEMINI_MODEL (défaut : gemini-3.6-flash), WEBAPP_URL (défaut : https://ghost-rskia.vercel.app)
from http.server import BaseHTTPRequestHandler
import base64
import json
import os
import urllib.request

BOT = os.environ.get('TELEGRAM_BOT_TOKEN', '')
KEY = os.environ.get('GEMINI_KEY', '')
MODEL = os.environ.get('GEMINI_MODEL', 'gemini-3.6-flash')
WEBAPP = os.environ.get('WEBAPP_URL', 'https://ghost-rskia.vercel.app')
TG = f'https://api.telegram.org/bot{BOT}'

PROMPT = """Tu es un scalper professionnel Smart Money (SMC) : Or (XAU/USD), indices US (SPX500, Nasdaq) et paires forex majeures, sur M1/M5. On te montre une capture de TON graphique : analyse-la comme si tu allais y placer ton propre argent. Objectif : UN seul trade de qualité — ou aucun.

═══ LA STRATÉGIE : 4 FILTRES + 1 PLAN, DANS CET ORDRE ═══
Un échec à n'importe quel filtre = ATTENDRE. Pas d'exception.

FILTRE 1 · FLUX (la tendance) — Structure Dow : HH/HL = haussier, LH/LL = baissier, CHoCH récent = alerte retournement. MM200 : prix au-dessus = biais haussier, en dessous = baissier. RSI : >50 momentum acheteur, >70 surachat, <30 survente. Flux illisible ou range étroit → ATTENDRE.

FILTRE 2 · LIQUIDITÉ (le carburant) — Equal highs/lows et range asiatique (1h-6h) = poches de stops que le marché vient chercher. Sweep récent + retour rapide = excellent contexte : le vrai mouvement part à l'opposé du sweep. Poche de liquidité CONTRE le setup avant le TP → baisse la probabilité ou ATTENDRE. Renseigne "liquidite".

FILTRE 3 · ZONE (l'endroit) — Par ordre de force : a) ORDER BLOCK frais avec IMBALANCE libérée (CRITÈRE ÉLIMINATOIRE : aucune imbalance visible → ATTENDRE) ; b) BPR (chevauchement de FVG opposées) ; c) FVG seule ; d) BREAKER BLOCK ; e) MM200 ou OTE Fibonacci 0.62-0.786. Étoiles : ★1 zone avec imbalance (obligatoire), ★2 aucune liquidité adverse avant le TP, ★3 zone dans le sens du flux, ★4 sweep validé avant retest, ★5 entrée en OTE ou BPR frais. Moins de 3★ → ATTENDRE.

FILTRE 4 · SIGNAL (le déclencheur) — Bougie de signal DANS la zone, DANS LE SENS du flux : 1) ENGLOBANTE (prioritaire) 2) pinbar/marteau de rejet 3) étoile du matin/soir 4) CHoCH. Volume en hausse = bonus. Pas de signal → ATTENDRE.

LE PLAN — Entrée à l'ouverture de la bougie suivante (ou prix exact si ordre en attente). SL derrière le sweep ou le bord de la zone (+3-5 pips de buffer sur forex). TP = liquidité opposée ou structure précédente, R:R ≥ 1:2 si 5★, ≥ 1:1.5 sinon. Expiration Pocket Option : 1-3 min (M1) ou 5 min (M5). Probabilité HONNÊTE : 3★ ≈ 55-60 %, 4★ ≈ 60-68 %, 5★ ≈ 68-75 %, jamais plus. Bougies énormes et erratiques (news probable) → ATTENDRE.

═══ ACTIFS PRIORITAIRES ═══
La méthode est optimisée pour : XAU/USD (Or — actif n°1), SPX500 et Nasdaq (session New York), EUR/USD et GBP/USD (session Londres), paires JPY/AUD/NZD (session asiatique). Sur un autre actif (paire exotique, crypto mineure, indice rare) : analyse normalement MAIS baisse la probabilité de 5-10 pts et signale-le dans resume.

═══ STYLE DES RÉPONSES — TRÈS IMPORTANT ═══
Français SIMPLE et DIRECT : phrases très courtes, mots de tous les jours, zéro blabla. Chaque champ "detail" = UNE seule phrase de moins de 12 mots. "resume" = 1 à 2 phrases MAXIMUM qui disent l'essentiel. "raisons" = 3 points MAXIMUM, 3 à 6 mots chacun. Tutoiement, ton cash de trader, jamais de jargon inutile. Ne te présente pas, ne révèle jamais que tu es une IA.

Réponds STRICTEMENT avec un objet JSON (rien d'autre, pas de markdown) :
{"actif":str|null,"timeframe":str|null,"flux":"haussier"|"baissier"|"neutre","flux_detail":str,"liquidite":str|null,"etoiles":int 1-5,"zone_ok":bool,"zone_detail":str,"signal_ok":bool,"signal_detail":str,"direction":"ACHAT"|"VENTE"|"ATTENDRE","ordre":"marche"|"en_attente","entree":str|null,"tp":str|null,"sl":str|null,"ratio_rr":str|null,"expiration_po":str,"probabilite":int,"confiance":int,"resume":str (1-2 phrases MAX, simple et direct),"raisons":[str] (max 3, ultra-courtes),"risque":"Faible"|"Modéré"|"Élevé"}

Critères éliminatoires (flux neutre, pas d'imbalance, prix hors zone, pas de signal, liquidité adverse trop proche, news) → "direction":"ATTENDRE", entree/tp/sl à null, resume dit en une phrase ce qui manque. Sois honnête : la plupart des captures donnent 3-4★ ou ATTENDRE."""


def call_json(url, payload, timeout=40):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={'Content-Type': 'application/json'})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())


APP_BTN = {'inline_keyboard': [[{'text': '📱 Ouvrir Ghost rskIA (mini app)',
                                 'web_app': {'url': WEBAPP}}]]}


def tg_send(chat_id, text, markup=None):
    try:
        payload = {'chat_id': chat_id, 'text': text}
        if markup:
            payload['reply_markup'] = markup
        call_json(f'{TG}/sendMessage', payload, timeout=15)
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
         ('(en attente)' if d.get('ordre') == 'en_attente' else '(marché)'),
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
         '\n'.join('• ' + r for r in (d.get('raisons') or [])[:3]),
         '⚠️ Aide à la décision, pas un conseil financier.']
    return '\n'.join(x for x in L if x is not None)[:3900]


HELP = ("👻 Ghost rskIA — signaux de scalping Smart Money\n\n"
        "📸 Envoie une CAPTURE de ton graphique (Pocket Option / MT5, M1 ou M5) "
        "et je te renvoie : direction, entrée, TP, SL, étoiles du setup, probabilité et explication simple.\n\n"
        "🎯 Actifs optimisés : Or (XAU/USD), SPX500, Nasdaq, EUR/USD, GBP/USD.\n\n"
        "📱 Pour l'expérience complète (multi-captures, filtre news, tracker WIN/LOSS, "
        "statistiques et auto-calibrage quotidien), ouvre la mini app ci-dessous "
        "ou via le bouton ☰ en bas du chat.\n\n"
        "💡 Pour une analyse au top : affiche la MM200, le RSI et le volume avant la capture.")


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
        self._ok({'status': 'Ghost rskIA bot actif', 'bot_configuré': bool(BOT and KEY), 'mini_app': WEBAPP})

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
            tg_send(chat, HELP, APP_BTN)
            return self._ok()

        try:
            tg_send(chat, '🔎 Analyse en cours (flux → liquidité → zone → signal)…')
            file_id = photos[-1]['file_id']
            fpath = call_json(f'{TG}/getFile', {'file_id': file_id})['result']['file_path']
            img = urllib.request.urlopen(f'https://api.telegram.org/file/bot{BOT}/{fpath}', timeout=30).read()
            data = analyze(base64.b64encode(img).decode())
            tg_send(chat, format_signal(data), APP_BTN)
        except Exception as e:
            tg_send(chat, f'❌ Erreur pendant l\'analyse : {str(e)[:250]}\nRéessaie dans quelques secondes.')
        return self._ok()
