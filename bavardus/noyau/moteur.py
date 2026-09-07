"""Le Moteur : assemble Décideur, Générateur et Émetteur.

Une seule méthode compte, `traiter`. Elle est écrite pour être testable de
bout en bout avec des doubles : c'est elle qui décide du comportement observé
du bot, et elle ne doit pas dépendre de Twitch pour être vérifiée.
"""

from __future__ import annotations

import asyncio
import logging
import time

from ..stockage.base import Base, Message
from .decideur import ContexteDecision, Decision, decider
from .emetteur import Emetteur, ResultatEmission
from .evenements import Evenement, EvenementChat, EvenementMinuterie
from .generateur import Generateur

journal = logging.getLogger("bavardus.moteur")


class Moteur:
    def __init__(self, gestionnaire_config, base: Base, generateur: Generateur,
                 emetteur: Emetteur, nom_bot: str, id_bot: str = "") -> None:
        self.config = gestionnaire_config
        self.base = base
        self.generateur = generateur
        self.emetteur = emetteur
        self.nom_bot = nom_bot
        self.id_bot = id_bot

    def _contexte(self, config) -> ContexteDecision:
        return ContexteDecision(
            nom_bot=self.nom_bot,
            id_bot=self.id_bot,
            messages_bot_derniere_minute=self.base.messages_bot_depuis(60),
            messages_spontanes_derniere_heure=self.base.messages_bot_depuis(3600),
            secondes_de_silence=self.base.secondes_depuis_dernier_message(
                humains_seulement=True),
        )

    async def traiter(self, evenement: Evenement) -> ResultatEmission:
        # La configuration est relue à chaque événement : elle est immuable,
        # donc ce traitement va au bout avec la version qu'il a lue, même si
        # l'interface la change entre-temps (D21).
        config = self.config.courante

        # Tout message humain entre dans l'historique, même sans réponse :
        # c'est le contexte des tours suivants et le calcul du silence.
        if isinstance(evenement, EvenementChat):
            await self.base.ajouter_message(Message(
                horodatage=evenement.horodatage, auteur=evenement.auteur,
                auteur_id=evenement.auteur_id, texte=evenement.texte))

        decision = decider(evenement, config, self._contexte(config))

        if not decision.repondre:
            # Une minuterie rejetée est le cas courant, pas un incident :
            # la journaliser noierait le journal des décisions sous le bruit.
            if not isinstance(evenement, EvenementMinuterie):
                await self.base.journaliser_decision(
                    decision.genre, False, decision.raison, decision.detail)
            return ResultatEmission(False, raison=decision.raison)

        await self.base.journaliser_decision(
            decision.genre, True, decision.raison, decision.detail)

        historique = self.base.contexte(config.conversation.contexte_messages)
        reponse = await self.generateur.produire(
            evenement, decision, config, historique, self.nom_bot)
        resultat = await self.emetteur.emettre(reponse, config)

        if not resultat.envoye:
            journal.warning("rien publié (%s) : %s", decision.raison, resultat.raison)
        return resultat

    async def executer(self, file: asyncio.Queue, arret: asyncio.Event) -> None:
        """Consomme la file jusqu'à l'arrêt.

        Une exception sur un événement ne doit pas emporter le bot : elle est
        journalisée et le traitement continue. Un live qui s'arrête parce
        qu'un message a mal tourné serait pire que le message manqué.
        """
        while not arret.is_set():
            try:
                evenement = await asyncio.wait_for(file.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                raise
            try:
                await self.traiter(evenement)
            except asyncio.CancelledError:
                raise
            except Exception:                       # noqa: BLE001
                journal.exception("échec du traitement d'un événement")
            finally:
                file.task_done()
