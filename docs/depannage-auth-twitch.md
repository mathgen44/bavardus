# Bavardus — déblocage de l'auth Twitch (bug B-001)

> ✅ **CLOS le 2026-09-06.** Le test du §2 a renvoyé « Bavardus OK » : la chaîne
> DNS → box → NPM → VM:8475 est saine, aucune correction n'a été nécessaire dans
> Nginx Proxy Manager. Le DynDNS n'était pas en cause.
>
> **Cause réelle : rien n'écoutait sur le port 8475** au moment du test — `--auth`
> n'ouvre son serveur HTTP que pendant le flux OAuth.
>
> ⚠️ **Correction d'une hypothèse fausse de cette fiche :** il y était écrit qu'un
> backend injoignable donne un 502 et jamais un 404. Sur cette installation, c'est
> faux — un upstream absent peut produire un 404. **Sur ce NPM, un 404 ne prouve
> pas l'absence de proxy host.** Le §3 reste utile comme checklist, mais sa
> prémisse de départ est à ignorer.
>
> **Règle à retenir :** ne jamais tester l'URL publique quand aucun service
> n'écoute derrière. Poser d'abord `python3 -m http.server 8475`, puis conclure.
>
> Le §4 (voie localhost) n'a pas servi. Il reste documenté comme secours.

---

## 0. Marche à suivre retenue

1. Couper le serveur de test (`Ctrl+C`) — sinon le port 8475 est occupé.
2. Dans le `.env` de la VM :
   `TWITCH_REDIRECT_URI=https://bavardus.mathgen.fr/api/twitch/callback`
   (identique au caractère près à la console dev Twitch, sans `/` final en trop).
3. `python3 test_twitch.py --auth` → ouvrir l'URL affichée, se connecter avec le
   **compte du bot**.
4. `--check`, puis `--refresh` (valide le risque R4), puis `--listen`.

---

## 1. Ce que dit le diagnostic

Le DynDNS **fonctionne**. Mesuré depuis Internet :

| Vérification | Résultat |
|---|---|
| `bavardus.mathgen.fr` résout | ✅ vers `86.236.115.226` |
| Port 80 joignable | ✅ |
| Port 443 joignable | ✅ |
| Certificat TLS | ✅ `*.mathgen.fr`, SAN `bavardus.mathgen.fr` |
| `GET /` | ❌ **404** |

Le certificat wildcard prouve que c'est **ton** Nginx Proxy Manager qui décroche :
DNS et redirection de ports sont bons. Le problème est derrière le proxy.

Et surtout : **un 404 n'est pas un backend éteint.** Un backend éteint donne
502 Bad Gateway. Un 404 est ce que NPM sert quand *aucun proxy host ne
correspond au nom demandé*.

Deuxième point, aussi important : `test_twitch.py --auth` n'ouvre le port 8475
**que pendant le flux OAuth**, et sur la machine où tu le lances. Hors de ce
créneau, l'URL publique ne peut rien renvoyer d'utile, même avec NPM parfait.

---

## 2. Test qui tranche en 30 secondes

Sur la VM du homelab, mets un serveur permanent sur le port 8475 :

```bash
mkdir -p /tmp/testnpm && echo "Bavardus OK" > /tmp/testnpm/index.html
cd /tmp/testnpm && python3 -m http.server 8475
```

Puis, depuis n'importe où, ouvre `https://bavardus.mathgen.fr` :

| Ce que tu vois | Ce que ça veut dire | Quoi faire |
|---|---|---|
| **Bavardus OK** | La chaîne complète marche | Rien — passe au §4 |
| **502 Bad Gateway** | NPM trouve le host mais n'atteint pas la VM | Mauvaise IP/port dans NPM, ou pare-feu VM (§3, points 2 et 6) |
| **404** | Aucun proxy host ne correspond | Créer le proxy host (§3, point 1) |

Ce test isole le problème sans dépendre du timing d'OAuth. Fais-le en premier.

---

## 3. Checklist Nginx Proxy Manager

1. **Le proxy host existe-t-il ?** Proxy Hosts → une entrée avec exactement
   `bavardus.mathgen.fr` dans Domain Names. Si elle n'existe pas, tout le reste
   est sans objet.
2. **Forward Hostname / IP** = l'IP de la **VM** sur le LAN, pas `127.0.0.1` ni
   `localhost` : si NPM est lui-même dans un conteneur, `localhost` désigne le
   conteneur NPM, pas ta VM. C'est l'erreur classique.
3. **Forward Port** = `8475`, **Scheme** = `http`.
4. **Websockets Support** = ON. Pas nécessaire pour OAuth, indispensable ensuite
   pour l'interface web et le flux d'événements.
5. **SSL** → certificat `*.mathgen.fr`, **Force SSL** ON.
6. **Pare-feu de la VM** : `sudo ufw allow from <IP_de_NPM> to any port 8475`
   si ufw est actif.
7. Depuis l'hôte de NPM : `curl -I http://<IP_VM>:8475` doit répondre pendant
   que le serveur de test du §2 tourne. Si ça échoue là, le problème est réseau,
   pas NPM.

---

## 4. Débloquer l'auth tout de suite, sans reverse proxy

Twitch autorise `http://localhost` comme URL de redirection — c'est la seule
exception à l'obligation de HTTPS. On s'en sert pour obtenir les jetons
maintenant, sans attendre NPM.

### Étape 1 — Ajouter la seconde URL de redirection

Console développeur Twitch → ton application → **Add** une deuxième OAuth
Redirect URL, en plus de l'existante :

```
http://localhost:8475/api/twitch/callback
```

Twitch exige une correspondance **exacte** : même schéma, même port, même
chemin, pas de `/` final en trop. Garde l'URL `https://bavardus...` — elle
resservira pour l'interface web.

### Étape 2 — Ouvrir un tunnel SSH depuis ton PC Windows

Le script tourne sur la VM, mais le navigateur qui reçoit la redirection est sur
ton PC. Le tunnel relie les deux. Dans PowerShell :

```powershell
ssh -L 8475:localhost:8475 <user>@<IP_VM>
```

Laisse cette fenêtre ouverte. `localhost:8475` sur ton PC pointe désormais vers
le port 8475 de la VM.

### Étape 3 — Lancer l'auth

Dans la session SSH (donc sur la VM), modifie le `.env` :

```
TWITCH_REDIRECT_URI=http://localhost:8475/api/twitch/callback
```

puis :

```bash
python3 test_twitch.py --auth
```

Le script affiche une URL. Copie-la dans le navigateur de ton PC.
**Connecte-toi avec le compte DU BOT**, pas ton compte principal.

### Étape 4 — Vérifier

```bash
python3 test_twitch.py --check     # jeton, scopes, compte
python3 test_twitch.py --refresh   # valide le risque R4
python3 test_twitch.py --listen    # chat en direct
```

### Repli si le tunnel SSH pose problème

Lance `test_twitch.py --auth` directement sur le PC Windows (avec son propre
`.env`), puis copie `.twitch_tokens.json` vers la VM. Les jetons sont liés au
`client_id`, pas à la machine : ils fonctionnent tels quels.

---

## 5. Une fois NPM réparé

Remets dans le `.env` de la VM :

```
TWITCH_REDIRECT_URI=https://bavardus.mathgen.fr/api/twitch/callback
```

et relance `--auth` pour confirmer que la voie publique marche aussi. Elle sera
de toute façon nécessaire pour l'interface web du bot.

---

## 6. Avant le premier commit (garde-fou G5)

`.env` et `.twitch_tokens.json` doivent être dans `.gitignore`. Le fichier de
jetons donne le contrôle du compte du bot.
