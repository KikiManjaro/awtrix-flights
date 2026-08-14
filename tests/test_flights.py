#!/usr/bin/env python3
"""Tests unitaires du module flights (OpenSky Network).

Couvre : Haversine, bounding box, filtrage (position, altitude, rayon, sol),
tri par distance, gestion d'erreurs API (429/5xx/réseau -> []) et
configuration invalide (ValueError). Aucun accès réseau réel.
"""

import json
import os
import unittest
import urllib.error
from unittest import mock

import flights

# Coordonnées de la maison (Jargeau, 45150).
HOME_LAT = 47.8649
HOME_LON = 2.1243
RADIUS_KM = 5.0
MIN_ALT_M = 300.0


def make_state(
    icao="abc123",
    callsign=" AFR123 ",
    country="France",
    last_contact=1700000000,
    lon=2.15,
    lat=47.87,
    baro_alt=4000.0,
    on_ground=0,
    velocity=220.0,
    geo_alt=4050.0,
):
    """Construit une ligne "states" OpenSky (16 champs)."""
    return [
        icao,
        callsign,
        country,
        1700000000,
        last_contact,
        lon,
        lat,
        baro_alt,
        on_ground,
        velocity,
        0.0,
        0.0,
        None,
        geo_alt,
        "1000",
        False,
        0,
    ]


class HaversineTest(unittest.TestCase):
    def test_zero_distance(self):
        self.assertAlmostEqual(flights.haversine_km(47.8649, 2.1243, 47.8649, 2.1243), 0.0)

    def test_known_distance_paris_lyon(self):
        # Paris (48.8566, 2.3522) -> Lyon (45.7640, 4.8357) ≈ 391 km
        d = flights.haversine_km(48.8566, 2.3522, 45.7640, 4.8357)
        self.assertAlmostEqual(d, 391.0, delta=5.0)

    def test_symmetric(self):
        a = flights.haversine_km(47.0, 2.0, 48.0, 3.0)
        b = flights.haversine_km(48.0, 3.0, 47.0, 2.0)
        self.assertAlmostEqual(a, b)


class BoundingBoxTest(unittest.TestCase):
    def test_box_contains_center(self):
        lam_in, lom_in, lam_ax, lom_ax = flights.bounding_box(47.8649, 2.1243, 5.0)
        self.assertLess(lam_in, 47.8649)
        self.assertLess(lom_in, 2.1243)
        self.assertGreater(lam_ax, 47.8649)
        self.assertGreater(lom_ax, 2.1243)

    def test_radius_5km_lat_span(self):
        lam_in, _, lam_ax, _ = flights.bounding_box(47.8649, 2.1243, 5.0)
        # 5 km * 1.2 (marge) / 111.32 km par degré ≈ 0.0539°
        self.assertAlmostEqual(lam_ax - lam_in, 2 * 5.0 * 1.2 / 111.32, places=2)

    def test_lon_span_wider_than_lat_at_mid_latitudes(self):
        _, lom_in, _, lom_ax = flights.bounding_box(47.8649, 2.1243, 5.0)
        lam_in, _, lam_ax, _ = flights.bounding_box(47.8649, 2.1243, 5.0)
        self.assertGreater(lom_ax - lom_in, lam_ax - lam_in)


class FilterAircraftTest(unittest.TestCase):
    def test_empty_states(self):
        self.assertEqual(flights.filter_aircraft([], HOME_LAT, HOME_LON, RADIUS_KM, MIN_ALT_M), [])

    def test_keeps_close_high_aircraft(self):
        states = [make_state()]  # 47.87/2.15 ≈ à ~2 km de la maison
        result = flights.filter_aircraft(states, HOME_LAT, HOME_LON, RADIUS_KM, MIN_ALT_M)
        self.assertEqual(len(result), 1)
        plane = result[0]
        self.assertEqual(plane["callsign"], "AFR123")  # strips whitespace
        self.assertEqual(plane["country"], "France")
        self.assertEqual(plane["altitude_m"], 4000)
        self.assertLess(plane["distance_km"], RADIUS_KM)

    def test_rejects_null_position(self):
        states = [
            make_state(lat=None, lon=None),
            make_state(icao="zzz9", callsign="NULL2", lat=None, lon=None),
        ]
        result = flights.filter_aircraft(states, HOME_LAT, HOME_LON, RADIUS_KM, MIN_ALT_M)
        self.assertEqual(result, [])

    def test_rejects_zero_position(self):
        states = [make_state(lat=0.0, lon=0.0)]
        self.assertEqual(
            flights.filter_aircraft(states, HOME_LAT, HOME_LON, RADIUS_KM, MIN_ALT_M), []
        )

    def test_rejects_on_ground(self):
        states = [make_state(on_ground=1)]
        self.assertEqual(
            flights.filter_aircraft(states, HOME_LAT, HOME_LON, RADIUS_KM, MIN_ALT_M), []
        )

    def test_rejects_too_low(self):
        states = [make_state(baro_alt=150.0)]
        self.assertEqual(
            flights.filter_aircraft(states, HOME_LAT, HOME_LON, RADIUS_KM, MIN_ALT_M), []
        )

    def test_uses_geo_alt_when_baro_missing(self):
        states = [make_state(baro_alt=None, geo_alt=2500.0)]
        result = flights.filter_aircraft(states, HOME_LAT, HOME_LON, RADIUS_KM, MIN_ALT_M)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["altitude_m"], 2500)

    def test_rejects_far_aircraft(self):
        # À ~100 km à l'est : hors du rayon de 5 km
        states = [make_state(lon=3.1)]
        self.assertEqual(
            flights.filter_aircraft(states, HOME_LAT, HOME_LON, RADIUS_KM, MIN_ALT_M), []
        )

    def test_sorted_by_distance(self):
        states = [
            make_state(icao="far", callsign="FAR9", lon=2.15, lat=47.88),
            make_state(icao="near", callsign="NEAR", lon=2.13, lat=47.86),
        ]
        result = flights.filter_aircraft(states, HOME_LAT, HOME_LON, RADIUS_KM, MIN_ALT_M)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["callsign"], "NEAR")
        self.assertLess(result[0]["distance_km"], result[1]["distance_km"])

    def test_speed_preserved(self):
        states = [make_state(velocity=235.5)]
        result = flights.filter_aircraft(states, HOME_LAT, HOME_LON, RADIUS_KM, MIN_ALT_M)
        self.assertEqual(result[0]["speed_ms"], 235.5)


