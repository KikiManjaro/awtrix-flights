#!/usr/bin/env python3
"""Tests du mode nuit (silence de l'écran pendant une plage horaire).

Aucun réseau : get_aircraft_overhead et notify_aircraft sont mockés.
Lancer : python3 -m unittest tests.test_night_mode -v
"""

import unittest
from datetime import datetime, timezone, tzinfo
from unittest import mock
from zoneinfo import ZoneInfo

import main

PARIS = ZoneInfo("Europe/Paris")


def _plane(callsign="AFR123"):
    return {
        "callsign": callsign,
        "country": "France",
        "altitude_m": 10000,
        "speed_ms": 230.0,
        "distance_km": 1.5,
        "last_contact": 1786700000,
    }


def _at(hour, minute, second=0, tz: tzinfo = PARIS):
    """Datetime conscient dans le fuseau donné (par défaut Europe/Paris)."""
    return datetime(2026, 1, 15, hour, minute, second, tzinfo=tz)


class NormalWindowTest(unittest.TestCase):
    """Plage qui ne traverse pas minuit (ex. 09:00 -> 17:00)."""

    def test_inside_window(self):
        self.assertTrue(main.in_night_window(_at(12, 0), "09:00", "17:00"))

    def test_before_window(self):
        self.assertFalse(main.in_night_window(_at(8, 59), "09:00", "17:00"))

    def test_after_window(self):
        self.assertFalse(main.in_night_window(_at(17, 1), "09:00", "17:00"))

    def test_start_is_inclusive(self):
        self.assertTrue(main.in_night_window(_at(9, 0), "09:00", "17:00"))
        self.assertTrue(main.in_night_window(_at(9, 0, 30), "09:00", "17:00"))

    def test_end_is_exclusive(self):
        self.assertFalse(main.in_night_window(_at(17, 0), "09:00", "17:00"))
        self.assertTrue(main.in_night_window(_at(16, 59, 59), "09:00", "17:00"))


class MidnightWindowTest(unittest.TestCase):
    """Passage de minuit : 23:00 -> 07:00 (le cas réel de la chambre)."""

    def test_late_evening_is_night(self):
        self.assertTrue(main.in_night_window(_at(23, 30), "23:00", "07:00"))

    def test_after_midnight_is_night(self):
        self.assertTrue(main.in_night_window(_at(0, 30), "23:00", "07:00"))
        self.assertTrue(main.in_night_window(_at(3, 0), "23:00", "07:00"))

    def test_last_second_before_end_is_night(self):
        self.assertTrue(main.in_night_window(_at(6, 59, 59), "23:00", "07:00"))

    def test_start_boundary_is_night(self):
        self.assertTrue(main.in_night_window(_at(23, 0), "23:00", "07:00"))

    def test_end_boundary_is_day(self):
        self.assertFalse(main.in_night_window(_at(7, 0), "23:00", "07:00"))

    def test_before_start_is_day(self):
        self.assertFalse(main.in_night_window(_at(22, 59), "23:00", "07:00"))

    def test_after_end_is_day(self):
        self.assertFalse(main.in_night_window(_at(7, 0, 1), "23:00", "07:00"))
        self.assertFalse(main.in_night_window(_at(12, 0), "23:00", "07:00"))


class DisabledAndInvalidWindowTest(unittest.TestCase):
    """Plage vide ou mal formée : le mode nuit ne doit jamais couper l'écran."""

    def test_empty_start(self):
        self.assertFalse(main.in_night_window(_at(3, 0), "", "07:00"))

    def test_empty_end(self):
        self.assertFalse(main.in_night_window(_at(3, 0), "23:00", ""))

    def test_both_empty(self):
        self.assertFalse(main.in_night_window(_at(3, 0), "", ""))

    def test_equal_bounds_disable_night(self):
        self.assertFalse(main.in_night_window(_at(3, 0), "23:00", "23:00"))

    def test_unparsable_start(self):
        self.assertFalse(main.in_night_window(_at(3, 0), "abc", "07:00"))

    def test_unparsable_end(self):
        self.assertFalse(main.in_night_window(_at(3, 0), "23:00", "25:00"))

    def test_missing_colon(self):
        self.assertFalse(main.in_night_window(_at(3, 0), "2300", "0700"))

    def test_seconds_not_accepted(self):
        self.assertFalse(main.in_night_window(_at(3, 0), "23:00:00", "07:00:00"))

    def test_whitespace_around_bounds_is_tolerated(self):
        self.assertTrue(main.in_night_window(_at(3, 0), " 23:00 ", " 07:00 "))


