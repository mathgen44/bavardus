"""Authentification de l'interface (D22, D23).

L'interface est exposée sur Internet et pilote un bot dont les jetons donnent
le contrôle d'un compte Twitch. Elle ne peut pas être ouverte.

**Connexion par OAuth Twitch, compte du diffuseur.** Aucun mot de passe à
gérer, donc aucun mot de passe par défaut que personne ne change — l'erreur
d'installation la plus répandue, et celle qui laisse une interface pilotable
par n'importe qui.

**Amorçage (D22) :** au premier démarrage, aucun propriétaire n'est
enregistré. Le premier compte Twitch qui se connecte le devient, et
l'installation se verrouille sur lui.

**Une seule URL de redirection (D23).** Les deux flux — connexion du
propriétaire et autorisation du bot — passent par la même callback. Le
paramètre `state` porte l'intention en plus de sa fonction anti-CSRF, ce qui
laisse à l'utilisateur une seule chaîne à copier sur la console Twitch, donc
une seule occasion de se tromper.
"""

from __future__ import annotations

import os
import secrets as aleatoire
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

import httpx
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

AUTORISATION = "https://id.twitch.tv/oauth2/authorize"
JETON = "https://id.twitch.tv/oauth2/token"
VALIDATION = "https://id.twitch.tv/oauth2/validate"

# Le bot lit et écrit dans le chat. Le propriétaire n'a besoin d'aucun scope :
# on ne veut que son identité, et /validate la donne sans autorisation
# particulière. Demander plus serait réclamer des droits dont on n'a pas
# l'usage — et un écran de consentement inutilement inquiétant.
SCOPES_CHAT = ["user:read:chat", "user:write:chat", "user:bot"]

# Demandés en plus pour la modération automatique. Séparés volontairement :
# une instance qui ne modère pas ne doit pas réclamer le droit d'exclure des
# spectateurs. L'interface les ajoute quand la modération est activée.
SCOPES_MODERATION = ["moderator:manage:chat_messages",
                     "moderator:manage:banned_users"]

SCOPES = {
    "bot": SCOPES_CHAT,
    "bot_moderation": SCOPES_CHAT + SCOPES_MODERATION,
    "proprietaire": [],
}

DUREE_ETAT = 600          # 10 min : le temps d'un flux OAuth, pas davantage
DUREE_SESSION = 30 * 86400
COOKIE = "bavardus_session"


class ErreurAuth(Exception):
    """Le message est destiné à l'utilisateur : il doit dire quoi faire."""


@dataclass(frozen=True, slots=True)
class Identite:
    login: str
    user_id: str


def cle_session(racine: Path) -> str:
    """Clé de signature des cookies, créée au premier démarrage.

    Persistée plutôt que régénérée : sinon chaque redémarrage du bot
    déconnecterait le propriétaire, ce qui rend l'interface pénible sans rien
    apporter à la sécurité.
    """
    chemin = Path(racine) / "cle_session"
    if chemin.exists():
        return chemin.read_text(encoding="utf-8").strip()

    chemin.parent.mkdir(parents=True, exist_ok=True)
    cle = aleatoire.token_urlsafe(48)
    descripteur = os.open(chemin, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descripteur, "w", encoding="utf-8") as fichier:
        fichier.write(cle)
    return cle


class Signataire:
    def __init__(self, cle: str) -> None:
        self._etats = URLSafeTimedSerializer(cle, salt="etat-oauth")
        self._sessions = URLSafeTimedSerializer(cle, salt="session")

    # ---------------------------------------------------------------- state
    def creer_etat(self, usage: str) -> str:
        """Signé plutôt que stocké : rien à garder côté serveur, et un
        redémarrage en plein flux ne casse pas la connexion en cours."""
        return self._etats.dumps({"usage": usage, "nonce": aleatoire.token_urlsafe(16)})

    def lire_etat(self, etat: str) -> str:
        try:
            donnees = self._etats.loads(etat, max_age=DUREE_ETAT)
        except SignatureExpired as erreur:
            raise ErreurAuth(
                "la demande d'autorisation a expiré — relancer la connexion") from erreur
        except BadSignature as erreur:
            raise ErreurAuth(
                "demande d'autorisation invalide : elle n'a pas été émise par "
                "cette instance. Relancer la connexion depuis l'interface.") from erreur
        return donnees["usage"]

    # -------------------------------------------------------------- session
    def creer_session(self, identite: Identite) -> str:
        return self._sessions.dumps({"login": identite.login,
                                     "user_id": identite.user_id})

    def lire_session(self, cookie: str) -> Identite | None:
        try:
            donnees = self._sessions.loads(cookie, max_age=DUREE_SESSION)
        except (BadSignature, SignatureExpired):
            return None
        return Identite(donnees["login"], donnees["user_id"])


def url_autorisation(config, client_id: str, usage: str, etat: str) -> str:
    parametres = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": config.url_redirection,      # D23
        "scope": " ".join(SCOPES[usage]),
        "state": etat,
    }
    if usage.startswith("bot"):
        # G12 : Twitch conserve la session du navigateur. Sans force_verify,
        # l'écran de consentement s'affiche pour le compte déjà connecté et
        # l'on repart avec le jeton du diffuseur sans que rien ne le signale.
        parametres["force_verify"] = "true"
    return f"{AUTORISATION}?{urllib.parse.urlencode(parametres)}"


async def echanger_code(code: str, config, client_id: str, client_secret: str) -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        reponse = await client.post(JETON, data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": config.url_redirection,
        })
    if reponse.status_code != 200:
        detail = reponse.text[:300]
        if "redirect_uri" in detail or "redirect" in detail.lower():
            raise ErreurAuth(
                f"Twitch refuse l'URL de redirection. Vérifier que la console "
                f"développeur contient EXACTEMENT : {config.url_redirection} "
                f"— sans « / » final, avec le même schéma et le même port.")
        raise ErreurAuth(f"Twitch a refusé l'échange du code : {detail}")
    return reponse.json()


async def identifier(acces: str) -> Identite:
    """À qui appartient ce jeton ? Question posée à Twitch, pas déduite."""
    async with httpx.AsyncClient(timeout=15) as client:
        reponse = await client.get(VALIDATION,
                                   headers={"Authorization": f"OAuth {acces}"})
    if reponse.status_code != 200:
        raise ErreurAuth("Twitch n'a pas validé le jeton obtenu")
    bloc = reponse.json()
    return Identite(bloc.get("login", ""), str(bloc.get("user_id", "")))


def proprietaire(jetons) -> Identite | None:
    """Le propriétaire est simplement celui dont on détient le jeton.

    Pas de fichier supplémentaire : l'existence du jeton « proprietaire » EST
    l'enregistrement. Un état de moins à maintenir cohérent.
    """
    jeton = jetons.get("proprietaire")
    if jeton is None or not jeton.user_id:
        return None
    return Identite(jeton.login, jeton.user_id)


def verifier_proprietaire(jetons, identite: Identite) -> None:
    """Verrouille l'installation sur le premier compte connecté (D22)."""
    actuel = proprietaire(jetons)
    if actuel is not None and actuel.user_id != identite.user_id:
        raise ErreurAuth(
            f"cette instance appartient déjà à « {actuel.login} ». "
            f"Le compte « {identite.login} » ne peut pas s'y connecter.")
