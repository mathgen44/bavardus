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

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from .. import secrets as module_secrets
from ..stockage.jetons import Jetons
from . import auth

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

    @application.get("/deconnexion")
    async def deconnexion():
        reponse = RedirectResponse("/connexion", status_code=303)
        reponse.delete_cookie(auth.COOKIE)
        return reponse

    application.state.contexte = contexte
    application.state.signataire = signataire
    application.state.connecte = connecte
    return application
