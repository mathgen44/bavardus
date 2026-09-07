"""Connecteur pour toute passerelle parlant le protocole OpenAI (D13).

OpenRouter, Larbinus, un vLLM local : le même code les interroge tous. Seuls
changent l'URL de base, la clé et le nom du modèle.

Sur la réflexion : ce protocole n'a pas de commutateur universel. On envoie
les deux formes connues (`reasoning_effort` côté modèles OpenAI récents,
`reasoning` côté OpenRouter) ; un fournisseur qui ne les connaît pas les
ignore. Si malgré tout les réponses reviennent vides, c'est le diagnostic de
`cause_vide` qui le dira — et sur Ollama, la réponse est d'utiliser le
connecteur natif (D16).
"""

from __future__ import annotations

import time

import httpx

from .base import Echange, ErreurModele, Reponse, diagnostiquer_vide


class ModeleCompatibleOpenAI:
    def __init__(self, url: str, nom: str, *, cle_api: str = "",
                 reflexion: bool = False, delai: float = 60.0) -> None:
        self.base = url.rstrip("/")
        if not self.base.endswith("/v1"):
            self.base += "/v1"
        self.nom = nom
        self.cle_api = cle_api
        self.reflexion = reflexion
        self.delai = delai

    def _entetes(self) -> dict[str, str]:
        entetes = {"Content-Type": "application/json"}
        if self.cle_api:
            entetes["Authorization"] = f"Bearer {self.cle_api}"
        return entetes

    async def produire(self, systeme: str, echanges: list[Echange],
                       plafond_jetons: int, temperature: float) -> Reponse:
        charge: dict = {
            "model": self.nom,
            "max_tokens": plafond_jetons,
            "temperature": temperature,
            "messages": ([{"role": "system", "content": systeme}] if systeme else [])
                        + [{"role": e.role, "content": e.contenu} for e in echanges],
        }
        if not self.reflexion:
            charge["reasoning_effort"] = "none"
            charge["reasoning"] = {"enabled": False}

        depart = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self.delai) as client:
                reponse = await client.post(f"{self.base}/chat/completions",
                                            json=charge, headers=self._entetes())
        except httpx.HTTPError as erreur:
            raise ErreurModele(f"fournisseur injoignable sur {self.base} : {erreur}") from erreur
        latence = int((time.perf_counter() - depart) * 1000)

        if reponse.status_code != 200:
            raise ErreurModele(
                f"le fournisseur a refusé la requête (HTTP {reponse.status_code}) : "
                f"{reponse.text[:200]}")

        bloc = reponse.json()
        choix = (bloc.get("choices") or [{}])[0]
        message = choix.get("message") or {}
        texte = (message.get("content") or "").strip()
        # Selon les passerelles : "reasoning", "reasoning_content"…
        reflexion = message.get("reasoning") or message.get("reasoning_content") or ""
        jetons = (bloc.get("usage") or {}).get("completion_tokens")

        if texte:
            return Reponse(texte=texte, latence_ms=latence, jetons=jetons,
                           reflexion_detectee=bool(reflexion), brut=bloc)

        return Reponse(
            cause_vide=diagnostiquer_vide(
                raison_arret=choix.get("finish_reason", ""),
                reflexion=reflexion, jetons_sortis=jetons, plafond=plafond_jetons),
            latence_ms=latence, jetons=jetons,
            reflexion_detectee=bool(reflexion), brut=bloc)

    async def disponible(self) -> tuple[bool, str]:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                reponse = await client.get(f"{self.base}/models", headers=self._entetes())
            if reponse.status_code == 401:
                return False, "clé d'API refusée (HTTP 401)"
            if reponse.status_code != 200:
                return False, f"le fournisseur répond HTTP {reponse.status_code}"
            noms = [m.get("id") for m in reponse.json().get("data", [])]
            if noms and self.nom not in noms:
                return True, (f"joignable, mais « {self.nom} » n'apparaît pas dans la "
                              f"liste des modèles — à vérifier si les réponses échouent")
            return True, f"fournisseur joignable, « {self.nom} » disponible"
        except httpx.HTTPError as erreur:
            return False, f"fournisseur injoignable sur {self.base} : {erreur}"
