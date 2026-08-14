#!/usr/bin/env python3
"""Client MQTT minimaliste (publish-only) — bibliothèque standard uniquement.

Implémente le strict minimum du protocole MQTT 3.1.1 pour publier des
messages sur un broker (Mosquitto, EMQX, ...) : CONNECT -> CONNACK ->
PUBLISH (QoS 0) -> DISCONNECT. Volontairement sans abonnement : le service
n'a besoin que d'émettre des événements de détection.

Configuration (variables d'environnement) :
    MQTT_ENABLED   -- "true"/"false" : active la publication (défaut: false)
    MQTT_HOST      -- adresse du broker (défaut: 127.0.0.1)
    MQTT_PORT      -- port du broker (défaut: 1883)
    MQTT_USER      -- utilisateur (optionnel)
    MQTT_PASSWORD  -- mot de passe (optionnel)
    MQTT_TOPIC     -- topic de publication (défaut: awtrix-flights/detection)
    MQTT_CLIENT_ID -- identifiant de session (défaut: awtrix-flights)
    MQTT_TIMEOUT_S -- timeout réseau en secondes (défaut: 3)

Exemple :
    from mqtt_client import publish
    ok = publish("awtrix-flights/detection", '{"callsign":"AFR123"}')

Ne lève JAMAIS d'exception : retourne False en cas d'échec réseau/protocole.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import socket
import struct
import time

logger = logging.getLogger("mqtt_client")

MQTT_PROTOCOL_LEVEL = 4  # MQTT 3.1.1


class MqttError(Exception):
    """Erreur réseau/protocole MQTT (jamais propagée hors de publish())."""


def _config() -> dict:
    """Lit la configuration MQTT depuis l'environnement."""
    return {
        "host": os.environ.get("MQTT_HOST", "").strip() or "127.0.0.1",
        "port": _int_env("MQTT_PORT", 1883),
        "username": os.environ.get("MQTT_USER", "").strip() or None,
        "password": os.environ.get("MQTT_PASSWORD", "") or None,
        "client_id": os.environ.get("MQTT_CLIENT_ID", "").strip() or "awtrix-flights",
        "timeout": _float_env("MQTT_TIMEOUT_S", 3.0),
    }


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        logger.warning("%s invalide (%r), défaut %s", name, raw, default)
        return default


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    try:
        return float(raw) if raw else default
    except ValueError:
        logger.warning("%s invalide (%r), défaut %s", name, raw, default)
        return default


def _encode_utf8(text: str) -> bytes:
    """Chaîne UTF-8 préfixée par sa longueur (format MQTT)."""
    data = text.encode("utf-8")
    return struct.pack(">H", len(data)) + data


def _remaining_length(payload: bytes) -> bytes:
    """Encodage de la longueur restante (1 à 4 octets, variable length)."""
    out = bytearray()
    value = len(payload)
    while True:
        digit = value % 128
        value //= 128
        if value > 0:
            digit |= 0x80
        out.append(digit)
        if value == 0:
            return bytes(out)


def _read_exact(sock: socket.socket, n: int) -> bytes:
    """Lit exactement n octets (boucle sur les recv partiels)."""
    chunks = []
    remaining = n
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            raise MqttError("connexion fermée par le broker")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _read_packet(sock: socket.socket) -> tuple[int, bytes]:
    """Lit un paquet MQTT complet (header + longueur variable + corps)."""
    first = _read_exact(sock, 1)[0]
    multiplier = 1
    length = 0
    while True:
        digit = _read_exact(sock, 1)[0]
        length += (digit & 0x7F) * multiplier
        if not (digit & 0x80):
            break
        multiplier *= 128
    body = _read_exact(sock, length)
    return first, body


def _connect(sock: socket.socket, cfg: dict) -> None:
    """Envoie CONNECT et vérifie CONNACK (code 0 = accepté)."""
    flags = 0x02  # clean session
    if cfg["username"]:
        flags |= 0x80
        if cfg["password"] is not None:
            flags |= 0x40
    payload = (
        _encode_utf8("MQTT")
        + bytes([MQTT_PROTOCOL_LEVEL, flags])
        + struct.pack(">H", 60)  # keepalive 60 s
        + _encode_utf8(cfg["client_id"])
    )
    if cfg["username"]:
        payload += _encode_utf8(cfg["username"])
        if cfg["password"] is not None:
            payload += _encode_utf8(cfg["password"])

    packet = bytes([0x10]) + _remaining_length(payload) + payload
    sock.sendall(packet)

    header, body = _read_packet(sock)
    if header != 0x20:
        raise MqttError(f"CONNACK attendu, reçu 0x{header:02x}")
    if len(body) < 2:
        raise MqttError("CONNACK tronqué")
    return_code = body[1]
    if return_code != 0:
        raise MqttError(f"connexion refusée par le broker (code {return_code})")


def _publish(sock: socket.socket, topic: str, payload: bytes) -> None:
    """PUBLISH QoS 0 (pas d'attente de PUBACK)."""
    body = _encode_utf8(topic) + payload
    packet = bytes([0x30]) + _remaining_length(body) + body
    sock.sendall(packet)


def publish(
    topic: str | None = None,
    payload: str | dict | bytes = "",
    **overrides,
) -> bool:
    """Publie un message sur le broker MQTT configuré.

    Args:
        topic: topic cible (défaut: MQTT_TOPIC, sinon awtrix-flights/detection).
        payload: chaîne, dict (sérialisé en JSON) ou bytes.
        **overrides: surcharge ponctuelle (host, port, username, password,
            client_id, timeout) — utile pour les tests.

    Retourne True si la publication a abouti, False sinon (jamais d'exception).
    """
    topic = (topic or os.environ.get("MQTT_TOPIC", "")).strip() or "awtrix-flights/detection"
    cfg = _config()
    cfg.update({k: v for k, v in overrides.items() if v is not None})

    if isinstance(payload, dict):
        body = json.dumps(payload).encode("utf-8")
    elif isinstance(payload, str):
        body = payload.encode("utf-8")
    else:
        body = payload

    sock = None
    try:
        sock = socket.create_connection((cfg["host"], cfg["port"]), timeout=cfg["timeout"])
        sock.settimeout(cfg["timeout"])
        _connect(sock, cfg)
        _publish(sock, topic, body)
        # Petit délai pour laisser le broker accuser réception avant DISCONNECT.
        time.sleep(0.05)
        sock.sendall(bytes([0xE0, 0x00]))  # DISCONNECT
        logger.info(
            "MQTT: publié %d octets sur %s (%s:%s)", len(body), topic, cfg["host"], cfg["port"]
        )
        return True
    except (OSError, MqttError, struct.error) as exc:
        logger.warning("MQTT: échec de publication sur %s:%s : %s", cfg["host"], cfg["port"], exc)
        return False
    finally:
        if sock is not None:
            with contextlib.suppress(OSError):
                sock.close()
