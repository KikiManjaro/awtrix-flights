#!/bin/bash
# ============================================================================
#  awtrix-flights — Unraid manual installation (no Community Apps needed)
#
#  Usage (run from a clone of the repo, e.g. on the Unraid flash drive):
#      git clone https://github.com/KikiManjaro/awtrix-flights.git
#      cd awtrix-flights
#      bash install-unraid.sh
#
#  What it does:
#    1. Copies the project to /mnt/user/appdata/awtrix-flights
#    2. Creates .env from .env.example (edit it before step 3 if needed)
#    3. Builds the Docker image and starts the container (auto-restart)
#
#  Customize before starting (optional):
#      nano /mnt/user/appdata/awtrix-flights/.env
#      docker restart awtrix-flights
# ============================================================================
set -euo pipefail

APP_DIR="/mnt/user/appdata/awtrix-flights"
IMAGE="awtrix-flights:latest"
CONTAINER="awtrix-flights"

echo "==> 1/4 Création du dossier $APP_DIR"
mkdir -p "$APP_DIR"

echo "==> 2/4 Copie des fichiers du projet"
cp main.py flights.py awtrix_client.py airlines.py mqtt_client.py \
   Dockerfile docker-compose.yml "$APP_DIR/"

echo "==> 3/4 Création du .env (défaut : Jargeau + 2 AWTRIX)"
if [ ! -f "$APP_DIR/.env" ]; then
    sed -e 's/^AWTRIX_HOST=.*/AWTRIX_HOST=192.168.1.27,192.168.1.123/' \
        .env.example > "$APP_DIR/.env"
    echo "    .env créé — vérifie HOME_LAT/HOME_LON/AWTRIX_HOST :"
    grep -E '^(HOME_LAT|HOME_LON|AWTRIX_HOST)=' "$APP_DIR/.env"
else
    echo "    .env existant conservé"
fi

cd "$APP_DIR"

echo "==> 4/4 Build + démarrage du conteneur"
docker build -t "$IMAGE" .
docker rm -f "$CONTAINER" 2>/dev/null || true
docker run -d \
    --name "$CONTAINER" \
    --restart unless-stopped \
    --read-only \
    --tmpfs /tmp \
    --env-file .env \
    "$IMAGE"

echo ""
echo "============================================="
echo "✅ Service démarré : $CONTAINER"
echo "============================================="
docker ps --filter "name=$CONTAINER" --format "table {{.Names}}\t{{.Status}}"
sleep 10
echo ""
echo "Logs (20 premières lignes) :"
docker logs "$CONTAINER" 2>&1 | head -20
echo ""
echo "Suivi en direct :  docker logs -f $CONTAINER"
echo "Arrêt :            docker stop $CONTAINER"
echo "Personnalisation : nano $APP_DIR/.env puis docker restart $CONTAINER"
