"""Le Générateur : produit le texte, une fois la décision prise.

Il n'a pas d'avis sur l'opportunité de parler — c'est le Décideur qui a
tranché (D17). Son seul travail : assembler le persona et le contexte, puis
interroger le modèle.

Le persona reçoit une **consigne de format non négociable** en plus du texte
libre configuré par l'utilisateur. Le test de qualité de la phase 1 l'a
montré : livré à lui-même, un modèle explique qu'il est une intelligence
artificielle, ou répond en trois phrases là où une suffit.
"""

from __future__ import annotations

from ..modeles.base import Echange, ErreurModele, Modele, Reponse
from ..stockage.base import Message
from .decideur import Decision
from .evenements import Evenement, EvenementAlerte, EvenementChat, EvenementMinuterie

# Ajouté au persona de l'utilisateur. Ce sont des contraintes de forme, pas
# de personnalité : elles ne doivent pas être laissées à sa charge, sous
# peine de les voir oubliées dans chaque persona écrit à la main.
CONSIGNES = """
Contraintes absolues :
- Une seule phrase, courte. Jamais de liste, jamais de paragraphe.
- Réponds uniquement le message à publier, sans guillemets ni préfixe.
- N'invente jamais un chiffre, un score ou un fait que tu ne peux pas connaître.
- Ne parle jamais de toi comme d'un bot, d'une IA ou d'un modèle.
- N'annonce pas ce que tu vas faire : fais-le.
""".strip()


def construire_systeme(persona: str) -> str:
    return f"{persona.strip()}\n\n{CONSIGNES}" if persona.strip() else CONSIGNES


def construire_echanges(evenement: Evenement, decision: Decision,
                        historique: list[Message], nom_bot: str) -> list[Echange]:
    """Transforme l'historique et l'événement en tours de parole.

    Les messages du bot sont marqués « assistant » : sans cela, le modèle
    relit ses propres réponses comme des messages de spectateurs et finit
    par se citer lui-même.
    """
    echanges: list[Echange] = []
    for message in historique:
        if message.du_bot:
            echanges.append(Echange("assistant", message.texte))
        else:
            echanges.append(Echange("user", f"{message.auteur} : {message.texte}"))

    if isinstance(evenement, EvenementChat):
        echanges.append(Echange("user", f"{evenement.auteur} : {evenement.texte}"))

    elif isinstance(evenement, EvenementAlerte):
        details = [f"{evenement.type_alerte} de {evenement.auteur}"]
        if evenement.montant:
            details.append(evenement.montant)
        if evenement.message:
            details.append(f"message : « {evenement.message} »")
        echanges.append(Echange(
            "user",
            f"[événement de la chaîne] {', '.join(details)}. "
            f"Réagis en une phrase, en t'adressant à {evenement.auteur}."))

    elif isinstance(evenement, EvenementMinuterie):
        echanges.append(Echange(
            "user",
            "[le chat est silencieux depuis un moment] Lance une remarque courte "
            "pour relancer la conversation. N'invente aucun fait sur ce qui se "
            "passe à l'écran."))

    return echanges


class Generateur:
    def __init__(self, modele: Modele) -> None:
        self.modele = modele

    async def produire(self, evenement: Evenement, decision: Decision,
                       config, historique: list[Message],
                       nom_bot: str) -> Reponse:
        """Retourne une Reponse, éventuellement vide.

        Une erreur du fournisseur est convertie en réponse vide porteuse de
        sa cause : le noyau ne doit pas s'arrêter parce qu'Ollama a hoqueté,
        mais la cause doit rester lisible dans le journal (G14).
        """
        systeme = construire_systeme(config.persona)
        echanges = construire_echanges(evenement, decision, historique, nom_bot)
        try:
            return await self.modele.produire(
                systeme, echanges,
                config.modele.plafond_jetons, config.modele.temperature)
        except ErreurModele as erreur:
            return Reponse(cause_vide=str(erreur))
