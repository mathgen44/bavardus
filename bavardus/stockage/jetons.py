"""Jetons OAuth Twitch : lecture, écriture, rafraîchissement.

Deux jeux coexistent (R16) :

- **bot** — lit et écrit dans le chat ;
- **proprietaire** — identité du diffuseur pour l'interface web (D22).

Les deux expirent. Celui du bot fait mourir le bot (R4) ; celui du
propriétaire ferme l'interface à son propre administrateur, ce qui est plus
sournois encore puisque le bot, lui, continue de tourner.

Le fichier donne le contrôle des comptes Twitch : droits 600, hors du dépôt
(G5), jamais dans la base SQLite.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import httpx

JETON = "https://id.twitch.tv/oauth2/token"

# Marge avant expiration réelle. Rafraîchir pile à l'échéance, c'est laisser
# passer les requêtes déjà parties : elles reviendraient en 401.
MARGE_SECONDES = 300


class JetonsIndisponibles(Exception):
    """Aucun jeton utilisable. Le message dit lequel et comment le refaire."""


@dataclass(slots=True)
class Jeton:
    acces: str
    rafraichissement: str
    expire_le: float          # horodatage epoch
    scopes: tuple[str, ...] = ()
    login: str = ""
    user_id: str = ""

    @property
    def perime(self) -> bool:
        return time.time() >= self.expire_le - MARGE_SECONDES

    @property
    def secondes_restantes(self) -> int:
        return max(0, int(self.expire_le - time.time()))


class Jetons:
    """Coffre des jetons, persisté dans un unique fichier JSON."""

    USAGES = ("bot", "proprietaire")

    def __init__(self, chemin: Path) -> None:
        self.chemin = Path(chemin)
        self._jetons: dict[str, Jeton] = {}
        self._verrou = asyncio.Lock()
        self.charger()

    # ------------------------------------------------------------ persistance
    def charger(self) -> None:
        if not self.chemin.exists():
            return
        donnees = json.loads(self.chemin.read_text(encoding="utf-8"))
        for usage, brut in donnees.items():
            if usage not in self.USAGES:
                continue
            self._jetons[usage] = Jeton(
                acces=brut["acces"],
                rafraichissement=brut["rafraichissement"],
                expire_le=float(brut["expire_le"]),
                scopes=tuple(brut.get("scopes", ())),
                login=brut.get("login", ""),
                user_id=brut.get("user_id", ""),
            )

    def _ecrire(self) -> None:
        """Écriture atomique, puis droits 600 — dans cet ordre.

        Le fichier temporaire est créé en 600 dès l'origine : le poser en
        lecture publique, même une fraction de seconde, suffirait à le
        compromettre sur une machine partagée.
        """
        contenu = json.dumps(
            {usage: asdict(j) for usage, j in self._jetons.items()},
            ensure_ascii=False, indent=2)
        temporaire = self.chemin.with_suffix(self.chemin.suffix + ".tmp")
        descripteur = os.open(temporaire, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descripteur, "w", encoding="utf-8") as fichier:
            fichier.write(contenu)
        os.replace(temporaire, self.chemin)
        os.chmod(self.chemin, 0o600)

    # ------------------------------------------------------------------ accès
    def get(self, usage: str) -> Jeton | None:
        return self._jetons.get(usage)

    def enregistrer(self, usage: str, reponse: dict, *,
                    login: str = "", user_id: str = "") -> Jeton:
        """Enregistre la réponse brute de Twitch pour un usage donné."""
        if usage not in self.USAGES:
            raise ValueError(f"usage inconnu : {usage!r}")
        ancien = self._jetons.get(usage)
        jeton = Jeton(
            acces=reponse["access_token"],
            # Twitch omet parfois refresh_token au rafraîchissement : on
            # conserve alors le précédent, qui reste valable. L'écraser par
            # une chaîne vide condamnerait l'installation au prochain cycle.
            rafraichissement=reponse.get("refresh_token")
                             or (ancien.rafraichissement if ancien else ""),
            expire_le=time.time() + float(reponse.get("expires_in", 0)),
            scopes=tuple(reponse.get("scope", ()) or ()),
            login=login or (ancien.login if ancien else ""),
            user_id=user_id or (ancien.user_id if ancien else ""),
        )
        if not jeton.rafraichissement:
            raise JetonsIndisponibles(
                f"jeton « {usage} » reçu sans refresh_token : il expirerait "
                "sans recours. Relancer l'autorisation.")
        self._jetons[usage] = jeton
        self._ecrire()
        return jeton

    # --------------------------------------------------------- rafraîchissement
    async def valide(self, usage: str, client_id: str, client_secret: str) -> Jeton:
        """Retourne un jeton utilisable, en le rafraîchissant au besoin.

        Le verrou évite que dix événements simultanés déclenchent dix
        rafraîchissements concurrents : Twitch invalide l'ancien jeton de
        rafraîchissement à chaque usage, et la course les grillerait tous.
        """
        jeton = self._jetons.get(usage)
        if jeton is None:
            raise JetonsIndisponibles(
                f"aucun jeton « {usage} ». "
                + ("Connecter le compte du bot depuis l'interface."
                   if usage == "bot" else
                   "Se connecter à l'interface avec le compte du diffuseur."))
        if not jeton.perime:
            return jeton

        async with self._verrou:
            jeton = self._jetons[usage]
            if not jeton.perime:          # rafraîchi pendant l'attente
                return jeton
            return await self.rafraichir(usage, client_id, client_secret)

    async def rafraichir(self, usage: str, client_id: str, client_secret: str) -> Jeton:
        jeton = self._jetons[usage]
        async with httpx.AsyncClient(timeout=15) as client:
            reponse = await client.post(JETON, data={
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "refresh_token",
                "refresh_token": jeton.rafraichissement,
            })
        if reponse.status_code != 200:
            raise JetonsIndisponibles(
                f"rafraîchissement du jeton « {usage} » refusé "
                f"(HTTP {reponse.status_code}) : {reponse.text[:200]}. "
                "Le jeton de rafraîchissement a probablement été révoqué — "
                "il faut relancer l'autorisation.")
        return self.enregistrer(usage, reponse.json())

    def etat(self) -> dict[str, dict]:
        """Résumé pour l'interface et le journal. Ne contient aucun secret."""
        return {
            usage: {
                "login": j.login,
                "user_id": j.user_id,
                "scopes": list(j.scopes),
                "secondes_restantes": j.secondes_restantes,
                "perime": j.perime,
            }
            for usage, j in self._jetons.items()
        }
