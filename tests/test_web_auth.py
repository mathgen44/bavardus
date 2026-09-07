"""Interface web : authentification et verrouillage de l'installation.

Ces tests décrivent qui peut faire quoi. C'est le module où une erreur ne
produit pas un bug visible mais une interface ouverte sur Internet.
"""

import time

import httpx
import pytest
from fastapi.testclient import TestClient

from bavardus.config import GestionnaireConfig, depuis_dict, ecrire
from bavardus.stockage.jetons import Jetons
from bavardus.web import auth
from bavardus.web.app import Contexte, creer_application


@pytest.fixture
def montage(tmp_path, monkeypatch):
    ecrire(tmp_path / "config.yaml",
           depuis_dict({"base_url": "http://localhost:8475",
                        "twitch": {"chaine": "mathgen"}}))
    (tmp_path / ".env").write_text(
        "TWITCH_CLIENT_ID=cid\nTWITCH_CLIENT_SECRET=csecret\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    jetons = Jetons(tmp_path / "jetons.json")
    contexte = Contexte(racine=tmp_path,
                        gestionnaire_config=GestionnaireConfig(tmp_path / "config.yaml"),
                        jetons=jetons)
    application = creer_application(contexte)
    return TestClient(application, follow_redirects=False), contexte


def poser_proprietaire(contexte, login="mathgen", user_id="64157622"):
    contexte.jetons.enregistrer("proprietaire", {
        "access_token": "at", "refresh_token": "rt", "expires_in": 9999},
        login=login, user_id=user_id)


def cookie_de(contexte, login="mathgen", user_id="64157622"):
    signataire = auth.Signataire(auth.cle_session(contexte.racine))
    return signataire.creer_session(auth.Identite(login, user_id))


# ------------------------------------------------------------- amorçage D22
def test_sans_proprietaire_on_atterrit_sur_linstallation(montage):
    client, _ = montage
    assert client.get("/").headers["location"] == "/installation"


def test_lassistant_est_ouvert_tant_quil_ny_a_pas_de_proprietaire(montage):
    client, _ = montage
    reponse = client.get("/installation")
    assert reponse.status_code == 200
    # L'URL exacte à coller doit être affichée : Twitch la compare au
    # caractère près, et c'est là que se jouent la plupart des échecs.
    assert "http://localhost:8475/api/twitch/callback" in reponse.text


def test_lassistant_se_referme_definitivement(montage):
    """Le laisser ouvert offrirait à un visiteur de réécrire les
    identifiants Twitch de l'instance."""
    client, contexte = montage
    poser_proprietaire(contexte)
    assert client.get("/installation").headers["location"] == "/connexion"


def test_post_installation_refuse_apres_verrouillage(montage):
    client, contexte = montage
    poser_proprietaire(contexte)
    reponse = client.post("/installation", data={
        "client_id": "pirate", "client_secret": "pirate", "chaine": "pirate"})
    assert reponse.headers["location"] == "/connexion"
    assert (contexte.racine / ".env").read_text(encoding="utf-8").count("cid") == 1


def test_installation_ecrit_env_et_config(montage):
    client, contexte = montage
    client.post("/installation", data={
        "client_id": "nouveau_id", "client_secret": "nouveau_secret",
        "chaine": "MaChaine"})
    env = (contexte.racine / ".env").read_text(encoding="utf-8")
    assert "TWITCH_CLIENT_ID=nouveau_id" in env
    # Le login Twitch est insensible à la casse : on normalise pour que la
    # comparaison avec l'auteur d'un message ne dépende pas de la saisie.
    contexte.gestionnaire_config.recharger()
    assert contexte.config.twitch.chaine == "machaine"


# ------------------------------------------------------------ accès protégé
def test_le_tableau_de_bord_exige_une_session(montage):
    client, contexte = montage
    poser_proprietaire(contexte)
    assert client.get("/tableau-de-bord").headers["location"] == "/connexion"


def test_session_valide_donne_acces(montage):
    client, contexte = montage
    poser_proprietaire(contexte)
    client.cookies.set(auth.COOKIE, cookie_de(contexte))
    assert client.get("/tableau-de-bord").status_code == 200


def test_cookie_forge_refuse(montage):
    client, contexte = montage
    poser_proprietaire(contexte)
    client.cookies.set(auth.COOKIE, "je-suis-le-proprietaire")
    assert client.get("/tableau-de-bord").headers["location"] == "/connexion"


def test_session_dun_autre_compte_refusee(montage):
    """Un cookie signé émis avant un changement de propriétaire ne doit pas
    rester valable."""
    client, contexte = montage
    poser_proprietaire(contexte, "mathgen", "64157622")
    client.cookies.set(auth.COOKIE, cookie_de(contexte, "intrus", "999"))
    assert client.get("/tableau-de-bord").headers["location"] == "/connexion"


def test_deconnexion_efface_le_cookie(montage):
    client, contexte = montage
    poser_proprietaire(contexte)
    client.cookies.set(auth.COOKIE, cookie_de(contexte))
    reponse = client.get("/deconnexion")
    assert reponse.headers["location"] == "/connexion"
    assert 'bavardus_session=""' in reponse.headers.get("set-cookie", "")


# --------------------------------------------------------------- flux OAuth
def test_le_flux_bot_force_lecran_de_consentement(montage):
    """G12 : sans force_verify, Twitch réutilise la session du navigateur et
    l'on repart avec le jeton du diffuseur."""
    client, contexte = montage
    poser_proprietaire(contexte)
    cible = client.get("/api/twitch/connexion?usage=bot").headers["location"]
    assert "force_verify=true" in cible
    assert "user%3Awrite%3Achat" in cible


def test_le_flux_proprietaire_ne_demande_aucun_scope(montage):
    """On ne veut que son identité. Réclamer des droits inutiles produit un
    écran de consentement inquiétant pour rien."""
    client, _ = montage
    cible = client.get("/api/twitch/connexion?usage=proprietaire").headers["location"]
    assert "scope=&" in cible or cible.endswith("scope=") or "scope=&state" in cible


def test_etat_signe_rejette_une_valeur_forgee(montage):
    client, _ = montage
    reponse = client.get("/api/twitch/callback?code=abc&state=forge")
    assert "erreur" in reponse.headers["location"]


def test_etat_expire_est_rejete(tmp_path, montage):
    client, contexte = montage
    signataire = auth.Signataire(auth.cle_session(contexte.racine))
    etat = signataire.creer_etat("proprietaire")
    with pytest.raises(auth.ErreurAuth, match="expiré"):
        # max_age est vérifié à la lecture : on simule le temps écoulé.
        import itsdangerous
        original = itsdangerous.URLSafeTimedSerializer.loads
        try:
            itsdangerous.URLSafeTimedSerializer.loads = lambda self, s, **kw: (
                _ for _ in ()).throw(itsdangerous.SignatureExpired("vieux"))
            signataire.lire_etat(etat)
        finally:
            itsdangerous.URLSafeTimedSerializer.loads = original


def test_twitch_refuse_lautorisation(montage):
    client, _ = montage
    reponse = client.get("/api/twitch/callback?error=access_denied"
                         "&error_description=refus")
    assert "refus" in reponse.headers["location"]


# ------------------------------------------------- verrouillage propriétaire
def test_un_second_compte_ne_peut_pas_semparer_de_linstance(montage):
    _, contexte = montage
    poser_proprietaire(contexte, "mathgen", "64157622")
    with pytest.raises(auth.ErreurAuth, match="appartient déjà"):
        auth.verifier_proprietaire(contexte.jetons, auth.Identite("intrus", "999"))


def test_le_proprietaire_peut_se_reconnecter(montage):
    _, contexte = montage
    poser_proprietaire(contexte, "mathgen", "64157622")
    auth.verifier_proprietaire(contexte.jetons, auth.Identite("mathgen", "64157622"))


def test_la_cle_de_session_survit_au_redemarrage(tmp_path):
    """Sinon chaque redémarrage du bot déconnecterait le propriétaire."""
    assert auth.cle_session(tmp_path) == auth.cle_session(tmp_path)


def test_url_de_redirection_construite_sans_surprise(montage):
    _, contexte = montage
    assert contexte.config.url_redirection == \
        "http://localhost:8475/api/twitch/callback"
