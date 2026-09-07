# Bavardus — architecture (Q16)

**Arrêtée le 2026-09-07.** Ce document décrit la structure cible. Il précède le code :
tout écart constaté à l'implémentation doit être reporté ici, pas subi.

---

## 1. Principes

Quatre décisions déjà prises structurent tout le reste.

- **D17 — le code décide de parler, jamais le modèle.** Le Décideur est un étage à part
  entière, pas une consigne dans un prompt.
- **D16 — le mode réflexion est coupé explicitement.** Sur Ollama, cela impose l'API
  native ; c'est une exception à D13, isolée dans un seul connecteur.
- **D13 — un seul protocole pour tous les fournisseurs de modèles.** Changer de modèle ne
  doit toucher qu'une ligne de configuration.
- **G14 — une réponse vide n'est jamais postée, et sa cause est journalisée.**

Auxquelles s'ajoute une contrainte issue du périmètre v1 :

- **La configuration est rechargeable à chaud.** Si régler le persona impose un
  redémarrage, l'interface web perd son intérêt et le bot se tait en plein live à chaque
  ajustement.

## 2. Chaîne de traitement

```
  SOURCES                 NOYAU                          SORTIE
  ┌──────────────┐
  │ Twitch       │        ┌───────────┐
  │ EventSub     │──┐     │ Décideur  │  faut-il répondre ?
  │ (chat, D15)  │  │     │   (D17)   │  mention · commande · alerte
  └──────────────┘  │     └─────┬─────┘  · minuterie · anti-flood
  ┌──────────────┐  │  file     │ oui
  │ Streamlabs   │──┼─────►     ▼
  │ (alertes)    │  │ asyncio  ┌───────────┐
  └──────────────┘  │  Queue   │Générateur │  persona + contexte glissant
  ┌──────────────┐  │          │           │  → modèle (D13/D16)
  │ Minuterie    │──┘          └─────┬─────┘
  │ (spontané)   │                   │ texte ou vide
  └──────────────┘                   ▼
                              ┌───────────┐      ┌──────────────┐
                              │ Émetteur  │─────►│ Twitch Helix │
                              │ G4 · G14  │      └──────────────┘
                              └───────────┘
```

**Le Décideur ne consulte jamais le modèle** (G17). Il tranche sur des règles explicites et
lisibles dans l'interface : le bot est-il mentionné, est-ce une commande connue, est-ce une
alerte à commenter, la minuterie de prise de parole est-elle échue, le débit maximum est-il
dépassé. Chaque décision est journalisée avec sa raison — c'est ce qui rendra le
comportement du bot explicable quand il paraîtra bavard ou muet.

**L'Émetteur est le seul point de sortie.** G4 (troncature à 500 caractères) et G14 (une
réponse vide n'est jamais postée) y sont appliqués une fois pour toutes, pas dispersés.

## 3. Déploiement

**Un seul conteneur, un seul processus asyncio.** Le moteur et l'interface web partagent
le même espace mémoire : aucune API interne, aucun bus externe, aucun broker. Le bus est
une `asyncio.Queue`.

C'est un choix assumé au service de l'objectif « utilisable par d'autres personnes » :
l'installation tient en un `docker compose up`. Le prix à payer — redémarrer l'interface
coupe le bot — est acceptable pour un outil qu'on ne redéploie pas en continu.

## 4. Structure du dépôt

```
bavardus/
├── bavardus/                    le paquet
│   ├── __main__.py              point d'entrée, démarrage des sources
│   ├── config.py                YAML + rechargement à chaud
│   ├── noyau/
│   │   ├── evenements.py        types d'événements internes
│   │   ├── decideur.py          D17 · G17
│   │   ├── generateur.py        persona, contexte, appel modèle
│   │   └── emetteur.py          G4 · G14, seul point de sortie
│   ├── sources/
│   │   ├── twitch.py            EventSub WebSocket — chat seul (D15)
│   │   ├── streamlabs.py        Socket.IO, versions épinglées (R1/G10)
│   │   └── minuterie.py         prise de parole spontanée
│   ├── modeles/
│   │   ├── base.py              interface commune (D13)
│   │   ├── ollama.py            API native, think:false (D16)
│   │   └── compatible_openai.py OpenRouter et équivalents
│   ├── stockage/
│   │   ├── jetons.py            lecture/écriture 600, rafraîchissement (R4)
│   │   └── base.py              SQLite : historique, journal, statistiques
│   └── web/
│       ├── app.py               FastAPI
│       ├── auth.py              OAuth Twitch (D22)
│       ├── routes/
│       └── gabarits/            Jinja2 + HTMX
├── outils/   diagnostics (diag_*.py)
├── docs/     suivi_de_projet.md, architecture.md, depannage-auth-twitch.md
├── tests/    tests unitaires du noyau
├── Dockerfile
├── compose.yaml
└── config.exemple.yaml
```

