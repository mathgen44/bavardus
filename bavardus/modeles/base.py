"""Interface commune aux fournisseurs de modèles (D13).

Changer de modèle ou de fournisseur ne doit toucher qu'une ligne de
configuration. Tout ce qui diffère entre Ollama et une passerelle compatible
OpenAI est confiné dans un connecteur ; le reste du moteur ne voit que
`Modele.produire`.

`Reponse` porte volontairement `vide` et `cause` : G14 exige qu'une réponse
vide ne soit jamais postée **et** que sa cause soit journalisée. Distinguer
un modèle qui réfléchit (R15) d'un modèle qui échoue est ce qui permet de
diagnostiquer un bot muet sans lire le code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True, slots=True)
class Echange:
    """Un tour de parole du contexte transmis au modèle."""
    role: str          # "user" | "assistant"
    contenu: str


@dataclass(frozen=True, slots=True)
class Reponse:
    texte: str = ""
    cause_vide: str = ""
    latence_ms: int = 0
    jetons: int | None = None
    reflexion_detectee: bool = False
    brut: dict = field(default_factory=dict)

    @property
    def vide(self) -> bool:
        return not self.texte.strip()


class ErreurModele(Exception):
    """Le fournisseur est injoignable ou a refusé la requête."""


class Modele(Protocol):
    nom: str

    async def produire(self, systeme: str, echanges: list[Echange],
                       plafond_jetons: int, temperature: float) -> Reponse:
        ...

    async def disponible(self) -> tuple[bool, str]:
        """(joignable, message). Appelé au démarrage : mieux vaut une ligne
        rouge tout de suite qu'un bot silencieux découvert en plein live."""
        ...


def diagnostiquer_vide(*, raison_arret: str, reflexion: str,
                       jetons_sortis: int | None, plafond: int) -> str:
    """Explique une réponse vide en une phrase actionnable.

    Ce texte finit dans le journal et sous les yeux de quelqu'un qui ne
    connaît pas le code. Il doit nommer la cause ET le remède.
    """
    if reflexion:
        return (f"le modèle a consommé ses {jetons_sortis or plafond} jetons en "
                f"réflexion interne ({len(reflexion)} caractères) sans rien "
                f"produire — désactiver la réflexion (modele.reflexion: false) "
                f"ou relever plafond_jetons au-delà de 512 (R15/D16)")
    if raison_arret == "length":
        return (f"plafond de {plafond} jetons atteint avant le premier mot : "
                f"le modèle est probablement en mode réflexion (R15/D16)")
    if raison_arret in ("content_filter", "stop_sequence"):
        return f"réponse interrompue par le fournisseur ({raison_arret})"
    return f"réponse vide sans cause identifiée (arrêt : {raison_arret or 'inconnu'})"
