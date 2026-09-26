# 🤖 AUTOBOT SNIPER Ghost rskIA — Installation (10 min)

Le bot trade **ton compte MT5 (classique)** tout seul, 100 % dans le cloud — aucun PC allumé requis. Fonctionne avec **n'importe quel broker MT5, y compris le MT5 de Pocket Option**.

**Marchés : XAUUSD · NAS100 · GBPUSD · BTCUSD** (détectés automatiquement sous leur nom exact chez ton broker : GOLD, USTEC, US100…).

## Architecture (gratuite)

```
cron-job.org (ping 1/min, gratuit)
  → https://ghost-rskia.vercel.app/api/autobot
      ├─ Bougies M5 + M15 des 4 marchés via MetaAPI (compte MT5 hébergé dans leur cloud)
      ├─ Graphiques rendus côté serveur (MM200 + volume), analyses en parallèle
      ├─ Analyse IA SNIPER : sweep liquidité → CHoCH/BOS M5 → OB frais + FVG
      |    Règles : ≥4★ · flux M15 aligné · R:R ≥ 1:2 · risque 1%
      |    4 trades/jour max · 2 simultanés max · stop après 2 pertes
      |    killzone New York 14h-20h Paris · filtre news réel
      └─ Ordres placés via MetaAPI (SL/TP inclus, breakeven à +1R)
État & journal : Upstash Redis (gratuit) — positions gérées même hors killzone
```

---

## Étape 1 — MetaAPI (connecter ton MT5) ⏱ 4 min

1. Va sur **app.metaapi.cloud** → crée un compte gratuit
2. **Accounts → New account** → entre :
   - login + mot de passe de ton compte MT5 (Pocket Option MT5 ou autre broker)
   - le **serveur** exact (affiché dans MT5 → Fichier → Ouvrir un compte, ex. `PocketOption-Server`)
3. Attends le statut **« Deployed »** (2-3 min) puis note :
   - **Account ID** (dans la fiche du compte)
   - **Token API** : profile → **API access → token** (copie-le)

> 💡 Commence avec un compte **DÉMO** : l'autobot peut trader un compte démo exactement pareil.

## Étape 2 — Upstash Redis (mémoire du bot) ⏱ 2 min

1. **console.upstash.com** → compte gratuit → **Create Database** (région proche, type `regional`)
2. Onglet **REST API** → copie `UPSTASH_REDIS_REST_URL` et `UPSTASH_REDIS_REST_TOKEN`

## Étape 3 — Variables sur Vercel ⏱ 2 min

Projet `ghost-rskia` → **Settings → Environment Variables** (Production) :

| Nom | Valeur |
|---|---|
| `METAAPI_TOKEN` | ton token MetaAPI |
| `METAAPI_ACCOUNT_ID` | ton Account ID |
| `UPSTASH_REDIS_REST_URL` | URL Upstash |
| `UPSTASH_REDIS_REST_TOKEN` | token Upstash |
| `TRADING_ENABLED` | **laisser VIDE = DRY-RUN sûr** · mettre `true` plus tard pour le réel |

(`ANALYZE_TOKEN`, `GEMINI_KEY` et `TELEGRAM_BOT_TOKEN` sont déjà en place.)

## Étape 4 — Le déclencheur chaque minute ⏱ 1 min

1. **cron-job.org** → compte gratuit → **Create cronjob**
2. URL : `https://ghost-rskia.vercel.app/api/autobot?key=TON_ANALYZE_TOKEN`
3. Intervalle : **toutes les 1 minute** · Save & enable

## Étape 5 — Vérifier ⏱ 1 min

Ouvre : `https://ghost-rskia.vercel.app/api/autobot`
→ tu dois voir `configuré: {token:true, gemini:true, metaapi:true, redis:true}` et le **journal** (log) des dernières actions.

---

## 🛡️ Sécurité intégrée (non négociable)

- **Mode DRY-RUN par défaut** : le bot journalise chaque signal qu'il *aurait* tradé (avec TP/SL virtuels suivis 90 min), sans toucher au compte
- **Règles de risque en dur** : 1 %/trade · **≥4★ sniper** (sweep + CHoCH/BOS + OB+imbalance + flux M15) · R:R ≥ 1:2 · max 4 trades/jour · **2 positions simultanées max (1 par marché)** · stop après 2 pertes/jour · analyses uniquement en killzone New York (14h-20h Paris) · aucun trade autour d'une news USD/GBP majeure
- **Cooldown anti-revanche** : 15 min après clôture, 30 min après une perte, par marché
- **Breakeven à +1R** automatique, positions gérées même hors killzone
- Passage en réel (`TRADING_ENABLED=true`) uniquement après 2 semaines de DRY-RUN/démo avec profit factor ≥ 1,3
- ⚠️ Le trading automatisé peut perdre de l'argent. N'active le réel qu'avec de l'argent que tu peux perdre.

## 🔧 Options (env)

`SYMBOLS` (défaut `XAUUSD,NAS100,GBPUSD,BTCUSD`) · `RISK_PCT` (1.0) · `MIN_STARS` (4) · `MIN_RR` (2.0) · `MAX_TRADES_DAY` (4) · `MAX_LOSSES_DAY` (2) · `MAX_SIMULT` (2) · `SESSION_START` (`14:00`) · `SESSION_END` (`20:00`, heure de Paris)

Pour un autre créneau : modifie `SESSION_START`/`SESSION_END`. Les noms de symboles sont résolus automatiquement (XAUUSD→GOLD, NAS100→USTEC/US100…).

*En cas d'erreur MetaAPI, le journal (`GET /api/autobot`) montre l'erreur exacte — envoie-la-moi.*
