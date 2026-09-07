"""Source Streamlabs : follow, don, abonnement, raid (D15).

Depuis D15, Streamlabs est la **source unique des alertes**. Ce connecteur
porte donc à lui seul un quart du périmètre v1 : s'il tombe, le bot ne
réagit plus à rien de ce qui se passe sur la chaîne, tout en continuant de
bavarder dans le chat — une panne partielle silencieuse.

**D24 — le client Socket.IO reste synchrone, dans un thread dédié.**
Streamlabs expose un serveur Socket.IO ancien (Engine.IO v3, R1) auquel seul
`python-socketio` 4.6.1 sait se connecter ; c'est cette version, en mode
synchrone, qui a été validée en phase 1. Passer à `AsyncClient` imposerait
`aiohttp` et une pile de transport différente — donc rejouer la validation
de R1 sans nécessité. On isole plutôt le client dans un thread qui dépose
ses événements dans la file du noyau, et le reste du moteur ne voit rien.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections import deque

from ..noyau.evenements import EvenementAlerte

URL = "https://sockets.streamlabs.com"

journal = logging.getLogger("bavardus.streamlabs")

# Correspondance des types Streamlabs vers les nôtres. Ce qui n'y figure pas
# est ignoré volontairement : « alertPlaying », « streamlabels » et consorts
# ne sont pas des événements de chaîne.
TYPES = {
    "donation": "don",
    "follow": "follow",
    "subscription": "abonnement",
    "resub": "abonnement",
    "raid": "raid",
    "host": "host",
    "bits": "bits",
}


def _montant(type_alerte: str, message: dict) -> str:
    """Le montant tel qu'on l'annoncerait à l'oral."""
    if type_alerte == "don":
        return str(message.get("formatted_amount")
                   or message.get("formattedAmount")
                   or message.get("amount", ""))
    if type_alerte == "abonnement":
        mois = message.get("months")
        return f"{mois} mois" if mois else ""
    if type_alerte in ("raid", "host"):
        nombre = message.get("raiders") or message.get("viewers")
        return f"{nombre} spectateurs" if nombre else ""
    if type_alerte == "bits":
        montant = message.get("amount")
        return f"{montant} bits" if montant else ""
    return ""


def en_evenement_alerte(type_streamlabs: str, message: dict) -> EvenementAlerte | None:
    """Convertit une entrée Streamlabs en événement interne. Fonction pure."""
    type_alerte = TYPES.get(type_streamlabs)
    if type_alerte is None:
        return None
    auteur = (message.get("name") or message.get("from")
              or message.get("display_name") or "").strip()
    if not auteur:
        return None
    return EvenementAlerte(
        type_alerte=type_alerte,
        auteur=auteur,
        montant=_montant(type_alerte, message),
        message=(message.get("message") or "").strip(),
    )


class SourceStreamlabs:
    def __init__(self, jeton: str, file: asyncio.Queue,
                 boucle: asyncio.AbstractEventLoop) -> None:
        self.jeton = jeton
        self.file = file
        self.boucle = boucle
        self._client = None
        self._thread: threading.Thread | None = None
        # Streamlabs réémet parfois un même événement. Sans mémoire des
        # identifiants déjà vus, le bot remercierait deux fois le même don.
        self._vus: deque[str] = deque(maxlen=200)

    # ------------------------------------------------------------- réception
    def _sur_evenement(self, donnees: dict) -> None:
        """Appelé depuis le thread Socket.IO, jamais depuis la boucle."""
        type_streamlabs = donnees.get("type", "")
        for message in donnees.get("message") or []:
            if not isinstance(message, dict):
                continue

            identifiant = str(message.get("_id") or "")
            if identifiant and identifiant in self._vus:
                journal.debug("événement %s déjà traité, ignoré", identifiant)
                continue
            if identifiant:
                self._vus.append(identifiant)

            evenement = en_evenement_alerte(type_streamlabs, message)
            if evenement is None:
                continue
            if donnees.get("isTest"):
                journal.info("alerte de TEST : %s de %s",
                             evenement.type_alerte, evenement.auteur)

            # Franchissement thread → boucle asyncio. put_nowait suffit :
            # la file du noyau n'a pas de borne, et bloquer ici gèlerait la
            # réception des alertes suivantes.
            self.boucle.call_soon_threadsafe(self.file.put_nowait, evenement)

    def _executer_client(self, arret_thread: threading.Event) -> None:
        import socketio                       # R1/G10 : version épinglée 4.6.1

        client = socketio.Client(reconnection=True, reconnection_delay=2,
                                 reconnection_delay_max=60)
        self._client = client

        @client.on("connect")
        def _connecte():                      # noqa: ANN202
            journal.info("connecté à Streamlabs")

        @client.on("disconnect")
        def _deconnecte():                    # noqa: ANN202
            journal.warning("déconnecté de Streamlabs")

        @client.on("event")
        def _evenement(donnees):              # noqa: ANN202
            try:
                self._sur_evenement(donnees or {})
            except Exception:                 # noqa: BLE001
                journal.exception("alerte Streamlabs illisible")

        try:
            client.connect(f"{URL}?token={self.jeton}",
                           transports=["websocket"])
            client.wait()
        except Exception as erreur:           # noqa: BLE001
            if not arret_thread.is_set():
                journal.error(
                    "connexion Streamlabs impossible : %s. Vérifier "
                    "STREAMLABS_SOCKET_TOKEN dans le .env (Paramètres du "
                    "compte > API Settings > Your Socket API Token).", erreur)
        finally:
            with_suppress = getattr(client, "disconnect", None)
            if with_suppress is not None:
                try:
                    client.disconnect()
                except Exception:             # noqa: BLE001
                    pass

    # ------------------------------------------------------------ cycle de vie
    async def executer(self, arret: asyncio.Event) -> None:
        if not self.jeton:
            journal.warning(
                "STREAMLABS_SOCKET_TOKEN absent : les alertes (follow, don, "
                "abonnement, raid) ne seront pas reçues. Le chat fonctionne "
                "normalement.")
            return

        arret_thread = threading.Event()
        self._thread = threading.Thread(
            target=self._executer_client, args=(arret_thread,),
            name="streamlabs", daemon=True)
        self._thread.start()

        try:
            await arret.wait()
        finally:
            arret_thread.set()
            if self._client is not None:
                try:
                    self._client.disconnect()
                except Exception:             # noqa: BLE001
                    pass
            # Thread démon : on lui laisse une seconde pour sortir, puis on
            # n'attend pas davantage — l'arrêt du bot ne doit pas dépendre
            # de la bonne volonté d'une bibliothèque tierce.
            if self._thread is not None:
                await asyncio.to_thread(self._thread.join, 1.0)
