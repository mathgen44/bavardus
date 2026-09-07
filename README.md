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

## Scripts de validation

Chacun se lance seul et diagnostique une brique. Aucun ne dépend de l'application.

| Script | Rôle |
|---|---|
| `test_twitch.py` | OAuth, rafraîchissement du jeton, EventSub, lecture et envoi de messages |
| `test_streamlabs.py` | Réception des alertes Streamlabs (Socket.IO) |
| `test_ollama.py` | Latence réelle des modèles installés |
| `test_qualite.py` | Comparaison qualitative de plusieurs modèles sur six situations types |

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-test.txt
cp .env.exemple .env      # puis remplir
python3 test_twitch.py --auth
```

`test_twitch.py --auth`, `--check`, `--refresh` et `--say` n'utilisent que la bibliothèque
standard. `--listen` et `test_streamlabs.py` ont besoin des dépendances ci-dessus.

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
- **Les dépendances Streamlabs sont épinglées volontairement.** Streamlabs expose un
  serveur Socket.IO ancien (protocole Engine.IO v3) ; `python-socketio` 5.x ne peut pas
  s'y connecter. Ne pas les mettre à jour sans tester.

## Sécurité

`.env` et `.twitch_tokens.json` ne doivent jamais être versionnés — ils sont dans le
`.gitignore`. Le fichier de jetons donne le contrôle du compte Twitch du bot.

## Licence

MIT — voir [LICENSE](LICENSE).
