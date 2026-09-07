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
import urllib.request
from pathlib import Path

VALIDATION = "https://id.twitch.tv/oauth2/validate"


def racine() -> Path:
    return Path(__file__).resolve().parent.parent


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

    try:
        login, user_id = identite(acces)
    except Exception as erreur:                     # noqa: BLE001
        print(f"Twitch n'a pas validé ce jeton : {erreur}\n"
              f"Il a probablement expiré — relancer diag_twitch.py --auth.",
              file=sys.stderr)
        return 1

    # L'échéance absolue, reconstruite depuis l'instant de l'obtention.
    obtenu = float(ancien.get("obtenu_le", time.time()))
    expire_le = obtenu + float(ancien.get("expires_in", 0))

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
