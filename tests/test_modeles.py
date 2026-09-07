"""Modèles : le diagnostic des réponses vides est ce qui compte (G14).

Aucun test ne joint un vrai serveur : on simule les réponses HTTP. Ces tests
doivent tourner sur une machine sans Ollama ni clé d'API.
"""

import httpx
import pytest

from bavardus.config import ConfigModele
from bavardus.modeles import construire
from bavardus.modeles.base import Echange, ErreurModele, diagnostiquer_vide
from bavardus.modeles.compatible_openai import ModeleCompatibleOpenAI
from bavardus.modeles.ollama import ModeleOllama


def transport(gestionnaire):
    return httpx.MockTransport(gestionnaire)


@pytest.fixture(autouse=True)
def client_simule(monkeypatch):
    """Remplace httpx.AsyncClient par un client à transport contrôlé."""
    etat = {}

    class ClientSimule(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport(etat["gestionnaire"])
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", ClientSimule)
    return etat


# ------------------------------------------------------------------- Ollama
def test_ollama_absorbe_une_url_en_v1():
    """Beaucoup colleront l'URL compatible OpenAI d'un tutoriel. C'est
    justement l'erreur que D16 rend fatale : autant l'absorber (B3)."""
    assert ModeleOllama("http://hote:11434/v1", "m").racine == "http://hote:11434"
    assert ModeleOllama("http://hote:11434/", "m").racine == "http://hote:11434"


async def test_ollama_envoie_think_false(client_simule):
    """D16 : le drapeau doit partir, c'est toute la raison d'être de ce
    connecteur."""
    vues = []

    def gestionnaire(requete):
        import json
        vues.append(json.loads(requete.content))
        return httpx.Response(200, json={"message": {"content": "salut"},
                                         "eval_count": 12})

    client_simule["gestionnaire"] = gestionnaire
    modele = ModeleOllama("http://hote:11434", "gemma4:e4b", reflexion=False)
    reponse = await modele.produire("persona", [Echange("user", "coucou")], 60, 0.7)

    assert vues[0]["think"] is False
    assert vues[0]["options"]["num_predict"] == 60
    assert reponse.texte == "salut" and not reponse.vide


async def test_ollama_reponse_vide_par_reflexion_est_expliquee(client_simule):
    """La panne exacte de la phase 1. Le message doit nommer la cause ET le
    remède, pour quelqu'un qui ne lit pas le code."""
    def gestionnaire(requete):
        return httpx.Response(200, json={
            "message": {"content": "", "thinking": "Thinking Process: " + "x" * 200},
            "done_reason": "length", "eval_count": 60,
        })

    client_simule["gestionnaire"] = gestionnaire
    modele = ModeleOllama("http://hote:11434", "qwen3.5:9b")
    reponse = await modele.produire("", [Echange("user", "?")], 60, 0.7)

    assert reponse.vide
    assert reponse.reflexion_detectee
    assert "réflexion interne" in reponse.cause_vide
    assert "modele.reflexion: false" in reponse.cause_vide


async def test_ollama_injoignable_leve_une_erreur_lisible(client_simule):
    def gestionnaire(requete):
        raise httpx.ConnectError("connexion refusée")

    client_simule["gestionnaire"] = gestionnaire
    modele = ModeleOllama("http://absent:11434", "m")
    with pytest.raises(ErreurModele, match="injoignable"):
        await modele.produire("", [Echange("user", "?")], 60, 0.7)


async def test_ollama_modele_absent_dit_comment_le_tirer(client_simule):
    def gestionnaire(requete):
        return httpx.Response(200, json={"models": [{"name": "mistral:latest"}]})

    client_simule["gestionnaire"] = gestionnaire
    joignable, message = await ModeleOllama("http://hote:11434", "gemma4:e4b").disponible()
    assert joignable is False
    assert "ollama pull gemma4:e4b" in message


# -------------------------------------------------------- compatible OpenAI
async def test_compatible_openai_coupe_la_reflexion(client_simule):
    vues = []

    def gestionnaire(requete):
        import json
        vues.append(json.loads(requete.content))
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {"completion_tokens": 5},
        })

    client_simule["gestionnaire"] = gestionnaire
    modele = ModeleCompatibleOpenAI("https://passerelle/v1", "m", cle_api="k")
    reponse = await modele.produire("p", [Echange("user", "x")], 60, 0.7)

    assert vues[0]["reasoning_effort"] == "none"
    assert vues[0]["reasoning"] == {"enabled": False}
    assert reponse.texte == "ok" and reponse.jetons == 5


async def test_compatible_openai_cle_refusee(client_simule):
    def gestionnaire(requete):
        return httpx.Response(401, json={"error": "unauthorized"})

    client_simule["gestionnaire"] = gestionnaire
    joignable, message = await ModeleCompatibleOpenAI("https://p", "m").disponible()
    assert joignable is False and "401" in message


# ------------------------------------------------------------- diagnostic
def test_diagnostic_distingue_reflexion_et_echec():
    """G14 : distinguer un modèle qui réfléchit d'un modèle qui échoue est
    tout l'intérêt de journaliser la cause."""
    avec = diagnostiquer_vide(raison_arret="length", reflexion="x" * 50,
                              jetons_sortis=60, plafond=60)
    sans = diagnostiquer_vide(raison_arret="content_filter", reflexion="",
                              jetons_sortis=0, plafond=60)
    inconnu = diagnostiquer_vide(raison_arret="", reflexion="",
                                 jetons_sortis=None, plafond=60)

    assert "R15/D16" in avec
    assert "content_filter" in sans and "R15" not in sans
    assert "sans cause identifiée" in inconnu


# ---------------------------------------------------------------- fabrique
def test_fabrique_selon_la_configuration():
    """D13 : changer de fournisseur ne doit toucher qu'une ligne de config."""
    assert isinstance(construire(ConfigModele(fournisseur="ollama")), ModeleOllama)
    assert isinstance(
        construire(ConfigModele(fournisseur="compatible_openai"), cle_api="k"),
        ModeleCompatibleOpenAI)


def test_fabrique_refuse_un_fournisseur_inconnu():
    with pytest.raises(ValueError, match="inconnu"):
        construire(ConfigModele(fournisseur="inexistant"))