class TimezoneTest(unittest.TestCase):
    """La plage suit l'heure murale du datetime reçu ; TZ fait la conversion."""

    def test_wall_clock_of_the_datetime_is_used(self):
        # Convention : ``in_night_window`` lit l'heure murale de ``now``.
        # C'est ``_local_datetime`` qui applique TZ (cf. test ci-dessous).
        self.assertTrue(main.in_night_window(_at(23, 30), "23:00", "07:00"))
        self.assertFalse(
            main.in_night_window(_at(22, 30, tz=timezone.utc), "23:00", "07:00"),
        )

    def test_tz_env_converts_utc_instant_into_local_wall_clock(self):
        # 22:30 UTC = 23:30 à Paris : la conversion TZ met bien dans la plage.
        instant = _at(22, 30, tz=timezone.utc)
        with mock.patch.dict(main.os.environ, {"TZ": "Europe/Paris"}, clear=False):
            local = main._local_datetime(instant.timestamp())
        self.assertEqual((local.hour, local.minute), (23, 30))
        self.assertTrue(main.in_night_window(local, "23:00", "07:00"))

    def test_tz_env_utc_keeps_the_instant_out_of_the_window(self):
        # Le même instant avec TZ=UTC (22:30) reste hors plage : le fuseau
        # compte vraiment, on ne compare pas des heures UTC à des heures locales.
        instant = _at(22, 30, tz=timezone.utc)
        with mock.patch.dict(main.os.environ, {"TZ": "UTC"}, clear=False):
            local = main._local_datetime(instant.timestamp())
        self.assertFalse(main.in_night_window(local, "23:00", "07:00"))

    def test_naive_datetime_is_treated_as_local_wall_clock(self):
        naive = datetime(2026, 1, 15, 3, 0)
        self.assertTrue(main.in_night_window(naive, "23:00", "07:00"))

    def test_summer_time_shift_is_handled(self):
        # Juillet : Paris est en UTC+2, 22:30 UTC = 00:30 local -> nuit.
        summer = datetime(2026, 7, 15, 22, 30, tzinfo=timezone.utc)
        with mock.patch.dict(main.os.environ, {"TZ": "Europe/Paris"}, clear=False):
            local = main._local_datetime(summer.timestamp())
        self.assertEqual(local.hour, 0)
        self.assertTrue(main.in_night_window(local, "23:00", "07:00"))


