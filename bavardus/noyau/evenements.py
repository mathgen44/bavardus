"""Les événements qui traversent le noyau.

Trois sources, trois formes, un seul canal (D19). Chaque événement est
immuable : il traverse le Décideur, le Générateur et l'Émetteur sans que
personne puisse le modifier en route.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class EvenementChat:
    auteur: str
    texte: str
    auteur_id: str = ""
    horodatage: float = field(default_factory=time.time)

    genre = "chat"


@dataclass(frozen=True, slots=True)
class EvenementAlerte:
    """Follow, don, abonnement, raid — toujours via Streamlabs (D15)."""
    type_alerte: str            # follow | don | abonnement | raid
    auteur: str
    montant: str = ""           # « 5 € », « 3 mois », « 42 viewers »
    message: str = ""
    horodatage: float = field(default_factory=time.time)

    genre = "alerte"


@dataclass(frozen=True, slots=True)
class EvenementMinuterie:
    """Le chat est silencieux depuis assez longtemps pour envisager une
    relance. C'est le Décideur qui tranche, pas la minuterie."""
    horodatage: float = field(default_factory=time.time)

    genre = "minuterie"


Evenement = EvenementChat | EvenementAlerte | EvenementMinuterie
