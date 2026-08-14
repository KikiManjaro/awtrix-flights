#!/usr/bin/env python3
"""Tests unitaires du client AWTRIX.

Couvre : construction du message (champs manquants/nuls), lecture des hôtes
et du port depuis l'environnement, envoi HTTP (2xx, non-2xx, erreur réseau,
timeout) et notify_aircraft multi-écrans. Aucun réseau réel.
"""

import os
import unittest
import urllib.error
from unittest import mock

import awtrix_client


class BuildMessageTest(unittest.TestCase):
    def test_full_plane_info(self):
        msg = awtrix_client.build_aircraft_message(
            {"callsign": "AFR123", "country": "France", "altitude_m": 10500, "speed_ms": 235.0}
        )
        self.assertEqual(msg, "AFR123 France 10500m 846km/h")

    def test_speed_converted_to_kmh(self):
        # 235 m/s * 3.6 = 846 km/h
        msg = awtrix_client.build_aircraft_message(
            {"callsign": "AFR123", "altitude_m": 10500, "speed_ms": 235}
        )
        self.assertEqual(msg, "AFR123 10500m 846km/h")

    def test_missing_country_omitted(self):
        msg = awtrix_client.build_aircraft_message(
            {"callsign": "AFR123", "altitude_m": 10500, "speed_ms": 235}
        )
        self.assertNotIn("None", msg)
        self.assertTrue(msg.startswith("AFR123"))

    def test_missing_altitude_and_speed(self):
        msg = awtrix_client.build_aircraft_message({"callsign": "AFR123", "country": "France"})
        self.assertEqual(msg, "AFR123 France")

    def test_callsign_fallback_unknown(self):
        msg = awtrix_client.build_aircraft_message({"callsign": "", "country": "France"})
        self.assertEqual(msg, "?? France")

    def test_empty_dict_returns_none(self):
        self.assertIsNone(awtrix_client.build_aircraft_message({}))

    def test_none_returns_none(self):
        self.assertIsNone(awtrix_client.build_aircraft_message(None))

    def test_non_numeric_altitude_omitted(self):
        msg = awtrix_client.build_aircraft_message({"callsign": "AFR123", "altitude_m": "FL350"})
        self.assertNotIn("FL350m", msg)

    def test_callsign_stripped(self):
        msg = awtrix_client.build_aircraft_message({"callsign": "  AFR123  ", "country": "France"})
        self.assertTrue(msg.startswith("AFR123 "))


class HostsPortTest(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("AWTRIX_HOST", None)
        os.environ.pop("AWTRIX_PORT", None)

    def test_default_host_when_unset(self):
        self.assertEqual(awtrix_client._get_hosts(), ["192.168.1.27"])

    def test_single_host(self):
        os.environ["AWTRIX_HOST"] = "192.168.1.50"
        self.assertEqual(awtrix_client._get_hosts(), ["192.168.1.50"])

    def test_multiple_hosts_comma_separated(self):
        os.environ["AWTRIX_HOST"] = "192.168.1.27, 192.168.1.123"
        self.assertEqual(awtrix_client._get_hosts(), ["192.168.1.27", "192.168.1.123"])

    def test_empty_env_falls_back_to_default(self):
        os.environ["AWTRIX_HOST"] = " , "
        self.assertEqual(awtrix_client._get_hosts(), ["192.168.1.27"])

    def test_default_port_when_unset(self):
        self.assertEqual(awtrix_client._get_port(), 80)

    def test_custom_port(self):
        os.environ["AWTRIX_PORT"] = "8080"
        self.assertEqual(awtrix_client._get_port(), 8080)

    def test_invalid_port_falls_back(self):
        os.environ["AWTRIX_PORT"] = "abc"
        self.assertEqual(awtrix_client._get_port(), 80)

    def test_out_of_range_port_falls_back(self):
        os.environ["AWTRIX_PORT"] = "99999"
        self.assertEqual(awtrix_client._get_port(), 80)


class SendToHostTest(unittest.TestCase):
    def _fake_response(self, status=200, body="OK"):
        resp = mock.Mock()
        resp.status = status
        resp.read.return_value = body.encode()
        return mock.Mock(__enter__=lambda s: resp, __exit__=lambda *a: False)

    def test_success_returns_true(self):
        with mock.patch(
            "awtrix_client.urllib.request.urlopen", return_value=self._fake_response(200, "OK")
        ) as m:
            ok = awtrix_client._send_to_host("192.168.1.27", 80, {"text": "hi"}, "avion")
        self.assertTrue(ok)
        url = m.call_args[0][0].full_url
        self.assertIn("/api/custom?name=avion", url)

    def test_2xx_returns_true(self):
        with mock.patch(
            "awtrix_client.urllib.request.urlopen", return_value=self._fake_response(204, "")
        ):
            self.assertTrue(awtrix_client._send_to_host("h", 80, {"text": "hi"}, "avion"))

    def test_http_error_returns_false(self):
        exc = urllib.error.HTTPError("url", 500, "Internal", mock.Mock(), None)
        exc.read = lambda *a: b"err"
        with mock.patch("awtrix_client.urllib.request.urlopen", side_effect=exc):
            self.assertFalse(awtrix_client._send_to_host("h", 80, {"text": "hi"}, "avion"))

    def test_urlerror_returns_false(self):
        with mock.patch(
            "awtrix_client.urllib.request.urlopen", side_effect=urllib.error.URLError("down")
        ):
            self.assertFalse(awtrix_client._send_to_host("h", 80, {"text": "hi"}, "avion"))

    def test_timeout_returns_false(self):
        with mock.patch(
            "awtrix_client.urllib.request.urlopen", side_effect=TimeoutError("timed out")
        ):
            self.assertFalse(awtrix_client._send_to_host("h", 80, {"text": "hi"}, "avion"))

    def test_oserror_returns_false(self):
        with mock.patch(
            "awtrix_client.urllib.request.urlopen", side_effect=OSError("conn refused")
        ):
            self.assertFalse(awtrix_client._send_to_host("h", 80, {"text": "hi"}, "avion"))


class NotifyAircraftTest(unittest.TestCase):
    def setUp(self):
        os.environ["AWTRIX_HOST"] = "192.168.1.27,192.168.1.123"

    def tearDown(self):
        os.environ.pop("AWTRIX_HOST", None)

    def test_sends_to_all_hosts(self):
        with mock.patch("awtrix_client._send_to_host", return_value=True) as send:
            ok = awtrix_client.notify_aircraft(
                {"callsign": "AFR123", "country": "France", "altitude_m": 10500, "speed_ms": 235}
            )
        self.assertTrue(ok)
        self.assertEqual(send.call_count, 2)

    def test_true_if_any_host_succeeds(self):
        with mock.patch("awtrix_client._send_to_host", side_effect=[False, True]):
            self.assertTrue(awtrix_client.notify_aircraft({"callsign": "AFR123"}))

    def test_false_if_all_hosts_fail(self):
        with mock.patch("awtrix_client._send_to_host", side_effect=[False, False]):
            self.assertFalse(awtrix_client.notify_aircraft({"callsign": "AFR123"}))

    def test_empty_plane_info_returns_false_without_sending(self):
        with mock.patch("awtrix_client._send_to_host") as send:
            self.assertFalse(awtrix_client.notify_aircraft({}))
        send.assert_not_called()


if __name__ == "__main__":
    unittest.main()
