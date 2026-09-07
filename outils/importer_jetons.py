#!/usr/bin/env python3
"""Convertit `.twitch_tokens.json` (diag_twitch.py) en `jetons.json` (moteur).

Les deux fichiers portent les mêmes secrets sous deux formes : le diagnostic
enregistre la réponse brute de Twitch, le moteur range les jetons par usage
(« bot » et « proprietaire », R16) avec une échéance absolue.

Ce script est une passerelle de transition. Une fois l'interface web en
place, l'autorisation s'y fera directement et il n'aura plus de raison d'être.

    python3 outils/importer_jetons.py                    # vers l'usage « bot »
    python3 outils/importer_jetons.py --usage proprietaire
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

VALIDATION = "https://id.twitch.tv/oauth2/validate"
JETON = "https://id.twitch.tv/oauth2/token"


def racine() -> Path:
    return Path(__file__).resolve().parent.parent


def lire_env(chemin: Path) -> dict:
    if not chemin.exists():
        return {}
    valeurs = {}
    for ligne in chemin.read_text(encoding="utf-8").splitlines():
        ligne = ligne.strip()
        if ligne and not ligne.startswith("#") and "=" in ligne:
            cle, valeur = ligne.split("=", 1)
            valeurs[cle.strip()] = valeur.strip().strip("\"'")
    return valeurs


def identite(acces: str) -> tuple[str, str]:
    """Interroge Twitch pour savoir à QUI appartient ce jeton.

    Vérification indispensable : c'est en croyant tenir le jeton du bot
    alors qu'il portait celui du diffuseur qu'on a perdu une soirée (B11).
    Autant que la conversion le dise tout de suite.
    """
    requete = urllib.request.Request(VALIDATION,
                                     headers={"Authorization": f"OAuth {acces}"})
    with urllib.request.urlopen(requete, timeout=15) as reponse:
        bloc = json.load(reponse)
    return bloc.get("login", ""), str(bloc.get("user_id", ""))


def rafraichir(rafraichissement: str, client_id: str, client_secret: str) -> dict:
    """Renouvelle le jeton d'accès.

    Un jeton d'accès Twitch vit environ quatre heures : après une nuit, il
    est expiré par construction. Ce n'est pas une panne, c'est le
    fonctionnement normal — le refresh_token existe précisément pour ça.
    """
    donnees = urllib.parse.urlencode({
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "refresh_token",
        "refresh_token": rafraichissement,
    }).encode()
    requete = urllib.request.Request(JETON, data=donnees, method="POST")
    with urllib.request.urlopen(requete, timeout=15) as reponse:
        return json.load(reponse)


def main() -> int:
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument("--usage", default="bot",
                           choices=("bot", "proprietaire"))
    analyseur.add_argument("--source", default=None,
                           help="chemin du .twitch_tokens.json")
    arguments = analyseur.parse_args()

    base = racine()
    source = Path(arguments.source) if arguments.source \
        else base / ".twitch_tokens.json"
    cible = base / "jetons.json"

    if not source.exists():
        print(f"{source} est introuvable. Lancer d'abord :\n"
              f"    python3 outils/diag_twitch.py --auth", file=sys.stderr)
        return 1

    ancien = json.loads(source.read_text(encoding="utf-8"))
    acces = ancien.get("access_token")
    rafraichissement = ancien.get("refresh_token")
    if not acces or not rafraichissement:
        print(f"{source} ne contient pas de couple access_token / refresh_token.",
              file=sys.stderr)
        return 1

    obtenu = float(ancien.get("obtenu_le", time.time()))
    expire_le = obtenu + float(ancien.get("expires_in", 0))

    try:
        login, user_id = identite(acces)
    except urllib.error.HTTPError as erreur:
        if erreur.code != 401:
            print(f"Twitch n'a pas validé ce jeton : {erreur}", file=sys.stderr)
            return 1

        # Cas normal après quelques heures : on renouvelle plutôt que
        # d'exiger une nouvelle autorisation.
        env = lire_env(base / ".env")
        client_id = env.get("TWITCH_CLIENT_ID", "")
        client_secret = env.get("TWITCH_CLIENT_SECRET", "")
        if not client_id or not client_secret:
            print("Jeton d'accès expiré, et TWITCH_CLIENT_ID / "
                  "TWITCH_CLIENT_SECRET absents du .env : impossible de le "
                  "renouveler.", file=sys.stderr)
            return 1

        print("jeton d'accès expiré — renouvellement…")
        try:
            neuf = rafraichir(rafraichissement, client_id, client_secret)
        except Exception as erreur_refresh:          # noqa: BLE001
            print(f"le renouvellement a échoué : {erreur_refresh}\n"
                  f"Le jeton de rafraîchissement a sans doute été révoqué — "
                  f"relancer : python3 outils/diag_twitch.py --auth",
                  file=sys.stderr)
            return 1

        acces = neuf["access_token"]
        rafraichissement = neuf.get("refresh_token") or rafraichissement
        expire_le = time.time() + float(neuf.get("expires_in", 0))
        ancien["scope"] = neuf.get("scope", ancien.get("scope", []))
        login, user_id = identite(acces)

    jetons = {}
    if cible.exists():
        jetons = json.loads(cible.read_text(encoding="utf-8"))

    jetons[arguments.usage] = {
        "acces": acces,
        "rafraichissement": rafraichissement,
        "expire_le": expire_le,
        "scopes": ancien.get("scope", []),
        "login": login,
        "user_id": user_id,
    }

    temporaire = cible.with_suffix(".tmp")
    descripteur = os.open(temporaire, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descripteur, "w", encoding="utf-8") as fichier:
        json.dump(jetons, fichier, ensure_ascii=False, indent=2)
    os.replace(temporaire, cible)
    os.chmod(cible, 0o600)

    restant = int(expire_le - time.time())
    print(f"jeton « {arguments.usage} » importé : {login} (id {user_id})")
    print(f"écrit dans {cible} (droits 600)")
    if restant <= 0:
        print("⚠️  ce jeton d'accès est expiré — le moteur le rafraîchira au "
              "démarrage grâce au refresh_token.")
    else:
        print(f"valable encore {restant} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
