# Bavardus

Un bot de chat Twitch autonome, propulsé par un modèle de langage local ou distant,
compatible avec les alertes Streamlabs.

> **État : phase de validation technique terminée, code de production à venir.**
> Ce dépôt ne contient pour l'instant que les scripts qui ont servi à prouver chaque
> brique avant d'écrire l'application. Ils restent utiles : ce sont eux qui diagnostiquent
> une installation qui ne démarre pas.

## Ce que Bavardus fera

- Répondre dans le chat, avec un persona configurable
- Réagir aux commandes classiques (`!commande`)
- Réagir aux alertes Streamlabs (follow, don, abonnement, raid)
- Modérer automatiquement
- Prendre la parole spontanément, avec fréquence réglable
- Se piloter depuis une interface web, sans toucher à un fichier de configuration

## Choix techniques

**Le fournisseur de modèle est libre.** Bavardus parle le protocole compatible OpenAI
(`/v1/chat/completions`), donc le même code interroge Ollama en local, OpenRouter, ou
n'importe quelle passerelle équivalente. Modèle validé par défaut : `gemma4:e4b` sur
Ollama — léger, tient un persona, et n'invente pas de faits qu'il ne peut pas connaître.

**Le mode réflexion est désactivé explicitement.** Les modèles récents l'activent souvent
par défaut et consomment alors la totalité du plafond de jetons en réflexion interne,
sans produire une seule ligne de réponse. Sur Ollama, seule l'API native `/api/chat`
honore `think: false`.

**Le bot ne décide pas de se taire.** C'est le moteur qui décide s'il faut répondre ; le
modèle ne produit que le texte une fois la décision prise. Un bot dont le silence dépend
de la bonne volonté d'un modèle finit par parler par-dessus tout le monde.

## Outils de diagnostic

Quatre scripts autonomes, dans `outils/`, sans aucune dépendance à l'application. Ils
prouvent — ou réparent — une brique isolée. Quand le bot ne répond pas, c'est là qu'on
cherche pourquoi avant de toucher au code. Détail complet dans
[`outils/README.md`](outils/README.md).

| Outil | Ce qu'il prouve |
|---|---|
| `outils/diag_twitch.py` | OAuth, rafraîchissement du jeton, EventSub, lecture et envoi de messages |
| `outils/diag_streamlabs.py` | Réception des alertes Streamlabs (Socket.IO) |
| `outils/diag_ollama.py` | Latence réelle des modèles installés |
| `outils/diag_qualite.py` | Comparaison qualitative de plusieurs modèles |

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r outils/requirements.txt
cp .env.exemple .env      # puis remplir
python3 outils/diag_twitch.py --auth
```

Ils lisent le `.env` à la racine du dépôt : les secrets ne sont jamais dupliqués.
Le préfixe est `diag_` et non `test_` — ce ne sont pas des tests automatisables, ils
exigent de vrais identifiants et une interaction humaine, et `pytest` ne doit pas les
collecter. Le dossier `tests/` reste réservé aux vrais tests unitaires.

### Pièges connus

- **L'auth Twitch attrape le mauvais compte.** Twitch conserve la session du navigateur :
  même avec `force_verify`, l'écran de consentement s'affiche pour le compte déjà
  connecté. **Ouvrir l'URL d'autorisation en navigation privée**, et vérifier avec
  `--check` que le compte du bot et celui de la chaîne ont bien deux identifiants
  différents.
- **Le bot lit mais ne parle pas, ou l'inverse.** Les deux sens ont des conditions
  d'autorisation distinctes. La lecture exige que le bot soit modérateur de la chaîne
  (`/mod <compte_du_bot>`) ou que le diffuseur lui ait accordé `channel:bot` ; l'envoi
  fonctionne sans, mais avec des limites anti-spam bien plus sévères.
- **Un modèle qui ne répond rien n'est pas forcément cassé.** Sur Ollama, il faut
  `--native --no-think` : le mode réflexion consomme sinon la totalité du plafond de
  jetons sans produire une ligne.
- **Les dépendances Streamlabs sont épinglées volontairement.** Streamlabs expose un
  serveur Socket.IO ancien (Engine.IO v3) ; `python-socketio` 5.x ne peut pas s'y
  connecter. Ne pas les mettre à jour sans relancer le diagnostic.

## Sécurité

`.env` et `.twitch_tokens.json` ne doivent jamais être versionnés — ils sont dans le
`.gitignore`. Le fichier de jetons donne le contrôle du compte Twitch du bot.

## Licence

MIT — voir [LICENSE](LICENSE).
