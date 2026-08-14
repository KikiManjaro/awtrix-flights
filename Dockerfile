# syntax=docker/dockerfile:1
# Image de base : Python slim (Debian) — aucune dépendance pip
# (le projet n'utilise que la bibliothèque standard).
FROM python:3.13-slim

# Métadonnées OCI (renseignées automatiquement par le CI pour les labels
# org.opencontainers.image.source/revision, voir docker-publish.yml)
LABEL org.opencontainers.image.title="awtrix-flights" \
      org.opencontainers.image.description="Affiche en live sur un AWTRIX 3 les avions qui survolent votre maison (OpenSky Network)" \
      org.opencontainers.image.licenses="MIT"

# Fuseau horaire (logs lisibles) — tzdata requis pour l'env TZ
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copie du code applicatif uniquement (voir .dockerignore)
COPY main.py flights.py awtrix_client.py ./

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Europe/Paris

# L'application n'écrit aucun fichier : exécution non-root
# (65534 = "nobody" standard Debian)
USER 65534:65534

# Démarrage du service : boucle infinie de détection
CMD ["python3", "main.py"]
