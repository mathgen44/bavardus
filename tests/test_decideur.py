"""Le Décideur : logique pure, donc testable intégralement.

C'est le module où les tests ont le plus de valeur — il décide de tout ce que
le bot dit ou ne dit pas, sans qu'aucun réseau n'intervienne.
"""

import pytest

from bavardus.config import (ConfigPriseDeParole, ConfigSpontanee, depuis_dict)
from bavardus.noyau.decideur import ContexteDecision, decider
from bavardus.noyau.evenements import (EvenementAlerte, EvenementChat,
                                       EvenementMinuterie)


@pytest.fixture
def config():
    return depuis_dict({"prise_de_parole": {"comptes_ignores": ["nightbot"]}})


@pytest.fixture
def ctx():
    return ContexteDecision(nom_bot="bavardus", id_bot="1537986664")


# ------------------------------------------------------ ne pas s'auto-alimenter
def test_le_bot_ignore_ses_propres_messages_par_id(config, ctx):
    evenement = EvenementChat(auteur="Bavardus", texte="@bavardus coucou",
                              auteur_id="1537986664")
    decision = decider(evenement, config, ctx)
    assert decision.repondre is False
    assert "lui-même" in decision.raison


def test_le_bot_signore_aussi_par_nom_sans_id(config):
    """Avant la première authentification, l'id n'est pas connu."""
    evenement = EvenementChat(auteur="bavardus", texte="@bavardus salut")
    decision = decider(evenement, config, ContexteDecision(nom_bot="bavardus"))
    assert decision.repondre is False


def test_les_autres_bots_sont_ignores(config, ctx):
    """Deux bots qui se répondent poliment saturent un chat en secondes."""
    evenement = EvenementChat(auteur="Nightbot", texte="@bavardus salut")
    decision = decider(evenement, config, ctx)
    assert decision.repondre is False
    assert "compte ignoré" in decision.raison


# ----------------------------------------------------------------- anti-flood
def test_le_debit_maximum_lemporte_sur_une_mention(config):
    """Garde-fou dur : un bot qui déborde nuit plus qu'un bot qui rate une
    réponse."""
    ctx = ContexteDecision(nom_bot="bavardus", messages_bot_derniere_minute=6)
    decision = decider(EvenementChat(auteur="kevin", texte="@bavardus ?"),
                       config, ctx)
    assert decision.repondre is False
    assert "débit maximum" in decision.raison


def test_sous_le_debit_maximum_on_repond(config):
    ctx = ContexteDecision(nom_bot="bavardus", messages_bot_derniere_minute=5)
    decision = decider(EvenementChat(auteur="kevin", texte="@bavardus ?"),
                       config, ctx)
    assert decision.repondre is True


# -------------------------------------------------------------------- mentions
@pytest.mark.parametrize("texte", [
    "@bavardus tu en penses quoi ?",
    "bavardus, tu dors ?",
    "hé @Bavardus regarde ça",
    "bavardus: viens voir",
])
def test_formes_de_mention_reconnues(config, ctx, texte):
    assert decider(EvenementChat(auteur="kevin", texte=texte), config, ctx).repondre


@pytest.mark.parametrize("texte", [
    "je préfère bavardus à l'autre bot",
    "le bot de la chaîne s'appelle bavardus je crois",
    "salut tout le monde",
])
def test_le_bot_ne_singere_pas_quand_on_parle_de_lui(config, ctx, texte):
    """« je préfère bavardus à l'autre bot » parle du bot sans lui parler.
    Un bot qui s'invite dans ces conversations devient vite pénible."""
    decision = decider(EvenementChat(auteur="kevin", texte=texte), config, ctx)
    assert decision.repondre is False
    assert "ne concerne pas" in decision.raison


def test_mention_desactivee(ctx):
    config = depuis_dict({"prise_de_parole": {"sur_mention": False}})
    decision = decider(EvenementChat(auteur="k", texte="@bavardus ?"), config, ctx)
    assert decision.repondre is False
    assert "désactivée" in decision.raison


