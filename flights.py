#!/usr/bin/env python3
"""Module d'interrogation des vols en temps réel (OpenSky Network).

Retourne la liste des avions actuellement présents au-dessus de la maison,
filtrés par distance horizontale (formule de Haversine) et altitude minimale.

Configuration (variables d'environnement) :
    HOME_LAT   : latitude de la maison en degrés décimaux (obligatoire)
    HOME_LON   : longitude de la maison en degrés décimaux (obligatoire)
    RADIUS_KM  : rayon de détection en kilomètres (défaut : 5)
    MIN_ALT_M  : altitude minimale en mètres (défaut : 300)

Utilisation :
    from flights import get_aircraft_overhead
    for avion in get_aircraft_overhead():
        print(avion)

Dépendances : uniquement la bibliothèque standard (urllib).
"""

import email.utils
import json
import logging
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request

OPEN_SKY_API = "https://opensky-network.org/api/states/all"
DEFAULT_RADIUS_KM = 5.0
DEFAULT_MIN_ALT_M = 300.0
REQUEST_TIMEOUT_S = 10.0
MAX_ATTEMPTS = 3
BACKOFF_BASE_S = 1.0

logger = logging.getLogger(__name__)

# Index des champs du tableau "states" renvoyé par l'API OpenSky.
_IDX_CALLSIGN = 1
_IDX_COUNTRY = 2
_IDX_LAST_CONTACT = 4
_IDX_LON = 5
_IDX_LAT = 6
_IDX_BARO_ALT = 7
_IDX_ON_GROUND = 8
_IDX_VELOCITY = 9
_IDX_TRUE_TRACK = 10
_IDX_GEO_ALT = 13
_IDX_CATEGORY = 17

# Libellés des catégories OpenSky (champ "category", index 17).
CATEGORY_NAMES = {
    0: "Inconnu",
    1: "No ADS-B",
    2: "Léger",
    3: "Petit",
    4: "Moyen",
    5: "Large",
    6: "Gros porteur",
    7: "Haute perf.",
    8: "Hélicoptère",
    9: "Planeur",
    10: "Ballon",
    11: "Parachutiste",
    12: "ULM",
    13: "Réservé",
    14: "Drone",
    15: "Spatial",
    16: "Surface",
    17: "Urgence",
    18: "Service",
    19: "Obstacle",
}


def category_name(category):
    """Libellé lisible d'une catégorie OpenSky (ou None si inconnue)."""
    if category is None:
        return None
    return CATEGORY_NAMES.get(int(category))


class OpenSkyError(Exception):
    """Erreur d'accès à l'API OpenSky (réseau, HTTP, limite de débit...)."""


def haversine_km(lat1, lon1, lat2, lon2):
    """Distance horizontale en km entre deux points (formule de Haversine)."""
    r_earth_km = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    return 2.0 * r_earth_km * math.asin(math.sqrt(a))


def bounding_box(lat, lon, radius_km):
    """Bounding box [lamin, lomin, lamax, lomax] autour de (lat, lon).

    Une marge de 20 % est ajoutée au rayon pour ne pas couper les avions
    proches du bord du cercle (le filtre Haversine s'applique ensuite).
    """
    margin = radius_km * 1.2
    dlat = margin / 111.32  # 1 degré de latitude ≈ 111,32 km
    dlon = margin / (111.32 * max(math.cos(math.radians(lat)), 0.01))
    return (lat - dlat, lon - dlon, lat + dlat, lon + dlon)


def _has_valid_position(lat, lon):
    """Vrai si la position est exploitable (non nulle)."""
    if lat is None or lon is None:
        return False
    return not (abs(lat) < 1e-6 and abs(lon) < 1e-6)


def _field(state, idx):
    """Accès sécurisé à un champ OpenSky.

    L'API renvoie des états de longueur variable (16 à 18 champs selon les
    cas) : un index hors limites retourne None au lieu de lever IndexError.
    """
    if idx < len(state):
        return state[idx]
    return None


def _altitude_m(state):
    """Altitude barométrique, sinon géométrique, sinon None."""
    baro = _field(state, _IDX_BARO_ALT)
    if baro is not None:
        return baro
    return _field(state, _IDX_GEO_ALT)


def filter_aircraft(states, home_lat, home_lon, radius_km, min_alt_m):
    """Filtre les états bruts OpenSky et construit la liste des avions.

    Ne garde que les avions avec une position non nulle, une distance
    horizontale <= radius_km et une altitude >= min_alt_m.
    La liste est triée par distance croissante.
    """
    aircraft = []
    for state in states:
        lat = _field(state, _IDX_LAT)
        lon = _field(state, _IDX_LON)
        if not _has_valid_position(lat, lon):
            continue
        if _field(state, _IDX_ON_GROUND):
            continue
        altitude = _altitude_m(state)
        if altitude is None or altitude < min_alt_m:
            continue
        distance = haversine_km(home_lat, home_lon, lat, lon)
        if distance > radius_km:
            continue
        callsign = (_field(state, _IDX_CALLSIGN) or "").strip()
        aircraft.append(
            {
                "callsign": callsign,
                "country": _field(state, _IDX_COUNTRY),
                "altitude_m": round(altitude),
                "speed_ms": _field(state, _IDX_VELOCITY),
                "distance_km": round(distance, 2),
                "last_contact": _field(state, _IDX_LAST_CONTACT),
                "track": _field(state, _IDX_TRUE_TRACK),
                "category": _field(state, _IDX_CATEGORY),
            }
        )
    aircraft.sort(key=lambda a: a["distance_km"])
    return aircraft


