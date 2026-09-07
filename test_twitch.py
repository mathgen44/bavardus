#!/usr/bin/env python3
"""
Bavardus — étapes 1.3, 1.4 et préfiguration de 3.1 / 3.2 / 4.1 : validation Twitch.

Ce script valide la chaîne complète avant qu'on écrive la moindre architecture :
  --auth      flux OAuth de bout en bout, à travers ton reverse proxy
  --check     jeton valide ? quels scopes ? quel compte ? modérateur ?
  --refresh   le rafraîchissement automatique fonctionne-t-il (R4) ?
  --listen    connexion EventSub WebSocket, affichage du chat en direct
  --say TEXTE envoi d'un message dans le chat

Dépendance : websocket-client (déjà dans requirements-test.txt).

Configuration, dans un fichier .env à côté du script :

    TWITCH_CLIENT_ID=...
    TWITCH_CLIENT_SECRET=...
    TWITCH_REDIRECT_URI=https://bavardus.mathgen.fr/api/twitch/callback
    TWITCH_CHANNEL=mathgen44          # la chaîne à écouter
    TWITCH_CALLBACK_PORT=8475         # port local écouté pendant --auth

ATTENTION : les jetons obtenus sont écrits dans .twitch_tokens.json.
Ce fichier donne le contrôle du compte du bot. Ajoute-le au .gitignore
en même temps que .env, avant le premier commit (G5).
"""

import argparse
import json
import os
import ssl
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

FICHIER_JETONS = ".twitch_tokens.json"

AUTORISATION = "https://id.twitch.tv/oauth2/authorize"
JETON = "https://id.twitch.tv/oauth2/token"
VALIDATION = "https://id.twitch.tv/oauth2/validate"
HELIX = "https://api.twitch.tv/helix"
EVENTSUB = "wss://eventsub.wss.twitch.tv/ws"

# Scopes minimaux pour lire et écrire dans le chat avec le compte du bot.
# user:bot est exigé pour l'envoi ; le bot doit être modérateur de la chaîne
# ou le diffuseur doit avoir accordé channel:bot.
SCOPES = ["user:read:chat", "user:write:chat", "user:bot"]

# Ces trois scopes ne permettent PAS de lire la liste des modérateurs
# (« moderation:read », côté diffuseur) : le 401 sur ce point est normal.


def log(tag, message):
    print(f"[{datetime.now():%H:%M:%S}] {tag:<12} {message}", flush=True)


# ---------------------------------------------------------------- configuration
ORIGINE = {}


def config():
    valeurs = {}
    if os.path.exists(".env"):
        with open(".env", encoding="utf-8") as fichier:
            for ligne in fichier:
                ligne = ligne.strip()
                if ligne and not ligne.startswith("#") and "=" in ligne:
                    cle, valeur = ligne.split("=", 1)
                    valeurs[cle.strip()] = valeur.strip().strip("\"'")
                    ORIGINE[cle.strip()] = ".env"

    # B4 : l'environnement l'emporte sur le fichier. Une variable exportée
    # lors d'un essai précédent écrase silencieusement le .env — d'où ORIGINE.
    for cle, valeur in os.environ.items():
        if cle.startswith("TWITCH_"):
            valeurs[cle] = valeur
            ORIGINE[cle] = "environnement"

    manquants = [c for c in ("TWITCH_CLIENT_ID", "TWITCH_CLIENT_SECRET", "TWITCH_REDIRECT_URI") if not valeurs.get(c)]
    if manquants:
        print(f"Configuration incomplète : {', '.join(manquants)}", file=sys.stderr)
        print("Voir l'en-tête du script pour le contenu attendu du fichier .env", file=sys.stderr)
        sys.exit(1)
    return valeurs


