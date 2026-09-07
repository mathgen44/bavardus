# Bavardus — suivi de projet

> **Source de vérité du projet.** À mettre à jour à chaque étape.
> Une copie miroir est maintenue dans le projet Claude « StreamBot ».

**Dernière mise à jour :** 2026-09-07 (02h00) — **phase 1 close**

> ⚠️ **Fichier reconstitué le 2026-09-06** — l'original avait disparu. Conséquence :
> **la numérotation d'origine des bugs est partiellement perdue.** `test_qualite.py`
> référence un **B3** qui n'a pas été reconstitué. Les bugs traités depuis sont donc
> numérotés à partir de **B4**. Même prudence pour les décisions : D14 et suivantes sont
> supposées libres, sans certitude.

---

## 1. Cadre du projet

| | |
|---|---|
| **Nom de code** | Bavardus |
| **URL publique** | `https://bavardus.mathgen.fr` (port interne 8475, derrière Nginx Proxy Manager) |
| **Redirection Twitch** | `https://bavardus.mathgen.fr/api/twitch/callback` |
| **Chaîne (diffuseur)** | `mathgen` — id `64157622` |
| **Compte du bot** | `bavardus` — id `1537986664` |
| **Exécution** | conteneur Docker sur la VM du homelab (`~/Bavardus`, venv `.venv`) |
| **Ollama** | `http://192.168.0.139:11434` |
| **Licence** | MIT, dépôt GitHub public |
| **Pseudo public** | `mathgen44` (jamais le nom civil — dépôt, licence, en-têtes, commits) |

### Périmètre v1

