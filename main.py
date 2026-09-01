#!/usr/bin/env python3
"""Boucle principale : détection des avions au-dessus de la maison -> AWTRIX.

Relie les deux modules du projet :
    flights.py        -- get_aircraft_overhead() interroge OpenSky Network
    awtrix_client.py  -- notify_aircraft() publie un message sur l'écran AWTRIX

Configuration (variables d'environnement) :
    HOME_LAT            latitude de la maison, degrés décimaux (obligatoire)
    HOME_LON            longitude de la maison, degrés décimaux (obligatoire)
    RADIUS_KM           rayon de détection en km (défaut 5, géré par flights)
    MIN_ALT_M           altitude minimale en m (défaut 300, géré par flights)
    AWTRIX_HOST         hôte(s) AWTRIX séparés par des virgules
                        (défaut 192.168.1.27, géré par awtrix_client)
    AWTRIX_PORT         port HTTP de l'API (défaut 80, géré par awtrix_client)
    POLL_INTERVAL_SEC   période d'interrogation en secondes (défaut 15)
    NOTIFY_COOLDOWN_SEC délai minimal entre 2 affichages du même callsign
                        (défaut 60) -- évite le spam quand un avion reste
                        dans la zone plusieurs cycles de suite.
    LOG_LEVEL           niveau de log : DEBUG/INFO/WARNING/ERROR (défaut INFO)
    LOG_FORMAT          format de log : text (défaut) ou json
    DRY_RUN             si true, n'envoie rien (équivalent --dry-run)

CLI :
    --dry-run           n'envoie rien à l'AWTRIX, affiche ce qui serait envoyé
    --once              exécute un seul cycle puis s'arrête (utile pour CI/cron)
    --validate-config   valide la configuration et s'arrête (code 0 ok, 2 erreur)
    --log-level LEVEL   surcharge LOG_LEVEL pour ce lancement

Comportement :
    - Interrogation immédiate au démarrage, puis toutes les POLL_INTERVAL_SEC.
    - Chaque avion détecté est affiché une fois ; le même callsign n'est pas
      réaffiché avant NOTIFY_COOLDOWN_SEC.
    - Aucun message d'effacement n'est envoyé quand le ciel est vide :
      l'affichage reste tranquille.
    - Ctrl-C ou SIGTERM -> arrêt propre (code 0).

Dépendances : uniquement la bibliothèque standard.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
import time

import awtrix_client
import flights
import mqtt_client

logger = logging.getLogger("main")

DEFAULT_POLL_INTERVAL_S = 15.0
DEFAULT_NOTIFY_COOLDOWN_S = 60.0
MIN_POLL_INTERVAL_S = 1.0
MIN_NOTIFY_COOLDOWN_S = 0.0
# Nombre maximum d'avions affichés par cycle de polling. Au-delà, les
# avions supplémentaires sont ignorés (cooldown marqué pour éviter le
# spam au cycle suivant). Limite conçue pour ne pas surcharger l'ESP32
# des AWTRIX avec trop de payloads draw en rafale.
MAX_NOTIFY_PER_CYCLE = 3

# Délai minimum (secondes) entre chaque envoi AWTRIX dans un même cycle.
# Donne à l'ESP32 le temps de traiter le payload précédent (JSON parser +
# rendu draw) avant de recevoir le suivant.
SEND_DELAY_S = 0.5

# Durée de rétention des entrées du tracker (nettoyage mémoire) : un avion
# revu au-delà de cette fenêtre est considéré comme une nouvelle visite.
TRACKER_RETENTION_S = 10 * 60.0

_LOG_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "WARN": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


class JsonFormatter(logging.Formatter):
    """Formateur JSON minimaliste (une ligne JSON par log)."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0] is not None:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def _resolve_log_level(raw: str | None) -> int | None:
    if not raw:
        return None
    return _LOG_LEVELS.get(raw.strip().upper())


