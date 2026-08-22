#!/usr/bin/env python3
"""Client d'envoi d'informations vers un afficheur AWTRIX 3.

Envoie des messages (texte + icône) vers l'API HTTP locale d'un AWTRIX 3
(firmware 0.98 testé chez Kylian) via ``POST /api/custom?name=<app>``.

Configuration (variables d'environnement) :
    AWTRIX_HOST      -- hôte(s) de l'afficheur, séparés par des virgules si
                        plusieurs écrans (défaut: 192.168.1.27, 1er AWTRIX).
                        Chez Kylian : 192.168.1.27 (awtrix_1e6aa4) et
                        192.168.1.123 (awtrix_1e6968) — publier sur les 2 pour
                        synchroniser les écrans.
    AWTRIX_PORT      -- port HTTP de l'API (défaut: 80). ⚠️ Le port 7001 de la
                        doc générique AWTRIX ne répond PAS sur les firmware
                        0.98 installés ici : l'API HTTP est sur le port 80.
    MESSAGE_TEMPLATE -- gabarit du message affiché. Placeholders disponibles :
                        {callsign} {country} {airline} {category} {altitude_m}
                        {altitude_ft} {speed_ms} {speed_kmh} {distance_km}
                        {track} {direction} — les champs inconnus/vides sont
                        omis proprement (espaces nettoyés).
                        Défaut: "{callsign} {country} {altitude_m}m {speed_kmh}km/h"
    ICON_ENABLED     -- "true"/"false" : affiche l'icône avion orientée (défaut: true)
    ICON_COLOR       -- couleur RGB de l'icône, "R,G,B" (défaut: 255,170,0)
    AWTRIX_BEARING   -- orientation de l'ÉCRAN : rotation en degrés du haut de
                        l'écran par rapport au nord (0 = haut = nord, 90 = haut
                        = est...). L'icône est tournée de track - bearing.
                        Défaut: 0 (haut de l'écran vers le nord).
    TEXT_CENTER      -- "true"/"false" : centrer le texte (défaut: false quand
                        l'icône est active, true sinon)

Usage :
    from awtrix_client import notify_aircraft
    ok = notify_aircraft({"callsign": "AFR123", "country": "France",
                          "altitude_m": 10500, "speed_ms": 235,
                          "track": 273})

Le timeout court (3 s) garantit que la boucle principale n'est jamais
bloquée : toute erreur réseau est journalisée et notify_aircraft() renvoie
False sans jamais lever d'exception.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import urllib.error
import urllib.request

import airlines
import flights

logger = logging.getLogger("awtrix_client")

# Nom de l'app AWTRIX utilisée pour l'affichage des avions (apparaît dans la
# boucle d'affichage ; les publications suivantes mettent son texte à jour).
AWTRIX_APP_NAME = "avion"

# Durée d'affichage (secondes) à chaque passage dans la boucle.
DISPLAY_DURATION_S = 5

DEFAULT_HOST = "192.168.1.27"  # 1er AWTRIX de Kylian (le .200 du ticket n'existe pas)
DEFAULT_PORT = 80  # port HTTP de l'API sur firmware 0.98 (7001 muet)

REQUEST_TIMEOUT_S = 3.0  # ne jamais bloquer la boucle principale

# ⚠️ FIRMWARE 0.98 : les commandes draw avec bitmap 8x8 (192 valeurs RGB)
# font CRASHER les AWTRIX (reset ESP32). Désactivé par défaut pour la
# fiabilité. Pour réactiver : ICON_ENABLED=true + AWTRIX_BEARING=126.
# Si vous réactivez, testez d'abord avec UN SEUL envoi pour vérifier que
# votre firmware le supporte.

# Gabarit par défaut du message (compatible avec l'ancien format).
DEFAULT_MESSAGE_TEMPLATE = "{callsign} {country} {altitude_m}m {speed_kmh}km/h"

# Sprite avion 8x8 — icône LaMetric 11594 « Airplane » (vue du dessus, nez
# vers le haut). 1 = pixel allumé. Asymétrique volontairement (nez fin /
# ailes / queue) pour que la rotation soit visible sur l'écran.
AIRCRAFT_SPRITE = [
    0b00011000,
    0b00011000,
    0b00111100,
    0b01111110,
    0b11011011,
    0b11011001,
    0b00011000,
    0b00111100,
]

# Directions cardinales (pour le placeholder {direction}).
_COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


def _get_hosts() -> list[str]:
    """Retourne la liste des hôtes AWTRIX (AWTRIX_HOST, séparés par des virgules)."""
    raw = os.environ.get("AWTRIX_HOST", "").strip()
    if not raw:
        return [DEFAULT_HOST]
    hosts = [h.strip() for h in raw.split(",") if h.strip()]
    return hosts or [DEFAULT_HOST]


def _get_port() -> int:
    """Retourne le port HTTP de l'API AWTRIX (AWTRIX_PORT)."""
    raw = os.environ.get("AWTRIX_PORT", "").strip()
    if not raw:
        return DEFAULT_PORT
    try:
        port = int(raw)
    except ValueError:
        logger.warning("AWTRIX_PORT invalide (%r), utilisation du défaut %s", raw, DEFAULT_PORT)
        return DEFAULT_PORT
    if not 1 <= port <= 65535:
        logger.warning("AWTRIX_PORT hors plage (%r), utilisation du défaut %s", raw, DEFAULT_PORT)
        return DEFAULT_PORT
    return port


