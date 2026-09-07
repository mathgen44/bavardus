# Bavardus — suivi de projet

> **Source de vérité du projet.** À mettre à jour à chaque étape.
> Une copie miroir est maintenue dans le projet Claude « StreamBot ».

**Dernière mise à jour :** 2026-09-07 (15h50) — **le bot est vivant**

> ⚠️ **Fichier reconstitué le 2026-09-06** — l'original avait disparu. Conséquence :
> **la numérotation d'origine des bugs est partiellement perdue.** Un balayage du code a
> retrouvé **B1**, **B3** et **B4** (voir §7), mais l'étendue réelle de la série est
> inconnue. Les bugs traités depuis sont donc numérotés **à partir de B10**, la plage
> **1–9 étant réservée à l'historique d'origine**. Correction du 2026-09-07 : ils avaient
> d'abord été notés B4 et B5, ce qui écrasait des références existantes.
>
> Même prudence pour les décisions : D14 et suivantes sont supposées libres, sans
> certitude — le balayage n'a trouvé dans le code que D5, D12, D13 et D15.

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
| 1.3b | Chaîne publique DNS → box → NPM → VM:8475 | ✅ (B10) |
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

### Phase 2 — Architecture ✅ **CLOSE le 2026-09-07**

Structure arrêtée dans [`architecture.md`](architecture.md) : chaîne
Sources → Décideur → Générateur → Émetteur, un conteneur, interface en rendu serveur,
authentification par OAuth Twitch (D19 à D23).

### Phase 3 — Construction

| # | Étape | État |
|---|---|---|
| 1 | `config.py`, `stockage/`, `modeles/` | ✅ 43 tests |
| 2 | `noyau/` — Décideur, Générateur, Émetteur | ✅ 88 tests |
| 3 | `sources/twitch.py` — EventSub et Helix | ✅ 112 tests |
| 4 | **Bot vivant en ligne de commande** | ✅ **JALON ATTEINT le 2026-09-07** |
| 5 | `sources/streamlabs.py` (la minuterie est faite) | ✅ 128 tests |
| 6 | `web/` : authentification, réglages, journal en direct | ✅ 162 tests |
| 7 | `Dockerfile` et `compose.yaml` | ✅ 167 tests · conteneur validé en réel (B15) |

**Le jalon de vérité est franchi.** Bavardus lit le chat de `mathgen`, décide s'il doit
répondre, interroge `gemma4:e4b` et publie sous son propre compte. Tout ce qui suit est du
confort ou de l'ouverture aux tiers — plus aucune inconnue de conception.

Constaté au premier démarrage réel :

