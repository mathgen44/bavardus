"""Configuration de Bavardus : chargement, validation, rechargement à chaud.

Deux exigences dictent la forme de ce module.

1. **Rechargeable à chaud.** Régler le persona depuis l'interface ne doit ni
   redémarrer le bot, ni le faire taire au milieu d'un live. La configuration
   est donc un objet *immuable* que le gestionnaire remplace d'un bloc : le
   noyau lit la version courante à chaque événement et ne voit jamais un état
   à moitié appliqué.

2. **Lisible et réparable à la main.** Quand l'interface web est inaccessible,
   `config.yaml` reste modifiable dans un éditeur. C'est le fichier qui sauve
   une installation cassée, il ne doit donc jamais devenir illisible.

Les secrets ne sont PAS ici (G5) : ils vivent dans `.env` et `jetons.json`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import yaml


class ConfigInvalide(Exception):
    """Configuration inutilisable. Le message dit quoi corriger, et où."""


# --------------------------------------------------------------------- sections
@dataclass(frozen=True, slots=True)
class ConfigTwitch:
    chaine: str = ""


@dataclass(frozen=True, slots=True)
class ConfigModele:
    fournisseur: str = "ollama"
    url: str = "http://localhost:11434"
    nom: str = "gemma4:e4b"
    plafond_jetons: int = 60          # D5
    temperature: float = 0.7
    reflexion: bool = False           # D16

    FOURNISSEURS = ("ollama", "compatible_openai")


@dataclass(frozen=True, slots=True)
class ConfigConversation:
    contexte_messages: int = 12
    longueur_max: int = 500           # G4


@dataclass(frozen=True, slots=True)
class ConfigSpontanee:
    active: bool = False
    minutes_de_silence: int = 5
    max_par_heure: int = 4


@dataclass(frozen=True, slots=True)
class ConfigPriseDeParole:
    sur_mention: bool = True
    sur_commande: bool = True
    sur_alerte: bool = True
    spontanee: ConfigSpontanee = field(default_factory=ConfigSpontanee)
    max_messages_par_minute: int = 6
    # Les autres bots de la chaîne. Sans cette liste, deux bots qui se
    # répondent poliment peuvent saturer un chat en quelques secondes.
    comptes_ignores: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ConfigModeration:
    active: bool = False
    mots_interdits: tuple[str, ...] = ()
    action: str = "supprimer"
    # Exclusion TEMPORAIRE, jamais définitive : une erreur dans la liste de
    # mots ne doit pas coûter un spectateur à la chaîne.
    duree_exclusion_secondes: int = 600

    ACTIONS = ("supprimer", "avertir", "exclure")


@dataclass(frozen=True, slots=True)
class Config:
    base_url: str = "http://localhost:8475"          # D23
    twitch: ConfigTwitch = field(default_factory=ConfigTwitch)
    modele: ConfigModele = field(default_factory=ConfigModele)
    persona: str = ""
    conversation: ConfigConversation = field(default_factory=ConfigConversation)
    prise_de_parole: ConfigPriseDeParole = field(default_factory=ConfigPriseDeParole)
    moderation: ConfigModeration = field(default_factory=ConfigModeration)
    niveau_journal: str = "INFO"

    @property
    def url_redirection(self) -> str:
        """D23 : l'unique URL à déclarer sur la console développeur Twitch.

        Une seule pour les deux flux OAuth (bot et propriétaire) ; c'est le
        paramètre `state` qui porte l'intention. Une seule chaîne à copier,
        donc une seule occasion de se tromper.
        """
        return f"{self.base_url.rstrip('/')}/api/twitch/callback"


# ------------------------------------------------------------------- validation
def _exiger(condition: bool, message: str) -> None:
    if not condition:
        raise ConfigInvalide(message)


def valider(config: Config) -> None:
    """Rejette ce qui produirait une panne illisible plus tard.

    On valide au chargement plutôt qu'à l'usage : une erreur au démarrage,
    avec le champ fautif nommé, vaut mieux qu'un bot qui se tait en plein
    live pour une raison que personne ne sait lire.
    """
    _exiger(config.base_url.startswith(("http://", "https://")),
            "base_url doit commencer par http:// ou https:// "
            f"(reçu : {config.base_url!r})")
    _exiger(not config.base_url.endswith("/"),
            "base_url ne doit pas finir par « / » : l'URL de redirection "
            "construite ne correspondrait plus, au caractère près, à celle "
            "déclarée sur Twitch")

    _exiger(config.modele.fournisseur in ConfigModele.FOURNISSEURS,
            f"modele.fournisseur doit valoir l'un de "
            f"{', '.join(ConfigModele.FOURNISSEURS)} "
            f"(reçu : {config.modele.fournisseur!r})")
    _exiger(bool(config.modele.nom), "modele.nom est vide")
    _exiger(config.modele.plafond_jetons > 0,
            "modele.plafond_jetons doit être positif")
    _exiger(0.0 <= config.modele.temperature <= 2.0,
            "modele.temperature doit être comprise entre 0 et 2")

    # D16 : on n'interdit pas la réflexion, on refuse de la laisser
    # s'activer là où elle produit à coup sûr des réponses vides (R15).
    _exiger(not (config.modele.reflexion and config.modele.plafond_jetons < 512),
            "modele.reflexion est activée avec un plafond de "
            f"{config.modele.plafond_jetons} jetons : la réflexion interne "
            "les consommera tous et le bot ne dira RIEN (R15/D16). "
            "Mettre reflexion: false, ou plafond_jetons à 512 au minimum.")

    _exiger(0 < config.conversation.longueur_max <= 500,
            "conversation.longueur_max doit être compris entre 1 et 500 : "
            "Twitch refuse au-delà (G4)")
    _exiger(config.conversation.contexte_messages >= 0,
            "conversation.contexte_messages ne peut pas être négatif")

    _exiger(config.prise_de_parole.max_messages_par_minute > 0,
            "prise_de_parole.max_messages_par_minute doit être positif : "
            "mettre 0 ne « désactive » rien, cela rend le bot muet sans le dire")
    _exiger(config.prise_de_parole.spontanee.minutes_de_silence > 0,
            "prise_de_parole.spontanee.minutes_de_silence doit être positif")
    _exiger(config.prise_de_parole.spontanee.max_par_heure >= 0,
            "prise_de_parole.spontanee.max_par_heure ne peut pas être négatif")

    _exiger(config.moderation.action in ConfigModeration.ACTIONS,
            f"moderation.action doit valoir l'un de "
            f"{', '.join(ConfigModeration.ACTIONS)}")
    _exiger(1 <= config.moderation.duree_exclusion_secondes <= 1209600,
            "moderation.duree_exclusion_secondes doit être compris entre 1 s "
            "et 14 jours (limite de Twitch pour une exclusion temporaire)")
    _exiger(not (config.moderation.active and not config.moderation.mots_interdits),
            "la modération est activée sans aucun mot interdit : elle ne "
            "ferait rien. Ajouter des mots, ou la désactiver.")

    _exiger(config.niveau_journal in ("DEBUG", "INFO", "WARNING", "ERROR"),
            f"journal.niveau invalide : {config.niveau_journal!r}")


# -------------------------------------------------------------------- lecture
def _section(donnees: dict[str, Any], nom: str) -> dict[str, Any]:
    valeur = donnees.get(nom) or {}
    if not isinstance(valeur, dict):
        raise ConfigInvalide(f"la section « {nom} » doit être un bloc, pas une valeur")
    return valeur


def depuis_dict(donnees: dict[str, Any]) -> Config:
    """Construit une Config depuis un dictionnaire YAML, puis la valide.

    Toute clé absente prend sa valeur par défaut : une configuration
    partielle reste utilisable, et une nouvelle option n'invalide pas les
    fichiers existants.
    """
    if not isinstance(donnees, dict):
        raise ConfigInvalide("le fichier de configuration doit contenir un bloc YAML")

    m = _section(donnees, "modele")
    c = _section(donnees, "conversation")
    p = _section(donnees, "prise_de_parole")
    sp = _section(p, "spontanee")
    mo = _section(donnees, "moderation")

    defauts = Config()
    config = Config(
        base_url=str(donnees.get("base_url", defauts.base_url)),
        twitch=ConfigTwitch(chaine=str(_section(donnees, "twitch").get("chaine", ""))),
        modele=ConfigModele(
            fournisseur=str(m.get("fournisseur", defauts.modele.fournisseur)),
            url=str(m.get("url", defauts.modele.url)),
            nom=str(m.get("nom", defauts.modele.nom)),
            plafond_jetons=int(m.get("plafond_jetons", defauts.modele.plafond_jetons)),
            temperature=float(m.get("temperature", defauts.modele.temperature)),
            reflexion=bool(m.get("reflexion", defauts.modele.reflexion)),
        ),
        persona=str(donnees.get("persona", "")).strip(),
        conversation=ConfigConversation(
            contexte_messages=int(c.get("contexte_messages",
                                        defauts.conversation.contexte_messages)),
            longueur_max=int(c.get("longueur_max", defauts.conversation.longueur_max)),
        ),
        prise_de_parole=ConfigPriseDeParole(
            sur_mention=bool(p.get("sur_mention", True)),
            sur_commande=bool(p.get("sur_commande", True)),
            sur_alerte=bool(p.get("sur_alerte", True)),
            spontanee=ConfigSpontanee(
                active=bool(sp.get("active", False)),
                minutes_de_silence=int(sp.get("minutes_de_silence", 5)),
                max_par_heure=int(sp.get("max_par_heure", 4)),
            ),
            max_messages_par_minute=int(p.get("max_messages_par_minute", 6)),
            comptes_ignores=tuple(
                str(c).lower() for c in (p.get("comptes_ignores") or ())),
        ),
        moderation=ConfigModeration(
            active=bool(mo.get("active", False)),
            mots_interdits=tuple(mo.get("mots_interdits") or ()),
            action=str(mo.get("action", "supprimer")),
            duree_exclusion_secondes=int(
                mo.get("duree_exclusion_secondes", 600)),
        ),
        niveau_journal=str(_section(donnees, "journal").get("niveau", "INFO")).upper(),
    )
    valider(config)
    return config


def charger(chemin: Path) -> Config:
    if not chemin.exists():
        raise ConfigInvalide(
            f"{chemin} est introuvable. Copier config.exemple.yaml en "
            f"{chemin.name} pour démarrer.")
    try:
        donnees = yaml.safe_load(chemin.read_text(encoding="utf-8"))
    except yaml.YAMLError as erreur:
        raise ConfigInvalide(f"{chemin} n'est pas un YAML valide : {erreur}") from erreur
    return depuis_dict(donnees or {})


# ---------------------------------------------------------------- gestionnaire
class GestionnaireConfig:
    """Détient la configuration courante et la remplace d'un bloc.

    Le noyau appelle `courante` à chaque événement. Comme Config est
    immuable, un traitement en cours continue sur la version qu'il a lue :
    aucun verrou, et jamais de configuration à moitié appliquée.

    En cas de rechargement invalide, **l'ancienne configuration est
    conservée** et l'erreur remonte à l'appelant. Une faute de frappe dans
    l'interface ne doit jamais faire taire un bot qui fonctionnait.
    """

    def __init__(self, chemin: Path, config: Config | None = None) -> None:
        self.chemin = Path(chemin)
        self._config = config if config is not None else charger(self.chemin)
        self._version = 1

    @property
    def courante(self) -> Config:
        return self._config

    @property
    def version(self) -> int:
        """Incrémentée à chaque changement effectif. Sert au journal et à
        l'interface pour signaler « rechargé » sans comparer les objets."""
        return self._version

    def recharger(self) -> Config:
        """Relit le fichier. L'ancienne configuration survit à un échec."""
        nouvelle = charger(self.chemin)     # lève avant toute affectation
        if nouvelle != self._config:
            self._config = nouvelle
            self._version += 1
        return self._config

    def appliquer(self, **champs: Any) -> Config:
        """Modifie la configuration en mémoire et l'écrit sur disque.

        Chemin d'écriture de l'interface web. La validation a lieu AVANT
        l'écriture : un réglage refusé ne laisse pas un fichier corrompu
        derrière lui.
        """
        candidate = replace(self._config, **champs)
        valider(candidate)
        ecrire(self.chemin, candidate)
        self._config = candidate
        self._version += 1
        return candidate


