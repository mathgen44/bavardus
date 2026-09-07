"""Application des sanctions de modération.

Séparé de `moderation.py` comme l'Émetteur l'est du Décideur : le premier
décide, celui-ci agit. C'est ce qui permet de tester la détection sans
Twitch, et de n'avoir qu'un seul endroit où des droits de modération sont
réellement exercés.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

from .moderation import Sanction

journal = logging.getLogger("bavardus.moderation")


class CanalModeration(Protocol):
    async def supprimer(self, message_id: str) -> None: ...
    async def exclure(self, utilisateur_id: str, duree: int, motif: str) -> None: ...
    async def annoncer(self, texte: str) -> None: ...


@dataclass(frozen=True, slots=True)
class ResultatSanction:
    appliquee: bool
    detail: str = ""


class Sanctionneur:
    def __init__(self, canal: CanalModeration) -> None:
        self.canal = canal

    async def appliquer(self, sanction: Sanction, evenement, config) -> ResultatSanction:
        """Applique, et n'interrompt jamais le bot en cas d'échec.

        Un refus de Twitch — scope manquant, bot non modérateur — ne doit pas
        arrêter le traitement du chat. Il est journalisé avec sa cause, et
        l'interface le montrera.
        """
        actes: list[str] = []
        try:
            # La suppression d'abord, dans tous les cas : c'est la seule
            # action qui retire réellement le message du chat.
            if evenement.message_id:
                await self.canal.supprimer(evenement.message_id)
                actes.append("message supprimé")
            else:
                actes.append("message non supprimé (identifiant absent)")

            if sanction.action == "exclure" and evenement.auteur_id:
                await self.canal.exclure(
                    evenement.auteur_id,
                    config.moderation.duree_exclusion_secondes,
                    sanction.motif)
                minutes = config.moderation.duree_exclusion_secondes // 60
                actes.append(f"exclusion de {minutes} min")

            elif sanction.action == "avertir":
                await self.canal.annoncer(
                    f"@{evenement.auteur} ce mot n'est pas le bienvenu ici.")
                actes.append("avertissement public")

        except Exception as erreur:                 # noqa: BLE001
            journal.error("modération impossible (%s) : %s. Vérifier que le "
                          "bot est modérateur de la chaîne et que les scopes "
                          "de modération ont été accordés.",
                          sanction.action, erreur)
            return ResultatSanction(False, f"échec : {erreur}")

        return ResultatSanction(True, ", ".join(actes))
