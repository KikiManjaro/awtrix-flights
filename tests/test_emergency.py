#!/usr/bin/env python3
"""Tests de la détection des avions en détresse (squawk d'urgence).

Couvre : normalisation du squawk OpenSky, libellés 7500/7600/7700, préfixe et
couleur d'alerte côté AWTRIX (texte brut et multicolore, icône orientée), et
affichage prioritaire dans la boucle principale (cooldown et limite par cycle
contournés). Aucun accès réseau réel.
"""

import os
import unittest
from unittest import mock

import awtrix_client
import flights
import main
from tests.test_flights import HOME_LAT, HOME_LON, MIN_ALT_M, RADIUS_KM, make_state


def _plane(**overrides):
    """Avion minimal, tel que produit par flights.filter_aircraft()."""
    base = {
        "callsign": "AFR123",
        "country": "France",
        "altitude_m": 10500,
        "speed_ms": 235.0,
        "distance_km": 1.2,
        "track": 270.0,
        "category": 4,
        "last_contact": 1786700000,
        "squawk": "1000",
    }
    base.update(overrides)
    return base


class SquawkParsingTest(unittest.TestCase):
    def test_normalize_valid_code(self):
        self.assertEqual(flights.normalize_squawk("7500"), "7500")
        self.assertEqual(flights.normalize_squawk(" 7700 "), "7700")
        self.assertEqual(flights.normalize_squawk("0000"), "0000")

    def test_normalize_accepts_int_codes(self):
        # OpenSky renvoie une chaîne, mais un code numérique reste exploitable.
        self.assertEqual(flights.normalize_squawk(7500), "7500")

    def test_normalize_rejects_absent_or_malformed(self):
        for raw in (None, "", "   ", "750", "75000", "75O0", "abc", 7500.0, True):
            self.assertIsNone(flights.normalize_squawk(raw), raw)

    def test_emergency_labels(self):
        self.assertEqual(flights.squawk_label("7500"), "HIJACK")
        self.assertEqual(flights.squawk_label("7600"), "RADIO FAIL")
        self.assertEqual(flights.squawk_label("7700"), "EMERGENCY")

    def test_non_emergency_codes(self):
        for code in ("1000", "2000", "1200", "0000"):
            self.assertIsNone(flights.squawk_label(code), code)
            self.assertFalse(flights.is_emergency_squawk(code), code)

    def test_missing_squawk_is_not_an_emergency(self):
        self.assertIsNone(flights.squawk_label(None))
        self.assertFalse(flights.is_emergency_squawk(None))
        self.assertFalse(flights.is_emergency_squawk("n/a"))

    def test_is_emergency(self):
        for code in sorted(flights.EMERGENCY_SQUAWKS):
            self.assertTrue(flights.is_emergency_squawk(code), code)


class FilterSquawkTest(unittest.TestCase):
    def _filter(self, states):
        return flights.filter_aircraft(states, HOME_LAT, HOME_LON, RADIUS_KM, MIN_ALT_M)

    def test_squawk_exposed_on_aircraft(self):
        state = make_state()
        state[flights._IDX_SQUAWK] = "7700"
        result = self._filter([state])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["squawk"], "7700")
        self.assertTrue(flights.is_emergency_squawk(result[0]["squawk"]))

    def test_squawk_none_when_truncated_state(self):
        # État tronqué avant l'index squawk : pas d'IndexError, squawk = None.
        result = self._filter([make_state()[:14]])
        self.assertEqual(len(result), 1)
        self.assertIsNone(result[0]["squawk"])

    def test_squawk_stripped_and_validated(self):
        state = make_state()
        state[flights._IDX_SQUAWK] = " 7600 "
        self.assertEqual(self._filter([state])[0]["squawk"], "7600")
        state[flights._IDX_SQUAWK] = "12"
        self.assertIsNone(self._filter([state])[0]["squawk"])


