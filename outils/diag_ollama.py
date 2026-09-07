#!/usr/bin/env python3
"""
Bavardus — étape 1.7 : mesure de la latence réelle d'Ollama.

Objectif : savoir, chiffres en main, quel modèle tient l'objectif de 3 secondes
dans un chat Twitch. C'est le risque R2 du projet.

Aucune dépendance : uniquement la bibliothèque standard.

Utilisation :
    export OLLAMA_URL="http://192.168.0.139:11434"     # ou --url
    python test_ollama.py                               # teste tous les modèles installés
    python test_ollama.py --models mistral:7b,llama3.1:8b
    python test_ollama.py --tours 5

Ce qui est mesuré :
  - premier jeton : le délai avant que la réponse commence à arriver.
    C'est ce que perçoit réellement le spectateur.
  - total : jusqu'au dernier jeton, plafonné à 60 jetons comme en production (D5).
  - débit : jetons par seconde, utile pour comparer les modèles entre eux.

Le premier appel à un modèle inclut son chargement en VRAM et fausse la mesure :
un tour de chauffe est donc fait puis ignoré.
"""

import argparse
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.request

# Conditions réalistes : persona court, contexte de chat, réponse brève.
PERSONA = (
    "Tu es le bot d'une chaîne Twitch. Tu réponds en français, "
    "sur un ton complice et bref. Jamais plus d'une phrase."
)

CONTEXTE = [
    "viewer_12 : ça fait combien de temps que tu streames ce jeu ?",
    "kevin_ : lol il vient de mourir au même endroit",
    "mathgen44 : bon on retente une dernière fois",
]

QUESTION = "viewer_12 : @bot il en est à combien de morts là ?"

PLAFOND_JETONS = 60          # D5
OBJECTIF_SECONDES = 3.0      # critère de réussite n°3


def appel(url, chemin, charge=None, timeout=120):
    donnees = json.dumps(charge).encode() if charge is not None else None
    requete = urllib.request.Request(
        f"{url.rstrip('/')}{chemin}",
        data=donnees,
        headers={"Content-Type": "application/json"},
    )
    return urllib.request.urlopen(requete, timeout=timeout)


def modeles_installes(url):
    try:
        with appel(url, "/api/tags", timeout=15) as reponse:
            donnees = json.load(reponse)
    except urllib.error.URLError as erreur:
        print(f"Ollama injoignable sur {url} : {erreur}", file=sys.stderr)
        print("Vérifie l'URL, et qu'Ollama écoute bien sur le réseau "
              "(OLLAMA_HOST=0.0.0.0) et pas seulement en local.", file=sys.stderr)
        sys.exit(2)
    return [m["name"] for m in donnees.get("models", [])]


def un_tour(url, modele):
    """Un appel en flux. Retourne (premier_jeton, total, jetons, texte)."""
    charge = {
        "model": modele,
        "stream": True,
        "options": {"num_predict": PLAFOND_JETONS, "temperature": 0.7},
        "messages": [
            {"role": "system", "content": PERSONA},
            {"role": "user", "content": "\n".join(CONTEXTE + [QUESTION])},
        ],
    }

    depart = time.perf_counter()
    premier = None
    morceaux = []
    jetons_evalues = 0

    with appel(url, "/api/chat", charge) as reponse:
        for ligne in reponse:
            if not ligne.strip():
                continue
            bloc = json.loads(ligne)
            contenu = bloc.get("message", {}).get("content", "")
            if contenu and premier is None:
                premier = time.perf_counter() - depart
            morceaux.append(contenu)
            if bloc.get("done"):
                jetons_evalues = bloc.get("eval_count", 0)

    total = time.perf_counter() - depart
    return premier or total, total, jetons_evalues, "".join(morceaux).strip()