def _setup_logging(cli_level: str | None = None, json_logs: bool | None = None) -> None:
    env_level_raw = os.environ.get("LOG_LEVEL", "").strip()
    level = _resolve_log_level(cli_level) if cli_level else _resolve_log_level(env_level_raw)
    if level is None:
        if cli_level and cli_level.strip().upper() not in _LOG_LEVELS:
            print(f"Invalid --log-level {cli_level!r}, using INFO", file=sys.stderr)
        elif env_level_raw and env_level_raw.upper() not in _LOG_LEVELS:
            print(f"Invalid LOG_LEVEL {env_level_raw!r}, using INFO", file=sys.stderr)
        level = logging.INFO
    use_json = json_logs
    if use_json is None:
        use_json = os.environ.get("LOG_FORMAT", "").strip().lower() == "json"
    handler = logging.StreamHandler()
    if use_json:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="awtrix-flights",
        description="Affiche les avions au-dessus de la maison sur AWTRIX 3 (OpenSky Network).",
    )
    p.add_argument("--dry-run", action="store_true", help="n'envoie rien, affiche ce qui serait envoyé et quitte")
    p.add_argument("--once", action="store_true", help="exécute un seul cycle de polling puis s'arrête")
    p.add_argument("--validate-config", action="store_true", help="valide HOME_LAT/HOME_LON et les intervalles puis quitte (0 ok, 2 erreur)")
    p.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"], help="niveau de log pour ce lancement")
    p.add_argument("--json-logs", action="store_true", help="logs au format JSON (une ligne par événement)")
    return p


class CooldownTracker:
    """Mémorise la dernière notification par callsign pour éviter le spam.

    Un callsign est « dû » (due) si aucune notification n'a été tentée
    pour lui depuis au moins ``cooldown_s`` secondes. La fenêtre est
    enregistrée même quand l'envoi échoue : on ne martèle pas un écran
    hors ligne à chaque cycle, on réessaie au rythme du cooldown.
    """

    def __init__(self, cooldown_s: float = DEFAULT_NOTIFY_COOLDOWN_S) -> None:
        self.cooldown_s = cooldown_s
        self._last_notified: dict[str, float] = {}

    def due(self, callsign: str, now: float | None = None) -> bool:
        """True si le callsign peut être affiché (hors fenêtre de cooldown)."""
        now = time.time() if now is None else now
        last = self._last_notified.get(callsign)
        if last is None:
            return True
        return (now - last) >= self.cooldown_s

    def mark(self, callsign: str, now: float | None = None) -> None:
        """Enregistre la tentative de notification pour ce callsign."""
        now = time.time() if now is None else now
        self._last_notified[callsign] = now
        self._prune(now)

    def remaining(self, callsign: str, now: float | None = None) -> float:
        """Secondes restantes avant la prochaine notification possible."""
        now = time.time() if now is None else now
        last = self._last_notified.get(callsign)
        if last is None:
            return 0.0
        return max(0.0, self.cooldown_s - (now - last))

    def _prune(self, now: float) -> None:
        """Oublie les callsigns notifiés il y a longtemps (visites terminées)."""
        retention = max(self.cooldown_s * 4.0, TRACKER_RETENTION_S)
        stale = [cs for cs, ts in self._last_notified.items() if (now - ts) >= retention]
        for cs in stale:
            del self._last_notified[cs]

    def __len__(self) -> int:
        return len(self._last_notified)


def _mqtt_enabled() -> bool:
    """Publication MQTT activée ? (MQTT_ENABLED, défaut false)."""
    raw = os.environ.get("MQTT_ENABLED", "").strip().lower()
    if not raw:
        return False
    return raw not in ("false", "0", "no", "off")


def _publish_mqtt(event: str, payload: dict) -> None:
    """Publie un événement MQTT (best effort, jamais bloquant)."""
    if not _mqtt_enabled():
        return
    topic = os.environ.get("MQTT_TOPIC_PREFIX", "").strip() or "awtrix-flights"
    mqtt_client.publish(f"{topic}/{event}", payload)


def _validate_base_config() -> tuple[float, float]:
    if not (os.environ.get("HOME_LAT") and os.environ.get("HOME_LON")):
        raise ValueError("HOME_LAT et HOME_LON sont obligatoires (voir le README).")
    poll = _parse_float_env("POLL_INTERVAL_SEC", DEFAULT_POLL_INTERVAL_S, MIN_POLL_INTERVAL_S)
    cd = _parse_float_env("NOTIFY_COOLDOWN_SEC", DEFAULT_NOTIFY_COOLDOWN_S, MIN_NOTIFY_COOLDOWN_S)
    try:
        float(os.environ["HOME_LAT"])
        float(os.environ["HOME_LON"])
    except ValueError:
        raise ValueError("HOME_LAT et HOME_LON doivent être des nombres décimaux.") from None
    return poll, cd