def en_dict(config: Config) -> dict[str, Any]:
    return {
        "base_url": config.base_url,
        "twitch": {"chaine": config.twitch.chaine},
        "modele": {
            "fournisseur": config.modele.fournisseur,
            "url": config.modele.url,
            "nom": config.modele.nom,
            "plafond_jetons": config.modele.plafond_jetons,
            "temperature": config.modele.temperature,
            "reflexion": config.modele.reflexion,
        },
        "persona": config.persona + "\n",
        "conversation": {
            "contexte_messages": config.conversation.contexte_messages,
            "longueur_max": config.conversation.longueur_max,
        },
        "prise_de_parole": {
            "sur_mention": config.prise_de_parole.sur_mention,
            "sur_commande": config.prise_de_parole.sur_commande,
            "sur_alerte": config.prise_de_parole.sur_alerte,
            "spontanee": {
                "active": config.prise_de_parole.spontanee.active,
                "minutes_de_silence": config.prise_de_parole.spontanee.minutes_de_silence,
                "max_par_heure": config.prise_de_parole.spontanee.max_par_heure,
            },
            "max_messages_par_minute": config.prise_de_parole.max_messages_par_minute,
            "comptes_ignores": list(config.prise_de_parole.comptes_ignores),
        },
        "moderation": {
            "active": config.moderation.active,
            "mots_interdits": list(config.moderation.mots_interdits),
            "action": config.moderation.action,
            "duree_exclusion_secondes": config.moderation.duree_exclusion_secondes,
        },
        "journal": {"niveau": config.niveau_journal},
    }


def ecrire(chemin: Path, config: Config) -> None:
    """Écriture atomique : fichier temporaire puis remplacement.

    Sans cela, une coupure en pleine écriture laisserait un config.yaml
    tronqué — et une installation qui ne redémarre plus.
    """
    chemin = Path(chemin)
    temporaire = chemin.with_suffix(chemin.suffix + ".tmp")
    temporaire.write_text(
        yaml.safe_dump(en_dict(config), allow_unicode=True, sort_keys=False),
        encoding="utf-8")
    os.replace(temporaire, chemin)