def poster(url, donnees):
    corps = urllib.parse.urlencode(donnees).encode()
    requete = urllib.request.Request(url, data=corps, method="POST")
    try:
        with urllib.request.urlopen(requete, timeout=30) as reponse:
            return json.load(reponse)
    except urllib.error.HTTPError as erreur:
        detail = erreur.read().decode(errors="replace")
        log("ÉCHEC", f"HTTP {erreur.code} — {detail[:300]}")
        if "invalid client" in detail:
            log("", "  « invalid client » = identifiant ou secret rejeté. Pistes :")
            log("", "  1. le secret a été régénéré depuis la copie (l'ancien est mort aussitôt)")
            log("", "  2. une variable TWITCH_* exportée écrase le .env — lance --diag")
            log("", "  3. identifiant d'une application et secret d'une autre")
            log("", "  4. copie incomplète du secret")
        raise SystemExit(2)


def helix(chemin, cfg, jetons, methode="GET", corps=None, parametres=None):
    url = f"{HELIX}{chemin}"
    if parametres:
        url += "?" + urllib.parse.urlencode(parametres, doseq=True)
    donnees = json.dumps(corps).encode() if corps is not None else None
    requete = urllib.request.Request(url, data=donnees, method=methode)
    requete.add_header("Client-Id", cfg["TWITCH_CLIENT_ID"])
    requete.add_header("Authorization", f"Bearer {jetons['access_token']}")
    if corps is not None:
        requete.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(requete, timeout=30) as reponse:
        brut = reponse.read()
        return json.loads(brut) if brut else {}


def charger_jetons():
    if not os.path.exists(FICHIER_JETONS):
        print(f"Aucun jeton enregistré. Lance d'abord : {sys.argv[0]} --auth", file=sys.stderr)
        sys.exit(1)
    with open(FICHIER_JETONS, encoding="utf-8") as fichier:
        return json.load(fichier)


def enregistrer_jetons(jetons):
    jetons["obtenu_le"] = time.time()
    with open(FICHIER_JETONS, "w", encoding="utf-8") as fichier:
        json.dump(jetons, fichier, indent=2)
    os.chmod(FICHIER_JETONS, 0o600)
    log("JETONS", f"enregistrés dans {FICHIER_JETONS} (droits 600)")


# ------------------------------------------------------------------------ OAuth
class Reception(BaseHTTPRequestHandler):
    code = None
    erreur = None
    chemin_attendu = "/"

    def do_GET(self):
        analyse = urllib.parse.urlparse(self.path)
        parametres = urllib.parse.parse_qs(analyse.query)

        if analyse.path != Reception.chemin_attendu:
            # Utile au diagnostic : le proxy peut réécrire le chemin.
            self.send_response(404)
            self.end_headers()
            self.wfile.write(f"Chemin recu : {analyse.path}".encode())
            log("PROXY", f"chemin reçu « {analyse.path} », attendu « {Reception.chemin_attendu} »")
            return

        Reception.code = parametres.get("code", [None])[0]
        Reception.erreur = parametres.get("error_description", parametres.get("error", [None]))[0]

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        message = "Autorisation reçue. Tu peux fermer cet onglet." if Reception.code else f"Échec : {Reception.erreur}"
        self.wfile.write(f"<html><body style='font-family:sans-serif'><h2>{message}</h2></body></html>".encode())

    def log_message(self, *args):
        pass


def authentifier(cfg):
    redirection = cfg["TWITCH_REDIRECT_URI"]
    port = int(cfg.get("TWITCH_CALLBACK_PORT", 8475))
    Reception.chemin_attendu = urllib.parse.urlparse(redirection).path or "/"

    parametres = {
        "response_type": "code",
        "client_id": cfg["TWITCH_CLIENT_ID"],
        "redirect_uri": redirection,
        "scope": " ".join(SCOPES),
        "force_verify": "true",          # force l'écran de consentement
    }
    url = f"{AUTORISATION}?{urllib.parse.urlencode(parametres)}"

    log("ÉCOUTE", f"port {port}, chemin attendu « {Reception.chemin_attendu} »")
    log("IMPORTANT", "connecte-toi avec le compte DU BOT, pas avec ton compte principal")
    print(f"\nOuvre cette adresse dans un navigateur :\n\n{url}\n")
    try:
        webbrowser.open(url)
    except Exception:
        pass

    serveur = HTTPServer(("0.0.0.0", port), Reception)
    serveur.timeout = 300
    while Reception.code is None and Reception.erreur is None:
        serveur.handle_request()
    serveur.server_close()

    if Reception.erreur:
        log("ÉCHEC", f"Twitch a refusé : {Reception.erreur}")
        sys.exit(2)

    log("CODE", "reçu, échange contre les jetons")
    jetons = poster(JETON, {
        "client_id": cfg["TWITCH_CLIENT_ID"],
        "client_secret": cfg["TWITCH_CLIENT_SECRET"],
        "code": Reception.code,
        "grant_type": "authorization_code",
        "redirect_uri": redirection,
    })
    log("SUCCÈS", f"jeton valable {jetons.get('expires_in')} s, scopes : {' '.join(jetons.get('scope', []))}")
    enregistrer_jetons(jetons)


