"""Source Twitch : interprétation du protocole, sans réseau."""

import json

import httpx
import pytest

from bavardus.secrets import charger, lire_env
from bavardus.sources.twitch import (ClientTwitch, ErreurTwitch, en_evenement_chat,
                                     interpreter)
from bavardus.stockage.jetons import Jetons


# ------------------------------------------------------------------ EventSub
def test_interpretation_dun_message():
    brut = json.dumps({"metadata": {"message_type": "session_welcome"},
                       "payload": {"session": {"id": "abc"}}})
    type_message, charge = interpreter(brut)
    assert type_message == "session_welcome"
    assert charge["session"]["id"] == "abc"


def test_notification_convertie_en_evenement():
    charge = {"event": {
        "chatter_user_name": "Kevin_", "chatter_user_id": "123",
        "message": {"text": "  @bavardus salut  "}}}
    evenement = en_evenement_chat(charge)
    assert evenement.auteur == "Kevin_"
    assert evenement.texte == "@bavardus salut"     # espaces retirés
    assert evenement.auteur_id == "123"


@pytest.mark.parametrize("charge", [
    {"event": {"chatter_user_name": "k", "message": {"text": "   "}}},
    {"event": {"chatter_user_name": "", "message": {"text": "salut"}}},
    {"event": {}},
    {},
])
def test_notifications_inexploitables_ignorees(charge):
    """Un message vide ou sans auteur ne doit pas entrer dans la file."""
    assert en_evenement_chat(charge) is None


# --------------------------------------------------------------------- Helix
@pytest.fixture
def client(tmp_path, monkeypatch):
    jetons = Jetons(tmp_path / "jetons.json")
    jetons.enregistrer("bot", {"access_token": "at", "refresh_token": "rt",
                               "expires_in": 9999}, login="bavardus")
    etat = {}

    class ClientSimule(httpx.AsyncClient):
        def __init__(self, *a, **kw):
            kw["transport"] = httpx.MockTransport(etat["gestionnaire"])
            super().__init__(*a, **kw)

    monkeypatch.setattr(httpx, "AsyncClient", ClientSimule)
    return ClientTwitch(jetons, "cid", "csecret"), etat


async def test_403_explique_le_remede(client):
    """L'erreur la plus probable en production, et la plus déroutante :
    l'envoi marche, la lecture non."""
    twitch, etat = client
    etat["gestionnaire"] = lambda r: httpx.Response(403, json={"message": "forbidden"})
    with pytest.raises(ErreurTwitch, match="/mod"):
        await twitch.appeler("/chat/messages", methode="POST")


async def test_401_distingue_revocation_et_expiration(client):
    twitch, etat = client
    etat["gestionnaire"] = lambda r: httpx.Response(401, json={})
    with pytest.raises(ErreurTwitch, match="révoqué"):
        await twitch.appeler("/users")


async def test_chaine_introuvable_pointe_la_configuration(client):
    twitch, etat = client
    etat["gestionnaire"] = lambda r: httpx.Response(200, json={"data": []})
    with pytest.raises(ErreurTwitch, match="config.yaml"):
        await twitch.utilisateur("inexistant")


async def test_envoi_de_message(client):
    twitch, etat = client
    vues = []

    def gestionnaire(requete):
        vues.append(json.loads(requete.content))
        return httpx.Response(200, json={"data": [{"is_sent": True}]})

    etat["gestionnaire"] = gestionnaire
    await twitch.envoyer_message("111", "222", "salut")
    assert vues[0] == {"broadcaster_id": "111", "sender_id": "222",
                       "message": "salut"}


# ------------------------------------------------------------------- secrets
def test_lecture_env(tmp_path):
    (tmp_path / ".env").write_text(
        '# commentaire\nTWITCH_CLIENT_ID="abc"\nVIDE=\nTWITCH_CLIENT_SECRET=xyz\n',
        encoding="utf-8")
    valeurs = lire_env(tmp_path / ".env")
    assert valeurs["TWITCH_CLIENT_ID"] == "abc"     # quotes retirées
    assert valeurs["TWITCH_CLIENT_SECRET"] == "xyz"


def test_environnement_lemporte_et_lorigine_est_tracee(tmp_path, monkeypatch):
    """B4 : une variable exportée lors d'un essai précédent écrase
    silencieusement le .env. Sans trace, on cherche une heure."""
    (tmp_path / ".env").write_text("TWITCH_CLIENT_ID=depuis_fichier\n", encoding="utf-8")
    monkeypatch.setenv("TWITCH_CLIENT_ID", "depuis_environnement")

    secrets = charger(tmp_path)
    assert secrets.twitch_client_id == "depuis_environnement"
    assert secrets.origines["TWITCH_CLIENT_ID"] == "environnement"


def test_secrets_manquants_disent_ou_les_mettre(tmp_path):
    from bavardus.secrets import SecretsIncomplets
    secrets = charger(tmp_path)
    with pytest.raises(SecretsIncomplets, match="dev.twitch.tv"):
        secrets.exiger_twitch()