## 5. Interface web

**FastAPI + Jinja2 + HTMX, rendu côté serveur.** Aucune étape de build, aucune dépendance
npm, un seul langage dans le dépôt. Le chat en direct et le journal des décisions arrivent
par flux d'événements (SSE) — suffisant ici, la communication ne va que du serveur vers le
navigateur.

Ce que l'interface pilote : persona, modèle et fournisseur, activation et fréquence de la
prise de parole spontanée, commandes, règles de modération, débit maximum. Plus un journal
en direct montrant, pour chaque message reçu, la décision prise **et sa raison**.

## 6. Authentification (D22)

L'interface est exposée sur Internet et pilote un bot dont les jetons donnent le contrôle
d'un compte Twitch. Elle ne peut pas être ouverte.

**Connexion par OAuth Twitch, compte du diffuseur.** Le code du flux existe déjà et a été
validé en phase 1 ; il est réutilisé avec un scope d'identité minimal. Session par cookie
signé.

**Amorçage :** au premier démarrage, aucun propriétaire n'est enregistré. Le premier compte
Twitch qui se connecte le devient, et l'installation se verrouille sur lui. C'est ce qui
permet à un tiers d'installer Bavardus sans éditer un fichier de configuration ni changer
un mot de passe par défaut — donc sans laisser une interface ouverte par négligence.

**Deux jeux de jetons coexistent** : celui du **bot** (lecture et écriture dans le chat) et
celui du **diffuseur** (identité pour l'interface, et autorisations côté chaîne si elles
deviennent nécessaires). Tous deux expirent et doivent être rafraîchis — **R16**.

## 6 bis. URL publique et installation par un tiers (D23)

### Le point dur

Le `client_secret` Twitch ne peut pas être distribué dans un dépôt public. **Chaque
utilisateur crée donc sa propre application** sur la console développeur Twitch et y
déclare sa propre URL de redirection. C'est incontournable ; ce qui se conçoit, c'est de
rendre l'étape indolore.

### Une seule variable : `BASE_URL`

Toutes les URL de l'application en découlent :

```
BASE_URL=https://bavardus.mathgen.fr        # derrière un reverse proxy
BASE_URL=http://localhost:8475              # installation locale, sans domaine
```

L'URL de redirection à déclarer sur Twitch est toujours `{BASE_URL}/api/twitch/callback`.

**`BASE_URL` est explicite, jamais déduite des en-têtes HTTP.** Déduire depuis `Host` ou
`X-Forwarded-Proto` fonctionne jusqu'au jour où un reverse proxy est mal configuré : on
construit alors une URL de redirection qui ne correspond plus à celle déclarée sur Twitch,
et l'authentification échoue avec un message que personne ne sait interpréter. Une variable
lisible dans un fichier vaut mieux qu'une devinette.

**Twitch autorise `http://localhost`** — seule exception à l'obligation de HTTPS. Un
utilisateur sans nom de domaine ni reverse proxy fait donc tourner Bavardus tel quel. C'est
le cas le plus fréquent en auto-hébergement, et il doit être le chemin par défaut : la
valeur livrée dans `config.exemple.yaml` est `http://localhost:8475`.

### Une seule URL de redirection, deux flux

Le bot et le propriétaire s'authentifient tous deux par OAuth, mais **une seule URL est
déclarée sur Twitch**. Le paramètre `state` porte l'intention (`bot` ou `proprietaire`) en
plus de sa fonction anti-CSRF. Un utilisateur a ainsi une seule chaîne à copier, et une
seule occasion de se tromper au lieu de deux.

En production, cette callback est **une route de l'application**, pas un serveur HTTP
éphémère comme dans `outils/diag_twitch.py` : l'application écoute déjà, il n'y a pas de
second port à ouvrir. `TWITCH_CALLBACK_PORT` disparaît de la configuration.

### Assistant d'installation

Au premier démarrage, aucun propriétaire n'est enregistré (D22). L'application sert alors
un assistant, dans cet ordre :

1. **`BASE_URL`** — pré-remplie avec l'adresse par laquelle l'utilisateur consulte la page,
   modifiable.
2. **L'URL de redirection exacte**, affichée en clair et sélectionnable, avec le lien vers
   la console développeur Twitch. C'est le geste décisif : Twitch compare la chaîne
   caractère par caractère, et les échecs viennent presque toujours d'un `/` final en trop,
   d'un `http` au lieu de `https`, ou d'un port oublié. L'utilisateur copie au lieu de
   retaper.
