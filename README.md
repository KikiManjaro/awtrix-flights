# awtrix-flights ✈️

> **Display live aircraft overflying your home on an [AWTRIX 3](https://blueforcer.github.io/awtrix3/) LED display.**

Every aircraft detected within the configured radius is shown with its callsign, airline, country, altitude and speed — plus a **plane icon rotated to match its true heading**. Data comes from the public [OpenSky Network API](https://opensky-network.org/) (ADS-B).

![CI](https://github.com/KikiManjaro/awtrix-flights/actions/workflows/ci.yml/badge.svg)
![Docker](https://github.com/KikiManjaro/awtrix-flights/actions/workflows/docker-publish.yml/badge.svg)
[![GHCR](https://img.shields.io/badge/GHCR-ghcr.io%2Fkikimanjaro%2Fawtrix-flights-blue?logo=docker)](https://github.com/users/KikiManjaro/packages/container/package/awtrix-flights)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## ✨ Features

- **Real-time detection**: polls OpenSky Network every `POLL_INTERVAL_SEC` seconds
- **Geographic filtering**: configurable radius around your home (Haversine) + minimum altitude
- **Customizable display**: free-form message template (`MESSAGE_TEMPLATE`) with placeholders
- **Heading-oriented icon**: the 8×8 plane sprite rotates with the aircraft's true track (screen orientation handled via `AWTRIX_BEARING`)
- **Airline name**: ICAO callsign prefix resolution (e.g. `AFR123` → Air France), customizable table
- **Aircraft category**: OpenSky label (heavy, helicopter, drone...)
- **MQTT**: publishes detections to your broker (Mosquitto, EMQX...) for home-automation integration
- **Anti-spam**: each aircraft is shown at most once per cooldown window (60 s default)
- **Multi-display**: publishes to several AWTRIX units at once (comma-separated hosts)
- **Zero dependencies**: Python standard library only (no pip install)
- **Resilient**: backoff on 429/network errors, never crashes on a network spike
- **Lightweight**: ~50 MB Docker image, non-root, auto-restart

## 📦 Quick start (Docker)

```bash
git clone https://github.com/KikiManjaro/awtrix-flights.git
cd awtrix-flights
cp .env.example .env
# Edit .env: HOME_LAT, HOME_LON (required), AWTRIX_HOST, etc.
docker compose up -d
```

Or with the pre-built image:

```bash
docker run -d \
  --name awtrix-flights \
  --restart unless-stopped \
  --env-file .env \
  ghcr.io/kikimanjaro/awtrix-flights:latest
```

## ⚙️ Configuration (environment variables)

### Detection

| Variable | Role | Default |
|---|---|---|
| `HOME_LAT` / `HOME_LON` | Home coordinates (decimal degrees) | **required** |
| `RADIUS_KM` | Detection radius around home | `5` |
| `MIN_ALT_M` | Minimum aircraft altitude | `300` |
| `POLL_INTERVAL_SEC` | OpenSky polling interval | `15` |
| `NOTIFY_COOLDOWN_SEC` | Anti-spam: min. delay between displays of the same aircraft | `60` |

### AWTRIX

| Variable | Role | Default |
|---|---|---|
| `AWTRIX_HOST` | AWTRIX unit(s), comma-separated | `192.168.1.27` |
| `AWTRIX_PORT` | AWTRIX API HTTP port (⚠️ 7001 is silent on firmware 0.98) | `80` |
| `MESSAGE_TEMPLATE` | Displayed message template (placeholders below) | `{callsign} {country} {altitude_m}m {speed_kmh}km/h` |
| `ICON_ENABLED` | Heading-oriented plane icon (`true`/`false`) | `true` |
| `ICON_COLOR` | Icon RGB color (`255,170,0`) | `255,170,0` |
| `AWTRIX_BEARING` | Screen orientation in degrees (see below) | `0` |
| `AIRLINES_FILE` | Custom airlines JSON file | — |

### Template placeholders (`MESSAGE_TEMPLATE`)

| Placeholder | Value | Example |
|---|---|---|
| `{callsign}` | Aircraft callsign | `AFR123` |
| `{country}` | Country of registration | `France` |
| `{airline}` | Airline (ICAO prefix resolved) | `Air France` |
| `{category}` | OpenSky category | `Heavy` |
| `{altitude_m}` | Altitude in meters | `10500` |
| `{altitude_ft}` | Altitude in feet | `34449` |
| `{speed_ms}` | Speed in m/s | `235` |
| `{speed_kmh}` | Speed in km/h | `846` |
| `{distance_km}` | Horizontal distance | `1.2` |
| `{track}` | Heading in degrees | `273` |
| `{direction}` | Cardinal direction | `W` |

Example templates:

```bash
# With airline and direction
MESSAGE_TEMPLATE={callsign} {airline} {direction} {altitude_ft}ft
# -> AFR123 Air France W 34449ft

# Minimal
MESSAGE_TEMPLATE={callsign} {altitude_m}m
```

### 🧭 Screen orientation (`AWTRIX_BEARING`)

The plane icon is rotated to point in the aircraft's **real direction**. For this to be accurate, tell the app how your display is placed — the angle between the **top of the screen** and **geographic north**, clockwise:

| Display position | Value |
|---|---|
| Top of screen facing north | `0` |
| Top of screen facing east | `90` |
| Top of screen facing south | `180` |
| Top of screen facing west | `270` |

> 💡 A flat-mounted AWTRIX with its USB port pointing north = `AWTRIX_BEARING=0`. A wall-mounted display (UI facing you): the top of the screen points north when you face north, etc.

### MQTT

| Variable | Role | Default |
|---|---|---|
| `MQTT_ENABLED` | Enable MQTT publishing (`true`/`false`) | `false` |
| `MQTT_HOST` | Broker address | `127.0.0.1` |
| `MQTT_PORT` | Broker port | `1883` |
| `MQTT_USER` / `MQTT_PASSWORD` | Authentication (optional) | — |
| `MQTT_TOPIC_PREFIX` | Topic prefix | `awtrix-flights` |

Published topics:

| Topic | Payload |
|---|---|
| `<prefix>/detection` | `{"callsign": "AFR123", "country": "France", "altitude_m": 10500, ..., "speed_kmh": 846, "notified_at": 1786700000}` |
| `<prefix>/status` | `{"state": "online", "started_at": ...}` / `{"state": "offline", ...}` |

Subscribe example: `mosquitto_sub -h 192.168.1.100 -t 'awtrix-flights/#'`

### Custom airlines (`AIRLINES_FILE`)

The prefix → airline mapping is built in (major European carriers). To extend it:

```json
{"MYC": "My Airline", "AFR": "Air France (overridden)"}
```

Entries from the file **override** the built-in table.

**Find your coordinates**: Google Maps → right-click your home → "What's here?".

## 🖼️ What it looks like

The message is rendered on a 32×8 LED matrix. With the default template and the heading icon, a detection looks like this (the plane sprite points west, matching `track=273`):

```
⬤═══════════════════════════════════
 AFR123 France 10500m 846km/h
```

With a custom template (`{callsign} {airline} {direction} {altitude_ft}ft`):

```
⬤ AFR123 Air France W 34449ft
```

The text scrolls when it exceeds the matrix width. The icon color matches `ICON_COLOR`, and its rotation updates every time the aircraft's track changes.

## 🖥️ Unraid (Community Apps)

A ready-made template is included in the repo (`template/awtrix-flights.xml`) — no command line needed.

**Installation:**
1. Unraid → **Apps** → *Settings* tab → **Template Repositories**
2. Add: `https://github.com/KikiManjaro/awtrix-flights`
3. Go back to **Apps** → search `awtrix-flights` → **Install**
4. Fill in `HOME_LAT`, `HOME_LON`, `AWTRIX_HOST` (comma-separated for multiple displays) → **Apply**

The template exposes every setting from the configuration tables above (template, icon color, bearing, MQTT...). The image is pulled from GHCR (`ghcr.io/kikimanjaro/awtrix-flights:latest`, multi-arch amd64/arm64) and restarts automatically (`--restart unless-stopped`).

> ⚠️ **Note for public use**: for the Community Apps template to be installable by everyone, the repository (and thus the GHCR package) must be **public**. While the repo is private, you can still install the template manually on your own Unraid (the template repository feature works with private repos for your account).

**Manual alternative** (without Community Apps): from a clone of the repo, run `bash install-unraid.sh` — it copies the project to `/mnt/user/appdata/awtrix-flights`, generates the `.env` and starts the container (auto-restart).

## 🔧 Without Docker (plain Python)

```bash
python3 -m venv .venv && source .venv/bin/activate   # optional, no dependencies
export HOME_LAT=47.8649 HOME_LON=2.1243
export AWTRIX_HOST=192.168.1.27,192.168.1.123
python3 main.py
```

## 🧪 Development

```bash
python3 -m unittest discover -s tests -v     # or: pytest
pytest --cov=. --cov-report=term-missing     # tests + coverage
ruff check .                                 # lint
ruff format --check .                        # format
```

The project is deliberately **stdlib-only**: no `requirements.txt` needed at runtime. `pytest`, `pytest-cov` and `ruff` are CI-only tools (`pip install -e ".[dev]"`).

## 🚀 CI / CD

GitHub Actions pipeline (`.github/workflows/`):

| Workflow | Trigger | Action |
|---|---|---|
| `ci.yml` | push/PR on `main` | Python tests (3.10 → 3.13) + coverage ≥ 80 %, ruff lint, Docker build smoke test |
| `docker-publish.yml` | push on `main` or tag `v*` | multi-arch build (amd64/arm64) + publish to GHCR |
| `release.yml` | tag `v*` | GitHub Release with automatic changelog |

**Dependabot** watches GitHub Actions and CI tools (weekly update PRs).

### Cutting a release

```bash
git tag v0.2.0 && git push origin v0.2.0
```

→ GitHub Release created, image `ghcr.io/kikimanjaro/awtrix-flights:v0.2.0` published.

Image tags on `ghcr.io/kikimanjaro/awtrix-flights`:
- `latest` (main branch)
- `<branch>` / `<sha>` (every push)
- `vX.Y.Z` (versioned tags, for stable releases)

## 📁 Project structure

```
awtrix-flights/
├── main.py            # main loop (poll, cooldown, signals, MQTT)
├── flights.py         # OpenSky Network client (bbox, filtering, retry, categories)
├── airlines.py        # airline resolution from callsign prefix
├── awtrix_client.py   # AWTRIX API client (template, oriented icon, multi-display)
├── mqtt_client.py     # publish-only MQTT client (stdlib, zero dependency)
├── tests/             # 111 unit tests (unittest, network 100% mocked)
├── Dockerfile         # ~50 MB image, non-root
├── docker-compose.yml # one-command deployment
└── .github/workflows/ # CI + GHCR publishing + releases
```

## 🛰️ How it works (API used)

The project queries the **public OpenSky Network API** (`https://opensky-network.org/api/states/all`) — a worldwide aggregator of the **ADS-B** network (aircraft broadcast their position, altitude, speed and heading by radio; thousands of ground receivers feed OpenSky).

### Endpoint

```
GET https://opensky-network.org/api/states/all?lamin=47.81&lomin=2.07&lamax=47.92&lomax=2.18
```

The `lamin/lomin/lamax/lomax` parameters define a **geographic bounding box** around the home (computed by `flights.bounding_box()` with a 20 % margin). The response contains a `states` array: **one row per aircraft** with 18 fields, including the ones used here:

| Index | OpenSky field | Usage |
|---|---|---|
| 1 | `callsign` | Callsign (e.g. `AFR123`) → airline via `airlines.py` |
| 2 | `origin_country` | Country of registration |
| 5/6 | `longitude` / `latitude` | Position → Haversine distance from home |
| 7 | `baro_altitude` | Altitude (falls back to `geo_altitude` index 13) |
| 8 | `on_ground` | Filtered out (aircraft on the ground are ignored) |
| 9 | `velocity` | Speed m/s → converted to km/h |
| 10 | `true_track` | **Heading in degrees → icon orientation** |
| 17 | `category` | Aircraft type (heavy, helicopter, drone...) |

The service never reports intermediate state: each cycle polls the zone, filters (valid position, not on ground, altitude ≥ `MIN_ALT_M`, distance ≤ `RADIUS_KM`), sorts by distance, then displays new aircraft (per-callsign anti-spam).

> ℹ️ **Limits**: the public API is free without an account (≈ 4 requests/min per IP in practice) with limited history. Built-in backoff handles `429` responses cleanly. For richer data, OpenSky offers free authenticated accounts — not required here.

## 🎨 Icons: anything to download on the AWTRIX?

**No, nothing to download.** 🎉

The plane icon does **not** use the AWTRIX LaMetric icon system (the one that requires downloading each icon through the web UI *Icon* tab). Instead, `awtrix_client.py` **draws the sprite pixel by pixel** via the AWTRIX `draw` API instruction:

```json
{"draw": [{"db": [x, y, 1, 1, [255, 170, 0]]}, ...]}
```

Each lit pixel of the 8×8 sprite is sent individually with its color (`ICON_COLOR`), which enables:
- **dynamic orientation** (the sprite is rotated in Python by `track − AWTRIX_BEARING`, impossible with a fixed downloaded icon),
- zero interaction with the display: the first `notify_aircraft()` does everything.

Only other apps (weather, energy...) use downloaded LaMetric icons — that's independent from this project.

## 📜 License

MIT licensed ([LICENSE](LICENSE)). Flight data provided by [OpenSky Network](https://opensky-network.org/) (open data). Airline prefixes based on public ICAO codes.
