"""Point d'entrée de Bavardus, en ligne de commande.

C'est le jalon de vérité de la phase 3 : un bot qui lit et répond dans un
vrai chat, sans interface web. Tout ce qui viendra après est du confort.

    python3 -m bavardus                 # démarre le bot
    python3 -m bavardus --verifier      # contrôle l'installation et sort
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import signal
import sys
from pathlib import Path

from . import secrets as module_secrets
from .config import ConfigInvalide, GestionnaireConfig
from .modeles import construire as construire_modele
from .noyau.emetteur import Emetteur
from .noyau.generateur import Generateur
from .noyau.moteur import Moteur
from .sources import minuterie as source_minuterie
from .sources.streamlabs import SourceStreamlabs
from .sources.twitch import CanalTwitch, ClientTwitch, ErreurTwitch, SourceTwitch
from .stockage.base import Base
from .stockage.jetons import Jetons, JetonsIndisponibles
from .web.app import Contexte, creer_application

journal = logging.getLogger("bavardus")


def racine() -> Path:
    return Path(__file__).resolve().parent.parent


def configurer_journal(niveau: str) -> None:
    logging.basicConfig(
        level=getattr(logging, niveau, logging.INFO),
        format="%(asctime)s  %(levelname)-7s %(name)-16s %(message)s",
        datefmt="%H:%M:%S")


async def verifier(gestionnaire, secrets, jetons, modele) -> list[str]:
    """Contrôles de démarrage. Retourne la liste des problèmes.

    G11 : mieux vaut une ligne rouge maintenant qu'un bot silencieux
    découvert en plein live. Chaque message dit quoi faire, pas seulement
    ce qui ne va pas.
    """
    problemes: list[str] = []
    config = gestionnaire.courante

    if not config.twitch.chaine:
        problemes.append(
            "twitch.chaine est vide dans config.yaml : indiquer le login de "
            "la chaîne à écouter.")

    try:
        secrets.exiger_twitch()
    except module_secrets.SecretsIncomplets as erreur:
        problemes.append(str(erreur))

    for usage, remede in (("bot", "connecter le compte du bot"),):
        if jetons.get(usage) is None:
            problemes.append(
                f"aucun jeton « {usage} » dans jetons.json : {remede}. "
                f"En attendant l'interface web, utiliser "
                f"outils/diag_twitch.py --auth puis recopier les jetons.")

    joignable, message = await modele.disponible()
    (problemes.append if not joignable else journal.info)(message)

    # Absence non bloquante : sans Streamlabs le chat fonctionne, seules les
    # alertes manquent. Mieux vaut un bot partiel qu'un bot qui refuse de
    # démarrer — mais il faut le dire, la panne serait sinon silencieuse.
    if not secrets.streamlabs_jeton_socket:
        journal.warning(
            "STREAMLABS_SOCKET_TOKEN absent du .env : aucune réaction aux "
            "follows, dons, abonnements et raids (D15). Le chat fonctionne.")

    # D23/R18 : une base_url fausse ne se voit qu'au moment d'une connexion.
    journal.info("URL de redirection à déclarer sur Twitch : %s",
                 config.url_redirection)
    return problemes


async def servir_interface(contexte, config, arret) -> None:
    """Sert l'interface web dans la même boucle que le moteur (D19).

    Un seul processus : l'interface et le bot partagent les mêmes objets, sans
    API interne ni sérialisation. Le prix est R17 — redémarrer l'un coupe
    l'autre — accepté pour un outil qu'on ne redéploie pas en continu.
    """
    import uvicorn

    hote, port = "0.0.0.0", 8475
    reste = config.base_url.split("://", 1)[-1]
    if ":" in reste.split("/")[0]:
        with contextlib.suppress(ValueError):
            port = int(reste.split("/")[0].rsplit(":", 1)[1])

    serveur = uvicorn.Server(uvicorn.Config(
        creer_application(contexte), host=hote, port=port,
        log_level="warning", access_log=False))
    tache = asyncio.create_task(serveur.serve())
    journal.info("interface web sur http://%s:%s (publiée en %s)",
                 hote, port, config.base_url)
    try:
        await arret.wait()
    finally:
        serveur.should_exit = True
        with contextlib.suppress(asyncio.CancelledError):
            await tache


async def demarrer(arguments) -> int:
    base_projet = racine()
    try:
        gestionnaire = GestionnaireConfig(base_projet / "config.yaml")
    except ConfigInvalide as erreur:
        print(f"Configuration inutilisable : {erreur}", file=sys.stderr)
        return 2

    config = gestionnaire.courante
    configurer_journal(config.niveau_journal)

    secrets = module_secrets.charger(base_projet)
    for cle, origine in sorted(secrets.origines.items()):
        if origine == "environnement":
            # B4 : une variable exportée lors d'un essai précédent écrase
            # silencieusement le .env. On le dit plutôt que de le subir.
            journal.warning("%s vient de l'environnement, pas du .env", cle)

    jetons = Jetons(base_projet / "jetons.json")
    modele = construire_modele(config.modele, secrets.cle_modele)

    if arguments.web_seul:
        configurer_journal(config.niveau_journal)
        contexte = Contexte(racine=base_projet, gestionnaire_config=gestionnaire,
                            jetons=jetons)
        arret = asyncio.Event()
        boucle = asyncio.get_running_loop()
        for signal_arret in (signal.SIGINT, signal.SIGTERM):
            with contextlib.suppress(NotImplementedError):
                boucle.add_signal_handler(signal_arret, arret.set)
        journal.info("mode installation : le bot ne démarre pas. "
                     "Ouvrir %s pour configurer.", config.base_url)
        await servir_interface(contexte, config, arret)
        return 0

    problemes = await verifier(gestionnaire, secrets, jetons, modele)
    if problemes:
        for probleme in problemes:
            journal.error("%s", probleme)
        if arguments.verifier:
            return 1
        journal.error("démarrage impossible : corriger les points ci-dessus")
        return 1
    if arguments.verifier:
        journal.info("installation conforme")
        return 0

    base = Base(base_projet / "donnees" / "bavardus.db")
    base.ouvrir()

    client = ClientTwitch(jetons, secrets.twitch_client_id,
                          secrets.twitch_client_secret)
    try:
        diffuseur = await client.utilisateur(config.twitch.chaine)
        jeton_bot = jetons.get("bot")
        compte_bot = await client.utilisateur(jeton_bot.login) if jeton_bot.login \
            else None
    except (ErreurTwitch, JetonsIndisponibles) as erreur:
        journal.error("%s", erreur)
        base.fermer()
        return 1

    id_bot = compte_bot["id"] if compte_bot else jeton_bot.user_id
    nom_bot = compte_bot["login"] if compte_bot else jeton_bot.login

    # G12 : le piège le plus coûteux de la phase 1. Si le jeton est celui du
    # diffuseur, le bot parlerait sous le pseudo du streamer.
    if str(id_bot) == str(diffuseur["id"]):
        journal.error(
            "le jeton « bot » appartient au DIFFUSEUR (%s) : le bot parlerait "
            "sous ton propre pseudo. Refaire l'autorisation avec le compte du "
            "bot, dans une fenêtre de navigation privée (G12).", nom_bot)
        base.fermer()
        return 1

    journal.info("bot %s (%s) sur la chaîne %s (%s)",
                 nom_bot, id_bot, diffuseur["login"], diffuseur["id"])

    canal = CanalTwitch(client, diffuseur["id"], id_bot)
    moteur = Moteur(gestionnaire, base, Generateur(modele),
                    Emetteur(canal, base, nom_bot), nom_bot, str(id_bot))

    file: asyncio.Queue = asyncio.Queue()
    arret = asyncio.Event()

    boucle = asyncio.get_running_loop()
    for signal_arret in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            boucle.add_signal_handler(signal_arret, arret.set)

    contexte_web = Contexte(racine=base_projet, gestionnaire_config=gestionnaire,
                            jetons=jetons, base=base)

    source = SourceTwitch(client, file, diffuseur["id"], str(id_bot))
    streamlabs = SourceStreamlabs(secrets.streamlabs_jeton_socket, file, boucle)
    taches = [
        asyncio.create_task(servir_interface(contexte_web, config, arret), name="web"),
        asyncio.create_task(source.executer(arret), name="twitch"),
        asyncio.create_task(streamlabs.executer(arret), name="streamlabs"),
        asyncio.create_task(source_minuterie.executer(file, arret), name="minuterie"),
        asyncio.create_task(moteur.executer(file, arret), name="moteur"),
    ]
    journal.info("Bavardus est en ligne. Ctrl+C pour arrêter.")

    try:
        await arret.wait()
    finally:
        journal.info("arrêt en cours…")
        for tache in taches:
            tache.cancel()
        await asyncio.gather(*taches, return_exceptions=True)
        base.fermer()
        journal.info("arrêté proprement")
    return 0


def main() -> int:
    analyseur = argparse.ArgumentParser(prog="bavardus", description="Bot Twitch Bavardus")
    analyseur.add_argument("--verifier", action="store_true",
                           help="contrôler l'installation et sortir")
    analyseur.add_argument("--web-seul", action="store_true",
                           help="servir l'interface sans démarrer le bot — pour "
                                "faire la première installation")
    arguments = analyseur.parse_args()
    try:
        return asyncio.run(demarrer(arguments))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
