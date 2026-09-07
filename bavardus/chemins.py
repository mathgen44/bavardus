"""Où vivent le code et l'état.

En local, les deux cohabitent dans le dossier du dépôt. En conteneur, le code
est en `/app` — remplaçable à chaque mise à jour d'image — et **tout l'état
tient dans un seul volume**, sauvegardable en le copiant.

D'où une unique variable, `BAVARDUS_DONNEES`. Cinq fichiers en dépendent, et
aucun autre : `config.yaml`, `.env`, `jetons.json`, la base et la clé de
session. Un utilisateur qui sauvegarde ce dossier a sauvegardé son
installation entière.
"""

from __future__ import annotations

import os
from pathlib import Path


def racine_code() -> Path:
    """Le dépôt ou `/app`. Jamais écrit à l'exécution."""
    return Path(__file__).resolve().parent.parent


def dossier_etat() -> Path:
    """Tout ce qui survit à une mise à jour d'image."""
    depuis_env = os.environ.get("BAVARDUS_DONNEES")
    chemin = Path(depuis_env) if depuis_env else racine_code()
    chemin.mkdir(parents=True, exist_ok=True)
    return chemin


def config_yaml() -> Path:
    return dossier_etat() / "config.yaml"


def fichier_env() -> Path:
    return dossier_etat() / ".env"


def fichier_jetons() -> Path:
    return dossier_etat() / "jetons.json"


def base_donnees() -> Path:
    return dossier_etat() / "bavardus.db"


def cle_session() -> Path:
    return dossier_etat() / "cle_session"


def preparer_config() -> tuple[Path, bool]:
    """Crée `config.yaml` depuis l'exemple s'il manque. (chemin, créé ?)

    Sans cela, un premier `docker compose up` échouerait sur un fichier
    absent que l'utilisateur n'a aucun moyen de deviner — alors que
    l'exemple contient exactement ce qu'il faut pour démarrer.
    """
    cible = config_yaml()
    if cible.exists():
        return cible, False
    exemple = racine_code() / "config.exemple.yaml"
    if not exemple.exists():
        return cible, False
    cible.write_text(exemple.read_text(encoding="utf-8"), encoding="utf-8")
    return cible, True
