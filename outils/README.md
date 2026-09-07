# Outils de diagnostic

Quatre scripts autonomes, sans dépendance à l'application. Ils servent à prouver — ou à
réparer — une brique isolée. Quand Bavardus ne répond pas, c'est ici qu'on cherche
pourquoi avant de toucher au code.

Ils lisent le `.env` **à la racine du dépôt** ; inutile d'en créer un second ici.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r outils/requirements.txt
python3 outils/diag_twitch.py --check
```

| Outil | Ce qu'il prouve |
|---|---|
| `diag_twitch.py` | OAuth, rafraîchissement du jeton, EventSub, lecture et envoi de messages |
| `diag_streamlabs.py` | Réception des alertes Streamlabs (Socket.IO) |
| `diag_ollama.py` | Latence réelle des modèles installés |
| `diag_qualite.py` | Comparaison qualitative de plusieurs modèles sur six situations types |

## diag_twitch.py

```bash
python3 outils/diag_twitch.py --auth        # flux OAuth complet
python3 outils/diag_twitch.py --check       # jeton valide ? quels scopes ? quel compte ?
python3 outils/diag_twitch.py --refresh     # le rafraîchissement fonctionne-t-il ?
python3 outils/diag_twitch.py --listen      # chat en direct
python3 outils/diag_twitch.py --say TEXTE   # envoi d'un message
```

`--auth`, `--check`, `--refresh` et `--say` n'utilisent que la bibliothèque standard.
`--listen` a besoin de `websocket-client`.

**Ouvre l'URL d'autorisation en navigation privée.** Twitch conserve la session du
navigateur : même avec `force_verify`, l'écran de consentement s'affiche pour le compte
déjà connecté, et tu repars avec le jeton du diffuseur sans que rien ne le signale.
`--check` compare les deux identifiants et alerte si c'est le cas.

**`--say` qui réussit ne prouve pas que le bot est autorisé.** N'importe quel spectateur
peut écrire dans un chat public. C'est `--listen` qui teste l'autorisation : la lecture
exige que le bot soit modérateur (`/mod <compte_du_bot>`) ou que le diffuseur lui ait
accordé `channel:bot`.

## diag_streamlabs.py

```bash
python3 outils/diag_streamlabs.py           # python-socketio 4.x
python3 outils/diag_streamlabs.py --raw     # WebSocket brut, plan B
```

Jeton sur streamlabs.com/dashboard → Paramètres du compte → API Settings → API Tokens →
**Your Socket API Token**. Puis, dans Streamlabs, déclencher les boutons de test de
l'Alert Box : chaque clic doit produire une ligne.

Les versions de `outils/requirements.txt` sont épinglées volontairement : Streamlabs
expose un serveur Socket.IO ancien (Engine.IO v3) que `python-socketio` 5.x ne sait pas
joindre. Ne pas les mettre à jour sans relancer ce diagnostic.

## diag_ollama.py et diag_qualite.py

```bash
python3 outils/diag_ollama.py --url http://192.168.0.139:11434
python3 outils/diag_qualite.py --api-base http://192.168.0.139:11434/v1 \
                               --models gemma4:e4b,qwen3.5:9b \
                               --native --no-think
```

**`--native --no-think` n'est pas optionnel sur Ollama.** Les modèles récents activent le
mode réflexion par défaut et consomment la totalité du plafond de 60 jetons en réflexion
interne, sans produire une ligne de réponse. Le point d'entrée `/v1` ignore `think:false` ;
seule l'API native `/api/chat` l'honore. Sans ces deux drapeaux, un bon modèle passe pour
un modèle cassé.

`diag_qualite.py` ne rend pas de verdict : il pose les mêmes six situations à chaque
modèle et affiche les réponses côte à côte. C'est un humain qui juge.
