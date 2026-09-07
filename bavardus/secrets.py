"""Secrets : `.env` et variables d'environnement.

Séparés de `config.yaml` (G5) : la configuration est éditable, versionnable
en exemple, et affichable dans l'interface ; les secrets ne le sont jamais.

**B4 — l'environnement l'emporte sur le fichier**, et l'origine de chaque
valeur est tracée. Une variable exportée lors d'un essai précédent écrase
silencieusement le `.env` : sans trace de l'origine, on cherche pendant une
heure pourquoi la valeur lue n'est pas celle qu'on vient d'écrire.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PREFIXES = ("TWITCH_", "STREAMLABS_", "BAVARDUS_", "OPENROUTER_", "LLM_")


class SecretsIncomplets(Exception):
    """Un secret indispensable manque. Le message dit lequel et où le mettre."""


@dataclass(slots=True)
class Secrets:
    twitch_client_id: str = ""
    twitch_client_secret: str = ""
    streamlabs_jeton_socket: str = ""
    cle_modele: str = ""
    origines: dict[str, str] = field(default_factory=dict)

    def exiger_twitch(self) -> None:
        manquants = [nom for nom, valeur in (
            ("TWITCH_CLIENT_ID", self.twitch_client_id),
            ("TWITCH_CLIENT_SECRET", self.twitch_client_secret),
        ) if not valeur]
        if manquants:
            raise SecretsIncomplets(
                f"{' et '.join(manquants)} absent(s). Les renseigner dans le "
                f"fichier .env à la racine, depuis l'application créée sur "
                f"https://dev.twitch.tv/console/apps")


def lire_env(chemin: Path) -> dict[str, str]:
    """Lit un .env minimal : KEY=valeur, # commentaires, quotes optionnelles."""
    if not chemin.exists():
        return {}
    valeurs: dict[str, str] = {}
    for ligne in chemin.read_text(encoding="utf-8").splitlines():
        ligne = ligne.strip()
        if not ligne or ligne.startswith("#") or "=" not in ligne:
            continue
        cle, valeur = ligne.split("=", 1)
        valeurs[cle.strip()] = valeur.strip().strip("\"'")
    return valeurs


def charger(racine: Path) -> Secrets:
    fichier = lire_env(Path(racine) / ".env")
    origines = {cle: ".env" for cle in fichier}

    fusion = dict(fichier)
    for cle, valeur in os.environ.items():
        if cle.startswith(PREFIXES):
            fusion[cle] = valeur
            origines[cle] = "environnement"      # B4

    return Secrets(
        twitch_client_id=fusion.get("TWITCH_CLIENT_ID", ""),
        twitch_client_secret=fusion.get("TWITCH_CLIENT_SECRET", ""),
        streamlabs_jeton_socket=fusion.get("STREAMLABS_SOCKET_TOKEN", ""),
        cle_modele=fusion.get("OPENROUTER_API_KEY") or fusion.get("LLM_API_KEY", ""),
        origines=origines,
    )