class HelpersTest(unittest.TestCase):
    def test_parse_hhmm_accepts_single_digit_hour(self):
        self.assertEqual(main._parse_hhmm("7:30").strftime("%H:%M"), "07:30")

    def test_parse_hhmm_rejects_out_of_range(self):
        for raw in ("24:00", "12:60", "abc", "", "0700"):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                main._parse_hhmm(raw)

    def test_night_config_reads_and_strips_env(self):
        env = {"NIGHT_START": " 23:00 ", "NIGHT_END": "07:00"}
        with mock.patch.dict(main.os.environ, env, clear=False):
            self.assertEqual(main._night_config(), ("23:00", "07:00"))

    def test_night_config_default_is_empty(self):
        with mock.patch.dict(main.os.environ, {}, clear=True):
            self.assertEqual(main._night_config(), ("", ""))

    def test_validate_night_config_ok(self):
        env = {"NIGHT_START": "23:00", "NIGHT_END": "07:00"}
        with mock.patch.dict(main.os.environ, env, clear=False):
            self.assertEqual(main._validate_night_config(), ("23:00", "07:00"))

    def test_validate_night_config_absent_is_ok(self):
        with mock.patch.dict(main.os.environ, {}, clear=True):
            self.assertEqual(main._validate_night_config(), ("", ""))

    def test_validate_night_config_single_bound_is_error(self):
        with (
            mock.patch.dict(main.os.environ, {"NIGHT_START": "23:00"}, clear=True),
            self.assertRaises(ValueError),
        ):
            main._validate_night_config()

    def test_validate_night_config_bad_format_names_the_variable(self):
        env = {"NIGHT_START": "23:00", "NIGHT_END": "7h"}
        with (
            mock.patch.dict(main.os.environ, env, clear=False),
            self.assertRaises(ValueError) as ctx,
        ):
            main._validate_night_config()
        self.assertIn("NIGHT_END", str(ctx.exception))

    def test_night_mode_label(self):
        with mock.patch.dict(
            main.os.environ, {"NIGHT_START": "23:00", "NIGHT_END": "07:00"}, clear=False
        ):
            self.assertEqual(main._night_mode_label(), "23:00 -> 07:00")
        with mock.patch.dict(main.os.environ, {}, clear=True):
            self.assertEqual(main._night_mode_label(), "")
        with mock.patch.dict(
            main.os.environ, {"NIGHT_START": "23:00", "NIGHT_END": "23:00"}, clear=False
        ):
            self.assertEqual(main._night_mode_label(), "")

    def test_resolve_tz_uses_tz_env(self):
        with mock.patch.dict(main.os.environ, {"TZ": "Europe/Paris"}, clear=False):
            self.assertEqual(str(main._resolve_tz()), "Europe/Paris")

    def test_resolve_tz_unknown_falls_back_without_spamming(self):
        main._TZ_WARNED.clear()
        with (
            mock.patch.dict(main.os.environ, {"TZ": "Nowhere/Unknown"}, clear=False),
            self.assertLogs("main", level="WARNING") as logs,
        ):
            self.assertIsNotNone(main._resolve_tz())
            self.assertIsNotNone(main._resolve_tz())
        # un seul avertissement malgré deux résolutions (pas de spam par cycle)
        self.assertEqual(len(logs.records), 1)
        main._TZ_WARNED.clear()

    def test_local_datetime_applies_tz_env(self):
        with mock.patch.dict(main.os.environ, {"TZ": "Europe/Paris"}, clear=False):
            stamp = datetime(2026, 1, 15, 23, 30, tzinfo=PARIS).timestamp()
            local = main._local_datetime(stamp)
        self.assertEqual(local.hour, 23)
        self.assertEqual(local.minute, 30)