def rafraichir(cfg, jetons):
    """R4 : si ceci ne fonctionne pas, le bot meurt en plein live sans message d'erreur."""
    nouveaux = poster(JETON, {
        "client_id": cfg["TWITCH_CLIENT_ID"],
        "client_secret": cfg["TWITCH_CLIENT_SECRET"],
        "refresh_token": jetons["refresh_token"],
        "grant_type": "refresh_token",
    })
    log("RAFRAÎCHI", f"nouveau jeton valable {nouveaux.get('expires_in')} s")
    enregistrer_jetons(nouveaux)
    return nouveaux


def empreinte(valeur):
    if not valeur:
        return "(vide)"
    return f"{len(valeur)} car., {valeur[:4]}…{valeur[-4:]}"


def diagnostic(cfg):
    """Isole le couple identifiant/secret du reste du flux (B4)."""
    log("DIAG", "origine et empreinte de chaque valeur :")
    for cle in ("TWITCH_CLIENT_ID", "TWITCH_CLIENT_SECRET", "TWITCH_REDIRECT_URI", "TWITCH_CHANNEL"):
        log("", f"  {cle:<22} [{ORIGINE.get(cle, 'absent'):<13}] {empreinte(cfg.get(cle))}")

    doublons = [c for c in ("TWITCH_CLIENT_ID", "TWITCH_CLIENT_SECRET") if ORIGINE.get(c) == "environnement"]
    if doublons:
        log("ALERTE", f"valeurs venant de l'environnement, pas du .env : {', '.join(doublons)}")
        log("", "  vérifie avec « env | grep TWITCH » puis « unset » si c'est un reste d'essai")

    for cle in ("TWITCH_CLIENT_ID", "TWITCH_CLIENT_SECRET"):
        valeur = cfg.get(cle, "")
        if valeur != valeur.strip():
            log("ALERTE", f"{cle} contient une espace en début ou fin")
        if len(valeur) != 30:
            log("NOTE", f"{cle} fait {len(valeur)} caractères — les valeurs Twitch en font habituellement 30")

    log("DIAG", "test du couple identifiant/secret seul (client_credentials)…")
    resultat = poster(JETON, {
        "client_id": cfg["TWITCH_CLIENT_ID"],
        "client_secret": cfg["TWITCH_CLIENT_SECRET"],
        "grant_type": "client_credentials",
    })
    log("SUCCÈS", f"couple valide — jeton applicatif obtenu ({resultat.get('expires_in')} s)")
    log("", "  Le problème ne vient donc pas des identifiants : regarde l'URL de redirection,")
    log("", "  qui doit correspondre au caractère près à celle de la console.")


