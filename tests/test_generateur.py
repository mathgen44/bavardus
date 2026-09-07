"""Le Générateur : assemblage du prompt et robustesse."""

import pytest

from bavardus.config import depuis_dict
from bavardus.modeles.base import Echange, ErreurModele, Reponse
from bavardus.noyau.decideur import Decision
from bavardus.noyau.generateur import (CONSIGNES, Generateur,
                                       construire_echanges, construire_systeme)
from bavardus.noyau.evenements import (EvenementAlerte, EvenementChat,
                                       EvenementMinuterie)
from bavardus.stockage.base import Message


def test_les_consignes_de_format_sont_toujours_ajoutees():
    """Contraintes de forme, pas de personnalité : les laisser à la charge
    de l'utilisateur, c'est les voir oubliées dans chaque persona."""
    assert CONSIGNES in construire_systeme("Tu es taquin.")
    assert CONSIGNES in construire_systeme("")


def test_les_messages_du_bot_sont_marques_assistant():
    """Sans cela, le modèle relit ses propres réponses comme des messages de
    spectateurs et finit par se citer lui-même."""
    historique = [
        Message(1.0, "kevin", "salut"),
        Message(2.0, "bavardus", "salut kevin", du_bot=True),
    ]
    echanges = construire_echanges(
        EvenementChat(auteur="kevin", texte="ça va ?"),
        Decision(True, "mention"), historique, "bavardus")

    assert echanges[0] == Echange("user", "kevin : salut")
    assert echanges[1] == Echange("assistant", "salut kevin")
    assert echanges[-1] == Echange("user", "kevin : ça va ?")


def test_alerte_donne_une_consigne_explicite():
    echanges = construire_echanges(
        EvenementAlerte("don", "kevin_", "5 €", "continue comme ça"),
        Decision(True, "alerte don"), [], "bavardus")
    dernier = echanges[-1].contenu
    assert "don de kevin_" in dernier and "5 €" in dernier
    assert "kevin_" in dernier


def test_minuterie_interdit_dinventer_du_contexte():
    """Le bot ne voit pas l'écran : sans cette consigne, il commente une
    partie imaginaire."""
    echanges = construire_echanges(EvenementMinuterie(), Decision(True, "relance"),
                                   [], "bavardus")
    assert "N'invente aucun fait" in echanges[-1].contenu


class ModeleMuet:
    nom = "faux"

    def __init__(self, reponse=None, erreur=None):
        self.reponse, self.erreur = reponse, erreur
        self.appels = []

    async def produire(self, systeme, echanges, plafond, temperature):
        self.appels.append((systeme, echanges, plafond, temperature))
        if self.erreur:
            raise self.erreur
        return self.reponse

    async def disponible(self):
        return True, ""


async def test_les_parametres_de_configuration_sont_transmis():
    modele = ModeleMuet(Reponse(texte="ok"))
    config = depuis_dict({"modele": {"plafond_jetons": 42, "temperature": 0.3}})
    await Generateur(modele).produire(
        EvenementChat(auteur="k", texte="?"), Decision(True, "mention"),
        config, [], "bavardus")
    _, _, plafond, temperature = modele.appels[0]
    assert plafond == 42 and temperature == 0.3


async def test_une_panne_du_fournisseur_devient_une_reponse_vide():
    """Le noyau ne doit pas s'arrêter parce qu'Ollama a hoqueté, mais la
    cause doit rester lisible dans le journal (G14)."""
    modele = ModeleMuet(erreur=ErreurModele("Ollama injoignable sur http://x"))
    reponse = await Generateur(modele).produire(
        EvenementChat(auteur="k", texte="?"), Decision(True, "mention"),
        depuis_dict({}), [], "bavardus")
    assert reponse.vide
    assert "injoignable" in reponse.cause_vide
