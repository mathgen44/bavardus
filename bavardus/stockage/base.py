"""Base SQLite : historique du chat, journal des décisions, statistiques.

Trois usages, un seul fichier, aucun service externe — l'installation doit
tenir dans un volume Docker qu'on sauvegarde en le copiant.

Le **journal des décisions** mérite un mot : il enregistre, pour chaque
événement reçu, si le bot a parlé et *pourquoi*. Sans lui, un bot jugé trop
bavard ou anormalement muet ne se diagnostique qu'en relisant le code. Avec
lui, l'interface répond à la question en une ligne.

`sqlite3` de la bibliothèque standard, appelé via `asyncio.to_thread` : pas
de dépendance supplémentaire, et les écritures ne bloquent pas la boucle.
"""

from __future__ import annotations

import asyncio
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    horodatage   REAL    NOT NULL,
    auteur       TEXT    NOT NULL,
    auteur_id    TEXT    NOT NULL DEFAULT '',
    texte        TEXT    NOT NULL,
    du_bot       INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_messages_horodatage ON messages(horodatage);

CREATE TABLE IF NOT EXISTS decisions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    horodatage   REAL    NOT NULL,
    evenement    TEXT    NOT NULL,   -- chat, alerte, minuterie
    repondu      INTEGER NOT NULL,
    raison       TEXT    NOT NULL,   -- G17 : toujours renseignée
    detail       TEXT    NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_decisions_horodatage ON decisions(horodatage);

