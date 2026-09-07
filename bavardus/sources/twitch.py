"""Source Twitch : EventSub WebSocket en lecture, Helix en écriture.

Reprend le protocole validé en phase 1 par `outils/diag_twitch.py`, porté en
asynchrone et durci pour tourner des heures sans surveillance.

**D15 : seul `channel.chat.message` est souscrit.** Les alertes viennent de
Streamlabs, source unique. `channel.follow` exigerait `moderator:read:followers`
sur un jeton du diffuseur, et ferait réagir deux fois au même événement.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time

import httpx
import websockets

from ..noyau.evenements import EvenementChat
from ..stockage.jetons import Jetons

HELIX = "https://api.twitch.tv/helix"
EVENTSUB = "wss://eventsub.wss.twitch.tv/ws"

journal = logging.getLogger("bavardus.twitch")


class ErreurTwitch(Exception):
    pass


class ClientTwitch:
    """Appels Helix, avec rafraîchissement transparent du jeton du bot."""

    def __init__(self, jetons: Jetons, client_id: str, client_secret: str,
                 usage: str = "bot") -> None:
        self.jetons = jetons
        self.client_id = client_id
        self.client_secret = client_secret
        self.usage = usage

    async def _entetes(self) -> dict[str, str]:
        jeton = await self.jetons.valide(self.usage, self.client_id, self.client_secret)
        return {"Client-Id": self.client_id,
                "Authorization": f"Bearer {jeton.acces}"}

    async def appeler(self, chemin: str, *, methode: str = "GET",
                      params: dict | None = None, corps: dict | None = None) -> dict:
        async with httpx.AsyncClient(timeout=15) as client:
            reponse = await client.request(
                methode, f"{HELIX}{chemin}", headers=await self._entetes(),
                params=params, json=corps)

        if reponse.status_code == 401:
            # Le jeton a été révoqué côté Twitch, pas simplement expiré :
            # le rafraîchissement automatique n'y peut rien.
            raise ErreurTwitch(
                f"Twitch refuse le jeton « {self.usage} » (401). Il a "
                f"probablement été révoqué — relancer l'autorisation.")
        if reponse.status_code == 403:
            raise ErreurTwitch(
                f"Twitch refuse l'action (403) sur {chemin} : le bot n'est pas "
                f"autorisé sur cette chaîne. Le nommer modérateur "
                f"(/mod <compte_du_bot>) ou faire accorder le scope channel:bot. "
                f"Détail : {reponse.text[:200]}")
        if reponse.status_code >= 400:
            raise ErreurTwitch(
                f"Twitch a répondu HTTP {reponse.status_code} sur {chemin} : "
                f"{reponse.text[:200]}")
        return reponse.json() if reponse.content else {}

    async def utilisateur(self, login: str) -> dict:
        donnees = await self.appeler("/users", params={"login": login})
        if not donnees.get("data"):
            raise ErreurTwitch(
                f"la chaîne « {login} » est introuvable sur Twitch. "
                f"Vérifier twitch.chaine dans config.yaml.")
        return donnees["data"][0]

    async def envoyer_message(self, broadcaster_id: str, sender_id: str,
                              texte: str) -> None:
        await self.appeler("/chat/messages", methode="POST", corps={
            "broadcaster_id": broadcaster_id,
            "sender_id": sender_id,
            "message": texte,
        })

    # ----------------------------------------------------------- modération
    async def supprimer_message(self, broadcaster_id: str, moderateur_id: str,
                                message_id: str) -> None:
        await self.appeler("/moderation/chat", methode="DELETE", params={
            "broadcaster_id": broadcaster_id,
            "moderator_id": moderateur_id,
            "message_id": message_id,
        })

    async def exclure(self, broadcaster_id: str, moderateur_id: str,
                      utilisateur_id: str, duree: int, motif: str) -> None:
        """Exclusion TEMPORAIRE. Un bot ne bannit jamais définitivement :
        une erreur de liste de mots ne doit pas coûter un spectateur."""
        await self.appeler(
            "/moderation/bans", methode="POST",
            params={"broadcaster_id": broadcaster_id,
                    "moderator_id": moderateur_id},
            corps={"data": {"user_id": utilisateur_id,
                            "duration": max(1, int(duree)),
                            "reason": motif[:500]}})


class CanalTwitch:
    """Canal de sortie de l'Émetteur (G18)."""

    def __init__(self, client: ClientTwitch, broadcaster_id: str,
                 sender_id: str) -> None:
        self.client = client
        self.broadcaster_id = broadcaster_id
        self.sender_id = sender_id

    async def envoyer(self, texte: str) -> None:
        await self.client.envoyer_message(self.broadcaster_id, self.sender_id, texte)