def _get_template() -> str:
    """Gabarit du message depuis MESSAGE_TEMPLATE (défaut si absent)."""
    return os.environ.get("MESSAGE_TEMPLATE", "").strip() or DEFAULT_MESSAGE_TEMPLATE


def _get_icon_enabled() -> bool:
    """L'icône orientée est-elle activée ? (ICON_ENABLED, défaut false).

    ⚠️ Firmware 0.98 : les draw avec bitmap 8x8 font crasher les AWTRIX.
    Désactivé par défaut. Pour réactiver : ICON_ENABLED=true.
    """
    raw = os.environ.get("ICON_ENABLED", "").strip().lower()
    if not raw:
        return False  # défaut = désactivé (sécurité firmware 0.98)
    return raw not in ("false", "0", "no", "off")


def _get_icon_color() -> list[int]:
    """Couleur RGB de l'icône (ICON_COLOR "R,G,B", défaut orange ambre)."""
    raw = os.environ.get("ICON_COLOR", "").strip()
    if raw:
        parts = [p.strip() for p in raw.split(",")]
        if len(parts) == 3:
            try:
                return [max(0, min(255, int(p))) for p in parts]
            except ValueError:
                logger.warning("ICON_COLOR invalide (%r), défaut utilisé", raw)
    return [255, 170, 0]


def _get_bearing() -> float:
    """Orientation de l'écran AWTRIX en degrés (AWTRIX_BEARING, défaut 0)."""
    raw = os.environ.get("AWTRIX_BEARING", "").strip()
    if not raw:
        return 0.0
    try:
        return float(raw) % 360.0
    except ValueError:
        logger.warning("AWTRIX_BEARING invalide (%r), défaut 0 utilisé", raw)
        return 0.0


def _get_text_center() -> bool | None:
    """Centrage du texte (TEXT_CENTER, None = auto selon l'icône)."""
    raw = os.environ.get("TEXT_CENTER", "").strip().lower()
    if not raw:
        return None
    return raw not in ("false", "0", "no", "off")


def direction_from_track(track) -> str | None:
    """Direction cardinale (N/NE/E...) depuis le cap en degrés."""
    if track is None:
        return None
    try:
        t = float(track) % 360.0
    except (TypeError, ValueError):
        return None
    return _COMPASS[int(round(t / 45.0)) % 8]