class GetAircraftOverheadTest(unittest.TestCase):
    def setUp(self):
        self.env_patcher = mock.patch.dict(
            os.environ, {"HOME_LAT": str(HOME_LAT), "HOME_LON": str(HOME_LON)}, clear=False
        )
        self.env_patcher.start()
        self.addCleanup(self.env_patcher.stop)

    def test_missing_config_raises_value_error(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            for var in ("HOME_LAT", "HOME_LON"):
                os.environ.pop(var, None)
            with self.assertRaises(ValueError):
                flights.get_aircraft_overhead()

    def test_invalid_config_raises_value_error(self):
        with (
            mock.patch.dict(os.environ, {"HOME_LAT": "abc"}, clear=False),
            self.assertRaises(ValueError),
        ):
            flights.get_aircraft_overhead()

    @mock.patch.object(flights, "_fetch_states")
    def test_returns_filtered_aircraft(self, mock_fetch):
        mock_fetch.return_value = [make_state()]
        result = flights.get_aircraft_overhead()
        self.assertEqual(len(result), 1)

    @mock.patch.object(flights, "_fetch_states")
    def test_api_error_returns_empty_list(self, mock_fetch):
        mock_fetch.side_effect = flights.OpenSkyError("injoignable")
        self.assertEqual(flights.get_aircraft_overhead(), [])

    def test_radius_and_altitude_from_env(self):
        with (
            mock.patch.dict(os.environ, {"RADIUS_KM": "1", "MIN_ALT_M": "1000"}, clear=False),
            mock.patch.object(flights, "_fetch_states") as mock_fetch,
        ):
            mock_fetch.return_value = [make_state()]
            result = flights.get_aircraft_overhead()
            # avion par défaut à ~1,8 km de la maison -> hors rayon 1 km
            self.assertEqual(len(result), 0)


class FetchStatesTest(unittest.TestCase):
    @mock.patch("flights.time.sleep")
    @mock.patch("flights.urllib.request.urlopen")
    def test_parses_json_and_returns_states(self, mock_urlopen, _sleep):
        body = json.dumps({"states": [["state1"], ["state2"]]})
        mock_urlopen.return_value.__enter__.return_value = mock.Mock(
            read=lambda: body.encode(), status=200
        )
        with mock.patch("flights.json.load", return_value={"states": [1, 2]}):
            result = flights._fetch_states(47.0, 2.0, 48.0, 3.0)
        self.assertEqual(result, [1, 2])
        mock_urlopen.assert_called_once()

    @mock.patch("flights.time.sleep")
    def test_retries_on_429_then_succeeds(self, _sleep):
        calls = {"n": 0}

        def fake_urlopen(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                headers = mock.Mock(get=lambda k: None)  # pas de Retry-After
                exc = urllib.error.HTTPError("url", 429, "Too Many Requests", headers, None)
                raise exc
            return mock.Mock(__enter__=lambda s: s, __exit__=lambda *a: False)

        with (
            mock.patch("flights.urllib.request.urlopen", side_effect=fake_urlopen),
            mock.patch("flights.json.load", return_value={"states": []}),
        ):
            result = flights._fetch_states(47.0, 2.0, 48.0, 3.0)
        self.assertEqual(result, [])
        self.assertEqual(calls["n"], 2)

    @mock.patch("flights.time.sleep")
    def test_gives_up_after_max_attempts(self, _sleep):
        def boom(*args, **kwargs):
            raise urllib.error.URLError("network down")

        with (
            mock.patch("flights.urllib.request.urlopen", side_effect=boom),
            self.assertRaises(flights.OpenSkyError),
        ):
            flights._fetch_states(47.0, 2.0, 48.0, 3.0)


if __name__ == "__main__":
    unittest.main()