def run_once(
    tracker: CooldownTracker,
    get_aircraft=None,
    notify=None,
    now: float | None = None,
    dry_run: bool = False,
) -> int:
    """Un cycle complet : interrogation OpenSky puis notifications AWTRIX.

    Retourne le nombre de notifications envoyées (0 si aucun avion, si le
    ciel est vide l'affichage n'est pas touché).

    - ``ValueError`` (configuration invalide : HOME_LAT/HOME_LON...) remonte
      vers main() qui stoppe proprement le service.
    - Toute autre exception inattendue est journalisée et le cycle continue
      (le service ne doit jamais mourir sur un pic de réseau).
    - Si ``dry_run`` est True, n'appelle jamais ``notify`` : affiche le
      payload qui serait envoyé et compte comme ``sent``.
    """
    if get_aircraft is None:
        get_aircraft = flights.get_aircraft_overhead
    if notify is None:
        notify = awtrix_client.notify_aircraft
    now = time.time() if now is None else now

    try:
        aircraft = get_aircraft()
    except ValueError:
        raise  # erreur de configuration -> arrêt immédiat dans main()
    except Exception as exc:  # noqa: BLE001 - filet de sécurité du service
        logger.exception("Erreur inattendue pendant l'interrogation : %s", exc)
        return 0

    if not aircraft:
        logger.info(
            "Ciel vide dans la zone : %d avion(s) détecté(s), affichage laissé tranquille.",
            len(aircraft),
        )
        return 0

    sent = 0
    skipped_no_callsign = 0
    skipped_cooldown = 0
    skipped_limit = 0
    for plane in aircraft:
        callsign = (plane.get("callsign") or "").strip()
        if not callsign:
            # Sans callsign on ne peut ni dédupliquer ni afficher un message
            # utile ("??" à l'écran) -> on ignore.
            skipped_no_callsign += 1
            logger.debug("Avion sans callsign ignoré : %s", plane.get("country"))
            continue
        if not tracker.due(callsign, now):
            skipped_cooldown += 1
            logger.debug(
                "Callsign %s déjà affiché récemment (cooldown %ss), ignoré ce cycle.",
                callsign,
                int(tracker.remaining(callsign, now)),
            )
            continue
        if sent >= MAX_NOTIFY_PER_CYCLE:
            skipped_limit += 1
            # Marquer le cooldown pour ne pas le revoir au cycle suivant
            tracker.mark(callsign, now)
            continue
        if dry_run:
            payload = awtrix_client.build_payload(plane)
            print(f"[dry-run] would notify {callsign}: {json.dumps(payload, ensure_ascii=False)}")
            tracker.mark(callsign, now)
            sent += 1
            continue
        ok = notify(plane)
        tracker.mark(callsign, now)
        if sent > 0:
            time.sleep(SEND_DELAY_S)
        if ok:
            sent += 1
            speed_ms = plane.get("speed_ms")
            if speed_ms is not None:
                try:
                    speed_kmh = int(round(float(speed_ms) * 3.6))
                except (TypeError, ValueError):
                    speed_kmh = None
            else:
                speed_kmh = None
            _alt = plane.get("altitude_m")
            _alt_str = str(_alt) if _alt is not None else "?"
            _dist = plane.get("distance_km")
            _dist_str = f"{_dist:.2f}" if _dist is not None else "?"
            logger.info(
                "DÉTECTION : %s %s à %sm, %s km, %s km/h -> affiché",
                callsign,
                plane.get("country") or "",
                _alt_str,
                _dist_str,
                speed_kmh if speed_kmh is not None else "?",
            )
            _publish_mqtt(
                "detection",
                {
                    **plane,
                    "speed_kmh": speed_kmh,
                    "notified_at": int(time.time()),
                },
            )
        else:
            logger.warning(
                "Échec d'affichage pour %s (écran injoignable ?) ; nouvel essai dans %ss.",
                callsign,
                int(tracker.cooldown_s),
            )

    logger.info(
        "%d avion(s) dans la zone : %d affiché(s), %d ignoré(s) (cooldown), %d ignoré(s) (limite %d), %d sans callsign.",
        len(aircraft),
        sent,
        skipped_cooldown,
        skipped_limit,
        MAX_NOTIFY_PER_CYCLE,
        skipped_no_callsign,
    )
    return sent


