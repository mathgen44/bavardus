#!/usr/bin/env python3
"""
Bavardus — étape 1.6 : validation du connecteur Streamlabs.

Objectif : prouver qu'on sait recevoir les événements Streamlabs en Python
AVANT d'écrire quoi que ce soit d'autre. C'est le risque R1 du projet.

Deux modes :
  - par défaut : python-socketio 4.x (voie normale)
  - --raw      : WebSocket brut en Engine.IO v3 (plan B si le mode normal échoue)

Le jeton se récupère sur https://streamlabs.com/dashboard
  -> Paramètres du compte -> API Settings -> API Tokens -> "Your Socket API Token"

Utilisation :
    pip install -r requirements-test.txt
    export STREAMLABS_SOCKET_TOKEN="..."      # ou --token, ou un fichier .env
    python test_streamlabs.py
    python test_streamlabs.py --raw

Ensuite, dans Streamlabs : Alert Box -> boutons de test (follow, don, sub, raid).
Chaque clic doit faire apparaître une ligne ici.

ATTENTION : le jeton socket donne accès aux événements de ta chaîne.
Ne le colle jamais dans un fichier suivi par git.
"""

import argparse
import json
import os
import sys
import threading
import time
from datetime import datetime

SOCKET_URL = "https://sockets.streamlabs.com"
RAW_URL = "wss://sockets.streamlabs.com/socket.io/?EIO=3&transport=websocket&token={token}"

# Types d'événements attendus, avec le champ qui porte l'essentiel du message.
INTERESSANTS = {
    "donation": "don",
    "follow": "follow",
    "subscription": "abonnement",
    "resub": "réabonnement",
    "bits": "bits",
    "raid": "raid",
    "host": "host",
}


# ---------------------------------------------------------------- emplacements
# B12 : depuis que les outils vivent dans outils/, le répertoire courant n'est
# plus forcément celui du .env. On cherche, dans l'ordre : le répertoire
# courant (usage historique), le dossier de l'outil, puis la racine du dépôt.
# Les secrets restent ainsi dans UN seul fichier, jamais dupliqué.
def racine_config():
    ici = os.path.dirname(os.path.abspath(__file__))
    for dossier in (os.getcwd(), ici, os.path.dirname(ici)):
        if os.path.exists(os.path.join(dossier, ".env")):
            return dossier
    return os.path.dirname(ici)


CONFIG_DIR = racine_config()
CHEMIN_ENV = os.path.join(CONFIG_DIR, ".env")

def log(tag, message):
    print(f"[{datetime.now():%H:%M:%S}] {tag:<10} {message}", flush=True)


def charger_jeton(argument):
    """Priorité : argument de ligne de commande, puis variable d'environnement, puis .env."""
    if argument:
        return argument.strip()

    depuis_env = os.environ.get("STREAMLABS_SOCKET_TOKEN")
    if depuis_env:
        return depuis_env.strip()

    if os.path.exists(CHEMIN_ENV):
        with open(CHEMIN_ENV, encoding="utf-8") as fichier:
            for ligne in fichier:
                if ligne.strip().startswith("STREAMLABS_SOCKET_TOKEN="):
                    return ligne.split("=", 1)[1].strip().strip("\"'")

    print(
        "Aucun jeton trouvé.\n"
        "  --token <jeton>, ou STREAMLABS_SOCKET_TOKEN dans l'environnement,\n"
        "  ou une ligne STREAMLABS_SOCKET_TOKEN=... dans un fichier .env",
        file=sys.stderr,
    )
    sys.exit(1)


def normaliser(charge_utile):
    """
    Préfigure le bus d'événements interne du bot.

    La doc Streamlabs le précise : la valeur reçue est toujours un tableau,
    un même événement peut donc en contenir plusieurs. On ne suppose rien
    d'autre sur la forme, on affiche ce qu'on trouve.
    """
    type_evenement = charge_utile.get("type", "inconnu")
    plateforme = charge_utile.get("for", "streamlabs")
    messages = charge_utile.get("message", [])

    if isinstance(messages, dict):          # au cas où Streamlabs renvoie un objet seul
        messages = [messages]
    if not isinstance(messages, list):
        messages = [{"brut": messages}]

    resultats = []
    for element in messages:
        if not isinstance(element, dict):
            element = {"brut": element}
        resultats.append(
            {
                "type": type_evenement,
                "libelle": INTERESSANTS.get(type_evenement, type_evenement),
                "plateforme": plateforme,
                "auteur": element.get("name") or element.get("from") or element.get("username"),
                "montant": element.get("formatted_amount") or element.get("amount"),
                "mois": element.get("months"),
                "viewers": element.get("viewers") or element.get("raiders"),
                "message": element.get("message") or element.get("comment"),
                "brut": element,
            }
        )
    return resultats


