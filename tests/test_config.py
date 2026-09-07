"""Configuration : ce sont les validations qui comptent.

Chaque test ici correspond à une panne réelle qu'on refuse de revivre.
"""

import pytest
import yaml

from bavardus.config import (Config, ConfigInvalide, GestionnaireConfig,
                             charger, depuis_dict, ecrire)


def ecrire_yaml(chemin, donnees):
    chemin.write_text(yaml.safe_dump(donnees, allow_unicode=True), encoding="utf-8")
    return chemin


def test_config_vide_donne_les_defauts():
    """Une configuration partielle reste utilisable : ajouter une option ne
    doit pas invalider les fichiers existants."""
    config = depuis_dict({})
    assert config.modele.nom == "gemma4:e4b"        # D18
    assert config.modele.plafond_jetons == 60       # D5
    assert config.conversation.longueur_max == 500  # G4
    assert config.modele.reflexion is False         # D16


def test_url_redirection_unique_et_exacte():
    """D23 : la chaîne à coller sur Twitch, construite sans surprise."""
    config = depuis_dict({"base_url": "https://bavardus.mathgen.fr"})
    assert config.url_redirection == "https://bavardus.mathgen.fr/api/twitch/callback"


def test_base_url_avec_slash_final_refusee():
    """Twitch compare caractère par caractère : un « / » de trop et
    l'authentification échoue avec un message illisible."""
    with pytest.raises(ConfigInvalide, match="ne doit pas finir"):
        depuis_dict({"base_url": "https://exemple.fr/"})


def test_base_url_sans_schema_refusee():
    with pytest.raises(ConfigInvalide, match="http"):
        depuis_dict({"base_url": "exemple.fr"})


def test_reflexion_avec_petit_plafond_refusee():
    """R15/D16 : la panne la plus coûteuse de la phase 1. Elle ne doit plus
    jamais pouvoir être introduite par configuration."""
    with pytest.raises(ConfigInvalide, match="RIEN"):
        depuis_dict({"modele": {"reflexion": True, "plafond_jetons": 60}})


def test_reflexion_autorisee_avec_grand_plafond():
    config = depuis_dict({"modele": {"reflexion": True, "plafond_jetons": 1024}})
    assert config.modele.reflexion is True


def test_longueur_max_au_dessus_de_500_refusee():
    """G4 : Twitch refuse au-delà de 500 caractères."""
    with pytest.raises(ConfigInvalide, match="500"):
        depuis_dict({"conversation": {"longueur_max": 900}})


def test_debit_nul_refuse():
    """Mettre 0 ne désactive pas la limite : cela rend le bot muet en
    silence. On le refuse plutôt que de laisser croire à une panne."""
    with pytest.raises(ConfigInvalide, match="muet"):
        depuis_dict({"prise_de_parole": {"max_messages_par_minute": 0}})


def test_fournisseur_inconnu_refuse():
    with pytest.raises(ConfigInvalide, match="fournisseur"):
        depuis_dict({"modele": {"fournisseur": "gemini"}})


def test_aller_retour_ecriture_lecture(tmp_path):
    """Ce que l'interface écrit doit être relisible à l'identique."""
    origine = depuis_dict({
        "base_url": "http://localhost:9000",
        "persona": "Tu es taquin.",
        "modele": {"nom": "qwen3.5:9b", "temperature": 0.4},
        "moderation": {"active": True, "mots_interdits": ["truc"], "action": "avertir"},
    })
    chemin = tmp_path / "config.yaml"
    ecrire(chemin, origine)
    assert charger(chemin) == origine


def test_fichier_absent_message_utile(tmp_path):
    with pytest.raises(ConfigInvalide, match="config.exemple.yaml"):
        charger(tmp_path / "config.yaml")


def test_yaml_invalide_message_utile(tmp_path):
    chemin = tmp_path / "config.yaml"
    chemin.write_text("modele: [non fermé\n", encoding="utf-8")
    with pytest.raises(ConfigInvalide, match="YAML"):
        charger(chemin)


def test_rechargement_a_chaud(tmp_path):
    chemin = ecrire_yaml(tmp_path / "config.yaml", {"persona": "Version 1"})
    gestionnaire = GestionnaireConfig(chemin)
    assert gestionnaire.courante.persona == "Version 1"
    assert gestionnaire.version == 1

    ecrire_yaml(chemin, {"persona": "Version 2"})
    gestionnaire.recharger()
    assert gestionnaire.courante.persona == "Version 2"
    assert gestionnaire.version == 2


def test_rechargement_sans_changement_ne_bouge_pas_la_version(tmp_path):
    chemin = ecrire_yaml(tmp_path / "config.yaml", {"persona": "Stable"})
    gestionnaire = GestionnaireConfig(chemin)
    gestionnaire.recharger()
    assert gestionnaire.version == 1


def test_rechargement_invalide_conserve_lancienne(tmp_path):
    """Le point crucial : une faute de frappe dans l'interface ne doit
    jamais faire taire un bot qui fonctionnait."""
    chemin = ecrire_yaml(tmp_path / "config.yaml", {"persona": "Qui marche"})
    gestionnaire = GestionnaireConfig(chemin)

    ecrire_yaml(chemin, {"base_url": "pas-une-url"})
    with pytest.raises(ConfigInvalide):
        gestionnaire.recharger()

    assert gestionnaire.courante.persona == "Qui marche"
    assert gestionnaire.version == 1


def test_appliquer_refuse_avant_decrire(tmp_path):
    """Un réglage invalide ne doit pas laisser un fichier corrompu."""
    chemin = ecrire_yaml(tmp_path / "config.yaml", {"persona": "Intact"})
    gestionnaire = GestionnaireConfig(chemin)
    avant = chemin.read_text(encoding="utf-8")

    from bavardus.config import ConfigConversation
    with pytest.raises(ConfigInvalide):
        gestionnaire.appliquer(conversation=ConfigConversation(longueur_max=9000))

    assert chemin.read_text(encoding="utf-8") == avant
    assert gestionnaire.courante.conversation.longueur_max == 500


def test_config_est_immuable():
    """Le noyau lit la config à chaque événement : elle ne doit pas pouvoir
    changer sous ses pieds au milieu d'un traitement."""
    config = Config()
    with pytest.raises(Exception):
        config.base_url = "http://autre"
