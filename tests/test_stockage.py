"""Stockage : jetons et base SQLite."""

import json
import os
import stat
import time

import pytest

from bavardus.stockage.base import Base, Message
from bavardus.stockage.jetons import Jeton, Jetons, JetonsIndisponibles


# ------------------------------------------------------------------- jetons
def test_jeton_perime_avec_marge():
    """On rafraîchit AVANT l'échéance : sinon les requêtes déjà parties
    reviennent en 401."""
    assert Jeton("a", "r", time.time() + 60).perime is True
    assert Jeton("a", "r", time.time() + 3600).perime is False


def test_enregistrement_et_droits_600(tmp_path):
    """Le fichier donne le contrôle des comptes Twitch (G5)."""
    chemin = tmp_path / "jetons.json"
    jetons = Jetons(chemin)
    jetons.enregistrer("bot", {
        "access_token": "at", "refresh_token": "rt",
        "expires_in": 14000, "scope": ["user:bot"],
    }, login="bavardus", user_id="1537986664")

    assert stat.S_IMODE(os.stat(chemin).st_mode) == 0o600
    relu = Jetons(chemin).get("bot")
    assert relu.acces == "at" and relu.login == "bavardus"


def test_refresh_token_absent_conserve_le_precedent(tmp_path):
    """Twitch omet parfois refresh_token au rafraîchissement. L'écraser par
    une chaîne vide condamnerait l'installation au cycle suivant."""
    jetons = Jetons(tmp_path / "jetons.json")
    jetons.enregistrer("bot", {"access_token": "a1", "refresh_token": "rt",
                               "expires_in": 100})
    jetons.enregistrer("bot", {"access_token": "a2", "expires_in": 100})
    assert jetons.get("bot").rafraichissement == "rt"
    assert jetons.get("bot").acces == "a2"


def test_jeton_sans_refresh_refuse(tmp_path):
    jetons = Jetons(tmp_path / "jetons.json")
    with pytest.raises(JetonsIndisponibles, match="refresh_token"):
        jetons.enregistrer("bot", {"access_token": "a", "expires_in": 100})


def test_les_deux_usages_coexistent(tmp_path):
    """R16 : bot et propriétaire sont deux jeux distincts."""
    chemin = tmp_path / "jetons.json"
    jetons = Jetons(chemin)
    jetons.enregistrer("bot", {"access_token": "b", "refresh_token": "rb",
                               "expires_in": 100}, login="bavardus")
    jetons.enregistrer("proprietaire", {"access_token": "p", "refresh_token": "rp",
                                        "expires_in": 100}, login="mathgen")
    relus = Jetons(chemin)
    assert relus.get("bot").login == "bavardus"
    assert relus.get("proprietaire").login == "mathgen"


def test_etat_ne_fuit_aucun_secret(tmp_path):
    """`etat()` alimente l'interface web : aucun jeton ne doit y transiter."""
    jetons = Jetons(tmp_path / "jetons.json")
    jetons.enregistrer("bot", {"access_token": "SECRET", "refresh_token": "AUSSI",
                               "expires_in": 100}, login="bavardus")
    serialise = json.dumps(jetons.etat())
    assert "SECRET" not in serialise and "AUSSI" not in serialise


async def test_jeton_absent_message_actionnable(tmp_path):
    jetons = Jetons(tmp_path / "jetons.json")
    with pytest.raises(JetonsIndisponibles, match="compte du bot"):
        await jetons.valide("bot", "id", "secret")


# --------------------------------------------------------------------- base
@pytest.fixture
def base(tmp_path):
    b = Base(tmp_path / "bavardus.db")
    b.ouvrir()
    yield b
    b.fermer()


async def test_contexte_en_ordre_chronologique(base):
    """Un modèle attend les messages du plus ancien au plus récent."""
    for i in range(5):
        await base.ajouter_message(Message(time.time() + i, f"u{i}", f"m{i}"))
    contexte = base.contexte(3)
    assert [m.texte for m in contexte] == ["m2", "m3", "m4"]


async def test_contexte_nul_ne_renvoie_rien(base):
    await base.ajouter_message(Message(time.time(), "u", "m"))
    assert base.contexte(0) == []


async def test_silence_ignore_les_messages_du_bot(base):
    """Sans cela, le bot se répondrait à lui-même indéfiniment : chacune de
    ses relances repousserait le compteur de silence."""
    await base.ajouter_message(Message(time.time() - 600, "kevin", "salut"))
    await base.ajouter_message(Message(time.time(), "bavardus", "relance", du_bot=True))

    assert base.secondes_depuis_dernier_message(humains_seulement=True) > 500
    assert base.secondes_depuis_dernier_message(humains_seulement=False) < 5


def test_silence_sans_message_renvoie_none(base):
    assert base.secondes_depuis_dernier_message() is None


async def test_decision_sans_raison_refusee(base):
    """G17 : une décision sans raison est inexploitable."""
    with pytest.raises(ValueError, match="G17"):
        await base.journaliser_decision("chat", False, "")


async def test_journal_des_decisions(base):
    await base.journaliser_decision("chat", True, "mention du bot")
    await base.journaliser_decision("chat", False, "pas concerné")
    dernieres = base.dernieres_decisions()
    assert [d["raison"] for d in dernieres] == ["pas concerné", "mention du bot"]


async def test_statistiques_taux_de_vides(base):
    """R15 : si ce taux grimpe, la réflexion s'est rallumée quelque part."""
    await base.journaliser_appel("gemma4:e4b", 800, jetons=40)
    await base.journaliser_appel("gemma4:e4b", 900, jetons=60, vide=True,
                                 cause_vide="réflexion interne")
    stats = base.statistiques()
    assert stats["appels_modele"] == 2
    assert stats["reponses_vides"] == 1
    assert stats["taux_vides"] == 0.5


async def test_comptage_pour_les_garde_fous_de_debit(base):
    await base.ajouter_message(Message(time.time(), "bavardus", "a", du_bot=True))
    await base.ajouter_message(Message(time.time(), "bavardus", "b", du_bot=True))
    await base.ajouter_message(Message(time.time(), "kevin", "c"))
    await base.ajouter_message(Message(time.time() - 7200, "bavardus", "vieux", du_bot=True))

    assert base.messages_bot_depuis(60) == 2
    assert base.messages_bot_depuis(86400) == 3


async def test_purge(base):
    await base.ajouter_message(Message(time.time() - 40 * 86400, "vieux", "m"))
    await base.ajouter_message(Message(time.time(), "recent", "m"))
    await base.purger(jours=30)
    assert [m.auteur for m in base.contexte(10)] == ["recent"]