def afficher(charge_utile):
    for evenement in normaliser(charge_utile):
        details = []
        for cle in ("auteur", "montant", "mois", "viewers", "message"):
            if evenement.get(cle):
                details.append(f"{cle}={evenement[cle]}")
        log("ÉVÉNEMENT", f"{evenement['libelle']} ({evenement['plateforme']}) " + " · ".join(details))
        log("", "  brut : " + json.dumps(evenement["brut"], ensure_ascii=False)[:400])


# --------------------------------------------------------------------------
# Mode normal : python-socketio 4.x
# --------------------------------------------------------------------------
def mode_socketio(jeton):
    try:
        import socketio
    except ImportError:
        print("python-socketio absent : pip install -r requirements-test.txt", file=sys.stderr)
        sys.exit(1)

    version = getattr(socketio, "__version__", "?")
    if str(version).startswith("5"):
        log("ALERTE", f"python-socketio {version} détecté. Streamlabs parle le protocole")
        log("", "  Engine.IO v3 : il faut la branche 4.x. Voir R1 dans le suivi de projet.")

    client = socketio.Client(reconnection=True, reconnection_attempts=0)

    @client.event
    def connect():
        log("CONNEXION", "socket ouvert — déclenche un test depuis Streamlabs (Alert Box)")

    @client.event
    def connect_error(*args):
        log("ÉCHEC", f"connexion refusée : {args if args else 'jeton invalide ?'}")

    @client.event
    def disconnect():
        log("FERMÉ", "socket refermé")

    @client.on("event")
    def on_event(donnees):
        afficher(donnees)

    log("DÉMARRAGE", "mode python-socketio")
    try:
        client.connect(f"{SOCKET_URL}?token={jeton}", transports=["websocket"])
    except Exception as erreur:
        log("ÉCHEC", f"connexion impossible : {erreur}")
        log("", "  Pistes, dans l'ordre :")
        log("", "  1. jeton invalide ou expiré — le régénérer dans le tableau de bord")
        log("", "  2. version de python-socketio — il faut la branche 4.x (R1)")
        log("", "  3. réseau ou pare-feu bloquant sockets.streamlabs.com")
        log("", "  4. si tout semble bon, essayer le plan B : --raw")
        sys.exit(2)
    client.wait()


# --------------------------------------------------------------------------
# Plan B : WebSocket brut, protocole Engine.IO v3
# --------------------------------------------------------------------------
def mode_brut(jeton):
    try:
        from websocket import create_connection
    except ImportError:
        print("websocket-client absent : pip install -r requirements-test.txt", file=sys.stderr)
        sys.exit(1)

    log("DÉMARRAGE", "mode WebSocket brut (Engine.IO v3)")
    try:
        connexion = create_connection(RAW_URL.format(token=jeton), timeout=30)
    except Exception as erreur:
        log("ÉCHEC", f"connexion impossible : {erreur}")
        log("", "  Jeton invalide, ou accès réseau à sockets.streamlabs.com bloqué.")
        sys.exit(2)

    ouverture = connexion.recv()
    if not ouverture.startswith("0"):
        log("ÉCHEC", f"trame d'ouverture inattendue : {ouverture[:120]}")
        return
    infos = json.loads(ouverture[1:])
    intervalle = infos.get("pingInterval", 25000) / 1000
    log("CONNEXION", f"ouvert, sid={infos.get('sid')}, ping toutes les {intervalle:.0f}s")

    arret = threading.Event()

    def battement():
        while not arret.wait(intervalle):
            try:
                connexion.send("2")          # ping Engine.IO v3
            except Exception as erreur:
                log("ÉCHEC", f"ping impossible : {erreur}")
                return

    threading.Thread(target=battement, daemon=True).start()
    log("PRÊT", "déclenche un test depuis Streamlabs (Alert Box)")

    try:
        while True:
            trame = connexion.recv()
            if trame in ("3", "40"):          # pong, ou confirmation de connexion
                continue
            if trame.startswith("42"):
                _, charge_utile = json.loads(trame[2:])
                afficher(charge_utile)
            else:
                log("TRAME", trame[:200])
    except KeyboardInterrupt:
        pass
    finally:
        arret.set()
        connexion.close()


def main():
    analyseur = argparse.ArgumentParser(description="Test du connecteur Streamlabs (Bavardus, étape 1.6)")
    analyseur.add_argument("--token", help="jeton socket Streamlabs")
    analyseur.add_argument("--raw", action="store_true", help="plan B : WebSocket brut Engine.IO v3")
    arguments = analyseur.parse_args()

    jeton = charger_jeton(arguments.token)
    log("JETON", f"chargé ({len(jeton)} caractères, se termine par …{jeton[-4:]})")

    try:
        if arguments.raw:
            mode_brut(jeton)
        else:
            mode_socketio(jeton)
    except KeyboardInterrupt:
        log("ARRÊT", "interrompu au clavier")


if __name__ == "__main__":
    main()
