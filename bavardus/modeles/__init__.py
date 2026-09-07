"""Fournisseurs de modèles. Un seul point d'entrée : `construire`."""

from __future__ import annotations

from .base import Echange, ErreurModele, Modele, Reponse
from .compatible_openai import ModeleCompatibleOpenAI
from .ollama import ModeleOllama

__all__ = ["Echange", "ErreurModele", "Modele", "Reponse",
           "ModeleOllama", "ModeleCompatibleOpenAI", "construire"]


def construire(config, cle_api: str = "") -> Modele:
    """Fabrique le connecteur décrit par la configuration (D13).

    C'est le seul endroit du moteur qui sait qu'Ollama et OpenRouter
    existent. Ajouter un fournisseur, c'est ajouter un fichier et une ligne
    ici — rien d'autre ne bouge.
    """
    if config.fournisseur == "ollama":
        return ModeleOllama(config.url, config.nom, reflexion=config.reflexion)
    if config.fournisseur == "compatible_openai":
        return ModeleCompatibleOpenAI(config.url, config.nom, cle_api=cle_api,
                                      reflexion=config.reflexion)
    raise ValueError(f"fournisseur inconnu : {config.fournisseur!r}")