CREATE TABLE IF NOT EXISTS appels_modele (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    horodatage   REAL    NOT NULL,
    modele       TEXT    NOT NULL,
    latence_ms   INTEGER NOT NULL,
    jetons       INTEGER,
    vide         INTEGER NOT NULL DEFAULT 0,
    cause_vide   TEXT    NOT NULL DEFAULT ''   -- G14
);
CREATE INDEX IF NOT EXISTS idx_appels_horodatage ON appels_modele(horodatage);
"""


@dataclass(slots=True)
class Message:
    horodatage: float
    auteur: str
    texte: str
    auteur_id: str = ""
    du_bot: bool = False


class Base:
    def __init__(self, chemin: Path) -> None:
        self.chemin = Path(chemin)
        self._connexion: sqlite3.Connection | None = None

    # ------------------------------------------------------------- cycle de vie
    def ouvrir(self) -> None:
        self.chemin.parent.mkdir(parents=True, exist_ok=True)
        self._connexion = sqlite3.connect(
            self.chemin, check_same_thread=False, isolation_level=None)
        self._connexion.row_factory = sqlite3.Row
        # WAL : les lectures de l'interface web ne bloquent pas les écritures
        # du bot. Sans cela, consulter le journal en direct pendant un live
        # ferait attendre l'émetteur.
        self._connexion.execute("PRAGMA journal_mode=WAL")
        self._connexion.execute("PRAGMA synchronous=NORMAL")
        self._connexion.executescript(SCHEMA)

    def fermer(self) -> None:
        if self._connexion is not None:
            self._connexion.close()
            self._connexion = None

    @property
    def connexion(self) -> sqlite3.Connection:
        if self._connexion is None:
            raise RuntimeError("base non ouverte : appeler ouvrir() d'abord")
        return self._connexion

    def _ecrire(self, requete: str, parametres: tuple) -> None:
        self.connexion.execute(requete, parametres)

    async def _ecrire_async(self, requete: str, parametres: tuple) -> None:
        await asyncio.to_thread(self._ecrire, requete, parametres)

    # ---------------------------------------------------------------- messages
    async def ajouter_message(self, message: Message) -> None:
        await self._ecrire_async(
            "INSERT INTO messages (horodatage, auteur, auteur_id, texte, du_bot)"
            " VALUES (?, ?, ?, ?, ?)",
            (message.horodatage, message.auteur, message.auteur_id,
             message.texte, int(message.du_bot)))

    def contexte(self, limite: int) -> list[Message]:
        """Les `limite` derniers messages, du plus ancien au plus récent.

        Ordre chronologique : c'est celui qu'attend un modèle de langage.
        """
        if limite <= 0:
            return []
        lignes = self.connexion.execute(
            "SELECT horodatage, auteur, auteur_id, texte, du_bot FROM messages"
            " ORDER BY id DESC LIMIT ?", (limite,)).fetchall()
        return [Message(horodatage=l["horodatage"], auteur=l["auteur"],
                        auteur_id=l["auteur_id"], texte=l["texte"],
                        du_bot=bool(l["du_bot"]))
                for l in reversed(lignes)]

    def secondes_depuis_dernier_message(self, *, humains_seulement: bool = True) -> float | None:
        """Silence du chat, pour la prise de parole spontanée.

        `humains_seulement` par défaut : sans cela, le bot se répondrait à
        lui-même indéfiniment, chacune de ses relances repoussant le compteur.
        """
        requete = "SELECT MAX(horodatage) AS dernier FROM messages"
        if humains_seulement:
            requete += " WHERE du_bot = 0"
        ligne = self.connexion.execute(requete).fetchone()
        if ligne is None or ligne["dernier"] is None:
            return None
        return time.time() - float(ligne["dernier"])

    # --------------------------------------------------------------- décisions
    async def journaliser_decision(self, evenement: str, repondu: bool,
                                   raison: str, detail: str = "") -> None:
        """G17 : aucune décision n'est enregistrée sans sa raison."""
        if not raison:
            raise ValueError("une décision sans raison est inexploitable (G17)")
        await self._ecrire_async(
            "INSERT INTO decisions (horodatage, evenement, repondu, raison, detail)"
            " VALUES (?, ?, ?, ?, ?)",
            (time.time(), evenement, int(repondu), raison, detail))

    def dernieres_decisions(self, limite: int = 50,
                            apres_id: int = 0) -> list[dict]:
        """Les plus récentes d'abord, ou celles postérieures à `apres_id`.

        `apres_id` sert au flux en direct de l'interface : on n'envoie que
        ce qui est nouveau, sans relire ni retransmettre tout l'historique
        à chaque battement.
        """
        if apres_id:
            lignes = self.connexion.execute(
                "SELECT id, horodatage, evenement, repondu, raison, detail"
                " FROM decisions WHERE id > ? ORDER BY id ASC LIMIT ?",
                (apres_id, limite)).fetchall()
        else:
            lignes = self.connexion.execute(
                "SELECT id, horodatage, evenement, repondu, raison, detail"
                " FROM decisions ORDER BY id DESC LIMIT ?", (limite,)).fetchall()
        return [dict(l) for l in lignes]

    def dernier_id_decision(self) -> int:
        ligne = self.connexion.execute(
            "SELECT MAX(id) AS dernier FROM decisions").fetchone()
        return int(ligne["dernier"] or 0)

    # ----------------------------------------------------------------- modèle
    async def journaliser_appel(self, modele: str, latence_ms: int,
                                jetons: int | None = None, vide: bool = False,
                                cause_vide: str = "") -> None:
        await self._ecrire_async(
            "INSERT INTO appels_modele (horodatage, modele, latence_ms, jetons,"
            " vide, cause_vide) VALUES (?, ?, ?, ?, ?, ?)",
            (time.time(), modele, latence_ms, jetons, int(vide), cause_vide))

    def statistiques(self, depuis_secondes: float = 3600) -> dict:
        """Chiffres de santé. Le taux de réponses vides est le plus parlant :
        s'il grimpe, le mode réflexion s'est rallumé quelque part (R15)."""
        seuil = time.time() - depuis_secondes
        ligne = self.connexion.execute(
            "SELECT COUNT(*) AS appels, AVG(latence_ms) AS latence_moyenne,"
            " MAX(latence_ms) AS latence_max, SUM(vide) AS vides"
            " FROM appels_modele WHERE horodatage >= ?", (seuil,)).fetchone()
        decisions = self.connexion.execute(
            "SELECT COUNT(*) AS total, SUM(repondu) AS repondus"
            " FROM decisions WHERE horodatage >= ?", (seuil,)).fetchone()
        appels = ligne["appels"] or 0
        return {
            "appels_modele": appels,
            "latence_moyenne_ms": round(ligne["latence_moyenne"] or 0),
            "latence_max_ms": ligne["latence_max"] or 0,
            "reponses_vides": ligne["vides"] or 0,
            "taux_vides": round((ligne["vides"] or 0) / appels, 3) if appels else 0.0,
            "evenements": decisions["total"] or 0,
            "reponses_envoyees": decisions["repondus"] or 0,
        }

    def messages_bot_depuis(self, secondes: float) -> int:
        """Sert aux garde-fous de débit (max par minute, max par heure)."""
        seuil = time.time() - secondes
        ligne = self.connexion.execute(
            "SELECT COUNT(*) AS n FROM messages WHERE du_bot = 1 AND horodatage >= ?",
            (seuil,)).fetchone()
        return int(ligne["n"] or 0)

    async def purger(self, jours: int = 30) -> None:
        """Le chat d'un live génère beaucoup de lignes ; sans purge, le volume
        Docker enfle indéfiniment sur une installation qu'on oublie."""
        seuil = time.time() - jours * 86400
        for table in ("messages", "decisions", "appels_modele"):
            await self._ecrire_async(
                f"DELETE FROM {table} WHERE horodatage < ?", (seuil,))
