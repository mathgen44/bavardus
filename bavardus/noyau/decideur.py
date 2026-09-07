"""Le Décideur : faut-il répondre ? (D17, G17)

C'est le module qui donne corps à D17. Le test de qualité de la phase 1 avait
montré qu'un modèle à qui l'on demande de répondre exactement « RIEN » répond
quand même : déléguer le silence au modèle, c'est accepter un bot qui parle
par-dessus tout le monde. La décision revient donc au code, sur des règles
explicites et lisibles dans l'interface.

**Ce module est de la logique pure.** Aucun accès réseau, aucun accès base :
tout ce dont il a besoin lui est passé dans un `ContexteDecision`. C'est ce
qui le rend intégralement testable, et c'est délibéré.

Chaque décision porte sa raison (G17). Sans elle, un bot jugé trop bavard ou
anormalement muet ne se diagnostique qu'en relisant le code.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .evenements import Evenement, EvenementAlerte, EvenementChat, EvenementMinuterie


@dataclass(frozen=True, slots=True)
class ContexteDecision:
    """Tout ce que le Décideur doit savoir du monde extérieur.

    Passé en paramètre plutôt que lu depuis la base : le Décideur reste une
    fonction pure, et ses tests n'ont besoin d'aucune infrastructure.
    """
    nom_bot: str
    id_bot: str = ""
    messages_bot_derniere_minute: int = 0
    messages_spontanes_derniere_heure: int = 0
    secondes_de_silence: float | None = None


@dataclass(frozen=True, slots=True)
class Decision:
    repondre: bool
    raison: str
    genre: str = ""
    detail: str = ""
    commande: str = ""
    arguments: str = ""


MOTIF_COMMANDE = re.compile(r"^\s*!([a-zA-Z0-9_-]{1,32})\s*(.*)$", re.DOTALL)


def _est_mentionne(texte: str, nom_bot: str) -> bool:
    """Mention au sens large : « @lebot », « lebot, » ou le nom en tête.

    On ne cherche pas le nom n'importe où dans la phrase : « je préfère
    bavardus à l'autre bot » parle du bot sans lui parler. Exiger la forme
    d'une interpellation évite au bot de s'inviter dans les conversations
    qui le mentionnent à la troisième personne.
    """
    if not nom_bot:
        return False
    nom = re.escape(nom_bot.lower())
    return bool(re.search(rf"(^|\s)@{nom}\b", texte.lower())
                or re.match(rf"^\s*{nom}\s*[,:!?]", texte.lower()))


def decider(evenement: Evenement, config, contexte: ContexteDecision) -> Decision:
    """Tranche, et dit pourquoi.

    L'ordre des règles est significatif : ce qui protège passe avant ce qui
    fait parler.
    """
    parole = config.prise_de_parole

    # --- 1. Ne jamais réagir à soi-même -------------------------------------
    # Avant tout le reste : ce n'est pas une décision de parole, c'est une
    # condition d'existence. Sans elle, le bot s'auto-alimente.
    if isinstance(evenement, EvenementChat):
        if (contexte.id_bot and evenement.auteur_id == contexte.id_bot) or \
           (evenement.auteur.lower() == contexte.nom_bot.lower()):
            return Decision(False, "message du bot lui-même", evenement.genre)

        # --- 2. Les autres bots de la chaîne --------------------------------
        # Deux bots qui se répondent poliment saturent un chat en quelques
        # secondes, et personne ne peut plus rien y écrire.
        if evenement.auteur.lower() in parole.comptes_ignores:
            return Decision(False, f"compte ignoré ({evenement.auteur})", evenement.genre)

    # --- 3. Anti-flood global ----------------------------------------------
    # Garde-fou dur : il l'emporte même sur une interpellation directe. Un bot
    # qui déborde est plus nuisible qu'un bot qui rate une réponse.
    if contexte.messages_bot_derniere_minute >= parole.max_messages_par_minute:
        return Decision(
            False,
            f"débit maximum atteint ({contexte.messages_bot_derniere_minute}/"
            f"{parole.max_messages_par_minute} par minute)",
            evenement.genre)

    # --- 4. Chat : commande, puis mention ----------------------------------
    if isinstance(evenement, EvenementChat):
        correspondance = MOTIF_COMMANDE.match(evenement.texte)
        if correspondance:
            if not parole.sur_commande:
                return Decision(False, "commandes désactivées", evenement.genre)
            return Decision(True, f"commande !{correspondance.group(1)}",
                            evenement.genre,
                            commande=correspondance.group(1).lower(),
                            arguments=correspondance.group(2).strip())

        if _est_mentionne(evenement.texte, contexte.nom_bot):
            if not parole.sur_mention:
                return Decision(False, "réponse aux mentions désactivée", evenement.genre)
            return Decision(True, "mention du bot", evenement.genre)

        return Decision(False, "message qui ne concerne pas le bot", evenement.genre)

    # --- 5. Alertes --------------------------------------------------------
    if isinstance(evenement, EvenementAlerte):
        if not parole.sur_alerte:
            return Decision(False, "réaction aux alertes désactivée", evenement.genre)
        return Decision(True, f"alerte {evenement.type_alerte}", evenement.genre,
                        detail=evenement.auteur)

    # --- 6. Prise de parole spontanée --------------------------------------
    if isinstance(evenement, EvenementMinuterie):
        spontanee = parole.spontanee
        if not spontanee.active:
            return Decision(False, "prise de parole spontanée désactivée",
                            evenement.genre)
        if contexte.secondes_de_silence is None:
            return Decision(False, "aucun message dans l'historique : rien à relancer",
                            evenement.genre)
        requis = spontanee.minutes_de_silence * 60
        if contexte.secondes_de_silence < requis:
            return Decision(
                False,
                f"silence trop court ({int(contexte.secondes_de_silence)} s "
                f"sur {int(requis)} requises)", evenement.genre)
        if contexte.messages_spontanes_derniere_heure >= spontanee.max_par_heure:
            return Decision(
                False,
                f"quota de relances atteint "
                f"({contexte.messages_spontanes_derniere_heure}/"
                f"{spontanee.max_par_heure} par heure)", evenement.genre)
        return Decision(True, "relance après silence", evenement.genre,
                        detail=f"{int(contexte.secondes_de_silence)} s de silence")

    return Decision(False, f"type d'événement non géré ({type(evenement).__name__})")
