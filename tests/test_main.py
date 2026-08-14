#!/usr/bin/env python3
"""Tests unitaires de main.py (tracker anti-spam + cycle run_once).

Aucun réseau : get_aircraft_overhead et notify_aircraft sont mockés.
Lancer : python3 -m unittest test_main -v
"""

import unittest
from unittest import mock

import main


def _plane(
    callsign="AFR123",
    country="France",
    altitude_m=10000,
    speed_ms=230.0,
    distance_km=1.5,
    last_contact=1786700000,
):
    return {
        "callsign": callsign,
        "country": country,
        "altitude_m": altitude_m,
        "speed_ms": speed_ms,
        "distance_km": distance_km,
        "last_contact": last_contact,
    }


class CooldownTrackerTest(unittest.TestCase):
    def test_first_call_is_due(self):
        tracker = main.CooldownTracker(cooldown_s=60)
        self.assertTrue(tracker.due("AFR123", now=1000.0))

    def test_not_due_after_mark_within_cooldown(self):
        tracker = main.CooldownTracker(cooldown_s=60)
        tracker.mark("AFR123", now=1000.0)
        self.assertFalse(tracker.due("AFR123", now=1059.0))

    def test_due_after_cooldown_elapsed(self):
        tracker = main.CooldownTracker(cooldown_s=60)
        tracker.mark("AFR123", now=1000.0)
        self.assertTrue(tracker.due("AFR123", now=1060.0))
        self.assertTrue(tracker.due("AFR123", now=1200.0))

    def test_boundary_exact_cooldown_is_due(self):
        tracker = main.CooldownTracker(cooldown_s=60)
        tracker.mark("AFR123", now=1000.0)
        self.assertTrue(tracker.due("AFR123", now=1060.0))

    def test_callsigns_independent(self):
        tracker = main.CooldownTracker(cooldown_s=60)
        tracker.mark("AFR123", now=1000.0)
        self.assertFalse(tracker.due("AFR123", now=1010.0))
        self.assertTrue(tracker.due("DLH456", now=1010.0))

    def test_mark_updates_timestamp(self):
        tracker = main.CooldownTracker(cooldown_s=60)
        tracker.mark("AFR123", now=1000.0)
        tracker.mark("AFR123", now=1030.0)  # tentative échouée puis retentée
        self.assertFalse(tracker.due("AFR123", now=1050.0))
        self.assertTrue(tracker.due("AFR123", now=1090.0))

    def test_remaining_seconds(self):
        tracker = main.CooldownTracker(cooldown_s=60)
        tracker.mark("AFR123", now=1000.0)
        self.assertEqual(tracker.remaining("AFR123", now=1010.0), 50.0)
        self.assertEqual(tracker.remaining("AFR123", now=1100.0), 0.0)
        self.assertEqual(tracker.remaining("INCONNU", now=1000.0), 0.0)

    def test_prune_forgets_stale_entries(self):
        tracker = main.CooldownTracker(cooldown_s=60)
        now = 1786700000.0
        tracker._last_notified["VIEUX"] = now - main.TRACKER_RETENTION_S - 100
        tracker._last_notified["RECENT"] = now - 30
        tracker._prune(now)
        self.assertNotIn("VIEUX", tracker._last_notified)
        self.assertIn("RECENT", tracker._last_notified)

    def test_custom_cooldown(self):
        tracker = main.CooldownTracker(cooldown_s=5)
        tracker.mark("AFR123", now=1000.0)
        self.assertTrue(tracker.due("AFR123", now=1005.0))