class EmergencyMessageTest(unittest.TestCase):
    def tearDown(self):
        for var in ("EMERGENCY_PREFIX", "MESSAGE_TEMPLATE"):
            os.environ.pop(var, None)

    def test_prefix_added_for_emergency(self):
        msg = awtrix_client.build_aircraft_message(_plane(squawk="7700"))
        self.assertEqual(msg, "EMERG AFR123 France 10500m 846km/h")

    def test_no_prefix_for_normal_aircraft(self):
        msg = awtrix_client.build_aircraft_message(_plane())
        self.assertEqual(msg, "AFR123 France 10500m 846km/h")

    def test_custom_prefix(self):
        os.environ["EMERGENCY_PREFIX"] = "7500 "
        self.assertEqual(
            awtrix_client.build_aircraft_message(_plane(squawk="7500")),
            "7500 AFR123 France 10500m 846km/h",
        )

    def test_prefix_can_be_disabled(self):
        os.environ["EMERGENCY_PREFIX"] = ""
        self.assertEqual(
            awtrix_client.build_aircraft_message(_plane(squawk="7600")),
            "AFR123 France 10500m 846km/h",
        )
        os.environ["EMERGENCY_PREFIX"] = "   "
        self.assertEqual(
            awtrix_client.build_aircraft_message(_plane(squawk="7600")),
            "AFR123 France 10500m 846km/h",
        )

    def test_squawk_and_emergency_placeholders(self):
        os.environ["MESSAGE_TEMPLATE"] = "{callsign} {squawk} {emergency}"
        # Code normal : pas de préfixe, {emergency} vide et nettoyé.
        self.assertEqual(
            awtrix_client.build_aircraft_message(_plane(squawk="1000")), "AFR123 1000"
        )
        # Code d'urgence : préfixe + libellé.
        self.assertEqual(
            awtrix_client.build_aircraft_message(_plane(squawk="7600")),
            "EMERG AFR123 7600 RADIO FAIL",
        )

    def test_emergency_placeholder_empty_for_normal_aircraft(self):
        os.environ["MESSAGE_TEMPLATE"] = "{callsign} {emergency}"
        self.assertEqual(awtrix_client.build_aircraft_message(_plane()), "AFR123")

    def test_squawk_placeholder_empty_when_unknown(self):
        os.environ["MESSAGE_TEMPLATE"] = "{callsign} {squawk}"
        self.assertEqual(awtrix_client.build_aircraft_message(_plane(squawk=None)), "AFR123")


