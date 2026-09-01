#!/usr/bin/env python3
"""Résolution du nom de compagnie depuis le préfixe du callsign.

Les callsigns OpenSky sont formés d'un préfixe ICAO (3 lettres, ex. "AFR"
pour Air France) suivi du numéro de vol ("AFR123"). Ce module résout le
préfixe vers un nom de compagnie lisible, avec une table embarquée par
défaut et la possibilité d'en fournir une personnalisée via le fichier
``AIRLINES_FILE`` (JSON : {"AFR": "Air France", ...}).

Zéro dépendance : la table par défaut est un simple dict Python.
"""

from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger(__name__)

# Table par défaut : préfixe ICAO -> compagnie. Couvre les compagnies
# fréquentes en Europe de l'Ouest (zone de vol typique de la maison).
DEFAULT_AIRLINES: dict[str, str] = {
    "AFR": "Air France",
    "HOP": "Air France Hop",
    "DLH": "Lufthansa",
    "BAW": "British Airways",
    "RYR": "Ryanair",
    "EZY": "EasyJet",
    "TRA": "Transavia",
    "BEL": "Brussels Airlines",
    "KLM": "KLM",
    "SWR": "Swiss",
    "AUA": "Austrian",
    "IBE": "Iberia",
    "TAP": "TAP Portugal",
    "LOT": "LOT Polish",
    "SAS": "Scandinavian",
    "FIN": "Finnair",
    "TUI": "TUI Airways",
    "WZZ": "Wizz Air",
    "ROT": "Tarom",
    "VLG": "Vueling",
    "TVF": "Transavia France",
    "RAM": "Royal Air Maroc",
    "UAL": "United Airlines",
    "THY": "Turkish",
    "UAE": "Emirates",
    "QTR": "Qatar Airways",
    "ETD": "Etihad",
    "ELY": "El Al",
    "CSC": "Sichuan Airlines",
    "CES": "China Eastern",
    "CPA": "Cathay Pacific",
    "SIA": "Singapore Airlines",
    "JAL": "Japan Airlines",
    "ACA": "Air Canada",
    "AIC": "Air India",
    "NAX": "Norwegian",
    "TAY": "TNT Airways",
    "FDX": "FedEx",
    "UPS": "UPS",
    "BOX": "Aerologic",
    "GEC": "Lufthansa Cargo",
    "CLX": "Cargolux",
    "RCH": "USAF",
    "CFC": "RCAF",
    "CTM": "French Air Force",
    "GAF": "German Air Force",
    "RRR": "RAF",
    "EJU": "EasyJet Europe",
    "EZS": "EasyJet Switzerland",
    "TVS": "TUI fly",
    "TOM": "TUI Airways",
    "EXS": "Jet2",
    "RYS": "Ryanair Sun",
    "ADR": "Adria Airways",
}

# Cache : {"AFR": "Air France"} fusionné (personnalisé > par défaut).
_airlines_cache: dict[str, str] | None = None
_airlines_lock = __import__("threading").Lock()
_MAX_AIRLINES_FILE_BYTES = 1_048_576  # 1 MB guard against DoS via huge file


def _load_airlines() -> dict[str, str]:
    """Charge la table des compagnies (par défaut + fichier personnalisé)."""
    global _airlines_cache
    if _airlines_cache is not None:
        return _airlines_cache
    with _airlines_lock:
        if _airlines_cache is not None:
            return _airlines_cache
        table = dict(DEFAULT_AIRLINES)
        custom_path = os.environ.get("AIRLINES_FILE", "").strip()
        if custom_path:
            try:
                size = __import__("os").path.getsize(custom_path)
                if size > _MAX_AIRLINES_FILE_BYTES:
                    logger.warning("AIRLINES_FILE trop volumineux (%d octets), ignoré", size)
                else:
                    with open(custom_path, encoding="utf-8") as fh:
                        custom = json.load(fh)
                    if isinstance(custom, dict):
                        table.update({str(k).upper(): str(v) for k, v in custom.items()})
                        logger.info("Table compagnies personnalisée chargée : %s", custom_path)
                    else:
                        logger.warning("AIRLINES_FILE doit être un objet JSON, ignoré")
            except OSError as exc:
                logger.warning("AIRLINES_FILE illisible (%s) : %s", custom_path, exc)
            except ValueError as exc:
                logger.warning("AIRLINES_FILE JSON invalide (%s) : %s", custom_path, exc)
        _airlines_cache = table
        return table


def clear_airlines_cache() -> None:
    """Réinitialise le cache (utile pour les tests)."""
    global _airlines_cache
    with _airlines_lock:
        _airlines_cache = None


def airline_for_callsign(callsign: str | None) -> str | None:
    """Nom de la compagnie pour un callsign (ex. "AFR123" -> "Air France").

    Extrait le préfixe alphabétique (3 lettres) du callsign et le cherche
    dans la table. Retourne None si inconnu ou callsign vide.
    """
    if not callsign:
        return None
    prefix = "".join(ch for ch in callsign if ch.isalpha())[:3].upper()
    if len(prefix) < 3:
        return None
    return _load_airlines().get(prefix)
