# Bavardus — image unique : moteur et interface web dans un seul processus (D19).
FROM python:3.12-slim

# Les dépendances d'abord : cette couche ne change qu'avec requirements.txt,
# donc une modification du code ne réinstalle pas tout.
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY bavardus/ ./bavardus/
COPY outils/ ./outils/
COPY config.exemple.yaml LICENSE README.md ./

# Tout l'état dans un seul volume : config.yaml, .env, jetons.json, la base
# et la clé de session. Le sauvegarder, c'est sauvegarder l'installation.
ENV BAVARDUS_DONNEES=/donnees \
    PYTHONUNBUFFERED=1
RUN mkdir -p /donnees

# Utilisateur non privilégié par défaut : le conteneur détient des jetons
# donnant le contrôle d'un compte Twitch, il n'a aucune raison de tourner
# en root.
#
# B15 : cet identifiant vaut pour un volume nommé. Avec un montage depuis
# l'hôte — le cas de compose.yaml — il faut au contraire adopter celui du
# propriétaire du dossier, sans quoi les fichiers en 600 (jetons, .env)
# restent illisibles. compose.yaml le surcharge donc explicitement.
RUN useradd --system --uid 10001 --home /donnees bavardus \
 && chown -R bavardus:bavardus /donnees
USER 10001:10001

VOLUME ["/donnees"]
EXPOSE 8475

# L'interface répond même quand le bot n'est pas encore configuré : c'est
# précisément l'état où l'on a besoin de savoir que le conteneur vit.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; \
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8475/', timeout=4).status < 500 else 1)"

ENTRYPOINT ["python", "-m", "bavardus"]
