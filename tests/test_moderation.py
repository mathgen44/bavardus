"""Modération : détection, exemptions, application.

Une fonction capable d'exclure un spectateur mérite d'être couverte
exhaustivement. Les faux positifs comptent autant que les faux négatifs.
"""

import pytest

from bavardus.config import ConfigInvalide, depuis_dict
from bavardus.noyau.evenements import EvenementChat
from bavardus.noyau.moderation import Sanction, examiner, mot_interdit, normaliser
from bavardus.noyau.sanctionneur import Sanctionneur


def config_moderation(**kw):
    base = {"active": True, "mots_interdits": ["idiot", "grosse bêtise"],
            "action": "supprimer"}
    base.update(kw)
    return depuis_dict({"moderation": base,
                        "prise_de_parole": {"comptes_ignores": ["nightbot"]}})


# ------------------------------------------------------------- détection
def test_normalisation_casse_et_accents():
    assert normaliser("Élève ÇA") == "eleve ca"


@pytest.mark.parametrize("texte", [
    "tu es un idiot", "IDIOT !", "Idiot.", "espèce d'idiot", "idiot",
])
def test_mots_interdits_detectes(texte):
    assert mot_interdit(texte, ["idiot"]) == "idiot"


@pytest.mark.parametrize("texte", [
    "idiotie",            # mot plus long
    "les idiots",         # pluriel : c'est un autre mot
    "unidiot",
    "",
])
def test_pas_de_correspondance_partielle(texte):
    """Un mot interdit ne doit pas déclencher sur un mot qui le contient :
    interdire « con » ne doit pas sanctionner « concert »."""
    assert mot_interdit(texte, ["idiot"]) == ""


def test_locution_cherchee_entiere():
    """Interdire une locution ne doit pas interdire chacun de ses mots."""
    assert mot_interdit("quelle grosse bêtise", ["grosse bêtise"]) == "grosse bêtise"
    assert mot_interdit("une grosse voiture", ["grosse bêtise"]) == ""


def test_liste_vide_ne_detecte_rien():
    assert mot_interdit("n'importe quoi", []) == ""


# ------------------------------------------------------------- exemptions
def test_moderation_desactivee(ctx=None):
    config = depuis_dict({"moderation": {"active": False,
                                         "mots_interdits": ["idiot"]}})
    assert examiner(EvenementChat(auteur="k", texte="idiot"), config) is None


def test_le_diffuseur_nest_jamais_modere():
    """Un bot qui exclut le streamer de son propre chat est une catastrophe
    que personne ne pardonne."""
    evenement = EvenementChat(auteur="mathgen", texte="idiot", auteur_id="64157622")
    assert examiner(evenement, config_moderation(),
                    id_diffuseur="64157622") is None


def test_le_bot_ne_se_modere_pas():
    evenement = EvenementChat(auteur="bavardus", texte="idiot", auteur_id="1537986664")
    assert examiner(evenement, config_moderation(), id_bot="1537986664") is None


def test_les_comptes_ignores_ne_sont_pas_moderes():
    evenement = EvenementChat(auteur="Nightbot", texte="idiot", auteur_id="9")
    assert examiner(evenement, config_moderation()) is None


def test_un_spectateur_ordinaire_est_sanctionne():
    evenement = EvenementChat(auteur="troll", texte="tu es un idiot", auteur_id="7")
    sanction = examiner(evenement, config_moderation(action="exclure"),
                        id_diffuseur="64157622", id_bot="1537986664")
    assert sanction.action == "exclure"
    assert "idiot" in sanction.motif


# ----------------------------------------------------------- configuration
def test_moderation_active_sans_mots_refusee():
    """Cocher la case sans rien lister ne protège de rien : le dire plutôt
    que de laisser croire le contraire."""
    with pytest.raises(ConfigInvalide, match="sans aucun mot"):
        depuis_dict({"moderation": {"active": True, "mots_interdits": []}})


