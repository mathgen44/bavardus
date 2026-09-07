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
    # Identifiant Twitch du message : sans lui, impossible de le supprimer.
    message_id: str = ""
    # Badges Twitch de l'auteur : broadcaster, moderator, subscriber, vip…
    # Ils disent qui parle, ce qui sert autant à la modération (ne pas
    # sanctionner un modérateur) qu'aux commandes réservées.
    badges: tuple[str, ...] = ()
    horodatage: float = field(default_factory=time.time)

    genre = "chat"

    @property
    def est_diffuseur(self) -> bool:
        return "broadcaster" in self.badges

    @property
    def est_moderateur(self) -> bool:
        return "moderator" in self.badges or self.est_diffuseur

    @property
    def est_abonne(self) -> bool:
        # Le diffuseur et ses modérateurs ne sont pas nécessairement
        # abonnés, mais leur refuser une commande réservée aux abonnés
        # n'aurait aucun sens.
        return ("subscriber" in self.badges or "founder" in self.badges
                or self.est_moderateur)


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