def _format_value(key: str, plane_info: dict) -> str:
    """Valeur formatée d'un placeholder pour un avion donné."""
    if key == "callsign":
        return str(plane_info.get("callsign") or "??").strip()
    if key == "country":
        return str(plane_info.get("country") or "").strip()
    if key == "airline":
        return airlines.airline_for_callsign(plane_info.get("callsign")) or ""
    if key == "category":
        cat = flights.category_name(plane_info.get("category"))
        return cat or ""
    if key == "altitude_m":
        alt = plane_info.get("altitude_m")
        try:
            return f"{int(alt)}"
        except (TypeError, ValueError):
            return ""
    if key == "altitude_ft":
        alt = plane_info.get("altitude_m")
        try:
            return f"{int(round(float(alt) * 3.28084))}"
        except (TypeError, ValueError):
            return ""
    if key == "speed_ms":
        spd = plane_info.get("speed_ms")
        try:
            return f"{int(round(float(spd)))}"
        except (TypeError, ValueError):
            return ""
    if key == "speed_kmh":
        spd = plane_info.get("speed_ms")
        try:
            return f"{int(round(float(spd) * 3.6))}"
        except (TypeError, ValueError):
            return ""
    if key == "distance_km":
        dist = plane_info.get("distance_km")
        try:
            return f"{float(dist):.1f}"
        except (TypeError, ValueError):
            return ""
    if key == "track":
        tr = plane_info.get("track")
        try:
            return f"{int(round(float(tr)))}"
        except (TypeError, ValueError):
            return ""
    if key == "direction":
        return direction_from_track(plane_info.get("track")) or ""
    return ""


def build_aircraft_message(plane_info: dict | None, template: str | None = None) -> str | None:
    """Construit le message selon MESSAGE_TEMPLATE (ou le gabarit passé).

    Les placeholders inconnus restent littéraux ; les champs vides sont
    retirés avec leurs espaces (ex. pays absent dans
    "{callsign} {country}" -> "AFR123 " nettoyé). Retourne None si le
    résultat est vide ou si plane_info est vide.
    """
    if not plane_info:
        return None
    tpl = template if template is not None else _get_template()

    # Résolution des placeholders {nom}. Les placeholders inconnus sont
    # conservés littéralement (le gabarit reste lisible).
    known_keys = {
        "callsign",
        "country",
        "airline",
        "category",
        "altitude_m",
        "altitude_ft",
        "speed_ms",
        "speed_kmh",
        "distance_km",
        "track",
        "direction",
    }

    def _sub(match):
        key = match.group(1)
        if key not in known_keys:
            return match.group(0)
        return _format_value(key, plane_info)

    message = re.sub(r"\{(\w+)\}", _sub, tpl)
    # Nettoyage des espaces multiples et des bouts de phrase vides
    # (ex. "AFR123 10500m" si le pays est absent).
    message = " ".join(message.split())
    # Retrait des unités orphelines laissées par un placeholder vide :
    # " m"/" ft"/" km/h" détachés par une espace (ex. "{altitude_m}m" sans
    # altitude -> " m" seul). Les valeurs collées ("10500m") sont conservées.
    message = re.sub(r"\s+(?:m|ft|km/h)(?=\s|$)", "", message)
    return message or None


def _rotate_sprite(sprite: list[int], angle_deg: float) -> list[tuple[int, int]]:
    """Pixels (x, y) du sprite tournés de ``angle_deg`` (sens horaire).

    Rotation autour du centre (3.5, 3.5) de la matrice 8x8, avec arrondi.
    Retourne la liste des pixels allumés dans la grille 8x8 après rotation.
    """
    angle = math.radians(angle_deg % 360.0)
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    cx = cy = 3.5
    pixels: list[tuple[int, int]] = []
    for y in range(8):
        for x in range(8):
            if not (sprite[y] >> (7 - x)) & 1:
                continue
            dx, dy = x - cx, y - cy
            # Rotation dans le sens horaire (repère écran, y vers le bas).
            rx = cx + dx * cos_a - dy * sin_a
            ry = cy + dx * sin_a + dy * cos_a
            px, py = round(rx), round(ry)
            if 0 <= px < 8 and 0 <= py < 8:
                pixels.append((px, py))
    return pixels


def build_draw_commands(plane_info: dict | None) -> list[dict]:
    """Instructions ``draw`` AWTRIX pour l'icône avion orientée.

    L'angle d'affichage = ``track - AWTRIX_BEARING`` (le track d'OpenSky est
    le cap de l'avion en degrés depuis le nord). Retourne [] si pas de track
    ou icône désactivée.

    ⚠️ Firmware 0.98 : envoyer UN SEUL ``db`` avec les 64 couleurs (matrice
    8x8) — plusieurs instructions ``db`` séparées font redémarrer l'écran.
    Les pixels éteints sont transparents ([0,0,0]).
    """
    if not plane_info or not _get_icon_enabled():
        return []
    track = plane_info.get("track")
    if track is None:
        return []
    try:
        track_f = float(track)
    except (TypeError, ValueError):
        return []
    bearing = _get_bearing()
    angle = (track_f - bearing) % 360.0
    color = _get_icon_color()
    pixels = set(_rotate_sprite(AIRCRAFT_SPRITE, angle))

    colors: list[int] = []
    for y in range(8):
        for x in range(8):
            if (x, y) in pixels:
                colors.extend(color)
            else:
                colors.extend([0, 0, 0])  # transparent
    return [{"db": [0, 0, 8, 8, colors]}]


