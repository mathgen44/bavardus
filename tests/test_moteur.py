"""Le Moteur de bout en bout, sans Twitch ni modèle réel.

Ces tests décrivent le comportement observable du bot : ce qu'il publie, ce
qu'il tait, et ce qu'il garde en mémoire.
"""

import asyncio

import pytest

from bavardus.config import GestionnaireConfig, depuis_dict
from bavardus.modeles.base import Reponse
from bavardus.noyau.emetteur import Emetteur
from bavardus.noyau.evenements import EvenementAlerte, EvenementChat, EvenementMinuterie
from bavardus.noyau.generateur import Generateur
from bavardus.noyau.moteur import Moteur
from bavardus.stockage.base import Base


class ModeleFixe:
    nom = "faux"

    def __init__(self, texte="Réponse du bot"):
        self.texte = texte
        self.appels = 0

    async def produire(self, systeme, echanges, plafond, temperature):
        self.appels += 1
        return Reponse(texte=self.texte, latence_ms=10)

    async def disponible(self):
        return True, ""


class Canal:
    def __init__(self):
        self.envoyes = []

    async def envoyer(self, texte):
        self.envoyes.append(texte)


class ConfigStatique:
    def __init__(self, config):
        self._config = config

    @property
    def courante(self):
        return self._config


def monter(tmp_path, donnees=None, texte="Réponse du bot"):
    base = Base(tmp_path / "b.db")
    base.ouvrir()
    canal, modele = Canal(), ModeleFixe(texte)
    config = ConfigStatique(depuis_dict(donnees or {}))
    moteur = Moteur(config, base, Generateur(modele),
                    Emetteur(canal, base, "bavardus"), "bavardus", "42")
    return moteur, canal, base, modele


async def test_mention_produit_une_reponse(tmp_path):
    moteur, canal, base, modele = monter(tmp_path)
    resultat = await moteur.traiter(EvenementChat(auteur="kevin", texte="@bavardus salut"))

    assert resultat.envoye is True
    assert canal.envoyes == ["Réponse du bot"]
    assert modele.appels == 1
    base.fermer()


async def test_message_ordinaire_reste_silencieux_mais_memorise(tmp_path):
    """Le message entre dans l'historique même sans réponse : c'est le
    contexte des tours suivants et le calcul du silence."""
    moteur, canal, base, modele = monter(tmp_path)
    await moteur.traiter(EvenementChat(auteur="kevin", texte="ce boss est dur"))

    assert canal.envoyes == []
    assert modele.appels == 0                       # aucun appel inutile au modèle
    assert [m.texte for m in base.contexte(5)] == ["ce boss est dur"]
    base.fermer()


async def test_le_modele_nest_pas_appele_quand_le_bot_se_tait(tmp_path):
    """D17 : la décision précède la génération. Interroger le modèle pour
    jeter sa réponse gaspillerait du temps de calcul à chaque message."""
    moteur, _, base, modele = monter(tmp_path)
    for i in range(10):
        await moteur.traiter(EvenementChat(auteur=f"u{i}", texte="bavardage"))
    assert modele.appels == 0
    base.fermer()


async def test_la_reponse_du_bot_entre_dans_lhistorique(tmp_path):
    moteur, _, base, _ = monter(tmp_path)
    await moteur.traiter(EvenementChat(auteur="kevin", texte="@bavardus salut"))

    historique = base.contexte(5)
    assert [(m.auteur, m.du_bot) for m in historique] == [
        ("kevin", False), ("bavardus", True)]
    base.fermer()


async def test_le_bot_ne_se_repond_pas_a_lui_meme(tmp_path):
    moteur, canal, base, _ = monter(tmp_path)
    await moteur.traiter(EvenementChat(auteur="bavardus", texte="@bavardus coucou",
                                       auteur_id="42"))
    assert canal.envoyes == []
    base.fermer()


async def test_anti_flood_coupe_apres_le_quota(tmp_path):
    moteur, canal, base, _ = monter(tmp_path,
                                    {"prise_de_parole": {"max_messages_par_minute": 3}})
    for i in range(6):
        await moteur.traiter(EvenementChat(auteur=f"u{i}", texte="@bavardus ?"))
    assert len(canal.envoyes) == 3
    base.fermer()


async def test_alerte_declenche_une_reaction(tmp_path):
    moteur, canal, base, _ = monter(tmp_path, texte="Merci Kevin !")
    await moteur.traiter(EvenementAlerte("don", "kevin_", "5 €"))
    assert canal.envoyes == ["Merci Kevin !"]
    base.fermer()


async def test_minuterie_rejetee_ne_pollue_pas_le_journal(tmp_path):
    """Le cas courant, pas un incident : le journaliser noierait le journal
    des décisions sous le bruit."""
    moteur, _, base, _ = monter(tmp_path)
    for _ in range(5):
        await moteur.traiter(EvenementMinuterie())
    assert base.dernieres_decisions() == []
    base.fermer()


async def test_les_decisions_sont_journalisees_avec_leur_raison(tmp_path):
    moteur, _, base, _ = monter(tmp_path)
    await moteur.traiter(EvenementChat(auteur="k", texte="@bavardus ?"))
    await moteur.traiter(EvenementChat(auteur="k", texte="rien à voir"))

    raisons = [d["raison"] for d in base.dernieres_decisions()]
    assert "mention du bot" in raisons
    assert any("ne concerne pas" in r for r in raisons)
    base.fermer()


async def test_configuration_relue_a_chaque_evenement(tmp_path):
    """D21 : régler le persona depuis l'interface ne coupe pas le bot."""
    chemin = tmp_path / "config.yaml"
    chemin.write_text("prise_de_parole:\n  sur_mention: true\n", encoding="utf-8")
    gestionnaire = GestionnaireConfig(chemin)

    base = Base(tmp_path / "b.db")
    base.ouvrir()
    canal = Canal()
    moteur = Moteur(gestionnaire, base, Generateur(ModeleFixe()),
                    Emetteur(canal, base, "bavardus"), "bavardus", "42")

    await moteur.traiter(EvenementChat(auteur="k", texte="@bavardus ?"))
    assert len(canal.envoyes) == 1

    chemin.write_text("prise_de_parole:\n  sur_mention: false\n", encoding="utf-8")
    gestionnaire.recharger()
    await moteur.traiter(EvenementChat(auteur="k", texte="@bavardus ?"))
    assert len(canal.envoyes) == 1                  # inchangé, sans redémarrage
    base.fermer()


async def test_un_evenement_qui_echoue_nemporte_pas_le_bot(tmp_path):
    """Un live qui s'arrête parce qu'un message a mal tourné serait pire
    que le message manqué."""
    class ModeleExplosif(ModeleFixe):
        async def produire(self, *args):
            raise RuntimeError("panne inattendue")

    base = Base(tmp_path / "b.db")
    base.ouvrir()
    canal = Canal()
    moteur = Moteur(ConfigStatique(depuis_dict({})), base,
                    Generateur(ModeleExplosif()),
                    Emetteur(canal, base, "bavardus"), "bavardus", "42")

    file: asyncio.Queue = asyncio.Queue()
    arret = asyncio.Event()
    tache = asyncio.create_task(moteur.executer(file, arret))

    await file.put(EvenementChat(auteur="k", texte="@bavardus ?"))
    await file.put(EvenementChat(auteur="k", texte="@bavardus encore ?"))
    await asyncio.sleep(0.1)

    assert tache.done() is False                    # le moteur a survécu
    arret.set()
    await asyncio.wait_for(tache, timeout=2)
    base.fermer()
