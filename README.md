# awtrix-flights ✈️

> **Affiche en live sur un écran [AWTRIX 3](https://blueforcer.github.io/awtrix3/) les avions qui survolent votre maison.**

Chaque avion détecté dans le rayon configuré est affiché avec son callsign, son pays, son altitude et sa vitesse. Les données viennent de l'[API publique OpenSky Network](https://opensky-network.org/) (réseau ADS-B).

![CI](https://github.com/KikiManjaro/awtrix-flights/actions/workflows/ci.yml/badge.svg)
![Docker](https://github.com/KikiManjaro/awtrix-flights/actions/workflows/docker-publish.yml/badge.svg)
[![GHCR](https://img.shields.io/badge/GHCR-ghcr.io%2Fkikimanjaro%2Fawtrix-flights-blue?logo=docker)](https://github.com/users/KikiManjaro/packages/container/package/awtrix-flights)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## ✨ Fonctionnalités

- **Détection temps réel** : interroge OpenSky Network toutes les `POLL_INTERVAL_SEC` secondes
- **Filtrage géographique** : rayon configurable autour de votre maison (Haversine) + altitude minimale
- **Anti-spam** : chaque avion n'est affiché qu'une fois par fenêtre de cooldown (60 s par défaut)
- **Multi-écrans** : publie sur plusieurs AWTRIX simultanément (séparés par des virgules)
- **Zéro dépendance** : uniquement la bibliothèque standard Python (pas de pip install)
- **Robuste** : backoff sur 429/erreurs réseau, ne plante jamais sur un pic réseau
- **Léger** : image Docker ~50 Mo, exécution non-root, redémarrage automatique

## 📦 Installation rapide (Docker)

```bash
git clone https://github.com/KikiManjaro/awtrix-flights.git
cd awtrix-flights
cp .env.example .env
# Éditer .env : HOME_LAT, HOME_LON (obligatoires), AWTRIX_HOST, etc.
docker compose up -d
```

Ou avec l'image pré-construite :

```bash
docker run -d \
  --name awtrix-flights \
  --restart unless-stopped \
  --env-file .env \
  ghcr.io/kikimanjaro/awtrix-flights:latest
```

## ⚙️ Configuration (variables d'environnement)

| Variable | Rôle | Défaut |
|---|---|---|
| `HOME_LAT` / `HOME_LON` | Coordonnées de la maison (degrés décimaux) | **obligatoire** |
| `RADIUS_KM` | Rayon de détection autour de la maison | `5` |
| `MIN_ALT_M` | Altitude minimale des avions pris en compte | `300` |
| `AWTRIX_HOST` | Écran(s) AWTRIX, séparés par des virgules | `192.168.1.27` |
| `AWTRIX_PORT` | Port HTTP de l'API AWTRIX (⚠️ 7001 muet sur firmware 0.98) | `80` |
| `POLL_INTERVAL_SEC` | Période d'interrogation d'OpenSky | `15` |
| `NOTIFY_COOLDOWN_SEC` | Anti-spam : délai min. entre 2 affichages du même avion | `60` |

**Trouver ses coordonnées** : Google Maps → clic droit sur votre maison → « Qu'y a-t-il ici ? ».

> 💡 **Astuce AWTRIX** : les écrans AWTRIX 3 sont joignables par leur API HTTP sur le **port 80** (web UI). Le port 7001 documenté ne répond pas sur les firmwares 0.98.

## 🔧 Sans Docker (Python direct)

```bash
python3 -m venv .venv && source .venv/bin/activate   # optionnel, aucune dépendance
export HOME_LAT=47.8649 HOME_LON=2.1243
export AWTRIX_HOST=192.168.1.27,192.168.1.123
python3 main.py
```

## 🧪 Développement

```bash
python3 -m unittest discover -s tests -v     # ou : pytest
ruff check .                                  # lint
ruff format --check .                         # format
```

Le projet est volontairement **stdlib-only** : aucun fichier `requirements.txt` nécessaire pour l'exécution. `pytest` et `ruff` ne sont utilisés que pour la CI.

## 🚀 CI / CD

Le pipeline GitHub Actions (`.github/workflows/`) :

| Workflow | Déclencheur | Action |
|---|---|---|
| `ci.yml` | push/PR sur `main` | tests Python (3.10 → 3.13), lint ruff, smoke-test du build Docker |
| `docker-publish.yml` | push sur `main` ou tag `v*` | build multi-arch (amd64/arm64) + publication sur GHCR |

Tags d'image publiés sur `ghcr.io/kikimanjaro/awtrix-flights` :
- `latest` (branche main)
- `<branche>` / `<sha>` (chaque push)
- `vX.Y.Z` (tags versionnés, pour des releases stables)

## 📁 Structure du projet

```
awtrix-flights/
├── main.py            # boucle principale (poll, cooldown, signaux)
├── flights.py         # client OpenSky Network (bbox, filtrage, retry)
├── awtrix_client.py   # client API AWTRIX (publish multi-écrans)
├── tests/             # tests unitaires (unittest, 100 % réseau mocké)
├── Dockerfile         # image ~50 Mo, non-root
├── docker-compose.yml # déploiement en une commande
└── .github/workflows/ # CI + publication GHCR
```

## 📜 Licence

Projet sous licence [MIT](LICENSE). Données de vol fournies par [OpenSky Network](https://opensky-network.org/) (données ouvertes).
