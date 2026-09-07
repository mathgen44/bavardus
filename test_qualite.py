#!/usr/bin/env python3
"""
Bavardus — étape 1.9 : comparaison qualitative des modèles.

La latence n'est plus le facteur limitant (étape 1.7). Ce qui reste à trancher,
c'est la QUALITÉ : quel modèle tient le persona, reste bref, répond en français,
n'invente pas de faits et ne récite pas ses consignes.

Ce script n'a pas de verdict automatique. Il pose les mêmes six situations à
chaque modèle et affiche les réponses côte à côte. C'est toi qui juges.

Il parle le protocole compatible OpenAI (`/v1/chat/completions`), donc le même
code interroge indifféremment Ollama, OpenRouter ou Larbinus (D13). Seuls
changent l'URL de base, la clé et le nom du modèle.

Aucune dépendance : bibliothèque standard uniquement.

Utilisation :
    # Ollama local
    python test_qualite.py --api-base http://192.168.0.139:11434/v1 \\
                           --models llama3.2:latest,mistral:latest

    # OpenRouter
    export OPENROUTER_API_KEY="sk-or-..."
    python test_qualite.py --api-base https://openrouter.ai/api/v1 \\
                           --models google/gemini-2.5-flash-lite,anthropic/claude-haiku-4.5

    # Lister les modèles disponibles contenant un mot
    python test_qualite.py --api-base https://openrouter.ai/api/v1 --list haiku

La clé se lit dans --api-key, OPENROUTER_API_KEY ou LLM_API_KEY.
Ne la mets jamais en dur dans un fichier suivi par git (G5).
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

PLAFOND_JETONS = 60          # D5

PERSONA = (
    "Tu es le bot d'une chaîne Twitch, complice et taquin. "
    "Tu réponds en français, en UNE phrase courte, jamais plus. "
    "Tu n'inventes JAMAIS de chiffre ni de fait sur le live : "
    "si tu ne sais pas, tu le dis ou tu esquives avec humour. "
    "Tu n'utilises pas de hashtags et tu ne te présentes pas."
)

# Chaque situation teste un comportement précis.
SITUATIONS = [
    {
        "nom": "Question simple adressée au bot",
        "cherche": "réponse brève, en français, dans le ton",
        "messages": [
            "kevin_ : ce boss est impossible",
            "viewer_12 : @bot tu penses qu'il y arrive cette fois ?",
        ],
    },
    {
        "nom": "PIÈGE — fait que le bot ne peut pas connaître (R11)",
        "cherche": "il doit ADMETTRE ne pas savoir, surtout pas inventer un chiffre",
        "messages": [
            "viewer_12 : @bot il en est à combien de morts depuis le début du stream ?",
        ],
    },
    {
        "nom": "Remerciement de don",
        "cherche": "chaleureux, court, sans surjouer",
        "messages": [
            "[événement] don de 5 € de kevin_, message : « continue comme ça »",
            "[consigne] remercie kevin_",
        ],
    },
    {
        "nom": "Provocation légère",
        "cherche": "ne mord pas à l'hameçon, reste léger, ne s'excuse pas platement",
        "messages": [
            "troll_99 : @bot t'es nul, un vrai bot de pauvre",
        ],
    },
    {
        "nom": "Message qui ne lui est pas adressé",
        "cherche": "IDÉALEMENT il ne dit rien — voir si le modèle sait se taire",
        "messages": [
            "kevin_ : quelqu'un sait quelle heure il est ?",
            "[consigne] si ce message ne te concerne pas, réponds exactement : RIEN",
        ],
    },
    {
        "nom": "Prise de parole spontanée après un silence",
        "cherche": "relance naturelle, sans inventer de contexte",
        "messages": [
            "[contexte] le chat est silencieux depuis 5 minutes, le streamer joue",
            "[consigne] lance une remarque courte pour relancer le chat",
        ],
    },
]


def entetes(cle):
    valeurs = {"Content-Type": "application/json"}
    if cle:
        valeurs["Authorization"] = f"Bearer {cle}"
        # Recommandé par OpenRouter pour identifier l'application appelante.
        valeurs["HTTP-Referer"] = "https://github.com/mathgen44/Bavardus"
        valeurs["X-Title"] = "Bavardus"
    return valeurs


def lister(api_base, cle, filtre):
    requete = urllib.request.Request(f"{api_base.rstrip('/')}/models", headers=entetes(cle))
    with urllib.request.urlopen(requete, timeout=60) as reponse:
        donnees = json.load(reponse)
    noms = sorted(m.get("id", "") for m in donnees.get("data", []))
    retenus = [n for n in noms if filtre.lower() in n.lower()] if filtre else noms
    print(f"{len(retenus)} modèle(s) sur {len(noms)} :")
    for nom in retenus:
        print(f"  {nom}")


def demander_natif(api_base, modele, messages, plafond, sans_reflexion, debug):
    """API native d'Ollama : seul chemin où "think": false est réellement pris en compte."""
    racine = api_base.rstrip("/")
    if racine.endswith("/v1"):
        racine = racine[:-3]

    charge = {
        "model": modele,
        "stream": False,
        "think": not sans_reflexion,
        "options": {"num_predict": plafond, "temperature": 0.7},
        "messages": [
            {"role": "system", "content": PERSONA},
            {"role": "user", "content": "\n".join(messages)},
        ],
    }
    requete = urllib.request.Request(
        f"{racine}/api/chat",
        data=json.dumps(charge).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(requete, timeout=180) as reponse:
        bloc = json.load(reponse)

    message = bloc.get("message", {}) or {}
    texte = (message.get("content") or "").strip()
    if texte:
        return texte, ""

    reflexion = message.get("thinking") or ""
    morceaux = [f"done_reason={bloc.get('done_reason')}", f"jetons sortis={bloc.get('eval_count')}"]
    if reflexion:
        morceaux.append(f"réflexion de {len(reflexion)} caractères — think:false sans effet sur ce modèle")
    if debug:
        morceaux.append("\n      brut : " + json.dumps(bloc, ensure_ascii=False)[:800])
    return "", " · ".join(morceaux)


def demander(api_base, cle, modele, messages, plafond=PLAFOND_JETONS,
             sans_reflexion=False, debug=False):
    """Retourne (texte, diagnostic). diagnostic est non vide quand la réponse l'est."""
    charge = {
        "model": modele,
        "max_tokens": plafond,
        "temperature": 0.7,
        "messages": [
            {"role": "system", "content": PERSONA},
            {"role": "user", "content": "\n".join(messages)},
        ],
    }
    if sans_reflexion:
        # B3 : sur le point d'entrée /v1 d'Ollama, "think" est ignoré. Le seul
        # levier est reasoning_effort ("none" coupe la réflexion). Certains
        # modèles (gemma4) ne le respectent pas non plus : utiliser --native.
        charge["reasoning_effort"] = "none"
        # OpenRouter : forme documentée côté passerelle.
        charge["reasoning"] = {"enabled": False}

    requete = urllib.request.Request(
        f"{api_base.rstrip('/')}/chat/completions",
        data=json.dumps(charge).encode(),
        headers=entetes(cle),
    )
    with urllib.request.urlopen(requete, timeout=180) as reponse:
        bloc = json.load(reponse)

    choix = bloc.get("choices", [{}])[0]
    message = choix.get("message", {}) or {}
    texte = (message.get("content") or "").strip()

    if texte:
        return texte, ""

    # Réponse vide : on explique POURQUOI au lieu d'afficher un simple <VIDE>.
    # C'est le seul moyen de distinguer un modèle qui réfléchit d'un modèle
    # qui échoue, et le bot devra faire la même distinction en production.
    raison = choix.get("finish_reason")
    champs = [c for c in message if c not in ("role", "content")]
    reflexion = message.get("reasoning") or message.get("reasoning_content") or message.get("thinking") or ""
    usage = bloc.get("usage", {})

    morceaux = [f"finish_reason={raison}"]
    if champs:
        morceaux.append(f"autres champs={champs}")
    if usage:
        morceaux.append(f"jetons sortis={usage.get('completion_tokens')}")
    if reflexion:
        morceaux.append(f"réflexion de {len(reflexion)} caractères : « {reflexion[:120].strip()}… »")

    if debug:
        morceaux.append("\n      brut : " + json.dumps(bloc, ensure_ascii=False)[:800])

    return "", " · ".join(morceaux)


def main():
    analyseur = argparse.ArgumentParser(description="Comparaison qualitative des modèles (Bavardus, étape 1.9)")
    analyseur.add_argument("--api-base", default=os.environ.get("LLM_API_BASE", "http://localhost:11434/v1"),
                           help="URL compatible OpenAI, terminée par /v1")
    analyseur.add_argument("--api-key", default=os.environ.get("OPENROUTER_API_KEY") or os.environ.get("LLM_API_KEY"))
    analyseur.add_argument("--models", help="liste séparée par des virgules")
    analyseur.add_argument("--list", dest="filtre", nargs="?", const="", help="lister les modèles disponibles")
    analyseur.add_argument("--tours", type=int, default=1, help="répétitions par situation, pour juger la constance")
    analyseur.add_argument("--max-tokens", type=int, default=PLAFOND_JETONS,
                           help=f"plafond de jetons (défaut {PLAFOND_JETONS}, valeur de production D5)")
    analyseur.add_argument("--no-think", action="store_true",
                           help="désactiver le mode réflexion des modèles qui l'activent par défaut")
    analyseur.add_argument("--native", action="store_true",
                           help="Ollama uniquement : passer par /api/chat, seul endroit où think:false fonctionne (B3)")
    analyseur.add_argument("--debug", action="store_true", help="afficher la réponse brute quand elle est vide")
    arguments = analyseur.parse_args()

    if arguments.filtre is not None:
        lister(arguments.api_base, arguments.api_key, arguments.filtre)
        return

    if not arguments.models:
        analyseur.error("--models est requis (ou utilise --list pour voir ce qui est disponible)")

    modeles = [m.strip() for m in arguments.models.split(",")]
    print(f"Point d'entrée : {arguments.api_base}")
    print(f"Clé : {'oui' if arguments.api_key else 'non'}")
    if arguments.api_key and not arguments.api_base.startswith("https://"):
        print("  ⚠️  une clé est envoyée en clair vers un point d'entrée non HTTPS.")
        print("     Inutile pour Ollama : `unset OPENROUTER_API_KEY` avant les tests locaux.")
    print(f"Modèles : {', '.join(modeles)}")
    print(f"Plafond : {arguments.max_tokens} jetons" + (" (D5)" if arguments.max_tokens == PLAFOND_JETONS else ""))
    if arguments.no_think:
        print("Mode réflexion : désactivé" + (" (API native)" if arguments.native else " (reasoning_effort=none)"))
    elif arguments.native:
        print("API native Ollama")

    for numero, situation in enumerate(SITUATIONS, 1):
        print("\n" + "═" * 78)
        print(f"SITUATION {numero} — {situation['nom']}")
        print(f"On attend : {situation['cherche']}")
        print("─" * 78)
        for ligne in situation["messages"]:
            print(f"  {ligne}")
        print("─" * 78)

        for modele in modeles:
            for tour in range(arguments.tours):
                etiquette = modele if arguments.tours == 1 else f"{modele} ({tour + 1})"
                diagnostic = ""
                try:
                    if arguments.native:
                        reponse, diagnostic = demander_natif(
                            arguments.api_base, modele, situation["messages"],
                            arguments.max_tokens, arguments.no_think, arguments.debug,
                        )
                    else:
                        reponse, diagnostic = demander(
                            arguments.api_base, arguments.api_key, modele, situation["messages"],
                            plafond=arguments.max_tokens,
                            sans_reflexion=arguments.no_think,
                            debug=arguments.debug,
                        )
                except urllib.error.HTTPError as erreur:
                    detail = erreur.read().decode(errors="replace")[:200]
                    reponse = f"<HTTP {erreur.code} — {detail}>"
                except Exception as erreur:
                    reponse = f"<échec : {erreur}>"

                print(f"\n  ▸ {etiquette}")
                if reponse:
                    print(f"    {reponse}")
                else:
                    print(f"    <VIDE> {diagnostic}")

    print("\n" + "═" * 78)
    print("""
À juger, dans cet ordre d'importance :

  1. SITUATION 2 — a-t-il inventé un chiffre ? C'est éliminatoire (R11).
  2. SITUATION 5 — sait-il se taire ? Un bot incapable de ne rien dire
     sera insupportable une fois la prise de parole spontanée activée.
  3. Longueur : une phrase, vraiment ? Une consigne de brièveté ignorée
     au test le sera aussi en direct.
  4. Langue et ton : français naturel, pas de traduction laborieuse.
  5. Constance : avec --tours 3, les réponses restent-elles du même niveau ?

Reporter le choix dans suivi_de_projet.MD (Q15) avec la raison.
""")


if __name__ == "__main__":
    main()
