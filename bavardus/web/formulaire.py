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

from ..config import (Config, ConfigCommande, ConfigConversation, ConfigModele,
                      ConfigModeration, ConfigPriseDeParole, ConfigSpontanee,
                      ConfigTwitch, valider)


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


def lire_commandes(texte: str) -> tuple[ConfigCommande, ...]:
    """Une commande par ligne : `!nom | réponse | options`.

    Un tableau de formulaire aurait été plus joli et bien plus pénible à
    éditer : ici, ajouter une commande c'est ajouter une ligne, et le champ
    entier se copie-colle d'une instance à l'autre.

    Options acceptées, séparées par des virgules : `alias=dc/serveur`,
    `pour=moderateurs`, `cooldown=30`.
    """
    commandes = []
    for ligne in (texte or "").splitlines():
        ligne = ligne.strip()
        if not ligne or ligne.startswith("#"):
            continue
        parts = [p.strip() for p in ligne.split("|")]
        nom = parts[0].lstrip("!").lower()
        reponse = parts[1] if len(parts) > 1 else ""
        alias: tuple[str, ...] = ()
        pour, cooldown = "tous", 15

        for option in (parts[2].split(",") if len(parts) > 2 else []):
            option = option.strip()
            if "=" not in option:
                continue
            cle, valeur = (m.strip() for m in option.split("=", 1))
            if cle == "alias":
                alias = tuple(a.strip().lstrip("!").lower()
                              for a in valeur.replace("/", ",").split(",")
                              if a.strip())
            elif cle == "pour":
                pour = valeur.lower()
            elif cle in ("cooldown", "cooldown_secondes"):
                try:
                    cooldown = int(valeur)
                except ValueError:
                    pass

        commandes.append(ConfigCommande(nom=nom, reponse=reponse, alias=alias,
                                        pour=pour, cooldown_secondes=cooldown))
    return tuple(commandes)


def ecrire_commandes(commandes) -> str:
    """L'inverse, pour remplir le formulaire."""
    lignes = []
    for c in commandes:
        options = []
        if c.alias:
            options.append("alias=" + "/".join(c.alias))
        if c.pour != "tous":
            options.append(f"pour={c.pour}")
        if c.cooldown_secondes != 15:
            options.append(f"cooldown={c.cooldown_secondes}")
        ligne = f"!{c.nom} | {c.reponse}"
        if options:
            ligne += " | " + ", ".join(options)
        lignes.append(ligne)
    return "\n".join(lignes)


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
        commandes=(lire_commandes(str(donnees["commandes"]))
                   if "commandes" in donnees else config.commandes),
        commandes_inconnues_au_modele=_bool(donnees, "commandes_inconnues_au_modele"),
    )
    valider(candidate)          # avant toute écriture sur disque
    return candidate