3. **`client_id` et `client_secret`** de son application.
4. **Connexion du propriétaire** — le compte qui se connecte devient propriétaire et
   verrouille l'installation (D22).
5. **Connexion du bot**, en rappelant d'utiliser une **fenêtre de navigation privée** (B11)
   et de faire du bot un modérateur de la chaîne (R13/R14).

L'assistant n'est joignable que tant qu'aucun propriétaire n'existe. Une fois
l'installation verrouillée, ces réglages passent dans l'interface authentifiée.

### Vérification au démarrage (G11)

À chaque démarrage, l'application appelle sa propre `BASE_URL` et journalise le résultat.
Une `BASE_URL` qui ne joint pas l'application est la panne la plus déroutante possible :
tout fonctionne jusqu'au moment où quelqu'un tente de se connecter. Mieux vaut une ligne
rouge au démarrage qu'une authentification qui échoue trois semaines plus tard, après un
changement d'adresse IP (R12).

## 7. Stockage

| Donnée | Support | Pourquoi |
|---|---|---|
| Configuration | `config.yaml` | lisible et modifiable à la main quand l'interface est inaccessible |
| Jetons | `jetons.json`, droits 600 | hors du dépôt (G5), jamais dans la base |
| Historique du chat | SQLite | fenêtre de contexte, et exploitation ultérieure |
| Journal des décisions | SQLite | expliquer pourquoi le bot a parlé ou s'est tu |
| Statistiques | SQLite | latence, réponses vides (G14), messages jetés |

Le tout dans **un seul volume Docker**, sauvegardable en le copiant.

**Rechargement à chaud :** `config.py` expose un objet immuable. L'interface écrit le YAML
et publie une nouvelle version ; le noyau lit la version courante à chaque événement. Pas
de verrou, pas de redémarrage, pas d'état à moitié appliqué.

## 8. Décisions nouvelles

| Réf | Décision |
|---|---|
| **D19** | Un seul conteneur, un seul processus asyncio. Bus interne = `asyncio.Queue`, pas de broker |
| **D20** | Interface en rendu serveur : FastAPI + Jinja2 + HTMX + SSE. Aucun build front |
| **D21** | Configuration en YAML rechargeable à chaud ; historique, journal et statistiques en SQLite ; jetons dans un fichier séparé à droits 600 |
| **D22** | Authentification de l'interface par OAuth Twitch. Le premier compte connecté devient propriétaire et verrouille l'installation |
| **D23** | **Une seule variable `BASE_URL`**, explicite et jamais déduite des en-têtes HTTP, d'où découlent toutes les URL. Une seule URL de redirection déclarée sur Twitch pour les deux flux, distingués par le paramètre `state`. Défaut livré : `http://localhost:8475`. Un assistant d'installation affiche la chaîne exacte à copier sur la console développeur Twitch |

## 9. Garde-fous et risques nouveaux

| Réf | |
|---|---|
| **G17** | Le Décideur ne consulte jamais le modèle, et journalise la raison de chaque décision |
| **G18** | L'Émetteur est le **seul** point de sortie vers Twitch. G4 et G14 y sont appliqués une fois, jamais dupliqués ailleurs |
| **R16** | Deux jeux de jetons à rafraîchir (bot et diffuseur). Celui du diffuseur expire aussi : sans rafraîchissement, l'interface se ferme au propriétaire sans explication |
| **R17** | Un seul processus : redémarrer l'interface coupe le bot. Accepté (D19), à documenter pour l'utilisateur |
| **R18** | Une `BASE_URL` erronée ou périmée ne se voit qu'au moment d'une connexion : tout paraît fonctionner jusque-là. Mitigé par la vérification au démarrage (G11) |

## 10. Ordre de construction

1. `config.py`, `stockage/`, `modeles/` avec le connecteur Ollama (D16) — testables seuls.
2. `noyau/` complet, alimenté par des événements simulés. **C'est ici que vont les premiers
   tests unitaires** : le Décideur est de la logique pure, sans réseau.
3. `sources/twitch.py`, en reprenant le code déjà validé de `outils/diag_twitch.py`.
4. Premier bot vivant en ligne de commande, sans interface. Jalon de vérité.
5. `sources/streamlabs.py` et la minuterie.
6. `web/` : authentification d'abord, réglages ensuite, journal en direct pour finir.
7. `Dockerfile` et `compose.yaml`.

Le bot doit parler dans un vrai chat à l'étape 4. Tout ce qui vient après est du confort ;
tout ce qui vient avant est indispensable.