def _parse_retry_after(value: str | None, fallback: float) -> float:
    """Parse Retry-After header robustly (delta-seconds or HTTP-date).

    - delta-seconds : valeur numérique directe.
    - HTTP-date     : date RFC 7231, convertie en délai.
    Retourne *fallback* si la valeur est absente, invalide ou mal formée.
    Le résultat est borné à [0, 60] s pour éviter un sleep excessif dans
    le retry loop.
    """
    if not value:
        return fallback
    value = value.strip()
    # delta-seconds path
    try:
        delay = float(value)
        if delay < 0:
            return fallback
        return min(delay, 60.0)
    except ValueError:
        pass
    # HTTP-date path
    try:
        retry_ts = email.utils.parsedate_to_datetime(value)
        if retry_ts is not None:
            # parsedate_to_datetime may return naive dt for some formats
            now_ts = time.time()
            dt_ts = retry_ts.timestamp()
            delay = dt_ts - now_ts
            if delay < 0:
                return fallback
            return min(delay, 60.0)
    except Exception:
        pass
    return fallback


def _fetch_states(lamin, lomin, lamax, lomax):
    """Interroge l'API OpenSky avec retry/backoff. Lève OpenSkyError en échec.

    Les erreurs réseau, les 5xx et le 429 (limite de débit) sont retentés
    avec un backoff exponentiel ; un message clair est journalisé en cas de
    limite de débit (en respectant l'en-tête Retry-After si présent).
    """
    params = urllib.parse.urlencode(
        {
            "lamin": lamin,
            "lomin": lomin,
            "lamax": lamax,
            "lomax": lomax,
        }
    )
    url = f"{OPEN_SKY_API}?{params}"
    last_error = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "awtrix-flights/1.0"})
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_S) as resp:
                data = json.load(resp)
                return data.get("states") or []
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code == 429:
                logger.warning(
                    "OpenSky : limite de débit atteinte (HTTP 429). Réessai après backoff."
                )
                backoff = BACKOFF_BASE_S * (2 ** (attempt - 1))
                delay = _parse_retry_after(exc.headers.get("Retry-After"), backoff)
            elif exc.code >= 500:
                delay = BACKOFF_BASE_S * (2 ** (attempt - 1))
            else:
                raise OpenSkyError(f"OpenSky : erreur HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
            delay = BACKOFF_BASE_S * (2 ** (attempt - 1))
        if attempt < MAX_ATTEMPTS:
            logger.debug(
                "Nouvelle tentative OpenSky dans %.1f s (essai %d/%d)",
                delay,
                attempt,
                MAX_ATTEMPTS,
            )
            time.sleep(delay)
    raise OpenSkyError(
        f"OpenSky injoignable après {MAX_ATTEMPTS} tentatives : {last_error}"
    ) from last_error


def get_aircraft_overhead():
    """Retourne la liste JSON-serializable des avions au-dessus de la maison.

    En cas d'API injoignable ou de limite de débit, journalise un message
    clair et retourne [] (ne lève jamais d'exception pour un problème
    réseau/API). Une configuration manquante (HOME_LAT/HOME_LON) lève en
    revanche une ValueError explicite.
    """
    home_lat = os.environ.get("HOME_LAT")
    home_lon = os.environ.get("HOME_LON")
    if home_lat is None or home_lon is None:
        raise ValueError("HOME_LAT et HOME_LON doivent être définies dans l'environnement.")
    try:
        home_lat = float(home_lat)
        home_lon = float(home_lon)
    except ValueError as exc:
        raise ValueError("HOME_LAT et HOME_LON doivent être des nombres décimaux.") from exc
    radius_km = float(os.environ.get("RADIUS_KM", DEFAULT_RADIUS_KM))
    min_alt_m = float(os.environ.get("MIN_ALT_M", DEFAULT_MIN_ALT_M))

    lamin, lomin, lamax, lomax = bounding_box(home_lat, home_lon, radius_km)
    try:
        states = _fetch_states(lamin, lomin, lamax, lomax)
    except OpenSkyError as exc:
        logger.warning("Aucune donnée de vol disponible : %s", exc)
        return []
    return filter_aircraft(states, home_lat, home_lon, radius_km, min_alt_m)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    for plane in get_aircraft_overhead():
        print(plane)
