# 👻 Ghost rskIA — Guide d'utilisation complet
### Stratégie Smart Money intégrée · Scalping Pocket Option / MT5

---

## 🕐 1. Les meilleures heures pour trader (heure de Paris ≈ Cotonou)

| Horaire | Session | Quoi faire |
|---|---|---|
| **1h – 6h** | 🌏 Asiatique | Elle **construit le range** (haut + bas) = tes futurs niveaux de liquidité. On prépare, on trade pas (sauf JPY/AUD). |
| **1h – 6h** | 🇦🇺 Sydney / 🇯🇵 Tokyo | Paires asiatiques actives : JPY, CNY, AUD, NZD. |
| **8h – 10h** | 🇬🇧 Ouverture Londres | EUR et GBP explosent, grosse bougie souvent vers **9h**. Sweeps du range asiatique fréquents → excellentes entrées. |
| **12h – 14h** | ⛔ Marché mort | **On ne trade pas.** Zéro volatilité, ranges piégeux. |
| **15h30 – 17h30** | 🗽 Ouverture New York | ✅ **LE meilleur créneau** : Or (XAU/USD), SPX500, Nasdaq, paires USD. Volatilité max entre 15h et 16h. |
| **News 4-5★** | ⛔ Zone interdite | Pas d'entrée **15 min avant ni après** une annonce majeure (NFP, CPI, Fed…). Vérifie *forexfactory.com* avant ta session. |

> 💡 **La volatilité est ton amie** : trade quand le marché bouge, jamais quand il dort.

---

## 📸 2. La capture d'écran parfaite

1. **Timeframe M1 ou M5** (le terrain du scalping) — M15 accepté pour le contexte.
2. **Indicateurs affichés** :
   - Moyenne mobile **200** (rouge, épaisse) — support/résistance + biais de tendance
   - **RSI** (>50 = momentum acheteur · 70 surachat · 30 survente)
   - **Volume** (valide les cassures)
   - 🎁 Bonus : l'indicateur gratuit **Asian Session** → [tradingview.com/script/QvTTZyiV](https://fr.tradingview.com/script/QvTTZyiV/)
3. **60 à 80 bougies visibles** + échelle des prix lisible à droite (le bot lit les prix pour ton entrée/TP/SL).
4. Colle avec **Ctrl+V** → **Analyser**.

---

## 🧠 3. Comment le bot analyse (4 filtres + 1 plan)

| Filtre | Ce que le bot vérifie | Règle |
|---|---|---|
| **1. FLUX** | Structure Dow (HH/HL ou LH/LL), CHoCH, position vs MM200, RSI | Neutre = on oublie. On ne trade QUE dans le sens du flux. |
| **2. LIQUIDITÉ** | Equal highs/lows, range asiatique = poches de stop loss | Un sweep récent dans ton sens = contexte premium. |
| **3. ZONE** | Order block + imbalance > BPR > FVG > breaker > MM200 / OTE 0.62-0.786 | ⚠️ **Pas d'imbalance = pas de trade** (critère éliminatoire). |
| **4. SIGNAL** | Englobante (prioritaire) > pinbar > étoile du matin | Volume en hausse = bonus. Pas de signal = on attend. |
| **PLAN** | Entrée bougie suivante · SL derrière le sweep/zone · TP = liquidité opposée | R:R ≥ 1:2 sur 5★ · ≥ 1:1.5 sinon. |

### ⭐ La notation en étoiles

| Étoiles | Signification | Action |
|---|---|---|
| ★ | Imbalance libérée à la création de la zone | Critère éliminatoire |
| ★★ | Aucune liquidité adverse sur le chemin | — |
| ★★★ | Dans le sens du flux (+ MM200 alignée) | ✅ **Minimum pour trader** |
| ★★★★ | Sweep de liquidité validé avant le retest | Beau setup (~60-68 %) |
| ★★★★★ | Entrée en OTE 0.62-0.786 ou BPR frais | 🎯 **Tir de sniper** (~68-75 %) |

### Le plan de trade reçu

- **Direction** : ACHAT / VENTE / ATTENDRE (jamais de trade sur ATTENDRE — « attendre est aussi une position »)
- **Entrée** : à l'ouverture de la bougie suivante, OU en attente au prix exact indiqué
- **SL / TP** placés **immédiatement** après l'entrée
- **Pocket Option** : expiration 1-3 min (M1) ou 5 min (M5)

---

## 🛡️ 4. Gestion du risque — NON NÉGOCIABLE

1. **1 % de ton capital par trade** au début (0,5 % si tu découvres). Les risques élevés (jusqu'à 10 %) sont réservés aux traders rentables en démo depuis 3+ mois.
2. **3 stop loss d'affilée → tu fermes la plateforme.** Pas dans 5 minutes. Tout de suite.
3. **Objectif journalier atteint (ex +2 %) → écrans éteints.** *« 2 % aujourd'hui et c'est fini. »*
4. **Jamais de martingale.** Doubler après une perte = compte cramé, surtout en binaire.
5. **Tiens un journal** : actif, heure, setup, étoiles, résultat → calcule ton winrate et profit factor chaque semaine.
6. **Compte DÉMO d'abord** (Pocket Option en offre un gratuit) — 2 semaines de validation avant le réel.

---

## 🥇 5. Les actifs prioritaires

- **OR (XAU/USD)** — le terrain de jeu n°1 (session NY)
- **SPX500 / Nasdaq** — ouverture US
- **EUR/USD, GBP/USD** — session Londres
- **JPY, AUD, NZD** — session asiatique
- **BTC/ETH** — 24/7 (volatilité élevée, spreads plus larges)

---

## 🧠 6. Auto-calibrage quotidien (apprentissage des pertes)

Chaque jour à **minuit**, l'IA passe en revue tous les trades que tu as marqués **WIN/LOSS** dans le journal. Elle identifie **la raison de chaque perte** (actif, heure, étoiles, direction, R:R, proba/confiance annoncées…) et mémorise les **paramètres influents** — **sans jamais modifier la stratégie**. Ces leçons servent uniquement à rendre ses calculs de **probabilité et de confiance de plus en plus justes**, jour après jour. Les leçons du jour sont visibles dans **Historique → Statistiques** (carte « Auto-calibrage IA »), et tu peux forcer une revue à tout moment.

---

## ⚠️ Avertissement

Ghost rskIA est une **aide à la décision** basée sur une stratégie Smart Money Concepts (flux → liquidité → zone → signal). Ce n'est **pas un conseil financier** ni une garantie de gains. Les options binaires et le trading à effet de levier comportent un risque élevé : tu peux perdre la totalité du capital engagé. Ne trade jamais d'argent dont tu as besoin.

---
*Ghost rskIA — deviens le sniper, pas la cible.* 👻