class CanalModerationTwitch:
    """Le seul endroit où des droits de modération sont exercés."""

    def __init__(self, client: ClientTwitch, broadcaster_id: str,
                 moderateur_id: str) -> None:
        self.client = client
        self.broadcaster_id = broadcaster_id
        self.moderateur_id = moderateur_id

    async def supprimer(self, message_id: str) -> None:
        await self.client.supprimer_message(self.broadcaster_id,
                                            self.moderateur_id, message_id)

    async def exclure(self, utilisateur_id: str, duree: int, motif: str) -> None:
        await self.client.exclure(self.broadcaster_id, self.moderateur_id,
                                  utilisateur_id, duree, motif)

    async def annoncer(self, texte: str) -> None:
        await self.client.envoyer_message(self.broadcaster_id,
                                          self.moderateur_id, texte)


# ------------------------------------------------------------------ EventSub
def interpreter(brut: str) -> tuple[str, dict]:
    """(type de message, charge utile). Fonction pure, donc testable."""
    message = json.loads(brut)
    return message.get("metadata", {}).get("message_type", ""), message.get("payload", {})


def en_evenement_chat(charge: dict) -> EvenementChat | None:
    """Convertit une notification `channel.chat.message` en événement interne."""
    evenement = charge.get("event") or {}
    texte = ((evenement.get("message") or {}).get("text") or "").strip()
    auteur = evenement.get("chatter_user_name") or evenement.get("chatter_user_login") or ""
    if not texte or not auteur:
        return None
    return EvenementChat(
        auteur=auteur,
        texte=texte,
        auteur_id=str(evenement.get("chatter_user_id", "")),
        message_id=str(evenement.get("message_id", "")),
        badges=tuple(b.get("set_id", "") for b in (evenement.get("badges") or [])
                     if isinstance(b, dict)),
        horodatage=time.time(),
    )


class SourceTwitch:
    """Écoute le chat et dépose des événements dans la file du noyau."""

    def __init__(self, client: ClientTwitch, file: asyncio.Queue,
                 broadcaster_id: str, user_id: str) -> None:
        self.client = client
        self.file = file
        self.broadcaster_id = broadcaster_id
        self.user_id = user_id
        self._session: str = ""

    async def _souscrire(self) -> None:
        """D15 : le chat, et rien d'autre."""
        await self.client.appeler("/eventsub/subscriptions", methode="POST", corps={
            "type": "channel.chat.message",
            "version": "1",
            "condition": {"broadcaster_user_id": self.broadcaster_id,
                          "user_id": self.user_id},
            "transport": {"method": "websocket", "session_id": self._session},
        })
        journal.info("abonné à channel.chat.message")

    async def executer(self, arret: asyncio.Event) -> None:
        """Boucle de connexion, avec reprise.

        Une coupure réseau en plein live ne doit pas laisser le bot muet
        jusqu'au prochain redémarrage manuel : on se reconnecte avec un
        délai croissant, plafonné pour ne pas marteler Twitch.
        """
        url = EVENTSUB
        attente = 1.0
        while not arret.is_set():
            try:
                async with websockets.connect(url, ping_interval=None) as connexion:
                    url = await self._session_active(connexion, arret)
                    attente = 1.0
                    if url is None:
                        url = EVENTSUB
            except asyncio.CancelledError:
                raise
            except Exception as erreur:            # noqa: BLE001
                if arret.is_set():
                    return
                journal.warning("EventSub interrompu (%s) — reprise dans %.0f s",
                                erreur, attente)
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(arret.wait(), timeout=attente)
                attente = min(attente * 2, 60)
                url = EVENTSUB

    async def _session_active(self, connexion, arret: asyncio.Event) -> str | None:
        """Traite une session ; retourne une URL de reconnexion, ou None."""
        async for brut in connexion:
            if arret.is_set():
                return None
            type_message, charge = interpreter(brut)

            if type_message == "session_welcome":
                self._session = charge["session"]["id"]
                journal.info("session EventSub %s…", self._session[:12])
                await self._souscrire()

            elif type_message == "notification":
                evenement = en_evenement_chat(charge)
                if evenement is not None:
                    await self.file.put(evenement)

            elif type_message == "session_reconnect":
                # Twitch prévient avant de fermer : on bascule sans perdre
                # de message, l'ancienne connexion restant ouverte le temps
                # que la nouvelle prenne le relais.
                nouvelle = charge["session"]["reconnect_url"]
                journal.info("Twitch demande une reconnexion")
                return nouvelle

            elif type_message == "revocation":
                journal.error(
                    "Twitch a révoqué l'abonnement : %s. "
                    "Vérifier que le bot est toujours autorisé sur la chaîne.",
                    charge.get("subscription", {}).get("status", "?"))

            # session_keepalive : rien à faire, la connexion vit.
        return None
