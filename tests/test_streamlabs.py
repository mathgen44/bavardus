"""Streamlabs : la conversion des alertes, sans réseau.

D15 fait de Streamlabs la source unique des alertes : ce module porte à lui
seul un quart du périmètre v1.
"""

import asyncio

import pytest

from bavardus.sources.streamlabs import SourceStreamlabs, en_evenement_alerte


@pytest.mark.parametrize("type_sl,message,attendu", [
    ("donation", {"name": "kevin_", "formatted_amount": "5,00 €",
                  "message": "continue comme ça"},
     ("don", "kevin_", "5,00 €", "continue comme ça")),
    ("follow", {"name": "Nouvelle"}, ("follow", "Nouvelle", "", "")),
    ("subscription", {"name": "kevin_", "months": 3, "message": "3 mois !"},
     ("abonnement", "kevin_", "3 mois", "3 mois !")),
    ("resub", {"name": "vieux", "months": 12}, ("abonnement", "vieux", "12 mois", "")),
    ("raid", {"name": "AutreStreamer", "raiders": 42},
     ("raid", "AutreStreamer", "42 spectateurs", "")),
    ("bits", {"name": "kevin_", "amount": 100}, ("bits", "kevin_", "100 bits", "")),
])
def test_conversion_des_types(type_sl, message, attendu):
    evenement = en_evenement_alerte(type_sl, message)
    assert (evenement.type_alerte, evenement.auteur,
            evenement.montant, evenement.message) == attendu


@pytest.mark.parametrize("type_sl,message", [
    ("alertPlaying", {"name": "x"}),        # bruit de l'interface Streamlabs
    ("streamlabels", {"name": "x"}),
    ("donation", {"name": "   "}),          # sans auteur, rien à dire
    ("donation", {}),
])
def test_ce_qui_est_ignore(type_sl, message):
    assert en_evenement_alerte(type_sl, message) is None


def test_montant_de_don_selon_les_variantes():
    """Streamlabs n'est pas constant sur le nom du champ."""
    assert en_evenement_alerte("donation", {"name": "k", "amount": 5}).montant == "5"
    assert en_evenement_alerte(
        "donation", {"name": "k", "formattedAmount": "5 €"}).montant == "5 €"


async def test_les_evenements_arrivent_dans_la_file():
    file: asyncio.Queue = asyncio.Queue()
    source = SourceStreamlabs("jeton", file, asyncio.get_running_loop())

    source._sur_evenement({"type": "donation", "message": [
        {"_id": "a1", "name": "kevin_", "formatted_amount": "5 €"}]})
    await asyncio.sleep(0)

    evenement = file.get_nowait()
    assert evenement.type_alerte == "don" and evenement.auteur == "kevin_"


async def test_un_meme_evenement_nest_traite_quune_fois():
    """Streamlabs réémet parfois : sans mémoire des identifiants, le bot
    remercierait deux fois le même don."""
    file: asyncio.Queue = asyncio.Queue()
    source = SourceStreamlabs("jeton", file, asyncio.get_running_loop())
    charge = {"type": "donation",
              "message": [{"_id": "meme-id", "name": "kevin_", "amount": 5}]}

    source._sur_evenement(charge)
    source._sur_evenement(charge)
    await asyncio.sleep(0)

    assert file.qsize() == 1


async def test_plusieurs_alertes_dans_un_seul_message():
    file: asyncio.Queue = asyncio.Queue()
    source = SourceStreamlabs("jeton", file, asyncio.get_running_loop())
    source._sur_evenement({"type": "follow", "message": [
        {"_id": "1", "name": "a"}, {"_id": "2", "name": "b"}]})
    await asyncio.sleep(0)
    assert file.qsize() == 2


async def test_une_charge_malformee_ne_leve_pas():
    file: asyncio.Queue = asyncio.Queue()
    source = SourceStreamlabs("jeton", file, asyncio.get_running_loop())
    source._sur_evenement({"type": "donation", "message": ["pas un dict", None]})
    source._sur_evenement({})
    assert file.qsize() == 0


async def test_sans_jeton_la_source_sarrete_proprement():
    """Le chat doit fonctionner même sans Streamlabs configuré."""
    file: asyncio.Queue = asyncio.Queue()
    source = SourceStreamlabs("", file, asyncio.get_running_loop())
    await asyncio.wait_for(source.executer(asyncio.Event()), timeout=2)
    assert file.qsize() == 0