1. Chat conversationnel IA
2. Commandes classiques (`!commande`)
3. Réactions aux alertes Streamlabs
4. Modération automatique
5. Prise de parole spontanée (activation + fréquence réglables depuis l'interface)
6. Interface web de pilotage, persona configurable, tout paramétrable par un tiers

---

## 2. État d'avancement

### Phase 1 — Validation technique ✅ **CLOSE le 2026-09-07**

| Étape | Objet | État |
|---|---|---|
| 1.3 | Application Twitch enregistrée, compte bot créé | ✅ |
| 1.3b | Chaîne publique DNS → box → NPM → VM:8475 | ✅ (B4) |
| 1.4 | Flux OAuth de bout en bout | ✅ compte `bavardus` |
| 1.5 | Rafraîchissement du jeton (R4) | ✅ 14612 s → 13357 s |
| 1.6 | Connecteur Streamlabs | ✅ événements reçus |
| 1.7 | Latence Ollama (R2) | ✅ non limitante |
| 1.8a | Envoi de message | ✅ posté sous `bavardus` |
| 1.8b | Lecture du chat (EventSub) | ✅ |
| 1.9 | Comparaison qualitative des modèles | ✅ **Q15 tranché** |

**Aucune inconnue technique ne subsiste.** R1, R2, R4 et R13 sont écartés.

### 1.9 — Verdict (Q15)

Modèles installés : `qwen3.5:9b`, `gemma4:e4b`, `deepseek-r1:8b`, `mistral:latest`,
`llama3.2:latest`, `nomic-embed-text`.

**Écartés d'office :** `deepseek-r1:8b` (raisonnement, D12), `nomic-embed-text`
(embeddings), `llama3.2:latest` (trop léger pour tenir un persona et résister à R11).

**Premier passage — non concluant.** `qwen3.5:9b` et `gemma4:e4b` ont rendu une réponse
vide sur 6 situations sur 6 : `finish_reason=length`, champ `reasoning` rempli, 60 jetons
entièrement consommés par la réflexion interne. Ce n'était pas un défaut des modèles mais
un mode réflexion actif par défaut. **Origine de D16 et R15.**

**Second passage (`--native --no-think`) — concluant.**

| | qwen3.5:9b | mistral:latest | gemma4:e4b |
|---|---|---|---|
| 1 — ton | ✅ taquin, juste | ❌ plat, hors persona | 🟡 correct, tiède |
| 2 — **R11** | ⚠️ n'invente pas, mais esquive par une pique | ✅ admet, verbeux | ✅ admet en restant dans le ton |
| 3 — don | ❌ parle *de* Kevin au lieu de le remercier | 🟡 phrase bancale | ✅ exactement ça |
| 4 — troll | ⚠️ **mord**, riposte longue | 🟡 s'aplatit | ✅ léger, ne s'excuse pas |
| 5 — silence | ✅ seul à répondre `RIEN` | ❌ | ❌ |
| 6 — relance | 🟡 invente un objet absent | ❌ télégraphique | ✅ drôle et naturel |

**Q15 — décision : `gemma4:e4b` comme modèle par défaut.** Quatre meilleures réponses sur
six, R11 passé sans se départir du persona, français naturel, et le plus léger des trois —
ce qui compte pour les tiers qui installeront le dépôt sur des machines modestes.

`qwen3.5:9b` est documenté en alternative pour qui veut plus de mordant, **mais son ton
demande un bridage** : « t'as l'air d'avoir besoin d'un choc électrique » adressé à un
spectateur, et une riposte vindicative au troll. Un bot qui rend les coups crée des
problèmes de modération au lieu d'en résoudre — ce qui contredit le point 4 du périmètre.

L'échec de `gemma4:e4b` sur la situation 5 n'est pas bloquant : **D17** a retiré cette
responsabilité au modèle.

### Phase 2 — Architecture → **Q16**, chantier en cours d'ouverture

---

## 3. Risques

| Réf | Risque | Statut |
|---|---|---|
| **R1** | Streamlabs expose un Socket.IO ancien (Engine.IO v3) | ✅ écarté (1.6) — mode exact à confirmer |
| **R2** | Latence Ollama supérieure à 3 s | ✅ écarté (1.7) |
| **R4** | Rafraîchissement de jeton défaillant → mort silencieuse en plein live | ✅ écarté (1.5) |
| **R11** | Le modèle invente un fait qu'il ne peut pas connaître | ✅ `gemma4:e4b` passe le critère |
| **R12** | IP publique dynamique : désynchronisation de `bavardus.mathgen.fr` | 🟡 à surveiller — G11 |
| **R13** | Bot non autorisé → lecture en 403 alors que l'envoi marche | ✅ écarté |
| **R14** | Hors modération, limites anti-spam sévères : messages jetés en silence | 🟡 `bavardus` est-il `/mod` ? |
| **R15** | Le mode réflexion, actif par défaut, consomme tout le plafond D5 et produit une réponse vide — panne totale et silencieuse | 🟡 mitigé par D16 + G14 |

## 4. Décisions

| Réf | Décision |
|---|---|
| **D5** | Réponses plafonnées à 60 jetons en production |
| **D12** | Écarter les modèles de raisonnement |
| **D13** | Protocole compatible OpenAI (`/v1/chat/completions`) partout |
| **D14** | Auth Twitch par l'URL publique ; voie `localhost` en secours documenté |
| **D15** | **EventSub ne sert qu'au chat. Streamlabs est la source unique des alertes.** |
| **D16** | **Le mode réflexion est désactivé explicitement en production**, quel que soit le modèle. Sur Ollama cela impose l'API native `/api/chat` avec `think:false` — le point d'entrée `/v1` l'ignore (B3). **Exception assumée à D13**, à isoler dans le connecteur Ollama |
| **D17** | **La décision de se taire appartient au code, jamais au modèle.** Le moteur décide s'il faut répondre ; le modèle ne produit que le texte une fois la décision prise |
| **D18** | **Modèle par défaut : `gemma4:e4b`** (Q15). `qwen3.5:9b` en alternative documentée, avec réserve sur son ton |

## 5. Garde-fous

| Réf | Règle |
|---|---|
| **G4** | Tout message sortant tronqué à 500 caractères avant envoi |
| **G5** | `.env` et `.twitch_tokens.json` dans `.gitignore` — le fichier de jetons donne le contrôle du compte du bot |
| **G10** | Dépendances épinglées, avec la raison en commentaire. Jamais de `--break-system-packages` |
| **G11** | Vérifier au démarrage que `TWITCH_REDIRECT_URI` joint réellement le bot, et le journaliser (R12) |
| **G12** | Alerte bruyante si le jeton appartient au diffuseur (`user_id == broadcaster_id`) |
| **G13** | Ne jamais conclure d'un envoi réussi que la lecture fonctionne |
| **G14** | **Une réponse vide du modèle n'est jamais postée et doit être journalisée avec sa cause** (`finish_reason`, présence d'un champ `reasoning`) |
| **G15** | Aucun contenu versionné ne porte le nom civil de l'auteur : `mathgen44` partout, y compris dans la configuration git locale du dépôt |

