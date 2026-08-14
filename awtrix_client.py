#!/usr/bin/env python3
"""Client d'envoi d'informations vers un afficheur AWTRIX 3.

Envoie des messages courts (texte) vers l'API HTTP locale d'un AWTRIX 3
(firmware 0.98 testé chez Kylian) via ``POST /api/custom?name=<app>``.

Configuration (variables d'environnement) :
    AWTRIX_HOST  -- hôte(s) de l'afficheur, séparés par des virgules si
                    plusieurs écrans (défaut: 192.168.1.27, 1er AWTRIX).
                    Chez Kylian : 192.168.1.27 (awtrix_1e6aa4) et
                    192.168.1.123 (awtrix_1e6968) — publier sur les 2 pour
                    synchroniser les écrans.
    AWTRIX_PORT  -- port HTTP de l'API (défaut: 80). ⚠️ Le port 7001 de la
                    doc générique AWTRIX ne répond PAS sur les firmware 0.98
                    installés ici : l'API HTTP est sur le port 80 (web UI).

Usage :
    from awtrix_client import notify_aircraft
    ok = notify_aircraft({"callsign": "AFR123", "country": "France",
                          "altitude_m": 10500, "speed_ms": 235})

Le timeout court (3 s) garantit que la boucle principale n'est jamais
bloquée : toute erreur réseau est journalisée et notify_aircraft() renvoie
False sans jamais lever d'exception.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request

logger = logging.getLogger("awtrix_client")

# Nom de l'app AWTRIX utilisée pour l'affichage des avions (apparaît dans la
# boucle d'affichage ; les publications suivantes mettent son texte à jour).
AWTRIX_APP_NAME = "avion"

# Durée d'affichage (secondes) à chaque passage dans la boucle.
DISPLAY_DURATION_S = 5

DEFAULT_HOST = "192.168.1.27"  # 1er AWTRIX de Kylian (le .200 du ticket n'existe pas)
DEFAULT_PORT = 80  # port HTTP de l'API sur firmware 0.98 (7001 muet)

REQUEST_TIMEOUT_S = 3.0  # ne jamais bloquer la boucle principale


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


def build_aircraft_message(plane_info: dict | None) -> str | None:
    """Construit un message court (callsign, pays, altitude, vitesse).

    Attendu depuis flights.get_aircraft_overhead() : callsign, country,
    altitude_m, speed_ms, distance_km, last_contact. Les champs manquants ou
    nuls sont simplement omis. Retourne None si rien d'exploitable.
    """
    if not plane_info:
        return None
    callsign = str(plane_info.get("callsign") or "??").strip()
    country = str(plane_info.get("country") or "").strip()
    parts = [callsign]
    if country:
        parts.append(country)
    altitude = plane_info.get("altitude_m")
    if altitude is not None:
        try:
            parts.append(f"{int(altitude)}m")
        except (TypeError, ValueError):
            logger.debug("altitude_m non convertible, omise : %r", altitude)
    speed = plane_info.get("speed_ms")
    if speed is not None:
        try:
            parts.append(f"{int(round(float(speed) * 3.6))}km/h")  # m/s -> km/h
        except (TypeError, ValueError):
            logger.debug("speed_ms non convertible, omise : %r", speed)
    message = " ".join(parts).strip()
    return message or None


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


def notify_aircraft(plane_info: dict | None, timeout: float = REQUEST_TIMEOUT_S) -> bool:
    """Affiche un avion détecté sur l'écran AWTRIX (tous les hôtes configurés).

    Construit un message court (callsign, pays, altitude, vitesse) et le publie
    sur l'app ``avion`` de chaque AWTRIX listé dans AWTRIX_HOST.

    Retourne True si au moins un écran a accepté le message, False sinon.
    Ne lève JAMAIS d'exception (écran hors ligne, timeout, port fermé...).
    """
    message = build_aircraft_message(plane_info)
    if message is None:
        logger.warning("notify_aircraft: plane_info vide ou inexploitable, rien à afficher")
        return False
    port = _get_port()
    hosts = _get_hosts()
    payload = {
        "text": message,
        "duration": DISPLAY_DURATION_S,
        "center": True,
    }
    logger.info("AWTRIX: affichage de %r sur %s (port %s)", message, hosts, port)
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
        "last_contact": 1786700000,
    }
    ok = notify_aircraft(sample)
    print("Résultat:", "OK" if ok else "ÉCHEC (écran injoignable ?)")
