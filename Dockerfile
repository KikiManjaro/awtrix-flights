# syntax=docker/dockerfile:1
# Image de base : Python slim (Debian) — aucune dépendance pip
# (le projet n'utilise que la bibliothèque standard).
FROM python:3.13-slim

# Métadonnées OCI (renseignées automatiquement par le CI pour les labels
# org.opencontainers.image.source/revision, voir docker-publish.yml)
LABEL org.opencontainers.image.title="awtrix-flights" \
      org.opencontainers.image.description="Affiche en live sur un AWTRIX 3 les avions qui survolent votre maison (OpenSky Network)" \
      org.opencontainers.image.licenses="MIT"

SHELL ["/bin/sh", "-o", "pipefail", "-c"]

# Fuseau horaire (logs lisibles) — tzdata requis pour l'env TZ
# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -r app --gid 65534 2>/dev/null || true \
    && id -u app >/dev/null 2>&1 || useradd -r -g app --uid 65534 --create-home app 2>/dev/null || true

WORKDIR /app

# Copie du code applicatif uniquement (voir .dockerignore)
COPY main.py flights.py awtrix_client.py airlines.py mqtt_client.py config.py ./

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Europe/Paris

# L'application n'écrit aucun fichier : exécution non-root
USER 65534:65534

STOPSIGNAL SIGTERM

# Démarrage du service : boucle infinie de détection
CMD ["python3", "main.py"]