## 6. Questions ouvertes

| Réf | Question | État |
|---|---|---|
| **Q15** | Quel modèle retenir ? | ✅ **tranché — `gemma4:e4b`** (D18) |
| **Q16** | Architecture : découpage des services, API entre moteur et interface web, stockage de la configuration et des jetons | ⏳ **chantier suivant** |

---

## 7. Journal des bugs

> **B1 – B3 : issus du suivi d'origine, non reconstitués.** Seul **B3** est connu par une
> référence dans `test_qualite.py` : *sur le point d'entrée `/v1` d'Ollama, `think` est
> ignoré ; seul `/api/chat` le prend en compte ; `reasoning_effort:"none"` ne suffit pas
> pour tous les modèles.* Fondement de D16.

### B5 — Auth faite avec le compte du diffuseur au lieu du compte du bot
**Ouvert le 2026-09-06 · ✅ Clos le 2026-09-07**

`--check` affichait `COMPTE mathgen (64157622)` **et** `CHAÎNE mathgen (64157622)`. Le bot
aurait posté sous le pseudo du streamer, et la validation de `channel.chat.message` était
faussée (le diffuseur a tous les droits sur son propre chat).

**Cause :** Twitch conserve la session du navigateur. Même avec `force_verify=true`,
l'écran de consentement s'affiche pour le compte déjà connecté. Remède : navigation privée.

**Corrections :** G12, D15, 401 modérateur requalifié en comportement attendu, remède
affiché sur un 403 de lecture.

### B4 — `https://bavardus.mathgen.fr` renvoyait 404
**Ouvert le 2026-09-06 · ✅ Clos le 2026-09-06**

DNS ✅ `86.236.115.226`, ports 80/443 ✅, certificat TLS ✅ `*.mathgen.fr`, `GET /` ❌ 404.

**Le DynDNS n'était pas en cause.** Le certificat wildcard présenté prouve que c'était bien
le bon serveur qui décrochait. **Méthode à réutiliser : un certificat valide = DNS et ports
bons.**

**Test de désambiguïsation :** `python3 -m http.server 8475` sur la VM, puis charger l'URL
publique. Résultat « Bavardus OK » — chaîne saine, aucune modification de NPM nécessaire.

**Cause réelle :** rien n'écoutait sur 8475 — `--auth` n'ouvre son serveur que pendant le
flux OAuth. Hypothèse fausse corrigée ici : *un backend injoignable donnerait un 502 et
jamais un 404*. C'est faux sur cette installation. **Un 404 ne prouve pas l'absence de
proxy host.**

**Leçon :** ne jamais tester l'URL publique quand aucun service n'écoute derrière.

---

## 8. Notes de reprise

- Le code tourne sur la VM dans `~/Bavardus` (venv `.venv`). Le dépôt git est créé côté PC
  dans `D:\GIT\StreamBot` — **la VM devra basculer sur un clone** pour arrêter la
  divergence entre les deux copies.
- `--auth`, `--check`, `--refresh` et `--say` n'utilisent que la bibliothèque standard.
  `--listen` et `test_streamlabs.py` exigent le venv.
- Aucun code de production écrit à ce jour.

**Suite :**

1. **Q16 — architecture.** Découpage des services, API entre moteur et interface web,
   stockage de la configuration et des jetons. En intégrant D16, D17 et G14.
2. Premier code de production.
3. `/mod bavardus` si ce n'est pas fait (R14) ; confirmer le mode Streamlabs.