def _parse_float_env(name: str, default: float, minimum: float) -> float:
    """Lit une variable d'environnement flottante avec message clair."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        raise ValueError(f"{name} doit être un nombre (reçu {raw!r}).") from None
    if value < minimum:
        raise ValueError(f"{name} doit être >= {minimum} (reçu {value}).")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv if argv is not None else [])
    env_dry_run = os.environ.get("DRY_RUN", "").strip().lower() not in ("", "false", "0", "no", "off")
    dry_run = args.dry_run or env_dry_run
    _setup_logging(cli_level=args.log_level, json_logs=args.json_logs or None)
    if args.validate_config:
        try:
            _validate_base_config()
            lat = float(os.environ.get("HOME_LAT", ""))
            lon = float(os.environ.get("HOME_LON", ""))
            if not -90 <= lat <= 90:
                raise ValueError(f"HOME_LAT must be between -90 and 90 (got {lat}).")
            if not -180 <= lon <= 180:
                raise ValueError(f"HOME_LON must be between -180 and 180 (got {lon}).")
            print("Configuration OK")
            return 0
        except ValueError as exc:
            print(f"Configuration invalide : {exc}", file=sys.stderr)
            return 2

    if not (os.environ.get("HOME_LAT") and os.environ.get("HOME_LON")):
        logger.error(
            "Configuration incomplète : HOME_LAT et HOME_LON sont obligatoires (voir le README)."
        )
        return 2

    try:
        poll_interval = _parse_float_env(
            "POLL_INTERVAL_SEC", DEFAULT_POLL_INTERVAL_S, MIN_POLL_INTERVAL_S
        )
        notify_cooldown = _parse_float_env(
            "NOTIFY_COOLDOWN_SEC", DEFAULT_NOTIFY_COOLDOWN_S, MIN_NOTIFY_COOLDOWN_S
        )
    except ValueError as exc:
        logger.error("Configuration invalide : %s", exc)
        return 2

    tracker = CooldownTracker(notify_cooldown)
    awtrix_host = os.environ.get("AWTRIX_HOST") or "192.168.1.27 (défaut)"
    radius = os.environ.get("RADIUS_KM")
    min_alt = os.environ.get("MIN_ALT_M")
    radius_label = f"{radius} km" if radius else "5 km (défaut)"
    min_alt_label = f"{min_alt} m" if min_alt else "300 m (défaut)"
    mode_label = ""
    if dry_run:
        mode_label = " [dry-run]"
    elif args.once:
        mode_label = " [once]"
    logger.info(
        "Surveillance des avions démarrée%s : lat=%s lon=%s "
        "rayon=%s alt_min=%s, poll=%ss, cooldown=%ss, AWTRIX=%s",
        mode_label,
        os.environ.get("HOME_LAT"),
        os.environ.get("HOME_LON"),
        radius_label,
        min_alt_label,
        int(poll_interval),
        int(notify_cooldown),
        awtrix_host,
    )

    if not dry_run:
        _publish_mqtt(
            "status",
            {"state": "online", "started_at": int(time.time())},
        )

    # Ctrl-C (SIGINT) et SIGTERM (docker stop, systemd stop) -> arrêt propre.
    def _request_stop(signum, frame):  # noqa: ARG001
        raise KeyboardInterrupt

    signal.signal(signal.SIGINT, _request_stop)
    signal.signal(signal.SIGTERM, _request_stop)

    if args.once or dry_run:
        try:
            n = run_once(tracker, dry_run=dry_run)
            if dry_run:
                print(f"[dry-run] cycle terminé : {n} notification(s) aurait(aient) été envoyée(s)")
            return 0
        except ValueError as exc:
            logger.error("Configuration invalide : %s", exc)
            return 2

    try:
        while True:
            run_once(tracker)
            time.sleep(poll_interval)
    except KeyboardInterrupt:
        logger.info("Arrêt demandé (Ctrl-C / SIGTERM), sortie propre.")
        if not dry_run:
            _publish_mqtt(
                "status",
                {"state": "offline", "stopped_at": int(time.time())},
            )
        return 0
    except ValueError as exc:
        logger.error("Configuration invalide : %s", exc)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