def test_duree_dexclusion_bornee():
    with pytest.raises(ConfigInvalide, match="14 jours"):
        depuis_dict({"moderation": {"active": True, "mots_interdits": ["x"],
                                    "duree_exclusion_secondes": 9999999}})


# ------------------------------------------------------------ application
class CanalEspion:
    def __init__(self, casse=False):
        self.supprimes, self.exclusions, self.annonces = [], [], []
        self.casse = casse

    async def supprimer(self, message_id):
        if self.casse:
            raise RuntimeError("HTTP 403 : le bot n'est pas modérateur")
        self.supprimes.append(message_id)

    async def exclure(self, utilisateur_id, duree, motif):
        self.exclusions.append((utilisateur_id, duree, motif))

    async def annoncer(self, texte):
        self.annonces.append(texte)


async def test_suppression_simple():
    canal = CanalEspion()
    evenement = EvenementChat(auteur="troll", texte="idiot", auteur_id="7",
                              message_id="m1")
    resultat = await Sanctionneur(canal).appliquer(
        Sanction("supprimer", "mot interdit"), evenement, config_moderation())
    assert resultat.appliquee and canal.supprimes == ["m1"]
    assert canal.exclusions == [] and canal.annonces == []


async def test_exclusion_supprime_aussi_le_message():
    """La suppression a lieu dans tous les cas : c'est la seule action qui
    retire réellement le message du chat."""
    canal = CanalEspion()
    evenement = EvenementChat(auteur="troll", texte="idiot", auteur_id="7",
                              message_id="m1")
    config = config_moderation(action="exclure", duree_exclusion_secondes=600)
    await Sanctionneur(canal).appliquer(
        Sanction("exclure", "mot interdit"), evenement, config)
    assert canal.supprimes == ["m1"]
    assert canal.exclusions[0][0] == "7" and canal.exclusions[0][1] == 600


async def test_avertissement_public():
    canal = CanalEspion()
    evenement = EvenementChat(auteur="troll", texte="idiot", auteur_id="7",
                              message_id="m1")
    await Sanctionneur(canal).appliquer(
        Sanction("avertir", "mot interdit"), evenement,
        config_moderation(action="avertir"))
    assert "@troll" in canal.annonces[0]


async def test_message_sans_identifiant_nest_pas_supprimable():
    canal = CanalEspion()
    evenement = EvenementChat(auteur="troll", texte="idiot", auteur_id="7")
    resultat = await Sanctionneur(canal).appliquer(
        Sanction("supprimer", "mot interdit"), evenement, config_moderation())
    assert resultat.appliquee and "identifiant absent" in resultat.detail


async def test_un_refus_de_twitch_ninterrompt_pas_le_bot():
    """Scope manquant ou bot non modérateur : journalisé, pas fatal."""
    canal = CanalEspion(casse=True)
    evenement = EvenementChat(auteur="troll", texte="idiot", auteur_id="7",
                              message_id="m1")
    resultat = await Sanctionneur(canal).appliquer(
        Sanction("supprimer", "mot interdit"), evenement, config_moderation())
    assert resultat.appliquee is False and "403" in resultat.detail


@pytest.mark.parametrize("texte", [
    "espèce d'idiot", "l'idiot", "quel idiot", "c'est l’idiot du village",
])
def test_lelision_ne_masque_pas_le_mot(texte):
    """L'apostrophe française marque une élision : « d'idiot » contient bien
    le mot « idiot », et la traiter comme une lettre le rendrait
    indétectable."""
    assert mot_interdit(texte, ["idiot"]) == "idiot"


def test_le_trait_dunion_unit_encore():
    """« porte-parole » reste un mot : le couper produirait des faux
    positifs sur « parole »."""
    assert mot_interdit("le porte-parole", ["parole"]) == ""
    assert mot_interdit("le porte-parole", ["porte-parole"]) == "porte-parole"
