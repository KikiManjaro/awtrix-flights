#!/usr/bin/env python3
"""Tests des nouvelles fonctionnalités : template personnalisable,
icône orientée (sprite rotaté), direction cardinale et compagnie.
"""

import os
import unittest
from unittest import mock

import awtrix_client
from awtrix_client import (
    AIRCRAFT_SPRITE,
    build_aircraft_message,
    build_draw_commands,
    build_payload,
    direction_from_track,
)


def _plane(**overrides):
    base = {
        "callsign": "AFR123",
        "country": "France",
        "altitude_m": 10500,
        "speed_ms": 235.0,
        "distance_km": 1.2,
        "track": 270.0,
        "category": 4,
        "last_contact": 1786700000,
    }
    base.update(overrides)
    return base


class TemplateTest(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("MESSAGE_TEMPLATE", None)

    def test_default_template(self):
        self.assertEqual(build_aircraft_message(_plane()), "AFR123 France 10500m 846km/h")

    def test_custom_template_with_airline(self):
        os.environ["MESSAGE_TEMPLATE"] = "{callsign} {airline} {altitude_m}m"
        self.assertEqual(build_aircraft_message(_plane()), "AFR123 Air France 10500m")

    def test_custom_template_unknown_airline_omitted(self):
        os.environ["MESSAGE_TEMPLATE"] = "{callsign} {airline}"
        self.assertEqual(build_aircraft_message(_plane(callsign="XYZ999")), "XYZ999")

    def test_template_with_direction(self):
        os.environ["MESSAGE_TEMPLATE"] = "{callsign} {direction}"
        self.assertEqual(build_aircraft_message(_plane(track=90)), "AFR123 E")

    def test_template_with_altitude_ft(self):
        os.environ["MESSAGE_TEMPLATE"] = "{callsign} {altitude_ft}ft"
        self.assertEqual(build_aircraft_message(_plane(altitude_m=10000)), "AFR123 32808ft")

    def test_template_with_distance(self):
        os.environ["MESSAGE_TEMPLATE"] = "{callsign} {distance_km}km"
        self.assertEqual(build_aircraft_message(_plane(distance_km=2.456)), "AFR123 2.5km")

    def test_template_with_category(self):
        os.environ["MESSAGE_TEMPLATE"] = "{callsign} {category}"
        self.assertEqual(build_aircraft_message(_plane(category=6)), "AFR123 Gros porteur")

    def test_unknown_placeholder_kept_literal(self):
        os.environ["MESSAGE_TEMPLATE"] = "{callsign} {inconnu}"
        self.assertEqual(build_aircraft_message(_plane()), "AFR123 {inconnu}")

    def test_whitespace_template_falls_back_to_default(self):
        os.environ["MESSAGE_TEMPLATE"] = "   "
        # Un gabarit vide retombe sur le défaut, pas sur None.
        self.assertEqual(build_aircraft_message(_plane()), "AFR123 France 10500m 846km/h")

    def test_missing_optional_fields_cleaned(self):
        # Sans pays ni vitesse ni altitude, l'unité orpheline est nettoyée.
        os.environ["MESSAGE_TEMPLATE"] = "{callsign} {country} {altitude_m}m {speed_kmh}km/h"
        plane = {"callsign": "AFR123"}
        self.assertEqual(build_aircraft_message(plane), "AFR123")


class DirectionTest(unittest.TestCase):
    def test_cardinal_points(self):
        self.assertEqual(direction_from_track(0), "N")
        self.assertEqual(direction_from_track(90), "E")
        self.assertEqual(direction_from_track(180), "S")
        self.assertEqual(direction_from_track(270), "W")

    def test_intercardinal(self):
        self.assertEqual(direction_from_track(45), "NE")
        self.assertEqual(direction_from_track(135), "SE")
        self.assertEqual(direction_from_track(225), "SW")
        self.assertEqual(direction_from_track(315), "NW")

    def test_rounding(self):
        self.assertEqual(direction_from_track(100), "E")  # 100/45=2.2 -> E
        self.assertEqual(direction_from_track(120), "SE")  # 120/45=2.7 -> SE

    def test_wrap_around(self):
        self.assertEqual(direction_from_track(360), "N")
        self.assertEqual(direction_from_track(-45), "NW")

    def test_none_and_invalid(self):
        self.assertIsNone(direction_from_track(None))
        self.assertIsNone(direction_from_track("abc"))


class SpriteRotationTest(unittest.TestCase):
    def test_zero_rotation_keeps_same_pixels(self):
        rotated = awtrix_client._rotate_sprite(AIRCRAFT_SPRITE, 0)
        original = [
            (x, y) for y in range(8) for x in range(8) if (AIRCRAFT_SPRITE[y] >> (7 - x)) & 1
        ]
        self.assertEqual(sorted(rotated), sorted(original))

    def test_90_degrees_rotates_clockwise(self):
        # Le nez (x=4, y=0) doit passer à droite (x=7, y=4) pour cap 90°.
        rotated = awtrix_client._rotate_sprite(AIRCRAFT_SPRITE, 90)
        self.assertIn((7, 4), rotated)
        # Le nez n'est plus en haut : aucun pixel en (4, 0).
        self.assertNotIn((4, 0), rotated)

    def test_180_degrees_points_down(self):
        rotated = awtrix_client._rotate_sprite(AIRCRAFT_SPRITE, 180)
        orig = awtrix_client._rotate_sprite(AIRCRAFT_SPRITE, 0)
        # Le nez (x=4, y=0) part en bas (x=3, y=7) après demi-tour.
        self.assertIn((3, 7), rotated)
        # Invariant de rotation : chaque pixel original transposé (x,y)->(7-x,7-y)
        # doit être présent dans la rotation à 180°.
        expected = {(7 - x, 7 - y) for x, y in orig}
        self.assertEqual(set(rotated), expected)
        # Le sprite est bien tourné : les deux rendus diffèrent.
        self.assertNotEqual(sorted(orig), sorted(rotated))

    def test_pixels_within_bounds(self):
        for angle in (0, 45, 90, 135, 180, 225, 270, 315):
            rotated = awtrix_client._rotate_sprite(AIRCRAFT_SPRITE, angle)
            for x, y in rotated:
                self.assertTrue(0 <= x < 8 and 0 <= y < 8)


class DrawCommandsTest(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("AWTRIX_BEARING", None)
        os.environ.pop("ICON_ENABLED", None)

    def test_draw_generated_for_track(self):
        draw = build_draw_commands(_plane(track=270))
        self.assertTrue(draw)
        # chaque instruction est un db 1x1
        for cmd in draw:
            self.assertEqual(cmd["db"][2], 1)
            self.assertEqual(cmd["db"][3], 1)
            self.assertEqual(len(cmd["db"][4]), 3)

    def test_no_draw_without_track(self):
        self.assertEqual(build_draw_commands(_plane(track=None)), [])

    def test_no_draw_when_disabled(self):
        os.environ["ICON_ENABLED"] = "false"
        self.assertEqual(build_draw_commands(_plane(track=270)), [])

    def test_bearing_affects_rotation(self):
        # Avec bearing=90, un avion cap 90 est affiché nez en haut (angle 0).
        draw_a = build_draw_commands(_plane(track=90))
        os.environ["AWTRIX_BEARING"] = "90"
        draw_b = build_draw_commands(_plane(track=90))
        # Même sprite rotaté de 0° dans les deux cas -> mêmes pixels.
        # Le premier (bearing=0) est rotaté de 90°, le second de 0°.
        self.assertNotEqual(
            sorted(c["db"][:2] for c in draw_a),
            sorted(c["db"][:2] for c in draw_b),
        )

    def test_draw_pixels_are_lit_in_sprite(self):
        draw = build_draw_commands(_plane(track=0))
        self.assertGreater(len(draw), 0)


class PayloadTest(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("TEXT_CENTER", None)

    def test_payload_with_draw_has_text_offset(self):
        payload = build_payload(_plane(track=270))
        self.assertEqual(payload["textOffset"], 9)
        self.assertFalse(payload["center"])
        self.assertIn("draw", payload)
        self.assertIn("text", payload)
        self.assertIn("duration", payload)

    def test_payload_without_draw_centered(self):
        payload = build_payload(_plane(track=None))
        self.assertTrue(payload["center"])
        self.assertNotIn("draw", payload)

    def test_text_center_override(self):
        os.environ["TEXT_CENTER"] = "true"
        payload = build_payload(_plane(track=270))
        self.assertTrue(payload["center"])


class AirlineLookupTest(unittest.TestCase):
    def test_known_prefix(self):
        import airlines

        self.assertEqual(airlines.airline_for_callsign("AFR123"), "Air France")
        self.assertEqual(airlines.airline_for_callsign("RYR45K"), "Ryanair")

    def test_unknown_prefix(self):
        import airlines

        self.assertIsNone(airlines.airline_for_callsign("ZZZ999"))

    def test_empty_and_none(self):
        import airlines

        self.assertIsNone(airlines.airline_for_callsign(None))
        self.assertIsNone(airlines.airline_for_callsign(""))
        self.assertIsNone(airlines.airline_for_callsign("12"))

    def test_custom_file(self):
        import tempfile

        import airlines

        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            fh.write('{"XYZ": "Ma Compagnie"}')
            path = fh.name
        try:
            with mock.patch.dict(os.environ, {"AIRLINES_FILE": path}, clear=False):
                airlines._airlines_cache = None  # reset cache
                self.assertEqual(airlines.airline_for_callsign("XYZ123"), "Ma Compagnie")
                # la table par défaut reste accessible
                self.assertEqual(airlines.airline_for_callsign("AFR123"), "Air France")
        finally:
            os.unlink(path)
            airlines._airlines_cache = None


if __name__ == "__main__":
    unittest.main()