class RunOnceTest(unittest.TestCase):
    def setUp(self):
        self.tracker = main.CooldownTracker(cooldown_s=60)

    def test_empty_sky_does_not_touch_display(self):
        notify = mock.Mock(return_value=True)
        sent = main.run_once(self.tracker, get_aircraft=lambda: [], notify=notify, now=1000.0)
        self.assertEqual(sent, 0)
        notify.assert_not_called()

    def test_aircraft_triggers_notification(self):
        notify = mock.Mock(return_value=True)
        sent = main.run_once(
            self.tracker, get_aircraft=lambda: [_plane()], notify=notify, now=1000.0
        )
        self.assertEqual(sent, 1)
        notify.assert_called_once_with(_plane())
        # le callsign est entré en cooldown
        self.assertFalse(self.tracker.due("AFR123", now=1000.0))

    def test_same_aircraft_not_repeated_within_cooldown(self):
        notify = mock.Mock(return_value=True)
        get_aircraft = lambda: [_plane()]  # noqa: E731
        sent1 = main.run_once(self.tracker, get_aircraft, notify, now=1000.0)
        sent2 = main.run_once(self.tracker, get_aircraft, notify, now=1015.0)
        self.assertEqual(sent1, 1)
        self.assertEqual(sent2, 0)
        self.assertEqual(notify.call_count, 1)

    def test_aircraft_notified_again_after_cooldown(self):
        notify = mock.Mock(return_value=True)
        get_aircraft = lambda: [_plane()]  # noqa: E731
        sent1 = main.run_once(self.tracker, get_aircraft, notify, now=1000.0)
        sent2 = main.run_once(self.tracker, get_aircraft, notify, now=1061.0)
        self.assertEqual(sent1, 1)
        self.assertEqual(sent2, 1)
        self.assertEqual(notify.call_count, 2)

    def test_two_aircraft_notified_once_each(self):
        notify = mock.Mock(return_value=True)
        planes = [_plane(callsign="AFR123"), _plane(callsign="DLH456")]
        sent = main.run_once(self.tracker, lambda: planes, notify, now=1000.0)
        self.assertEqual(sent, 2)
        self.assertEqual(notify.call_count, 2)

    def test_aircraft_without_callsign_skipped(self):
        notify = mock.Mock(return_value=True)
        planes = [_plane(callsign="   ", distance_km=0.8), _plane(callsign="BAW222")]
        sent = main.run_once(self.tracker, lambda: planes, notify, now=1000.0)
        self.assertEqual(sent, 1)
        # seul BAW222 est passé à notify
        self.assertEqual(notify.call_count, 1)
        self.assertEqual(notify.call_args[0][0]["callsign"], "BAW222")

    def test_failed_notification_marks_cooldown(self):
        notify = mock.Mock(return_value=False)
        get_aircraft = lambda: [_plane()]  # noqa: E731
        sent1 = main.run_once(self.tracker, get_aircraft, notify, now=1000.0)
        sent2 = main.run_once(self.tracker, get_aircraft, notify, now=1015.0)
        self.assertEqual(sent1, 0)
        self.assertEqual(sent2, 0)  # pas de martèlement : cooldown malgré l'échec
        self.assertEqual(notify.call_count, 1)

    def test_failed_notification_retried_after_cooldown(self):
        notify = mock.Mock(return_value=False)
        get_aircraft = lambda: [_plane()]  # noqa: E731
        main.run_once(self.tracker, get_aircraft, notify, now=1000.0)
        sent2 = main.run_once(self.tracker, get_aircraft, notify, now=1061.0)
        self.assertEqual(sent2, 0)  # échec à nouveau
        self.assertEqual(notify.call_count, 2)

    def test_unexpected_error_does_not_kill_cycle(self):
        def boom():
            raise RuntimeError("pic réseau simulé")

        notify = mock.Mock(return_value=True)
        sent = main.run_once(self.tracker, get_aircraft=boom, notify=notify, now=1000.0)
        self.assertEqual(sent, 0)
        notify.assert_not_called()

    def test_value_error_propagates_to_main(self):
        def bad_config():
            raise ValueError("HOME_LAT et HOME_LON doivent être définies.")

        with self.assertRaises(ValueError):
            main.run_once(self.tracker, get_aircraft=bad_config, notify=mock.Mock(), now=1000.0)


class MainConfigTest(unittest.TestCase):
    def test_missing_home_coords_exits_2(self):
        with mock.patch.dict(main.os.environ, {}, clear=False):
            for var in ("HOME_LAT", "HOME_LON"):
                main.os.environ.pop(var, None)
            with mock.patch("main.logging.basicConfig"):
                self.assertEqual(main.main(), 2)

    def test_invalid_poll_interval_exits_2(self):
        env = {"HOME_LAT": "47.8642", "HOME_LON": "2.0871", "POLL_INTERVAL_SEC": "abc"}
        with (
            mock.patch.dict(main.os.environ, env, clear=False),
            mock.patch("main.logging.basicConfig"),
        ):
            self.assertEqual(main.main(), 2)

    def test_parse_float_env_default_and_valid(self):
        with mock.patch.dict(main.os.environ, {}, clear=False):
            self.assertEqual(main._parse_float_env("POLL_INTERVAL_SEC", 15.0, 1.0), 15.0)
        with mock.patch.dict(main.os.environ, {"POLL_INTERVAL_SEC": "7"}, clear=False):
            self.assertEqual(main._parse_float_env("POLL_INTERVAL_SEC", 15.0, 1.0), 7.0)
        with (
            mock.patch.dict(main.os.environ, {"POLL_INTERVAL_SEC": "0.5"}, clear=False),
            self.assertRaises(ValueError),
        ):
            main._parse_float_env("POLL_INTERVAL_SEC", 15.0, 1.0)


if __name__ == "__main__":
    unittest.main()