- `--verifier` a nommé les trois points manquants (base_url, URL d'Ollama, jetons) avant
  toute tentative de connexion. G11 fait son travail.
- **B13** — `importer_jetons.py` traitait un jeton d'accès expiré comme une panne. Un jeton
  Twitch vit environ quatre heures : après une nuit il est expiré **par construction**, et
  le `refresh_token` existe précisément pour ça. Corrigé : le script renouvelle, puis
  vérifie l'identité du jeton renouvelé.

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
| **R17** | Un seul processus : redémarrer l'interface coupe le bot | 🟡 accepté (D19), à documenter |
| **R16** | Deux jeux de jetons à rafraîchir (bot et diffuseur). Celui du diffuseur expire aussi : sans rafraîchissement, l'interface se ferme au propriétaire sans explication | 🟡 à traiter dès `web/auth.py` |
| **R19** | *(nouveau)* La détection de modération porte sur des mots entiers et ne déjoue aucun contournement (`c0n`, caractères ressemblants). Choix assumé : un faux positif coûte plus cher qu'un mot passé au travers. AutoMod de Twitch reste l'outil de référence pour une modération large | 🟡 documenté dans l'interface |
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
| **D25** | *(nouveau)* **Tout l'état d'instance tient dans un seul dossier**, désigné par `BAVARDUS_DONNEES` : `config.yaml`, `.env`, `jetons.json`, la base et la clé de session. Le code est séparé et remplaçable (image Docker) ; sauvegarder ce dossier sauvegarde l'installation entière |
| **D27** | *(nouveau)* **La modération précède tout le reste et exempte le diffuseur.** Un message sanctionné n'entre pas dans le contexte du modèle — qui le relirait et pourrait s'en inspirer — et ne déclenche aucune réponse. Le diffuseur, le bot et les comptes ignorés ne sont jamais modérés : un bot qui exclut le streamer de son propre chat est une catastrophe que personne ne pardonne |
| **D29** | *(nouveau)* **La liste de mots livrée vise le spam, pas les insultes identitaires.** AutoMod de Twitch couvre ces catégories par thème et par niveau, avec le contexte, et se met à jour seul : une liste de mots ne le remplace pas, elle le complète sur ce qui est propre à une chaîne. Un dépôt public n'a par ailleurs pas à héberger un fichier d'insultes identitaires. Le bouton d'ajout **fusionne** au lieu de remplacer |
| **D28** | **L'exclusion est toujours temporaire**, jamais un bannissement définitif : une erreur dans la liste de mots ne doit pas coûter un spectateur à la chaîne. Les scopes de modération sont demandés séparément (`usage=bot_moderation`) — une instance qui ne modère pas ne doit pas réclamer le droit d'exclure |
| **D26** | **Une configuration incomplète démarre l'interface au lieu de refuser de démarrer.** Refuser laisserait l'utilisateur sans moyen de corriger, alors que c'est précisément l'interface qui sert à configurer : un `docker compose up` sur une instance neuve doit mener quelque part |
| **D24** | **Le client Socket.IO Streamlabs reste synchrone, isolé dans un thread.** `python-socketio` 4.6.1 en mode synchrone est la seule configuration validée contre R1 ; passer à `AsyncClient` imposerait `aiohttp` et une pile de transport différente, donc rejouer la validation sans nécessité. Le thread dépose ses événements dans la file du noyau, qui ne voit rien |

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
| **G18** | L'Émetteur est le **seul** point de sortie vers Twitch : G4 et G14 y sont appliqués une fois, jamais dupliqués ailleurs |
| **G17** | Le Décideur ne consulte jamais le modèle, et journalise la raison de chaque décision |
| **G16** | Les outils de diagnostic portent le préfixe `diag_`, jamais `test_` : ils exigent de vrais identifiants et une interaction humaine, et `pytest` ne doit pas les collecter. `tests/` reste réservé aux vrais tests unitaires |
| **G15** | Aucun contenu versionné ne porte le nom civil de l'auteur : `mathgen44` partout, y compris dans la configuration git locale du dépôt |

## 6. Questions ouvertes

| Réf | Question | État |
|---|---|---|
| **Q15** | Quel modèle retenir ? | ✅ **tranché — `gemma4:e4b`** (D18) |
| **Q16** | Architecture | ✅ **tranchée le 2026-09-07** — voir [`architecture.md`](architecture.md) (D19 à D22) |

---

## 7. Journal des bugs

> **B1 – B9 : plage réservée au suivi d'origine, non reconstitué.** Trois entrées ont été
> retrouvées par balayage du code le 2026-09-07 :
>
> - **B1** — les modèles d'embedding n'ont pas de point d'entrée de conversation.
> - **B3** — sur le point d'entrée `/v1` d'Ollama, `think` est ignoré ; seul `/api/chat`
>   le prend en compte, et `reasoning_effort:"none"` ne suffit pas pour tous les modèles.
>   **Fondement de D16.**
> - **B4** — l'environnement l'emporte sur le fichier `.env` : une variable exportée lors
>   d'un essai précédent écrase silencieusement la configuration, d'où l'affichage de
>   l'origine de chaque valeur.
>
> B2 et B5–B9 restent inconnus.

### B15 — Le conteneur redémarrait en boucle : `/donnees/.env` illisible
**Ouvert et clos le 2026-09-07**

Premier `docker compose up` : `PermissionError: [Errno 13] Permission denied:
'/donnees/.env'`, conteneur en `Restarting` sans fin, et **502** sur l'interface publique.

**Cause :** le Dockerfile crée un utilisateur non privilégié (uid 10001) et lui donne
`/donnees`. Mais un **montage depuis l'hôte écrase ce dossier** : `./donnees` arrive avec
le propriétaire de l'hôte (uid 1000) et des fichiers en 600 — jetons et `.env` — que
l'uid 10001 ne peut pas lire. Le `chown` de l'image ne sert que pour un volume nommé.

C'est le piège classique du montage depuis l'hôte avec un utilisateur non root ; il aurait
dû être traité en écrivant `compose.yaml`.

**Correction :** `compose.yaml` fixe `user: "${BAVARDUS_UID:-1000}:${BAVARDUS_GID:-1000}"`
et `HOME=/donnees` — sans ce dernier, l'identifiant surchargé n'a pas de foyer dans
l'image et les bibliothèques qui cherchent `~` écrivent dans `/`.

**Point de vigilance :** Docker Compose lit le fichier `.env` situé **à côté de
`compose.yaml`** pour ses propres variables. En exécution native, le `.env` applicatif se
trouve justement là. Sans conséquence tant qu'aucun secret ne contient de `$` — sinon,
doubler le caractère (`$$`) ou lancer `docker compose --env-file /dev/null`.

**Note de méthode :** un 502 signalait ici un backend absent, là où B10 en donnait un 404
dans une situation voisine. Ces codes ne se déduisent pas ; les logs du service, eux, ont
nommé la cause en une ligne.

---

### B14 — Une dépendance manquante produisait une trace illisible
**Ouvert et clos le 2026-09-07**

Après un `git pull` ajoutant `python-multipart`, le démarrage échouait sur une trace de
quarante lignes se terminant par le nom du paquet. Le cas se reproduira à chaque nouvelle
dépendance, et sur chaque installation tierce.

**Correction :** `dependances_manquantes()` est appelée avant toute autre chose et liste
les paquets absents avec ce que leur perte coûte, suivis de la commande à lancer. Les
imports de l'interface web sont devenus paresseux pour que ce diagnostic passe **avant**
l'erreur d'import. Le nom `python_multipart` (renommage récent) est accepté aussi.

---

### B12 — Les outils déplacés dans `outils/` ne trouvaient plus le `.env`
**Ouvert et clos le 2026-09-07 — corrigé préventivement, jamais rencontré en usage**

Les scripts lisaient `.env` et écrivaient `.twitch_tokens.json` dans le **répertoire
courant**. Après leur déplacement dans `outils/`, les lancer depuis ce dossier aurait
imposé un second fichier de secrets — exactement ce que G5 cherche à éviter.

**Correction :** `racine_config()` cherche le `.env` dans le répertoire courant (usage
historique préservé), puis dans le dossier de l'outil, puis à la racine du dépôt. Les
secrets restent dans un seul fichier, à la racine.

---

### B11 — Auth faite avec le compte du diffuseur au lieu du compte du bot
**Ouvert le 2026-09-06 · ✅ Clos le 2026-09-07**

`--check` affichait `COMPTE mathgen (64157622)` **et** `CHAÎNE mathgen (64157622)`. Le bot
aurait posté sous le pseudo du streamer, et la validation de `channel.chat.message` était
faussée (le diffuseur a tous les droits sur son propre chat).

**Cause :** Twitch conserve la session du navigateur. Même avec `force_verify=true`,
l'écran de consentement s'affiche pour le compte déjà connecté. Remède : navigation privée.

**Corrections :** G12, D15, 401 modérateur requalifié en comportement attendu, remède
affiché sur un 403 de lecture.

### B10 — `https://bavardus.mathgen.fr` renvoyait 404
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

**Méthode de travail établie :** Claude écrit dans le dépôt côté PC (`D:\GIT\StreamBot`),
Hervé pousse depuis Windows, puis tire et exécute sur la VM (`~/Bavardus`, clone du dépôt,
venv `.venv`). Un `git push` / `git pull` entre chaque étape — il n'y a pas de raccourci.

- `config.yaml`, `.env` et `jetons.json` sont hors du dépôt (G5) : un `git pull` ne les
  écrase jamais.
- Démarrage : `python3 -m bavardus --verifier` puis `python3 -m bavardus`.
- En attendant l'interface web, les jetons viennent de
  `outils/diag_twitch.py --auth` puis `outils/importer_jetons.py`.

**⚠️ Avant de basculer la VM sur le clone :** `~/Bavardus` contient encore l'ancienne
arborescence à plat (`test_*.py`), plus `.env`, `.twitch_tokens.json` et `.venv`. Faire le
ménage **avant** le clone, en préservant les deux fichiers de secrets — ils ne sont pas
dans le dépôt (G5) et seraient perdus sans précaution. Les commandes deviennent ensuite
`python3 outils/diag_twitch.py --check`, avec le `.env` à la racine.

**La phase 3 est close.** L'infrastructure est complète : moteur, sources, interface,
conteneur. **Mais le périmètre v1 ne l'est pas.**

### Périmètre v1 — état réel

| # | Fonction | État |
|---|---|---|
| 1 | Chat conversationnel IA | ✅ |
| 2 | Commandes classiques (`!commande`) | 🟡 **partiel** — le Décideur les reconnaît et les découpe, mais aucune commande n'est configurable : tout est passé au modèle, qui improvise une réponse |
| 3 | Réactions aux alertes Streamlabs | ✅ |
| 4 | **Modération automatique** | ✅ **faite le 2026-09-07** — détection sur mots entiers, trois sanctions, exemptions ; 196 tests |
| 5 | Prise de parole spontanée | ✅ |
| 6 | Interface web, persona configurable | ✅ |

Deux chantiers restent donc **dans le périmètre annoncé**, et non en supplément.

**Reste à faire, par ordre d'utilité :**

1. **Les commandes personnalisées** (point 2 du périmètre) : `!commande` avec réponses
   fixes, éditables depuis l'interface, avant de passer la main au modèle.
2. **Éprouver en conditions réelles** — un vrai live, prise de parole spontanée activée.
   Le seul test que rien ne remplace.
4. `/mod bavardus` si ce n'est pas fait (R14).
5. Retirer `outils/importer_jetons.py` une fois que l'autorisation par l'interface aura
   servi au moins une fois.
6. Publier une image sur ghcr.io pour qu'une installation tierce n'exige plus de build.