# ----------------------------------------------------------------- vérification
def verifier(cfg, jetons):
    requete = urllib.request.Request(VALIDATION)
    requete.add_header("Authorization", f"OAuth {jetons['access_token']}")
    try:
        with urllib.request.urlopen(requete, timeout=30) as reponse:
            infos = json.load(reponse)
    except urllib.error.HTTPError as erreur:
        log("EXPIRÉ", f"jeton invalide (HTTP {erreur.code}) — essaie --refresh")
        return None

    log("COMPTE", f"{infos.get('login')} (id {infos.get('user_id')})")
    log("EXPIRE", f"dans {infos.get('expires_in')} s")
    log("SCOPES", " ".join(infos.get("scopes", [])))

    absents = [s for s in SCOPES if s not in infos.get("scopes", [])]
    if absents:
        log("ALERTE", f"scopes manquants : {', '.join(absents)} — relance --auth")

    chaine = cfg.get("TWITCH_CHANNEL")
    if not chaine:
        return infos

    donnees = helix("/users", cfg, jetons, parametres={"login": chaine})
    if not donnees.get("data"):
        log("ALERTE", f"chaîne « {chaine} » introuvable")
        return infos
    diffuseur = donnees["data"][0]
    log("CHAÎNE", f"{diffuseur['display_name']} (id {diffuseur['id']})")

    # G12 : le piège le plus coûteux du flux OAuth. Twitch garde la session du
    # navigateur : même avec force_verify, l'écran de consentement s'affiche pour
    # le compte DÉJÀ connecté. On repart donc avec le jeton du diffuseur sans
    # rien remarquer — le bot parlerait sous le pseudo du streamer.
    if str(infos.get("user_id")) == str(diffuseur["id"]):
        log("ALERTE", "═" * 60)
        log("ALERTE", "Ce jeton est celui du DIFFUSEUR, pas d'un compte bot dédié.")
        log("ALERTE", "Le bot posterait sous ton propre pseudo dans ton propre chat.")
        log("ALERTE", "Refais --auth dans une fenêtre de NAVIGATION PRIVÉE, sinon")
        log("ALERTE", "Twitch te reconnectera sur ce même compte.")
        log("ALERTE", "═" * 60)

    try:
        moderateurs = helix("/moderation/moderators", cfg, jetons,
                            parametres={"broadcaster_id": diffuseur["id"], "user_id": infos["user_id"]})
        if moderateurs.get("data"):
            log("MODÉRATEUR", "oui — limites d'envoi élevées")
        else:
            log("MODÉRATEUR", "NON — limites d'envoi réduites et anti-spam plus sévère")
    except urllib.error.HTTPError as erreur:
        if erreur.code == 401:
            log("MODÉRATEUR", "non vérifiable — attendu : le scope « moderation:read » "
                              "n'est pas demandé ici. Ce n'est PAS une anomalie.")
        else:
            log("MODÉRATEUR", f"vérification impossible (HTTP {erreur.code}), à contrôler à la main")

    infos["broadcaster_id"] = diffuseur["id"]
    return infos


def envoyer(cfg, jetons, texte):
    infos = verifier(cfg, jetons)
    if not infos or "broadcaster_id" not in infos:
        log("ÉCHEC", "impossible de déterminer la chaîne cible (TWITCH_CHANNEL)")
        return
    if len(texte) > 500:
        log("TRONQUÉ", "message ramené à 500 caractères (G4)")
        texte = texte[:500]
    helix("/chat/messages", cfg, jetons, methode="POST", corps={
        "broadcaster_id": infos["broadcaster_id"],
        "sender_id": infos["user_id"],
        "message": texte,
    })
    log("ENVOYÉ", texte)


