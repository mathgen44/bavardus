"""L'Émetteur : le seul point de sortie (G18).

Ces tests valident les deux garde-fous qui, dispersés dans le code, se
diluent : G4 (troncature) et G14 (une réponse vide n'est jamais postée).
"""

import pytest

from bavardus.config import depuis_dict
from bavardus.modeles.base import Reponse
from bavardus.noyau.emetteur import Emetteur
from bavardus.stockage.base import Base


class CanalEspion:
    def __init__(self):
        self.envoyes = []

    async def envoyer(self, texte):
        self.envoyes.append(texte)


@pytest.fixture
def attirail(tmp_path):
    base = Base(tmp_path / "b.db")
    base.ouvrir()
    canal = CanalEspion()
    yield Emetteur(canal, base, "bavardus"), canal, base
    base.fermer()


# ------------------------------------------------------------------ nettoyage
@pytest.mark.parametrize("brut,attendu", [
    ('"Salut tout le monde"', "Salut tout le monde"),
    ("« Salut »", "Salut"),
    ("  Salut\n\n  les   gens  ", "Salut les gens"),
    ("Salut", "Salut"),
])
def test_nettoyage(brut, attendu):
    """Les modèles encadrent volontiers leur réponse de guillemets. Publié
    tel quel, cela se voit immédiatement dans un chat."""
    assert Emetteur.nettoyer(brut, 500)[0] == attendu


def test_troncature_coupe_au_dernier_espace():
    """Une phrase amputée en plein mot est plus visible qu'une phrase un peu
    plus courte."""
    texte = "mot " * 200
    coupe, tronque = Emetteur.nettoyer(texte, 500)
    assert tronque is True
    assert len(coupe) <= 501
    assert coupe.endswith("…")
    assert "mo…" not in coupe


def test_pas_de_troncature_sous_la_limite():
    coupe, tronque = Emetteur.nettoyer("court", 500)
    assert tronque is False and coupe == "court"


# ------------------------------------------------------------------- G4 / G14
async def test_message_normal_publie_et_historise(attirail):
    emetteur, canal, base = attirail
    resultat = await emetteur.emettre(Reponse(texte="Salut !", latence_ms=800),
                                      depuis_dict({}))
    assert resultat.envoye is True
    assert canal.envoyes == ["Salut !"]
    # Le message du bot entre dans l'historique : contexte du tour suivant
    # et compteurs de débit.
    assert base.messages_bot_depuis(60) == 1


async def test_troncature_appliquee_a_la_sortie(attirail):
    """G4 : le plafond de Twitch est appliqué ici, une fois pour toutes."""
    emetteur, canal, _ = attirail
    config = depuis_dict({"conversation": {"longueur_max": 50}})
    resultat = await emetteur.emettre(Reponse(texte="a " * 100), config)
    assert resultat.tronque is True
    assert len(canal.envoyes[0]) <= 51


async def test_reponse_vide_jamais_publiee(attirail):
    """G14 : rien ne sort, et la cause est journalisée."""
    emetteur, canal, base = attirail
    reponse = Reponse(cause_vide="réflexion interne (R15/D16)", latence_ms=900,
                      jetons=60)
    resultat = await emetteur.emettre(reponse, depuis_dict({}))

    assert resultat.envoye is False
    assert canal.envoyes == []
    assert "R15" in resultat.raison
    stats = base.statistiques()
    assert stats["reponses_vides"] == 1 and stats["taux_vides"] == 1.0


async def test_reponse_devenue_vide_apres_nettoyage(attirail):
    emetteur, canal, _ = attirail
    resultat = await emetteur.emettre(Reponse(texte='  ""  '), depuis_dict({}))
    assert resultat.envoye is False and canal.envoyes == []


async def test_une_reponse_vide_ne_pollue_pas_lhistorique(attirail):
    """Sinon le contexte du tour suivant contiendrait des trous."""
    emetteur, _, base = attirail
    await emetteur.emettre(Reponse(cause_vide="panne"), depuis_dict({}))
    assert base.messages_bot_depuis(60) == 0
