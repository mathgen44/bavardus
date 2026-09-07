"""Modération automatique : détection et sanction.

**Ce module décide, il n'agit pas.** Comme le Décideur, il est de la logique
pure : on lui passe un message et une configuration, il retourne une sanction
ou rien. C'est ce qui permet de le tester exhaustivement — et sur une
fonction qui peut exclure un spectateur, ce n'est pas un luxe.

**Limite à connaître, et à assumer.** La détection porte sur des mots
entiers, après normalisation de la casse et des accents. Elle n'essaie pas
de déjouer les contournements (`c0n`, `c.o.n`, caractères Unicode
ressemblants) : une détection agressive produit des faux positifs, et un bot
qui exclut un spectateur innocent fait plus de dégâts qu'un mot grossier
passé au travers. Pour une modération sérieuse, AutoMod de Twitch reste
l'outil de référence ; celui-ci couvre une liste de mots précise que le
diffuseur veut bannir de sa chaîne.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

ACTIONS = ("supprimer", "avertir", "exclure")

FICHIER_EXEMPLE = "moderation.exemple.txt"


def liste_exemple(racine) -> tuple[str, ...]:
    """La liste de départ livrée avec le projet.

    Volontairement centrée sur le spam et les arnaques de viewers : les
    catégories générales (insultes identitaires, harcèlement) relèvent
    d'AutoMod, qui les traite par thème et par niveau, tient compte du
    contexte et se met à jour tout seul. Une liste de mots ne le remplace
    pas — elle couvre ce qui est propre à une chaîne.
    """
    from pathlib import Path

    chemin = Path(racine) / FICHIER_EXEMPLE
    if not chemin.exists():
        return ()
    lignes = chemin.read_text(encoding="utf-8").splitlines()
    return tuple(l.strip() for l in lignes
                 if l.strip() and not l.strip().startswith("#"))


@dataclass(frozen=True, slots=True)
class Sanction:
    action: str
    motif: str
    mot: str = ""


# L'apostrophe française marque une élision : « espèce d'idiot » contient
# bien le mot « idiot », et la traiter comme une lettre le rendrait
# indétectable. Le trait d'union, lui, unit (« porte-parole » est un mot).
APOSTROPHES = "'\u2019\u2018\u00b4`"


def normaliser(texte: str) -> str:
    """Minuscules, sans accents, apostrophes converties en espaces.

    On ne va pas plus loin. Retirer toute la ponctuation interne
    permettrait d'attraper « c-o-n », mais couperait « porte-parole » en
    deux et multiplierait les faux positifs. On préfère laisser passer un
    contournement qu'exclure quelqu'un à tort.
    """
    sans_accents = unicodedata.normalize("NFD", texte.lower())
    nu = "".join(c for c in sans_accents if unicodedata.category(c) != "Mn")
    for apostrophe in APOSTROPHES:
        nu = nu.replace(apostrophe, " ")
    return nu


def mots(texte: str) -> list[str]:
    return re.findall(r"[0-9a-z]+(?:-[0-9a-z]+)*", normaliser(texte))


def mot_interdit(texte: str, interdits) -> str:
    """Retourne le premier mot interdit trouvé, ou une chaîne vide.

    Une entrée contenant une espace est cherchée comme expression exacte
    dans le texte normalisé : cela permet d'interdire une locution sans
    interdire chacun de ses mots pris séparément.
    """
    if not interdits:
        return ""
    presents = set(mots(texte))
    normalise = normaliser(texte)
    for interdit in interdits:
        cible = normaliser(interdit).strip()
        if not cible:
            continue
        if " " in cible:
            if cible in normalise:
                return interdit
        elif cible in presents:
            return interdit
    return ""


def examiner(evenement, config, *, id_diffuseur: str = "",
             id_bot: str = "") -> Sanction | None:
    """La sanction à appliquer, ou None.

    **Le diffuseur n'est jamais modéré**, ni le bot lui-même, ni les comptes
    déclarés ignorés. Un bot qui exclut le streamer de son propre chat est
    une catastrophe que personne ne pardonne, et c'est arrivé à d'autres.
    """
    if not config.moderation.active:
        return None
    if not config.moderation.mots_interdits:
        return None

    auteur = (getattr(evenement, "auteur", "") or "").lower()
    auteur_id = str(getattr(evenement, "auteur_id", "") or "")

    if id_diffuseur and auteur_id == str(id_diffuseur):
        return None
    if id_bot and auteur_id == str(id_bot):
        return None
    if auteur in config.prise_de_parole.comptes_ignores:
        return None

    trouve = mot_interdit(getattr(evenement, "texte", ""),
                          config.moderation.mots_interdits)
    if not trouve:
        return None

    return Sanction(action=config.moderation.action,
                    motif=f"mot interdit : « {trouve} »", mot=trouve)
