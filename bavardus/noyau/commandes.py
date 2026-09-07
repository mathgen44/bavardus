"""Commandes à réponse fixe.

Une réponse écrite d'avance vaut mieux qu'une réponse improvisée dès qu'il
s'agit de donner un fait : demandé son lien Discord, un modèle en invente un
plausible et faux. C'est R11 appliqué à ce qui compte le plus — les liens
qu'on donne à sa communauté.

Comme le Décideur, ce module est de la logique pure. L'état des délais
d'attente est passé en paramètre, pas lu depuis une horloge globale : les
tests n'ont pas à dormir.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Resolution:
    """Ce qu'il faut faire d'un appel de commande."""
    texte: str = ""             # réponse fixe à publier
    au_modele: bool = False     # laisser le modèle improviser
    refus: str = ""             # raison de ne rien faire

    @property
    def agit(self) -> bool:
        return bool(self.texte) or self.au_modele


def substituer(gabarit: str, *, auteur: str, chaine: str, argument: str) -> str:
    """Remplace les marques connues, laisse le reste intact.

    Une marque inconnue est conservée telle quelle plutôt que vidée : mieux
    vaut afficher « {truc} » et voir son erreur que publier une phrase
    amputée sans comprendre pourquoi.
    """
    valeurs = {"auteur": auteur, "chaine": chaine, "argument": argument,
               "arguments": argument}
    return re.sub(r"\{(\w+)\}",
                  lambda m: valeurs.get(m.group(1), m.group(0)), gabarit)


def resoudre(decision, evenement, config, *,
             dernier_appel: float | None = None,
             maintenant: float = 0.0) -> Resolution:
    """Que répondre à `!quelquechose` ?

    `dernier_appel` est l'horodatage du dernier déclenchement de CETTE
    commande, ou None si elle n'a jamais servi.
    """
    commande = config.commande(decision.commande)

    if commande is None:
        # Les chats sont pleins de commandes destinées à d'autres bots
        # (!uptime, !lurk, !drop). Y répondre ferait doublon.
        if config.commandes_inconnues_au_modele:
            return Resolution(au_modele=True)
        return Resolution(refus=f"commande !{decision.commande} inconnue")

    if commande.pour == "moderateurs" and not getattr(
            evenement, "est_moderateur", False):
        return Resolution(refus=f"!{commande.nom} est réservée aux modérateurs")
    if commande.pour == "abonnes" and not getattr(evenement, "est_abonne", False):
        return Resolution(refus=f"!{commande.nom} est réservée aux abonnés")

    if (dernier_appel is not None and commande.cooldown_secondes > 0
            and maintenant - dernier_appel < commande.cooldown_secondes):
        reste = int(commande.cooldown_secondes - (maintenant - dernier_appel))
        return Resolution(
            refus=f"!{commande.nom} en délai d'attente ({reste} s restantes)")

    return Resolution(texte=substituer(
        commande.reponse,
        auteur=getattr(evenement, "auteur", ""),
        chaine=config.twitch.chaine,
        argument=decision.arguments))
