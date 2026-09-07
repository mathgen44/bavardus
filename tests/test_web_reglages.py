"""Réglages et journal : la conversion du formulaire, et l'accès."""

import pytest

from bavardus.config import ConfigInvalide, GestionnaireConfig, depuis_dict, ecrire
from bavardus.stockage.base import Base
from bavardus.stockage.jetons import Jetons
from bavardus.web import auth
from bavardus.web.app import Contexte, creer_application
from bavardus.web.formulaire import appliquer_formulaire
from fastapi.testclient import TestClient


BASE = {"persona": "Tu es taquin.", "chaine": "mathgen",
        "fournisseur": "ollama", "url_modele": "http://x:11434",
        "nom_modele": "gemma4:e4b", "plafond_jetons": "60",
        "temperature": "0.7", "contexte_messages": "12", "longueur_max": "500",
        "minutes_de_silence": "5", "max_par_heure": "4",
        "max_messages_par_minute": "6", "action_moderation": "supprimer"}


def formulaire(**extra):
    donnees = dict(BASE)
    donnees.update(extra)
    return donnees


# ------------------------------------------------------------- conversion
def test_une_case_decochee_vaut_faux():
    """Le navigateur n'envoie pas les cases décochées : leur absence est le
    seul moyen de les distinguer."""
    config = appliquer_formulaire(depuis_dict({}), formulaire())
    assert config.prise_de_parole.sur_mention is False
    assert config.modele.reflexion is False


def test_une_case_cochee_vaut_vrai():
    config = appliquer_formulaire(depuis_dict({}),
                                  formulaire(sur_mention="on", sur_alerte="on"))
    assert config.prise_de_parole.sur_mention is True
    assert config.prise_de_parole.sur_alerte is True
    assert config.prise_de_parole.sur_commande is False


def test_liste_acceptee_en_lignes_ou_virgules():
    a = appliquer_formulaire(depuis_dict({}),
                             formulaire(comptes_ignores="nightbot\nStreamElements"))
    b = appliquer_formulaire(depuis_dict({}),
                             formulaire(comptes_ignores="nightbot, StreamElements"))
    assert a.prise_de_parole.comptes_ignores == b.prise_de_parole.comptes_ignores
    assert "streamelements" in a.prise_de_parole.comptes_ignores   # normalisé


def test_temperature_a_la_virgule_acceptee():
    """Un clavier français produit « 0,4 » sans y penser."""
    config = appliquer_formulaire(depuis_dict({}), formulaire(temperature="0,4"))
    assert config.modele.temperature == 0.4


def test_valeur_illisible_retombe_sur_lancienne():
    """Une saisie ratée ne doit pas remettre un réglage à zéro en silence."""
    origine = depuis_dict({"conversation": {"contexte_messages": 20}})
    config = appliquer_formulaire(origine, formulaire(contexte_messages="douze"))
    assert config.conversation.contexte_messages == 20


def test_la_chaine_est_normalisee_en_minuscules():
    config = appliquer_formulaire(depuis_dict({}), formulaire(chaine="  MathGen "))
    assert config.twitch.chaine == "mathgen"


def test_reflexion_avec_petit_plafond_refusee():
    """R15/D16 : la garde vaut aussi pour l'interface, pas seulement pour le
    fichier écrit à la main."""
    with pytest.raises(ConfigInvalide, match="RIEN"):
        appliquer_formulaire(depuis_dict({}), formulaire(reflexion="on"))


def test_longueur_au_dela_de_500_refusee():
    with pytest.raises(ConfigInvalide, match="500"):
        appliquer_formulaire(depuis_dict({}), formulaire(longueur_max="900"))


def test_ce_que_le_formulaire_ne_porte_pas_est_preserve():
    """Une page qui n'expose pas un champ ne doit pas l'effacer."""
    origine = depuis_dict({"base_url": "https://bavardus.mathgen.fr"})
    config = appliquer_formulaire(origine, formulaire())
    assert config.base_url == "https://bavardus.mathgen.fr"


# ------------------------------------------------------------------ accès
@pytest.fixture
def montage(tmp_path, monkeypatch):
    ecrire(tmp_path / "config.yaml",
           depuis_dict({"base_url": "http://localhost:8475"}))
    (tmp_path / ".env").write_text("TWITCH_CLIENT_ID=cid\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    jetons = Jetons(tmp_path / "jetons.json")
    jetons.enregistrer("proprietaire", {"access_token": "at", "refresh_token": "rt",
                                        "expires_in": 9999},
                       login="mathgen", user_id="64157622")
    base = Base(tmp_path / "b.db")
    base.ouvrir()
    contexte = Contexte(racine=tmp_path,
                        gestionnaire_config=GestionnaireConfig(tmp_path / "config.yaml"),
                        jetons=jetons, base=base)
    client = TestClient(creer_application(contexte), follow_redirects=False)
    signataire = auth.Signataire(auth.cle_session(tmp_path))
    client.cookies.set(auth.COOKIE,
                       signataire.creer_session(auth.Identite("mathgen", "64157622")))
    yield client, contexte
    base.fermer()


def test_reglages_exigent_une_session(montage):
    client, _ = montage
    client.cookies.clear()
    assert client.get("/reglages").headers["location"] == "/connexion"
    assert client.post("/reglages", data={}).headers["location"] == "/connexion"
    assert client.get("/journal").headers["location"] == "/connexion"
    assert client.get("/api/journal/flux").headers["location"] == "/connexion"


def test_enregistrement_applique_sans_redemarrage(montage):
    client, contexte = montage
    avant = contexte.gestionnaire_config.version
    reponse = client.post("/reglages", data=formulaire(
        persona="Nouveau persona", sur_mention="on"))
    assert reponse.headers["location"].startswith("/reglages?info")
    assert contexte.config.persona == "Nouveau persona"
    assert contexte.gestionnaire_config.version > avant


def test_reglage_refuse_ne_touche_pas_la_config_en_vigueur(montage):
    """Un réglage invalide ne doit pas faire taire un bot qui marchait."""
    client, contexte = montage
    client.post("/reglages", data=formulaire(persona="Bon persona", sur_mention="on"))
    version = contexte.gestionnaire_config.version

    reponse = client.post("/reglages", data=formulaire(reflexion="on"))
    assert "erreur" in reponse.headers["location"]
    assert contexte.config.persona == "Bon persona"
    assert contexte.config.modele.reflexion is False
    assert contexte.gestionnaire_config.version == version


def test_le_journal_saffiche(montage):
    client, contexte = montage
    import asyncio
    asyncio.run(contexte.base.journaliser_decision("chat", True, "mention du bot"))
    reponse = client.get("/journal")
    assert reponse.status_code == 200
    assert "mention du bot" in reponse.text
