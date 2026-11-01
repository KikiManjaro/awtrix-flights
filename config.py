#!/usr/bin/env python3
"""Centralized configuration parsing and validation.

All environment variables are read and validated in one place with
clear error messages and strict bounds. The rest of the codebase
should call :func:`load_config` at startup.

No external dependencies — standard library only.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


class ConfigError(ValueError):
    """Invalid configuration (bad env var)."""


def _parse_bool(raw: str | None, default: bool = False) -> bool:
    if raw is None:
        return default
    s = raw.strip().lower()
    if not s:
        return default
    if s in ("1", "true", "yes", "on"):
        return True
    if s in ("0", "false", "no", "off"):
        return False
    raise ConfigError(f"Boolean invalide {raw!r} (attendu true/false)")


def _parse_float_env(name: str, raw: str | None, default: float | None, minimum: float | None = None, maximum: float | None = None) -> float:
    if raw is None or not raw.strip():
        if default is None:
            raise ConfigError(f"{name} est obligatoire")
        return default
    try:
        v = float(raw.strip())
    except ValueError:
        raise ConfigError(f"{name} doit être un nombre (reçu {raw!r})") from None
    if minimum is not None and v < minimum:
        raise ConfigError(f"{name} doit être >= {minimum} (reçu {v})")
    if maximum is not None and v > maximum:
        raise ConfigError(f"{name} doit être <= {maximum} (reçu {v})")
    return v


def _parse_int_env(name: str, raw: str | None, default: int | None, minimum: int | None = None, maximum: int | None = None) -> int:
    if raw is None or not raw.strip():
        if default is None:
            raise ConfigError(f"{name} est obligatoire")
        return default
    try:
        v = int(raw.strip())
    except ValueError:
        raise ConfigError(f"{name} doit être un entier (reçu {raw!r})") from None
    if minimum is not None and v < minimum:
        raise ConfigError(f"{name} doit être >= {minimum} (reçu {v})")
    if maximum is not None and v > maximum:
        raise ConfigError(f"{name} doit être <= {maximum} (reçu {v})")
    return v


@dataclass(frozen=True)
class Config:
    home_lat: float
    home_lon: float
    radius_km: float = 5.0
    min_alt_m: float = 300.0
    awtrix_host: str = "192.168.1.27"
    awtrix_port: int = 80
    poll_interval_s: float = 15.0
    notify_cooldown_s: float = 60.0
    log_level: str = "INFO"
    log_format: str = "text"
    mqtt_enabled: bool = False
    mqtt_host: str = "127.0.0.1"
    mqtt_port: int = 1883


_VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "WARN", "ERROR", "CRITICAL"}
_VALID_LOG_FORMATS = {"text", "json"}


def load_config(env: dict[str, str] | None = None) -> Config:
    """Load and validate configuration from environment (or *env* dict for tests).

    Raises :class:`ConfigError` (a :class:`ValueError`) on any invalid value.
    """
    get = (env.get if env is not None else os.environ.get)

    # Required coordinates
    lat_raw = get("HOME_LAT")
    lon_raw = get("HOME_LON")
    if not lat_raw or not lat_raw.strip() or not lon_raw or not lon_raw.strip():
        raise ConfigError("HOME_LAT et HOME_LON sont obligatoires")
    home_lat = _parse_float_env("HOME_LAT", lat_raw, None, minimum=-90, maximum=90)
    home_lon = _parse_float_env("HOME_LON", lon_raw, None, minimum=-180, maximum=180)

    radius_km = _parse_float_env("RADIUS_KM", get("RADIUS_KM"), 5.0, minimum=0.01, maximum=1000)
    min_alt_m = _parse_float_env("MIN_ALT_M", get("MIN_ALT_M"), 300.0, minimum=0, maximum=20000)
    poll_interval_s = _parse_float_env("POLL_INTERVAL_SEC", get("POLL_INTERVAL_SEC"), 15.0, minimum=1.0, maximum=3600)
    notify_cooldown_s = _parse_float_env("NOTIFY_COOLDOWN_SEC", get("NOTIFY_COOLDOWN_SEC"), 60.0, minimum=0, maximum=3600)

    awtrix_host = (get("AWTRIX_HOST") or "").strip() or "192.168.1.27"
    # Validate each host is non-empty; port checked below
    hosts = [h.strip() for h in awtrix_host.split(",") if h.strip()]
    if not hosts:
        raise ConfigError("AWTRIX_HOST ne peut pas être vide")
    awtrix_port = _parse_int_env("AWTRIX_PORT", get("AWTRIX_PORT"), 80, minimum=1, maximum=65535)

    log_level = (get("LOG_LEVEL") or "").strip().upper() or "INFO"
    if log_level not in _VALID_LOG_LEVELS:
        raise ConfigError(f"LOG_LEVEL invalide {log_level!r} (attendu DEBUG/INFO/WARNING/ERROR/CRITICAL)")
    log_format = (get("LOG_FORMAT") or "").strip().lower() or "text"
    if log_format not in _VALID_LOG_FORMATS:
        raise ConfigError(f"LOG_FORMAT invalide {log_format!r} (attendu text/json)")

    mqtt_enabled = _parse_bool(get("MQTT_ENABLED"), default=False)
    mqtt_host = (get("MQTT_HOST") or "").strip() or "127.0.0.1"
    mqtt_port = _parse_int_env("MQTT_PORT", get("MQTT_PORT"), 1883, minimum=1, maximum=65535)

    return Config(
        home_lat=home_lat,
        home_lon=home_lon,
        radius_km=radius_km,
        min_alt_m=min_alt_m,
        awtrix_host=",".join(hosts),
        awtrix_port=awtrix_port,
        poll_interval_s=poll_interval_s,
        notify_cooldown_s=notify_cooldown_s,
        log_level=log_level,
        log_format=log_format,
        mqtt_enabled=mqtt_enabled,
        mqtt_host=mqtt_host,
        mqtt_port=mqtt_port,
    )