class RunOnceNightTest(unittest.TestCase):
    """Le cycle complet en mode nuit : polling oui, envois non."""

    def setUp(self):
        self.tracker = main.CooldownTracker(cooldown_s=60)
        # 23:30 heure de Paris, dans la plage 23:00 -> 07:00.
        self.night_ts = datetime(2026, 1, 15, 23, 30, tzinfo=PARIS).timestamp()
        self.day_ts = datetime(2026, 1, 15, 12, 0, tzinfo=PARIS).timestamp()
        self.env = {"TZ": "Europe/Paris", "NIGHT_START": "23:00", "NIGHT_END": "07:00"}

    def test_night_cycle_skips_notifications_but_keeps_polling(self):
        get_aircraft = mock.Mock(return_value=[_plane(), _plane(callsign="DLH456")])
        notify = mock.Mock(return_value=True)
        with (
            mock.patch.dict(main.os.environ, self.env, clear=False),
            mock.patch("main._publish_mqtt") as publish,
        ):
            sent = main.run_once(self.tracker, get_aircraft, notify, now=self.night_ts)
        self.assertEqual(sent, 0)
        get_aircraft.assert_called_once()  # OpenSky est bien interrogé
        notify.assert_not_called()
        publish.assert_not_called()

    def test_night_cycle_marks_no_cooldown(self):
        with mock.patch.dict(main.os.environ, self.env, clear=False):
            main.run_once(self.tracker, lambda: [_plane()], mock.Mock(), now=self.night_ts)
        # rien n'a été affiché : le callsign reste immédiatement éligible
        self.assertTrue(self.tracker.due("AFR123", now=self.night_ts))

    def test_night_cycle_logs_night_mode_once_per_cycle(self):
        planes = [_plane(), _plane(callsign="DLH456"), _plane(callsign="BAW222")]
        with (
            mock.patch.dict(main.os.environ, self.env, clear=False),
            self.assertLogs("main", level="INFO") as logs,
        ):
            main.run_once(self.tracker, lambda: planes, mock.Mock(), now=self.night_ts)
        night_lines = [line for line in logs.output if "MODE NUIT" in line]
        self.assertEqual(len(night_lines), 1)
        self.assertIn("23:00 -> 07:00", night_lines[0])
        self.assertIn("3 avion(s)", night_lines[0])

    def test_night_cycle_with_empty_sky_still_logs_night_mode(self):
        with (
            mock.patch.dict(main.os.environ, self.env, clear=False),
            self.assertLogs("main", level="INFO") as logs,
        ):
            sent = main.run_once(self.tracker, lambda: [], mock.Mock(), now=self.night_ts)
        self.assertEqual(sent, 0)
        self.assertTrue(any("MODE NUIT" in line for line in logs.output))

    def test_day_cycle_notifies_normally(self):
        notify = mock.Mock(return_value=True)
        with mock.patch.dict(main.os.environ, self.env, clear=False):
            sent = main.run_once(self.tracker, lambda: [_plane()], notify, now=self.day_ts)
        self.assertEqual(sent, 1)
        notify.assert_called_once()

    def test_night_mode_disabled_without_env(self):
        notify = mock.Mock(return_value=True)
        with mock.patch.dict(main.os.environ, {"TZ": "Europe/Paris"}, clear=True):
            sent = main.run_once(self.tracker, lambda: [_plane()], notify, now=self.night_ts)
        self.assertEqual(sent, 1)
        notify.assert_called_once()

    def test_invalid_night_config_fails_open(self):
        """Une plage mal formée ne doit pas rendre l'écran muet."""
        notify = mock.Mock(return_value=True)
        env = {**self.env, "NIGHT_START": "nuit"}
        with mock.patch.dict(main.os.environ, env, clear=False):
            sent = main.run_once(self.tracker, lambda: [_plane()], notify, now=self.night_ts)
        self.assertEqual(sent, 1)
        notify.assert_called_once()


class MainNightConfigTest(unittest.TestCase):
    def test_invalid_night_start_exits_2(self):
        env = {
            "HOME_LAT": "47.8642",
            "HOME_LON": "2.0871",
            "NIGHT_START": "23h",
            "NIGHT_END": "07:00",
        }
        with mock.patch.dict(main.os.environ, env, clear=False):
            self.assertEqual(main.main(["--once"]), 2)

    def test_single_night_bound_exits_2(self):
        env = {"HOME_LAT": "47.8642", "HOME_LON": "2.0871", "NIGHT_START": "23:00"}
        with mock.patch.dict(main.os.environ, env, clear=False):
            self.assertEqual(main.main(["--once"]), 2)

    def test_validate_config_accepts_night_window(self):
        env = {
            "HOME_LAT": "47.8642",
            "HOME_LON": "2.0871",
            "NIGHT_START": "23:00",
            "NIGHT_END": "07:00",
        }
        with (
            mock.patch.dict(main.os.environ, env, clear=False),
            mock.patch("builtins.print") as printed,
        ):
            self.assertEqual(main.main(["--validate-config"]), 0)
        self.assertIn("Configuration OK", str(printed.call_args))

    def test_validate_config_rejects_bad_night_window(self):
        env = {
            "HOME_LAT": "47.8642",
            "HOME_LON": "2.0871",
            "NIGHT_START": "23:00",
            "NIGHT_END": "99:99",
        }
        with (
            mock.patch.dict(main.os.environ, env, clear=False),
            mock.patch("builtins.print"),
        ):
            self.assertEqual(main.main(["--validate-config"]), 2)


if __name__ == "__main__":
    unittest.main()
