"""L'Émetteur : seul point de sortie vers Twitch (G18).

Tout message publié passe ici, sans exception. C'est ce qui garantit que G4
(troncature à 500 caractères) et G14 (une réponse vide n'est jamais postée)
sont appliqués une fois pour toutes. Dispersés dans le code, ces garde-fous
se diluent : dans six mois, un chemin enverrait un message sans troncature,
et le défaut resterait invisible jusqu'au jour où le bot posterait 900
caractères.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol

from ..modeles.base import Reponse
from ..stockage.base import Base, Message


class CanalSortie(Protocol):
    """Abstraction du canal d'envoi. Le noyau se teste ainsi sans Twitch."""

    async def envoyer(self, texte: str) -> None:
        ...


@dataclass(frozen=True, slots=True)
class ResultatEmission:
    envoye: bool
    texte: str = ""
    raison: str = ""
    tronque: bool = False


class Emetteur:
    def __init__(self, canal: CanalSortie, base: Base, nom_bot: str) -> None:
        self.canal = canal
        self.base = base
        self.nom_bot = nom_bot

    @staticmethod
    def nettoyer(texte: str, longueur_max: int) -> tuple[str, bool]:
        """Met le texte en état d'être publié.

        Les modèles encadrent volontiers leur réponse de guillemets, ou la
        préfixent de leur propre nom. Publié tel quel, cela se voit
        immédiatement dans un chat.

        La troncature coupe au dernier espace : une phrase amputée en plein
        mot est plus visible qu'une phrase un peu plus courte.
        """
        propre = " ".join(texte.strip().split())
        for ouvrant, fermant in (('"', '"'), ("«", "»"), ("“", "”"), ("'", "'")):
            if propre.startswith(ouvrant) and propre.endswith(fermant) and len(propre) > 1:
                propre = propre[len(ouvrant):-len(fermant)].strip()

        if len(propre) <= longueur_max:
            return propre, False

        coupe = propre[:longueur_max]
        espace = coupe.rfind(" ")
        if espace > longueur_max * 0.6:
            coupe = coupe[:espace]
        return coupe.rstrip(" ,;:-") + "…", True

    async def emettre(self, reponse: Reponse, config, *,
                      spontane: bool = False) -> ResultatEmission:
        """Publie, ou explique pourquoi rien n'a été publié."""
        # G14 : une réponse vide n'est jamais postée, et sa cause est
        # journalisée. C'est ce qui distingue un modèle qui réfléchit (R15)
        # d'un modèle qui échoue — le bot doit faire cette distinction en
        # production, pas seulement les outils de diagnostic.
        if reponse.vide:
            await self.base.journaliser_appel(
                config.modele.nom, reponse.latence_ms, reponse.jetons,
                vide=True, cause_vide=reponse.cause_vide)
            return ResultatEmission(False, raison=reponse.cause_vide
                                    or "réponse vide sans cause identifiée")

        texte, tronque = self.nettoyer(reponse.texte, config.conversation.longueur_max)
        if not texte:
            await self.base.journaliser_appel(
                config.modele.nom, reponse.latence_ms, reponse.jetons,
                vide=True, cause_vide="réponse vide après nettoyage")
            return ResultatEmission(False, raison="réponse vide après nettoyage")

        await self.canal.envoyer(texte)

        await self.base.journaliser_appel(
            config.modele.nom, reponse.latence_ms, reponse.jetons)
        # Le message du bot entre dans l'historique : il sert de contexte au
        # tour suivant, et alimente les compteurs de débit. Marqué du_bot,
        # il n'influence pas le calcul du silence (le bot se répondrait
        # sinon à lui-même indéfiniment).
        await self.base.ajouter_message(Message(
            horodatage=time.time(), auteur=self.nom_bot, texte=texte,
            du_bot=True))

        return ResultatEmission(True, texte=texte, tronque=tronque)
