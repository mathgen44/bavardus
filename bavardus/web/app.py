"""Interface web : application FastAPI en rendu serveur (D20).

Trois états, dans cet ordre :

1. **aucun propriétaire** → l'assistant d'installation, accessible sans
   authentification. C'est le seul moment où l'interface est ouverte, et il
   se referme dès la première connexion (D22).
2. **propriétaire enregistré, visiteur non connecté** → écran de connexion.
3. **propriétaire connecté** → le tableau de bord.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import asyncio
import json
import time

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from ..config import ConfigInvalide, ecrire as ecrire_config
from .. import secrets as module_secrets
from ..stockage.jetons import Jetons
from . import auth
from .formulaire import appliquer_formulaire

journal = logging.getLogger("bavardus.web")


@dataclass
class Contexte:
    """Ce que l'application partage avec le moteur. Un seul processus (D19),
    donc les mêmes objets — ni API interne, ni sérialisation."""
    racine: Path
    gestionnaire_config: object
    jetons: Jetons
    base: object | None = None

    @property
    def config(self):
        return self.gestionnaire_config.courante

    def secrets(self):
        return module_secrets.charger(self.racine)


def creer_application(contexte: Contexte) -> FastAPI:
    application = FastAPI(title="Bavardus", docs_url=None, redoc_url=None)
    gabarits = Jinja2Templates(
        directory=str(Path(__file__).parent / "gabarits"))
    signataire = auth.Signataire(auth.cle_session(contexte.racine))

    def rendre(requete: Request, gabarit: str, **valeurs) -> HTMLResponse:
        return gabarits.TemplateResponse(requete, gabarit, valeurs)

    def session(requete: Request) -> auth.Identite | None:
        cookie = requete.cookies.get(auth.COOKIE)
        return signataire.lire_session(cookie) if cookie else None

    def connecte(requete: Request) -> bool:
        """Connecté ET propriétaire : un cookie signé émis avant un
        changement de propriétaire ne doit pas rester valable."""
        identite = session(requete)
        actuel = auth.proprietaire(contexte.jetons)
        return (identite is not None and actuel is not None
                and identite.user_id == actuel.user_id)

    # ------------------------------------------------------------- accueil
    @application.get("/", response_class=HTMLResponse)
    async def accueil(requete: Request):
        if auth.proprietaire(contexte.jetons) is None:
            return RedirectResponse("/installation", status_code=303)
        if not connecte(requete):
            return RedirectResponse("/connexion", status_code=303)
        return RedirectResponse("/tableau-de-bord", status_code=303)

    # -------------------------------------------------------- installation
    @application.get("/installation", response_class=HTMLResponse)
    async def installation(requete: Request, erreur: str = "", info: str = ""):
        if auth.proprietaire(contexte.jetons) is not None:
            # L'assistant se referme définitivement : le laisser ouvert
            # offrirait à un visiteur de réécrire les identifiants Twitch.
            return RedirectResponse("/connexion", status_code=303)
        config = contexte.config
        return rendre(requete, "installation.html",
                      url_redirection=config.url_redirection,
                      base_url=config.base_url,
                      client_id=contexte.secrets().twitch_client_id,
                      chaine=config.twitch.chaine,
                      erreur=erreur, info=info)

    @application.post("/installation")
    async def enregistrer_installation(
            client_id: str = Form(...), client_secret: str = Form(...),
            chaine: str = Form(...)):
        if auth.proprietaire(contexte.jetons) is not None:
            return RedirectResponse("/connexion", status_code=303)

        module_secrets.ecrire_env(contexte.racine, {
            "TWITCH_CLIENT_ID": client_id.strip(),
            "TWITCH_CLIENT_SECRET": client_secret.strip(),
        })
        from ..config import ConfigTwitch
        contexte.gestionnaire_config.appliquer(
            twitch=ConfigTwitch(chaine=chaine.strip().lower()))
        journal.info("identifiants Twitch enregistrés, chaîne : %s", chaine)
        return RedirectResponse("/connexion", status_code=303)

    # ------------------------------------------------------------ connexion
    @application.get("/connexion", response_class=HTMLResponse)
    async def connexion(requete: Request, erreur: str = ""):
        if connecte(requete):
            return RedirectResponse("/tableau-de-bord", status_code=303)
        actuel = auth.proprietaire(contexte.jetons)
        return rendre(requete, "connexion.html",
                      proprietaire=actuel.login if actuel else "",
                      erreur=erreur)

    @application.get("/api/twitch/connexion")
    async def demarrer_flux(usage: str = "proprietaire"):
        if usage not in auth.SCOPES:
            return RedirectResponse("/connexion?erreur=usage+inconnu", status_code=303)
        secrets = contexte.secrets()
        if not secrets.twitch_client_id:
            return RedirectResponse(
                "/installation?erreur=identifiants+Twitch+manquants", status_code=303)
        etat = signataire.creer_etat(usage)
        return RedirectResponse(
            auth.url_autorisation(contexte.config, secrets.twitch_client_id,
                                  usage, etat),
            status_code=303)

    # D23 : une seule callback pour les deux flux, distingués par `state`.
    @application.get("/api/twitch/callback")
    async def callback(code: str = "", state: str = "", error: str = "",
                       error_description: str = ""):
        if error:
            return RedirectResponse(
                f"/connexion?erreur=Twitch+a+refusé+:+{error_description or error}",
                status_code=303)
        if not code or not state:
            return RedirectResponse("/connexion?erreur=réponse+incomplète",
                                    status_code=303)

        secrets = contexte.secrets()
        try:
            usage = signataire.lire_etat(state)
            jetons_twitch = await auth.echanger_code(
                code, contexte.config, secrets.twitch_client_id,
                secrets.twitch_client_secret)
            identite = await auth.identifier(jetons_twitch["access_token"])
        except auth.ErreurAuth as erreur:
            return RedirectResponse(f"/connexion?erreur={erreur}", status_code=303)

        if usage == "proprietaire":
            try:
                auth.verifier_proprietaire(contexte.jetons, identite)
            except auth.ErreurAuth as erreur:
                return RedirectResponse(f"/connexion?erreur={erreur}", status_code=303)

            contexte.jetons.enregistrer("proprietaire", jetons_twitch,
                                        login=identite.login,
                                        user_id=identite.user_id)
            journal.info("propriétaire connecté : %s (%s)",
                         identite.login, identite.user_id)
            reponse = RedirectResponse("/tableau-de-bord", status_code=303)
            reponse.set_cookie(
                auth.COOKIE, signataire.creer_session(identite),
                max_age=auth.DUREE_SESSION, httponly=True, samesite="lax",
                secure=contexte.config.base_url.startswith("https://"))
            return reponse

        # usage == "bot"
        actuel = auth.proprietaire(contexte.jetons)
        if actuel is not None and identite.user_id == actuel.user_id:
            # G12 : le piège le plus coûteux du flux OAuth. Twitch conserve
            # la session du navigateur ; sans ce contrôle, le bot parlerait
            # sous le pseudo du streamer.
            return RedirectResponse(
                "/tableau-de-bord?erreur=Ce+jeton+est+celui+du+diffuseur,+pas+"
                "d'un+compte+bot.+Recommencer+dans+une+fenêtre+de+navigation+privée.",
                status_code=303)

        contexte.jetons.enregistrer("bot", jetons_twitch, login=identite.login,
                                    user_id=identite.user_id)
        journal.info("compte du bot autorisé : %s (%s)",
                     identite.login, identite.user_id)
        return RedirectResponse(
            f"/tableau-de-bord?info=Compte+{identite.login}+autorisé",
            status_code=303)

    # ------------------------------------------------------- tableau de bord
    @application.get("/tableau-de-bord", response_class=HTMLResponse)
    async def tableau(requete: Request, erreur: str = "", info: str = ""):
        if not connecte(requete):
            return RedirectResponse("/connexion", status_code=303)
        return rendre(requete, "tableau.html",
                      identite=session(requete),
                      bot=contexte.jetons.get("bot"),
                      config=contexte.config,
                      erreur=erreur, info=info)

    # ------------------------------------------------------------- réglages
    @application.get("/reglages", response_class=HTMLResponse)
    async def reglages(requete: Request, erreur: str = "", info: str = ""):
        if not connecte(requete):
            return RedirectResponse("/connexion", status_code=303)
        jeton_bot = contexte.jetons.get("bot")
        return rendre(requete, "reglages.html",
                      identite=session(requete), config=contexte.config,
                      nom_bot=jeton_bot.login if jeton_bot else "lebot",
                      erreur=erreur, info=info)

    @application.post("/reglages")
    async def enregistrer_reglages(requete: Request):
        if not connecte(requete):
            return RedirectResponse("/connexion", status_code=303)
        donnees = await requete.form()

        if donnees.get("action") == "charger_exemple":
            # Fusion, jamais remplacement : l'utilisateur a peut-être déjà
            # ajouté des mots propres à sa chaîne, et les perdre en cliquant
            # sur un bouton d'aide serait le contraire d'une aide.
            from ..noyau.moderation import liste_exemple
            from ..chemins import racine_code
            existants = set(contexte.config.moderation.mots_interdits)
            proposes = set(liste_exemple(racine_code()))
            fusion = "\n".join(sorted(existants | proposes))
            donnees = dict(donnees)
            donnees["mots_interdits"] = fusion

        try:
            candidate = appliquer_formulaire(contexte.config, donnees)
        except ConfigInvalide as erreur:
            # La configuration en vigueur n'a pas bougé : un réglage refusé
            # ne doit pas faire taire un bot qui fonctionnait.
            return RedirectResponse(f"/reglages?erreur={erreur}", status_code=303)

        gestionnaire = contexte.gestionnaire_config
        ecrire_config(gestionnaire.chemin, candidate)
        gestionnaire.recharger()
        journal.info("réglages enregistrés (version %s)", gestionnaire.version)
        return RedirectResponse("/reglages?info=Réglages+appliqués", status_code=303)

    # -------------------------------------------------------------- journal
    def _formater(ligne: dict) -> dict:
        return {
            "id": ligne.get("id", 0),
            "heure": time.strftime("%H:%M:%S", time.localtime(ligne["horodatage"])),
            "repondu": bool(ligne["repondu"]),
            "evenement": ligne["evenement"],
            "raison": ligne["raison"],
            "detail": ligne["detail"],
        }

    STATS_VIDES = {"evenements": 0, "reponses_envoyees": 0,
                   "latence_moyenne_ms": 0, "taux_vides": 0.0}

    @application.get("/journal", response_class=HTMLResponse)
    async def page_journal(requete: Request):
        if not connecte(requete):
            return RedirectResponse("/connexion", status_code=303)
        if contexte.base is None:
            return rendre(requete, "journal.html", identite=session(requete),
                          decisions=[], stats=STATS_VIDES,
                          info="Le bot n'est pas démarré : rien à journaliser.")
        return rendre(requete, "journal.html", identite=session(requete),
                      decisions=[_formater(l)
                                 for l in contexte.base.dernieres_decisions(60)],
                      stats=contexte.base.statistiques())

    @application.get("/api/journal/flux")
    async def flux_journal(requete: Request):
        if not connecte(requete):
            return RedirectResponse("/connexion", status_code=303)

        async def evenements():
            if contexte.base is None:
                return
            dernier = contexte.base.dernier_id_decision()
            while True:
                if await requete.is_disconnected():
                    return
                # Interrogation périodique plutôt que notification : le
                # volume est faible (quelques décisions par minute) et cela
                # évite de coupler l'émetteur au serveur web.
                nouvelles = await asyncio.to_thread(
                    contexte.base.dernieres_decisions, 50, dernier)
                for ligne in nouvelles:
                    dernier = max(dernier, ligne["id"])
                    yield f"data: {json.dumps(_formater(ligne), ensure_ascii=False)}\n\n"
                if not nouvelles:
                    # Commentaire SSE : maintient la connexion ouverte à
                    # travers les proxys qui coupent les flux inactifs.
                    yield ": battement\n\n"
                await asyncio.sleep(2)

        return StreamingResponse(evenements(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache",
                                          "X-Accel-Buffering": "no"})

    @application.get("/deconnexion")
    async def deconnexion():
        reponse = RedirectResponse("/connexion", status_code=303)
        reponse.delete_cookie(auth.COOKIE)
        return reponse

    application.state.contexte = contexte
    application.state.signataire = signataire
    application.state.connecte = connecte
    return application
