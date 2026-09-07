"""Minuterie : propose une relance, ne la décide pas.

Elle dépose un `EvenementMinuterie` à intervalle régulier. C'est le Décideur
qui tranche (D17) : silence réellement écoulé, quota horaire, débit global.
Séparer la proposition de la décision permet de changer les règles depuis
l'interface sans toucher à l'ordonnancement.
"""

from __future__ import annotations

import asyncio
import contextlib

from ..noyau.evenements import EvenementMinuterie

# Le pas de vérification, pas le délai de silence. Court, parce que le
# Décideur rejette de toute façon ce qui est prématuré, et que la relance
# doit tomber peu après l'échéance plutôt qu'un quart d'heure plus tard.
PAS_SECONDES = 30


async def executer(file: asyncio.Queue, arret: asyncio.Event,
                   pas: float = PAS_SECONDES) -> None:
    while not arret.is_set():
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(arret.wait(), timeout=pas)
        if arret.is_set():
            return
        await file.put(EvenementMinuterie())
