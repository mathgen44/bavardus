"""Commandes à réponse fixe."""

import pytest

from bavardus.config import ConfigInvalide, depuis_dict
from bavardus.noyau.commandes import resoudre, substituer
from bavardus.noyau.decideur import ContexteDecision, decider
from bavardus.noyau.evenements import EvenementChat


def config_commandes(**kw):
    base = {"twitch": {"chaine": "mathgen"}, "commandes": [
        {"nom": "discord", "reponse": "Le Discord : https://discord.gg/xyz",
         "alias": ["dc"], "cooldown_secondes": 30},
        {"nom": "ban", "reponse": "Commande réservée", "pour": "moderateurs"},
        {"nom": "vip", "reponse": "Merci l'abonné !", "pour": "abonnes"},
        {"nom": "salut", "reponse": "Salut {auteur}, bienvenue sur {chaine} !",
         "cooldown_secondes": 0},
    ]}
    base.update(kw)
    return depuis_dict(base)


def appel(texte, config, **badges):
    evenement = EvenementChat(auteur="kevin", texte=texte, auteur_id="7",
                              badges=tuple(badges.get("badges", ())))
    decision = decider(evenement, config, ContexteDecision(nom_bot="bavardus"))
    return decision, evenement


# ------------------------------------------------------------ substitution
def test_substitution_des_marques_connues():
    assert substituer("Salut {auteur} sur {chaine} !", auteur="kevin",
                      chaine="mathgen", argument="") == "Salut kevin sur mathgen !"


def test_marque_inconnue_conservee():
    """Mieux vaut afficher « {truc} » et voir son erreur que publier une
    phrase amputée sans comprendre pourquoi."""
    assert substituer("Voici {truc}", auteur="a", chaine="b",
                      argument="c") == "Voici {truc}"


# --------------------------------------------------------------- résolution
def test_commande_connue_repond_sans_le_modele():
    """R11 appliqué à ce qui compte le plus : un modèle inventerait une URL
    de Discord plausible et fausse."""
    config = config_commandes()
    decision, evenement = appel("!discord", config)
    resolution = resoudre(decision, evenement, config)
    assert resolution.texte == "Le Discord : https://discord.gg/xyz"
    assert resolution.au_modele is False


def test_alias_reconnu():
    config = config_commandes()
    decision, evenement = appel("!dc", config)
    assert "discord.gg" in resoudre(decision, evenement, config).texte


def test_substitution_dans_la_reponse():
    config = config_commandes()
    decision, evenement = appel("!salut", config)
    resolution = resoudre(decision, evenement, config)
    assert resolution.texte == "Salut kevin, bienvenue sur mathgen !"


def test_commande_inconnue_ignoree_par_defaut():
    """Les chats sont pleins de commandes destinées à d'autres bots :
    y répondre ferait doublon."""
    config = config_commandes()
    decision, evenement = appel("!uptime", config)
    resolution = resoudre(decision, evenement, config)
    assert resolution.agit is False
    assert "inconnue" in resolution.refus


def test_commande_inconnue_au_modele_si_demande():
    config = config_commandes(commandes_inconnues_au_modele=True)
    decision, evenement = appel("!uptime", config)
    assert resoudre(decision, evenement, config).au_modele is True


# ------------------------------------------------------------- restrictions
def test_commande_moderateur_refusee_a_un_viewer():
    config = config_commandes()
    decision, evenement = appel("!ban", config)
    assert "modérateurs" in resoudre(decision, evenement, config).refus


def test_commande_moderateur_acceptee_pour_un_modo():
    config = config_commandes()
    decision, evenement = appel("!ban", config, badges=("moderator",))
    assert resoudre(decision, evenement, config).texte == "Commande réservée"


def test_le_diffuseur_compte_comme_moderateur():
    config = config_commandes()
    decision, evenement = appel("!ban", config, badges=("broadcaster",))
    assert resoudre(decision, evenement, config).texte == "Commande réservée"


def test_commande_abonne_refusee_puis_acceptee():
    config = config_commandes()
    decision, viewer = appel("!vip", config)
    assert "abonnés" in resoudre(decision, viewer, config).refus

    decision, abonne = appel("!vip", config, badges=("subscriber",))
    assert resoudre(decision, abonne, config).texte == "Merci l'abonné !"


