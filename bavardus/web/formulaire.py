"""Conversion d'un formulaire de réglages en Config (D21).

Fonction pure, isolée des routes : c'est ici que se joue la correction des
réglages, et cela doit se tester sans serveur.

Le principe : **partir de la configuration courante et n'écraser que ce que
le formulaire porte**. Une page qui n'expose pas un champ ne doit pas le
remettre à zéro en silence — c'est ainsi qu'on perd un réglage édité à la
main dans `config.yaml`.
"""

from __future__ import annotations

from dataclasses import replace

from ..config import (Config, ConfigConversation, ConfigModele, ConfigModeration,
                      ConfigPriseDeParole, ConfigSpontanee, ConfigTwitch, valider)


def _bool(donnees, cle: str) -> bool:
    """Une case décochée n'est pas transmise par le navigateur : son absence
    vaut faux, et c'est le seul moyen de la distinguer."""
    return donnees.get(cle) in ("on", "true", "1", "oui")


def _entier(donnees, cle: str, defaut: int) -> int:
    try:
        return int(str(donnees.get(cle, defaut)).strip())
    except (TypeError, ValueError):
        return defaut


def _decimal(donnees, cle: str, defaut: float) -> float:
    try:
        return float(str(donnees.get(cle, defaut)).strip().replace(",", "."))
    except (TypeError, ValueError):
        return defaut


def _liste(valeur: str) -> tuple[str, ...]:
    """Accepte une liste séparée par virgules ou retours à la ligne."""
    if not valeur:
        return ()
    brut = valeur.replace(",", "\n").splitlines()
    return tuple(sorted({m.strip().lower() for m in brut if m.strip()}))


def appliquer_formulaire(config: Config, donnees) -> Config:
    """Retourne une nouvelle Config. Lève ConfigInvalide si elle ne tient pas."""
    modele = ConfigModele(
        fournisseur=str(donnees.get("fournisseur", config.modele.fournisseur)),
        url=str(donnees.get("url_modele", config.modele.url)).strip(),
        nom=str(donnees.get("nom_modele", config.modele.nom)).strip(),
        plafond_jetons=_entier(donnees, "plafond_jetons",
                               config.modele.plafond_jetons),
        temperature=_decimal(donnees, "temperature", config.modele.temperature),
        reflexion=_bool(donnees, "reflexion"),
    )
    conversation = ConfigConversation(
        contexte_messages=_entier(donnees, "contexte_messages",
                                  config.conversation.contexte_messages),
        longueur_max=_entier(donnees, "longueur_max",
                             config.conversation.longueur_max),
    )
    parole = ConfigPriseDeParole(
        sur_mention=_bool(donnees, "sur_mention"),
        sur_commande=_bool(donnees, "sur_commande"),
        sur_alerte=_bool(donnees, "sur_alerte"),
        spontanee=ConfigSpontanee(
            active=_bool(donnees, "spontanee_active"),
            minutes_de_silence=_entier(
                donnees, "minutes_de_silence",
                config.prise_de_parole.spontanee.minutes_de_silence),
            max_par_heure=_entier(
                donnees, "max_par_heure",
                config.prise_de_parole.spontanee.max_par_heure),
        ),
        max_messages_par_minute=_entier(
            donnees, "max_messages_par_minute",
            config.prise_de_parole.max_messages_par_minute),
        comptes_ignores=_liste(str(donnees.get("comptes_ignores", ""))),
    )
    moderation = ConfigModeration(
        active=_bool(donnees, "moderation_active"),
        mots_interdits=_liste(str(donnees.get("mots_interdits", ""))),
        action=str(donnees.get("action_moderation", config.moderation.action)),
        duree_exclusion_secondes=_entier(
            donnees, "duree_exclusion_secondes",
            config.moderation.duree_exclusion_secondes),
    )

    candidate = replace(
        config,
        twitch=ConfigTwitch(chaine=str(donnees.get(
            "chaine", config.twitch.chaine)).strip().lower()),
        modele=modele,
        persona=str(donnees.get("persona", config.persona)).strip(),
        conversation=conversation,
        prise_de_parole=parole,
        moderation=moderation,
    )
    valider(candidate)          # avant toute écriture sur disque
    return candidate
