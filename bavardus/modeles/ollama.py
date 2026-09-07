"""Connecteur Ollama, via l'API native `/api/chat`.

**Pourquoi pas `/v1` malgré D13 ?** Parce que le point d'entrée compatible
OpenAI d'Ollama ignore `think: false` (B3). Un modèle récent y consomme alors
la totalité du plafond de 60 jetons en réflexion interne et ne produit pas un
mot (R15) — un bon modèle passe pour un modèle cassé. Seule `/api/chat`
honore le drapeau, d'où l'exception assumée de D16, confinée à ce fichier.
"""

from __future__ import annotations

import time

import httpx

from .base import Echange, ErreurModele, Reponse, diagnostiquer_vide


class ModeleOllama:
    def __init__(self, url: str, nom: str, *, reflexion: bool = False,
                 delai: float = 60.0) -> None:
        self.racine = self._racine(url)
        self.nom = nom
        self.reflexion = reflexion
        self.delai = delai

    @staticmethod
    def _racine(url: str) -> str:
        """Accepte indifféremment http://hote:11434 et .../v1.

        Beaucoup d'utilisateurs colleront l'URL compatible OpenAI trouvée
        dans un tutoriel. Plutôt que d'échouer, on retire le /v1 : c'est
        exactement l'erreur que D16 rend fatale, autant l'absorber ici.
        """
        racine = url.rstrip("/")
        if racine.endswith("/v1"):
            racine = racine[:-3]
        return racine

    async def produire(self, systeme: str, echanges: list[Echange],
                       plafond_jetons: int, temperature: float) -> Reponse:
        charge = {
            "model": self.nom,
            "stream": False,
            "think": self.reflexion,          # D16
            "options": {"num_predict": plafond_jetons, "temperature": temperature},
            "messages": ([{"role": "system", "content": systeme}] if systeme else [])
                        + [{"role": e.role, "content": e.contenu} for e in echanges],
        }
        depart = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self.delai) as client:
                reponse = await client.post(f"{self.racine}/api/chat", json=charge)
        except httpx.HTTPError as erreur:
            raise ErreurModele(f"Ollama injoignable sur {self.racine} : {erreur}") from erreur
        latence = int((time.perf_counter() - depart) * 1000)

        if reponse.status_code != 200:
            raise ErreurModele(
                f"Ollama a refusé la requête (HTTP {reponse.status_code}) : "
                f"{reponse.text[:200]}")

        bloc = reponse.json()
        message = bloc.get("message") or {}
        texte = (message.get("content") or "").strip()
        reflexion = message.get("thinking") or ""

        if texte:
            return Reponse(texte=texte, latence_ms=latence,
                           jetons=bloc.get("eval_count"),
                           reflexion_detectee=bool(reflexion), brut=bloc)

        return Reponse(
            cause_vide=diagnostiquer_vide(
                raison_arret=bloc.get("done_reason", ""),
                reflexion=reflexion,
                jetons_sortis=bloc.get("eval_count"),
                plafond=plafond_jetons),
            latence_ms=latence, jetons=bloc.get("eval_count"),
            reflexion_detectee=bool(reflexion), brut=bloc)

    async def disponible(self) -> tuple[bool, str]:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                reponse = await client.get(f"{self.racine}/api/tags")
            if reponse.status_code != 200:
                return False, f"Ollama répond HTTP {reponse.status_code}"
            noms = [m["name"] for m in reponse.json().get("models", [])]
            if self.nom not in noms:
                return False, (f"le modèle « {self.nom} » n'est pas installé sur "
                               f"{self.racine} — disponibles : {', '.join(noms) or 'aucun'}. "
                               f"Le tirer avec : ollama pull {self.nom}")
            return True, f"Ollama joignable, « {self.nom} » présent"
        except httpx.HTTPError as erreur:
            return False, f"Ollama injoignable sur {self.racine} : {erreur}"