def _send_to_host(
    host: str, port: int, payload: dict, app_name: str, timeout: float = REQUEST_TIMEOUT_S
) -> bool:
    """POST du payload vers un seul AWTRIX. True si réponse 2xx, sinon False."""
    url = f"http://{host}:{port}/api/custom?name={app_name}"
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "hermes-awtrix-client/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = response.status
            reply = response.read(200).decode("utf-8", errors="replace").strip()
        if 200 <= status < 300:
            logger.info("AWTRIX %s: message envoyé (HTTP %s, %r)", host, status, reply)
            return True
        logger.warning("AWTRIX %s: réponse non-2xx HTTP %s (%r)", host, status, reply)
        return False
    except urllib.error.HTTPError as exc:
        reply = exc.read(200).decode("utf-8", errors="replace").strip()
        logger.warning("AWTRIX %s: HTTP %s (%r)", host, exc.code, reply)
        return False
    except urllib.error.URLError as exc:
        logger.warning("AWTRIX %s: erreur réseau: %s", host, exc.reason)
        return False
    except TimeoutError:
        logger.warning("AWTRIX %s: timeout après %ss", host, timeout)
        return False
    except OSError as exc:
        logger.warning("AWTRIX %s: erreur de connexion: %s", host, exc)
        return False


def build_payload(plane_info: dict | None) -> dict | None:
    """Payload complet pour l'API AWTRIX (texte + icône orientée).

    Retourne None si rien d'affichable.
    """
    message = build_aircraft_message(plane_info)
    if message is None:
        return None
    draw = build_draw_commands(plane_info)
    center_override = _get_text_center()
    center = center_override if center_override is not None else (not draw)
    payload: dict = {
        "text": message,
        "duration": DISPLAY_DURATION_S,
        "center": center,
    }
    if draw:
        # Icône dessinée à gauche (8 px) -> texte décalé de 8 + 1 de marge.
        payload["textOffset"] = 9
        payload["draw"] = draw
    return payload


def notify_aircraft(plane_info: dict | None, timeout: float = REQUEST_TIMEOUT_S) -> bool:
    """Affiche un avion détecté sur l'écran AWTRIX (tous les hôtes configurés).

    Construit le message personnalisé (callsign, pays/compagnie, altitude,
    vitesse...) et l'icône avion orientée selon le cap, puis publie sur
    l'app ``avion`` de chaque AWTRIX listé dans AWTRIX_HOST.

    Retourne True si au moins un écran a accepté le message, False sinon.
    Ne lève JAMAIS d'exception (écran hors ligne, timeout, port fermé...).
    """
    payload = build_payload(plane_info)
    if payload is None:
        logger.warning("notify_aircraft: plane_info vide ou inexploitable, rien à afficher")
        return False
    port = _get_port()
    hosts = _get_hosts()
    logger.info("AWTRIX: affichage de %r sur %s (port %s)", payload.get("text"), hosts, port)
    results = [_send_to_host(host, port, payload, AWTRIX_APP_NAME, timeout) for host in hosts]
    return any(results)


if __name__ == "__main__":
    # Auto-test manuel (équivalent de la vérification curl demandée) :
    #     python3 awtrix_client.py
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    sample = {
        "callsign": "AFR123",
        "country": "France",
        "altitude_m": 10500,
        "speed_ms": 235,
        "distance_km": 1.2,
        "track": 273,
        "last_contact": 1786700000,
    }
    print("Message :", build_aircraft_message(sample))
    print("Pixels icône (track=273, bearing=0) :", len(build_draw_commands(sample)))
    ok = notify_aircraft(sample)
    print("Résultat:", "OK" if ok else "ÉCHEC (écran injoignable ?)")
