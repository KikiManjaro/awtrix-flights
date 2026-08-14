# awtrix-flights ✈️

> **Affiche en live sur un écran [AWTRIX 3](https://blueforcer.github.io/awtrix3/) les avions qui survolent votre maison.**

Chaque avion détecté dans le rayon configuré est affiché avec son callsign, sa compagnie, son pays, son altitude et sa vitesse — avec une **icône avion orientée selon son cap**. Les données viennent de l'[API publique OpenSky Network](https://opensky-network.org/) (réseau ADS-B).

![CI](https://github.com/KikiManjaro/awtrix-flights/actions/workflows/ci.yml/badge.svg)
![Docker](https://github.com/KikiManjaro/awtrix-flights/actions/workflows/docker-publish.yml/badge.svg)
[![GHCR](https://img.shields.io/badge/GHCR-ghcr.io%2Fkikimanjaro%2Fawtrix-flights-blue?logo=docker)](https://github.com/users/KikiManjaro/packages/container/package/awtrix-flights)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> 🇬🇧 English version: [README.md](README.md) — cette page est la version française.

---

## ✨ Fonctionnalités

- **Détection temps réel** : interroge OpenSky Network toutes les `POLL_INTERVAL_SEC` secondes
- **Filtrage géographique** : rayon configurable autour de votre maison (Haversine) + altitude minimale
- **Affichage personnalisable** : gabarit de message libre (`MESSAGE_TEMPLATE`) avec placeholders
- **Icône avion orientée** : le sprite 8×8 tourne selon le cap de l'avion (prise en compte de l'orientation de votre écran via `AWTRIX_BEARING`)
- **Nom de compagnie** : résolution du préfixe ICAO du callsign (ex. `AFR123` → Air France), table personnalisable
- **Catégorie d'avion** : libellé OpenSky (gros porteur, hélicoptère, drone...)
- **MQTT** : publie les détections sur votre broker (Mosquitto, EMQX...) pour intégration domotique
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

### Détection

| Variable | Rôle | Défaut |
|---|---|---|
| `HOME_LAT` / `HOME_LON` | Coordonnées de la maison (degrés décimaux) | **obligatoire** |
| `RADIUS_KM` | Rayon de détection autour de la maison | `5` |
| `MIN_ALT_M` | Altitude minimale des avions pris en compte | `300` |
| `POLL_INTERVAL_SEC` | Période d'interrogation d'OpenSky | `15` |
| `NOTIFY_COOLDOWN_SEC` | Anti-spam : délai min. entre 2 affichages du même avion | `60` |

### AWTRIX

| Variable | Rôle | Défaut |
|---|---|---|
| `AWTRIX_HOST` | Écran(s) AWTRIX, séparés par des virgules | `192.168.1.27` |
| `AWTRIX_PORT` | Port HTTP de l'API AWTRIX (⚠️ 7001 muet sur firmware 0.98) | `80` |
| `MESSAGE_TEMPLATE` | Gabarit du message affiché (placeholders ci-dessous) | `{callsign} {country} {altitude_m}m {speed_kmh}km/h` |
| `ICON_ENABLED` | Icône avion orientée (`true`/`false`) | `true` |
| `ICON_COLOR` | Couleur RGB de l'icône (`255,170,0`) | `255,170,0` |
| `AWTRIX_BEARING` | Orientation de l'écran en degrés (voir ci-dessous) | `0` |
| `AIRLINES_FILE` | Fichier JSON de compagnies personnalisées | — |

### Placeholders du gabarit (`MESSAGE_TEMPLATE`)

| Placeholder | Valeur | Exemple |
|---|---|---|
| `{callsign}` | Indicatif de l'avion | `AFR123` |
| `{country}` | Pays d'origine | `France` |
| `{airline}` | Compagnie (préfixe ICAO résolu) | `Air France` |
| `{category}` | Catégorie OpenSky | `Gros porteur` |
| `{altitude_m}` | Altitude en mètres | `10500` |
| `{altitude_ft}` | Altitude en pieds | `34449` |
| `{speed_ms}` | Vitesse en m/s | `235` |
| `{speed_kmh}` | Vitesse en km/h | `846` |
| `{distance_km}` | Distance horizontale | `1.2` |
| `{track}` | Cap en degrés | `273` |
| `{direction}` | Direction cardinale | `W` |

Exemples de gabarits :

```bash
# Avec compagnie et direction
MESSAGE_TEMPLATE={callsign} {airline} {direction} {altitude_ft}ft
# -> AFR123 Air France W 34449ft

# Minimaliste
MESSAGE_TEMPLATE={callsign} {altitude_m}m
```

### 🧭 Orientation de l'écran (`AWTRIX_BEARING`)

L'icône avion est tournée pour pointer dans la **direction réelle** du vol. Pour que ce soit exact, il faut indiquer comment ton écran est posé.

**Définition** : `AWTRIX_BEARING` est l'angle, dans le sens horaire, entre le **haut de l'écran** (tel qu'affiché — le côté où le texte défile) et le **nord géographique**.

| Le haut de l'écran pointe vers… | Valeur |
|---|---|
| Nord | `0` |
| Est | `90` |
| Sud | `180` |
| Ouest | `270` |

**Comment le mesurer (30 secondes) :**
1. Regarde ton AWTRIX et repère le **bord supérieur de la matrice LED** (le côté où le texte commence — le « haut » de l'heure).
2. Ouvre la **boussole de ton téléphone**.
3. Pose le téléphone le long du bord supérieur de l'écran (comme pour viser depuis ce bord).
4. La direction affichée = ton `AWTRIX_BEARING`.

*Exemple* : si le haut de ton écran fait face à ta baie vitrée orientée à l'ouest → `AWTRIX_BEARING=270`. Un avion qui vole plein ouest sera dessiné avec le nez pointant vers le haut de l'écran (= l'ouest réel ✅).

**Deux pièges à connaître :**
1. **Rotation d'écran dans le firmware** : si tu as activé une *Screen rotation* dans l'UI web AWTRIX, le « haut » désigne ici le **haut affiché** (là où le texte commence), pas le haut physique du boîtier.
2. **Même convention horaire qu'OpenSky** : angle affiché = `track − bearing`. Si tu te trompes de 180°, l'icône pointera dans la direction opposée (facile à repérer sur un vol évident vers l'est).

**Astuce de calibrage** : en cas de doute, commence avec `AWTRIX_BEARING=0`, attends un avion au cap évident (ex. un vol vers l'est), et vérifie que l'icône pointe à droite. Si elle pointe à gauche, ajoute 180.

### MQTT

| Variable | Rôle | Défaut |
|---|---|---|
| `MQTT_ENABLED` | Active la publication MQTT (`true`/`false`) | `false` |
| `MQTT_HOST` | Adresse du broker | `127.0.0.1` |
| `MQTT_PORT` | Port du broker | `1883` |
| `MQTT_USER` / `MQTT_PASSWORD` | Authentification (optionnel) | — |
| `MQTT_TOPIC_PREFIX` | Préfixe des topics | `awtrix-flights` |

Topics publiés :

| Topic | Payload |
|---|---|
| `<prefix>/detection` | `{"callsign": "AFR123", "country": "France", "altitude_m": 10500, ..., "speed_kmh": 846, "notified_at": 1786700000}` |
| `<prefix>/status` | `{"state": "online", "started_at": ...}` / `{"state": "offline", ...}` |

Exemple d'abonnement : `mosquitto_sub -h 192.168.1.100 -t 'awtrix-flights/#'`

### Compagnies personnalisées (`AIRLINES_FILE`)

Le mapping préfixe → compagnie est intégré (les principales compagnies européennes). Pour l'étendre :

```json
{"MYC": "Ma Compagnie", "AFR": "Air France (surchargé)"}
```

Les entrées du fichier **surchargent** la table intégrée.

**Trouver ses coordonnées** : Google Maps → clic droit sur votre maison → « Qu'y a-t-il ici ? ».

## 🖼️ À quoi ça ressemble

Le message est rendu sur une matrice 32×8. Avec le gabarit par défaut et l'icône orientée, une détection ressemble à ceci (le sprite pointe vers l'ouest, cap `track=273`) :

```
⬤═══════════════════════════════════
 AFR123 France 10500m 846km/h
```

Avec un gabarit personnalisé (`{callsign} {airline} {direction} {altitude_ft}ft`) :

```
⬤ AFR123 Air France W 34449ft
```

Le texte défile s'il dépasse la largeur de la matrice. La couleur de l'icône suit `ICON_COLOR`, et sa rotation se met à jour à chaque changement de cap de l'avion.

## 🖥️ Unraid (Community Apps)

Un template prêt à l'emploi est inclus dans le repo (`template/awtrix-flights.xml`) — deux commandes `curl` et c'est installé.

> ℹ️ **Note** : depuis Unraid 6.10, le réglage *Template Repositories* a été retiré de l'UI. Le template s'installe en déposant le XML directement sur la clé USB — même résultat, sans édition de fichier manuelle.

**Installation :**
1. Unraid → **Tools** → **Terminal** (ou SSH) et lancer :
   ```bash
   mkdir -p /boot/config/plugins/dockerMan/templates-user
   curl -o /boot/config/plugins/dockerMan/templates-user/awtrix-flights.xml \
     https://raw.githubusercontent.com/KikiManjaro/awtrix-flights/main/template/awtrix-flights.xml
   ```
2. **Docker** → **Add Container** → choisir **awtrix-flights** dans la liste des templates
3. Renseigner `HOME_LAT`, `HOME_LON`, `AWTRIX_HOST` (séparés par des virgules pour plusieurs écrans) → **Apply**

Le template expose tous les réglages des tableaux ci-dessus (gabarit, couleur d'icône, orientation, MQTT...). L'image est tirée de GHCR (`ghcr.io/kikimanjaro/awtrix-flights:latest`, multi-arch amd64/arm64, publique) et redémarre automatiquement (`--restart unless-stopped`).

**Alternative via Community Apps** (template géré par CA, catégorie *Private*) :
```bash
mkdir -p /boot/config/plugins/community.applications/private/LTM
curl -o /boot/config/plugins/community.applications/private/LTM/awtrix-flights.xml \
  https://raw.githubusercontent.com/KikiManjaro/awtrix-flights/main/template/awtrix-flights.xml
```

**Alternative manuelle** (sans template) : depuis un clone du repo, lancer `bash install-unraid.sh` — il copie le projet dans `/mnt/user/appdata/awtrix-flights`, génère le `.env` et lance le conteneur (redémarrage auto).

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
pytest --cov=. --cov-report=term-missing     # tests + coverage
ruff check .                                 # lint
ruff format --check .                        # format
```

Le projet est volontairement **stdlib-only** : aucun fichier `requirements.txt` nécessaire pour l'exécution. `pytest`, `pytest-cov` et `ruff` ne sont utilisés que pour la CI (`pip install -e ".[dev]"`).

## 🚀 CI / CD

Le pipeline GitHub Actions (`.github/workflows/`) :

| Workflow | Déclencheur | Action |
|---|---|---|
| `ci.yml` | push/PR sur `main` | tests Python (3.10 → 3.13) + coverage ≥ 80 %, lint ruff, smoke-test du build Docker |
| `docker-publish.yml` | push sur `main` ou tag `v*` | build multi-arch (amd64/arm64) + publication sur GHCR |
| `release.yml` | tag `v*` | GitHub Release avec changelog automatique |

**Dependabot** surveille les actions GitHub et les outils de CI (PR de mise à jour automatiques chaque semaine).

### Créer une release

```bash
git tag v0.2.0 && git push origin v0.2.0
```

→ GitHub Release créée, image `ghcr.io/kikimanjaro/awtrix-flights:v0.2.0` publiée.

Tags d'image publiés sur `ghcr.io/kikimanjaro/awtrix-flights` :
- `latest` (branche main)
- `<branche>` / `<sha>` (chaque push)
- `vX.Y.Z` (tags versionnés, pour des releases stables)

## 📁 Structure du projet

```
awtrix-flights/
├── main.py            # boucle principale (poll, cooldown, signaux, MQTT)
├── flights.py         # client OpenSky Network (bbox, filtrage, retry, catégories)
├── airlines.py        # résolution compagnie depuis le préfixe callsign
├── awtrix_client.py   # client API AWTRIX (template, icône orientée, multi-écrans)
├── mqtt_client.py     # client MQTT publish-only (stdlib, zéro dépendance)
├── tests/             # 111 tests unitaires (unittest, réseau 100% mocké)
├── Dockerfile         # image ~50 Mo, non-root
├── docker-compose.yml # déploiement en une commande
└── .github/workflows/ # CI + publication GHCR + releases
```

## 🛰️ Comment ça marche (API utilisée)

Le projet interroge l'**API publique OpenSky Network** (`https://opensky-network.org/api/states/all`) — un agrégateur mondial du réseau **ADS-B** (le même système que les récepteurs qui équipent les avions : ils diffusent leur position, altitude, vitesse et cap par radio, et des milliers de récepteurs terrestres collectent ces données pour OpenSky).

### Endpoint utilisé

```
GET https://opensky-network.org/api/states/all?lamin=47.81&lomin=2.07&lamax=47.92&lomax=2.18
```

Les 4 paramètres `lamin/lomin/lamax/lomax` délimitent une **boîte géographique** autour de la maison (calculée par `flights.bounding_box()` avec 20 % de marge). La réponse contient un tableau `states` : **une ligne par avion** avec 18 champs, dont ceux utilisés ici :

| Index | Champ OpenSky | Utilisation |
|---|---|---|
| 1 | `callsign` | Indicatif (ex. `AFR123`) → compagnie via `airlines.py` |
| 2 | `origin_country` | Pays d'immatriculation |
| 5/6 | `longitude` / `latitude` | Position → distance Haversine depuis la maison |
| 7 | `baro_altitude` | Altitude (repli sur `geo_altitude` index 13) |
| 8 | `on_ground` | Filtré (on ignore les avions au sol) |
| 9 | `velocity` | Vitesse m/s → convertie en km/h |
| 10 | `true_track` | **Cap en degrés → orientation de l'icône** |
| 17 | `category` | Type d'avion (gros porteur, hélico, drone…) |

Le service **ne remonte jamais d'état intermédiaire** : chaque cycle interroge la zone, filtre (position valide, hors sol, altitude ≥ `MIN_ALT_M`, distance ≤ `RADIUS_KM`), trie par distance, puis affiche les nouveaux avions (anti-spam par callsign).

> ℹ️ **Limites** : l'API publique est gratuite sans compte (≈ 4 requêtes/min par IP en pratique) et l'historique est limité. Le backoff intégré gère les réponses `429` proprement. Pour des données plus riches, OpenSky propose des comptes gratuits avec authentification — non requis ici.

## 🎨 Icônes : faut-il télécharger quoi que ce soit sur l'AWTRIX ?

**Non, rien à télécharger.** 🎉

L'icône avion n'utilise **pas** le système d'icônes LaMetric de l'AWTRIX (celui qui exige de télécharger chaque icône via l'onglet *Icon* de l'interface web). À la place, `awtrix_client.py` **dessine le sprite pixel par pixel** via l'instruction `draw` de l'API AWTRIX :

```json
{"draw": [{"db": [x, y, 1, 1, [255, 170, 0]]}, ...]}
```

Chaque pixel allumé du sprite 8×8 est envoyé individuellement avec sa couleur (`ICON_COLOR`), ce qui permet :
- l'**orientation dynamique** (le sprite est tourné en Python selon `track − AWTRIX_BEARING`, impossible avec une icône fixe téléchargée),
- zéro manipulation sur l'écran : le premier `notify_aircraft()` fait tout.

Seules les autres apps du repo (météo, énergie…) utilisent des icônes LaMetric téléchargées — c'est indépendant de ce projet.

## 📜 Licence

Projet sous licence [MIT](LICENSE). Données de vol fournies par [OpenSky Network](https://opensky-network.org/) (données ouvertes). Préfixes de compagnies basés sur les codes OACI/ICAO publics.