def test_un_moderateur_accede_aux_commandes_abonnes():
    """Refuser une commande d'abonné à un modérateur n'aurait aucun sens."""
    config = config_commandes()
    decision, evenement = appel("!vip", config, badges=("moderator",))
    assert resoudre(decision, evenement, config).texte == "Merci l'abonné !"


# --------------------------------------------------------- délai d'attente
def test_delai_dattente_bloque_le_spam():
    config = config_commandes()
    decision, evenement = appel("!discord", config)
    resolution = resoudre(decision, evenement, config,
                          dernier_appel=1000.0, maintenant=1010.0)
    assert resolution.agit is False
    assert "20 s" in resolution.refus


def test_delai_ecoule_laisse_passer():
    config = config_commandes()
    decision, evenement = appel("!discord", config)
    resolution = resoudre(decision, evenement, config,
                          dernier_appel=1000.0, maintenant=1040.0)
    assert "discord.gg" in resolution.texte


def test_cooldown_nul_ne_bloque_jamais():
    config = config_commandes()
    decision, evenement = appel("!salut", config)
    resolution = resoudre(decision, evenement, config,
                          dernier_appel=1000.0, maintenant=1000.1)
    assert resolution.texte


# ------------------------------------------------------------ configuration
def test_commande_sans_reponse_refusee():
    """Elle ne produirait rien tout en paraissant configurée."""
    with pytest.raises(ConfigInvalide, match="sans réponse"):
        depuis_dict({"commandes": [{"nom": "vide", "reponse": "  "}]})


def test_nom_en_double_refuse():
    """La seconde ne se déclencherait jamais."""
    with pytest.raises(ConfigInvalide, match="deux fois"):
        depuis_dict({"commandes": [{"nom": "a", "reponse": "x"},
                                   {"nom": "a", "reponse": "y"}]})


def test_alias_en_conflit_refuse():
    with pytest.raises(ConfigInvalide, match="deux fois"):
        depuis_dict({"commandes": [{"nom": "discord", "reponse": "x"},
                                   {"nom": "dc", "reponse": "y",
                                    "alias": ["discord"]}]})


def test_le_point_dexclamation_est_absorbe():
    """Un utilisateur écrira « !discord » dans le formulaire par réflexe."""
    config = depuis_dict({"commandes": [{"nom": "!discord", "reponse": "x",
                                         "alias": ["!dc"]}]})
    assert config.commandes[0].nom == "discord"
    assert config.commandes[0].alias == ("dc",)


def test_aller_retour_config(tmp_path):
    from bavardus.config import charger, ecrire
    origine = config_commandes()
    ecrire(tmp_path / "c.yaml", origine)
    assert charger(tmp_path / "c.yaml") == origine


# ------------------------------------------------------- format du formulaire
def test_lecture_du_format_texte():
    from bavardus.web.formulaire import lire_commandes

    commandes = lire_commandes(
        "!discord | Le Discord : https://discord.gg/x | alias=dc/serveur, cooldown=30\n"
        "# un commentaire\n"
        "\n"
        "!ban | Réservé | pour=moderateurs\n"
        "simple | Sans options\n")

    assert len(commandes) == 3
    assert commandes[0].nom == "discord"
    assert commandes[0].reponse == "Le Discord : https://discord.gg/x"
    assert commandes[0].alias == ("dc", "serveur")
    assert commandes[0].cooldown_secondes == 30
    assert commandes[1].pour == "moderateurs"
    assert commandes[2].nom == "simple" and commandes[2].cooldown_secondes == 15


def test_aller_retour_du_format_texte():
    """Ce que l'interface affiche doit se relire à l'identique."""
    from bavardus.web.formulaire import ecrire_commandes, lire_commandes

    origine = config_commandes().commandes
    assert lire_commandes(ecrire_commandes(origine)) == origine


def test_une_reponse_contenant_un_tube_nest_pas_coupee_en_silence():
    """Le séparateur est le premier tube : le reste appartient à la réponse
    seulement si aucune option ne suit. Cas limite documenté."""
    from bavardus.web.formulaire import lire_commandes

    commandes = lire_commandes("!x | a | pour=tous")
    assert commandes[0].reponse == "a"