class EmergencyColoredSegmentsTest(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("FIELD_COLORS", None)

    def test_red_prefix_segment_first(self):
        os.environ["FIELD_COLORS"] = "callsign=FFAA00"
        segments = awtrix_client.build_colored_segments(_plane(squawk="7700"))
        self.assertEqual(segments[0], {"t": "EMERG ", "c": awtrix_client.EMERGENCY_TEXT_COLOR})
        self.assertTrue(any("AFR123" in seg["t"] for seg in segments))

    def test_no_prefix_segment_for_normal_aircraft(self):
        os.environ["FIELD_COLORS"] = "callsign=FFAA00"
        segments = awtrix_client.build_colored_segments(_plane())
        self.assertNotIn(
            {"t": "EMERG ", "c": awtrix_client.EMERGENCY_TEXT_COLOR},
            segments,
        )
        self.assertFalse(any("EMERG" in seg["t"] for seg in segments))

    def test_full_text_matches_plain_message(self):
        os.environ["FIELD_COLORS"] = "callsign=FFAA00"
        segments = awtrix_client.build_colored_segments(_plane(squawk="7500"))
        full = "".join(seg["t"] for seg in segments)
        self.assertEqual(full, "EMERG AFR123 France 10500m 846km/h")


class EmergencyIconTest(unittest.TestCase):
    def setUp(self):
        os.environ["ICON_ENABLED"] = "true"
        os.environ["ICON_COLOR"] = "255,170,0"

    def tearDown(self):
        for var in ("ICON_ENABLED", "ICON_COLOR", "EMERGENCY_ICON_COLOR"):
            os.environ.pop(var, None)

    def _lit_colors(self, plane):
        draw = awtrix_client.build_draw_commands(plane)
        colors = draw[0]["db"][4]
        lit = [tuple(colors[i : i + 3]) for i in range(0, len(colors), 3)]
        return {c for c in lit if c != (0, 0, 0)}

    def test_emergency_icon_is_red(self):
        self.assertEqual(self._lit_colors(_plane(squawk="7700")), {(255, 0, 0)})

    def test_normal_icon_uses_icon_color(self):
        self.assertEqual(self._lit_colors(_plane()), {(255, 170, 0)})

    def test_emergency_icon_color_override(self):
        os.environ["EMERGENCY_ICON_COLOR"] = "0,255,255"
        self.assertEqual(self._lit_colors(_plane(squawk="7500")), {(0, 255, 255)})

    def test_invalid_emergency_icon_color_falls_back_to_red(self):
        os.environ["EMERGENCY_ICON_COLOR"] = "rouge"
        self.assertEqual(awtrix_client._get_emergency_icon_color(), [255, 0, 0])
        os.environ["EMERGENCY_ICON_COLOR"] = "300,-5"
        self.assertEqual(awtrix_client._get_emergency_icon_color(), [255, 0, 0])

    def test_icon_color_parser_bounds_and_defaults(self):
        self.assertEqual(awtrix_client._get_icon_color(), [255, 170, 0])
        os.environ["ICON_COLOR"] = "999,-3,10"
        self.assertEqual(awtrix_client._get_icon_color(), [255, 0, 10])
        os.environ["ICON_COLOR"] = "nope"
        self.assertEqual(awtrix_client._get_icon_color(), [255, 170, 0])

    def test_emergency_without_track_has_no_draw(self):
        self.assertEqual(awtrix_client.build_draw_commands(_plane(squawk="7700", track=None)), [])


class EmergencyRunOnceTest(unittest.TestCase):
    def setUp(self):
        self.tracker = main.CooldownTracker(cooldown_s=60)

    def test_emergency_bypasses_cooldown_on_next_cycle(self):
        notify = mock.Mock(return_value=True)
        plane = _plane(squawk="7700")
        with self.assertLogs("main", level="WARNING") as logs:
            first = main.run_once(self.tracker, lambda: [plane], notify, now=1000.0)
            second = main.run_once(self.tracker, lambda: [plane], notify, now=1010.0)
        self.assertEqual(first, 1)
        self.assertEqual(second, 1)  # cooldown ignoré : alerte réaffichée
        self.assertEqual(notify.call_count, 2)
        self.assertTrue(any("SQUAWK D'URGENCE" in line for line in logs.output))
        self.assertTrue(any("EMERGENCY" in line for line in logs.output))

    def test_normal_aircraft_still_subject_to_cooldown(self):
        notify = mock.Mock(return_value=True)
        plane = _plane()
        first = main.run_once(self.tracker, lambda: [plane], notify, now=1000.0)
        second = main.run_once(self.tracker, lambda: [plane], notify, now=1010.0)
        self.assertEqual((first, second), (1, 0))
        self.assertEqual(notify.call_count, 1)

    def test_emergency_bypasses_per_cycle_limit(self):
        notify = mock.Mock(return_value=True)
        planes = [_plane(callsign=f"AFR{100 + i}") for i in range(4)]
        planes.append(_plane(callsign="URG001", squawk="7700"))
        sent = main.run_once(self.tracker, lambda: planes, notify, now=1000.0)
        # 3 avions normaux (limite) + l'avion en détresse
        self.assertEqual(sent, 4)
        notified = [call[0][0]["callsign"] for call in notify.call_args_list]
        self.assertIn("URG001", notified)
        self.assertNotIn("AFR103", notified)

    def test_emergency_does_not_consume_a_normal_slot(self):
        notify = mock.Mock(return_value=True)
        planes = [_plane(callsign="URG001", squawk="7600")]
        planes += [_plane(callsign=f"AFR{100 + i}") for i in range(3)]
        sent = main.run_once(self.tracker, lambda: planes, notify, now=1000.0)
        self.assertEqual(sent, 4)
        notified = [call[0][0]["callsign"] for call in notify.call_args_list]
        for expected in ("URG001", "AFR100", "AFR101", "AFR102"):
            self.assertIn(expected, notified)

    def test_emergency_detection_published_on_mqtt(self):
        notify = mock.Mock(return_value=True)
        with (
            mock.patch.dict(os.environ, {"MQTT_ENABLED": "true"}, clear=False),
            mock.patch("main.mqtt_client.publish", return_value=True) as publish,
        ):
            main.run_once(self.tracker, lambda: [_plane(squawk="7700")], notify, now=1000.0)
        payload = publish.call_args[0][1]
        self.assertTrue(payload["emergency"])
        self.assertEqual(payload["squawk"], "7700")

    def test_emergency_in_dry_run_is_not_sent(self):
        notify = mock.Mock(return_value=True)
        sent = main.run_once(
            self.tracker, lambda: [_plane(squawk="7700")], notify, now=1000.0, dry_run=True
        )
        self.assertEqual(sent, 1)
        notify.assert_not_called()


if __name__ == "__main__":
    unittest.main()