def mesurer(url, modele, tours):
    print(f"\n── {modele}")

    # B1 : les modèles d'embedding n'ont pas de point d'entrée de conversation
    # et renvoient un HTTP 400. On les écarte avant de perdre du temps dessus.
    if any(marqueur in modele.lower() for marqueur in ("embed", "bge-", "e5-")):
        print("   ignoré : modèle d'embedding, non conversationnel")
        return None

    try:
        print("   chauffe…", end="", flush=True)
        un_tour(url, modele)                     # chargement en VRAM, ignoré
        print(" fait")
    except urllib.error.HTTPError as erreur:
        if erreur.code == 400:
            print(" ignoré : ce modèle ne gère pas /api/chat (embedding ?)")
        else:
            print(f" échec : HTTP {erreur.code}")
        return None
    except Exception as erreur:
        print(f" échec : {erreur}")
        return None

    premiers, totaux, debits = [], [], []
    dernier_texte = ""

    for numero in range(1, tours + 1):
        try:
            premier, total, jetons, texte = un_tour(url, modele)
        except Exception as erreur:
            print(f"   tour {numero} : échec — {erreur}")
            continue
        premiers.append(premier)
        totaux.append(total)
        if total > 0 and jetons:
            debits.append(jetons / total)
        dernier_texte = texte
        print(f"   tour {numero} : premier jeton {premier:5.2f}s · total {total:5.2f}s · {jetons} jetons")

    if not totaux:
        return None

    if not dernier_texte:
        print("   ⚠️  réponse VIDE : modèle de raisonnement probable — les jetons sont")
        print("       partis dans la réflexion interne, rien n'est sorti. Voir D12.")

    resultat = {
        "modele": modele,
        "premier": statistics.median(premiers),
        "total": statistics.median(totaux),
        "debit": statistics.median(debits) if debits else 0.0,
        "exemple": dernier_texte,
    }
    print(f"   réponse : {dernier_texte[:160]}")
    return resultat


def main():
    analyseur = argparse.ArgumentParser(description="Mesure de latence Ollama (Bavardus, étape 1.7)")
    analyseur.add_argument("--url", default=os.environ.get("OLLAMA_URL", "http://localhost:11434"))
    analyseur.add_argument("--models", help="liste séparée par des virgules ; par défaut, tous les modèles installés")
    analyseur.add_argument("--tours", type=int, default=3)
    arguments = analyseur.parse_args()

    print(f"Ollama : {arguments.url}")
    disponibles = modeles_installes(arguments.url)
    if not disponibles:
        print("Aucun modèle installé sur cette instance.", file=sys.stderr)
        sys.exit(2)

    if arguments.models:
        cibles = [m.strip() for m in arguments.models.split(",")]
        inconnus = [m for m in cibles if m not in disponibles]
        if inconnus:
            print(f"Modèles absents : {', '.join(inconnus)}")
            print(f"Installés : {', '.join(disponibles)}")
    else:
        cibles = disponibles
        print(f"Modèles installés : {', '.join(disponibles)}")

    resultats = [r for r in (mesurer(arguments.url, m, arguments.tours) for m in cibles) if r]
    if not resultats:
        print("\nAucune mesure exploitable.")
        sys.exit(1)

    resultats.sort(key=lambda r: r["total"])
    print("\n" + "=" * 78)
    print(f"{'modèle':<28} {'1er jeton':>10} {'total':>8} {'jetons/s':>10}   verdict")
    print("-" * 78)
    for r in resultats:
        verdict = "✅ tenable" if r["total"] <= OBJECTIF_SECONDES else "⚠️  trop lent"
        print(f"{r['modele']:<28} {r['premier']:>9.2f}s {r['total']:>7.2f}s {r['debit']:>9.1f}   {verdict}")
    print("=" * 78)
    print(f"Objectif : réponse complète sous {OBJECTIF_SECONDES:.0f}s, plafond de {PLAFOND_JETONS} jetons (D5).")
    print("Médianes sur", arguments.tours, "tours, hors chauffe.")
    print("\nÀ reporter dans suivi_de_projet.MD, étape 1.7 et risque R2.")


if __name__ == "__main__":
    main()