# --------------------------------------------------------------------- EventSub
def ecouter(cfg, jetons):
    try:
        from websocket import create_connection
    except ImportError:
        print("websocket-client absent : pip install -r requirements-test.txt", file=sys.stderr)
        sys.exit(1)

    infos = verifier(cfg, jetons)
    if not infos or "broadcaster_id" not in infos:
        log("ÉCHEC", "TWITCH_CHANNEL est nécessaire pour s'abonner au chat")
        return

    log("EVENTSUB", "connexion à la WebSocket")
    connexion = create_connection(EVENTSUB, timeout=60, sslopt={"cert_reqs": ssl.CERT_REQUIRED})

    accueil = json.loads(connexion.recv())
    if accueil.get("metadata", {}).get("message_type") != "session_welcome":
        log("ÉCHEC", f"message d'accueil inattendu : {accueil}")
        return
    session = accueil["payload"]["session"]["id"]
    delai = accueil["payload"]["session"].get("keepalive_timeout_seconds")
    log("SESSION", f"{session[:12]}… keepalive {delai} s")

    # D15 : EventSub ne sert QU'AU CHAT. Les alertes (follow, sub, don, raid)
    # viennent de Streamlabs, source unique — pas de double réaction possible
    # sur un même événement, et pas de scope supplémentaire à demander.
    # « channel.follow » v2 est volontairement retiré : il exige le scope
    # moderator:read:followers sur un jeton du diffuseur ou d'un modérateur.
    abonnements = [
        ("channel.chat.message", "1", {"broadcaster_user_id": infos["broadcaster_id"], "user_id": infos["user_id"]}),
    ]
    for type_evenement, version, condition in abonnements:
        try:
            helix("/eventsub/subscriptions", cfg, jetons, methode="POST", corps={
                "type": type_evenement,
                "version": version,
                "condition": condition,
                "transport": {"method": "websocket", "session_id": session},
            })
            log("ABONNÉ", type_evenement)
        except urllib.error.HTTPError as erreur:
            detail = erreur.read().decode(errors="replace")[:200]
            log("REFUSÉ", f"{type_evenement} — HTTP {erreur.code} : {detail}")
            if type_evenement == "channel.chat.message" and erreur.code == 403:
                log("", "  Cause quasi certaine : le compte du bot n'est pas autorisé sur")
                log("", "  cette chaîne. Deux remèdes, le premier suffit :")
                log("", "   1. depuis le chat du diffuseur : /mod <compte_du_bot>")
                log("", "   2. ou faire accorder le scope channel:bot par le diffuseur")

    log("PRÊT", "écris dans le chat de la chaîne, les messages doivent apparaître ici")
    try:
        while True:
            brut = connexion.recv()
            message = json.loads(brut)
            type_message = message.get("metadata", {}).get("message_type")

            if type_message == "session_keepalive":
                continue
            if type_message == "session_reconnect":
                log("RECONNEXION", "Twitch demande une reconnexion — à gérer en 3.1")
                continue
            if type_message == "revocation":
                log("RÉVOQUÉ", json.dumps(message.get("payload"), ensure_ascii=False)[:200])
                continue
            if type_message != "notification":
                log("AUTRE", type_message)
                continue

            evenement = message["payload"]["event"]
            sujet = message["payload"]["subscription"]["type"]
            if sujet == "channel.chat.message":
                auteur = evenement.get("chatter_user_name")
                texte = evenement.get("message", {}).get("text", "")
                log("CHAT", f"{auteur} : {texte}")
            else:
                log(sujet.upper()[:12], json.dumps(evenement, ensure_ascii=False)[:200])
    except KeyboardInterrupt:
        log("ARRÊT", "interrompu au clavier")
    finally:
        connexion.close()


def main():
    analyseur = argparse.ArgumentParser(description="Validation Twitch (Bavardus, phase 1)")
    analyseur.add_argument("--diag", action="store_true", help="diagnostiquer les identifiants (invalid client)")
    analyseur.add_argument("--auth", action="store_true", help="flux OAuth complet")
    analyseur.add_argument("--check", action="store_true", help="état du jeton, scopes, compte, modération")
    analyseur.add_argument("--refresh", action="store_true", help="tester le rafraîchissement (R4)")
    analyseur.add_argument("--listen", action="store_true", help="écouter le chat via EventSub")
    analyseur.add_argument("--say", metavar="TEXTE", help="envoyer un message dans le chat")
    arguments = analyseur.parse_args()

    cfg = config()

    if arguments.diag:
        diagnostic(cfg)
        return

    if arguments.auth:
        authentifier(cfg)
        return

    jetons = charger_jetons()

    if arguments.refresh:
        jetons = rafraichir(cfg, jetons)
    if arguments.check or arguments.refresh:
        verifier(cfg, jetons)
    if arguments.say:
        envoyer(cfg, jetons, arguments.say)
    if arguments.listen:
        ecouter(cfg, jetons)
    if not any([arguments.check, arguments.refresh, arguments.say, arguments.listen]):
        analyseur.print_help()


if __name__ == "__main__":
    main()