# ------------------------------------------------------------------- commandes
def test_commande_reconnue_et_decoupee(config, ctx):
    decision = decider(EvenementChat(auteur="k", texte="!discord viens donc"),
                       config, ctx)
    assert decision.repondre is True
    assert decision.commande == "discord"
    assert decision.arguments == "viens donc"


def test_commande_sans_argument(config, ctx):
    decision = decider(EvenementChat(auteur="k", texte="!uptime"), config, ctx)
    assert decision.commande == "uptime" and decision.arguments == ""


def test_commande_prioritaire_sur_la_mention(config, ctx):
    """Une commande est une intention explicite : elle prime."""
    decision = decider(EvenementChat(auteur="k", texte="!info @bavardus"),
                       config, ctx)
    assert decision.commande == "info"


@pytest.mark.parametrize("texte", ["!", "! espace", "!!!", "c'est génial !"])
def test_ce_qui_nest_pas_une_commande(config, ctx, texte):
    decision = decider(EvenementChat(auteur="k", texte=texte), config, ctx)
    assert decision.commande == ""


# --------------------------------------------------------------------- alertes
def test_alerte_declenche_une_reaction(config, ctx):
    decision = decider(EvenementAlerte("don", "kevin_", "5 €"), config, ctx)
    assert decision.repondre is True
    assert "don" in decision.raison


def test_alertes_desactivees(ctx):
    config = depuis_dict({"prise_de_parole": {"sur_alerte": False}})
    assert decider(EvenementAlerte("follow", "k"), config, ctx).repondre is False


# ------------------------------------------------------------------ spontanée
def config_spontanee(**kw):
    base = {"active": True, "minutes_de_silence": 5, "max_par_heure": 4}
    base.update(kw)
    return depuis_dict({"prise_de_parole": {"spontanee": base}})


def test_spontanee_desactivee_par_defaut(config, ctx):
    decision = decider(EvenementMinuterie(), config, ctx)
    assert decision.repondre is False
    assert "désactivée" in decision.raison


def test_spontanee_apres_silence_suffisant():
    ctx = ContexteDecision(nom_bot="bavardus", secondes_de_silence=400)
    decision = decider(EvenementMinuterie(), config_spontanee(), ctx)
    assert decision.repondre is True
    assert "relance" in decision.raison


def test_spontanee_silence_trop_court():
    ctx = ContexteDecision(nom_bot="bavardus", secondes_de_silence=120)
    decision = decider(EvenementMinuterie(), config_spontanee(), ctx)
    assert decision.repondre is False
    assert "trop court" in decision.raison


def test_spontanee_quota_horaire_respecte():
    ctx = ContexteDecision(nom_bot="bavardus", secondes_de_silence=999,
                           messages_spontanes_derniere_heure=4)
    decision = decider(EvenementMinuterie(), config_spontanee(), ctx)
    assert decision.repondre is False
    assert "quota" in decision.raison


def test_spontanee_sans_historique_ne_relance_rien():
    """Chat vide : il n'y a personne à relancer, et le bot parlerait seul."""
    ctx = ContexteDecision(nom_bot="bavardus", secondes_de_silence=None)
    decision = decider(EvenementMinuterie(), config_spontanee(), ctx)
    assert decision.repondre is False
    assert "rien à relancer" in decision.raison


# ---------------------------------------------------------------------- G17
def test_toute_decision_porte_une_raison(config, ctx):
    """G17 : sans raison, un bot muet ou bavard ne se diagnostique qu'en
    relisant le code."""
    evenements = [
        EvenementChat(auteur="k", texte="salut"),
        EvenementChat(auteur="k", texte="@bavardus ?"),
        EvenementChat(auteur="k", texte="!info"),
        EvenementAlerte("raid", "k", "42 viewers"),
        EvenementMinuterie(),
    ]
    for evenement in evenements:
        decision = decider(evenement, config, ctx)
        assert decision.raison, f"décision sans raison pour {evenement}"
        assert decision.genre == evenement.genre
