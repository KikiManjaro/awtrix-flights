#!/usr/bin/env python3
"""Tests du client MQTT minimaliste (publish-only).

Un faux broker MQTT 3.1.1 est monté sur un socket local pour valider le
vrai échange de paquets : CONNECT -> CONNACK -> PUBLISH -> DISCONNECT.
"""

import json
import os
import socket
import struct
import threading
import unittest

import mqtt_client


class FakeBroker:
    """Mini-broker MQTT 3.1.1 : accepte 1 connexion, répond CONNACK,
    lit le PUBLISH et enregistre (topic, payload)."""

    def __init__(self):
        self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind(("127.0.0.1", 0))
        self._srv.listen(1)
        self.port = self._srv.getsockname()[1]
        self.received = []
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _read_exact(self, conn, n):
        data = b""
        while len(data) < n:
            chunk = conn.recv(n - len(data))
            if not chunk:
                raise ConnectionError("closed")
            data += chunk
        return data

    def _read_packet(self, conn):
        first = self._read_exact(conn, 1)[0]
        multiplier = 1
        length = 0
        while True:
            digit = self._read_exact(conn, 1)[0]
            length += (digit & 0x7F) * multiplier
            if not (digit & 0x80):
                break
            multiplier *= 128
        return first, self._read_exact(conn, length)

    def _parse_utf8(self, data, offset):
        (length,) = struct.unpack(">H", data[offset : offset + 2])
        return data[offset + 2 : offset + 2 + length].decode("utf-8"), offset + 2 + length

    def _serve(self):
        conn, _ = self._srv.accept()
        try:
            # CONNECT attendu
            first, body = self._read_packet(conn)
            assert first == 0x10, f"CONNECT attendu, reçu 0x{first:02x}"
            # Réponse CONNACK (0x20 0x02 0x00 0x00 = accepté)
            conn.sendall(bytes([0x20, 0x02, 0x00, 0x00]))
            # PUBLISH ou DISCONNECT
            while True:
                first, body = self._read_packet(conn)
                if first == 0x30:  # PUBLISH QoS 0
                    topic, offset = self._parse_utf8(body, 0)
                    payload = body[offset:].decode("utf-8", errors="replace")
                    self.received.append((topic, payload))
                elif first == 0xE0:  # DISCONNECT
                    break
                else:
                    break
        except Exception:
            pass
        finally:
            conn.close()

    def close(self):
        self._srv.close()


class MqttConfigTest(unittest.TestCase):
    def tearDown(self):
        for var in (
            "MQTT_HOST",
            "MQTT_PORT",
            "MQTT_USER",
            "MQTT_PASSWORD",
            "MQTT_CLIENT_ID",
            "MQTT_TOPIC",
            "MQTT_TIMEOUT_S",
        ):
            os.environ.pop(var, None)

    def test_defaults(self):
        cfg = mqtt_client._config()
        self.assertEqual(cfg["host"], "127.0.0.1")
        self.assertEqual(cfg["port"], 1883)
        self.assertIsNone(cfg["username"])
        self.assertEqual(cfg["client_id"], "awtrix-flights")

    def test_env_override(self):
        os.environ.update(
            {
                "MQTT_HOST": "192.168.1.50",
                "MQTT_PORT": "1884",
                "MQTT_USER": "kiki",
                "MQTT_PASSWORD": "secret",
                "MQTT_CLIENT_ID": "test-client",
            }
        )
        cfg = mqtt_client._config()
        self.assertEqual(cfg["host"], "192.168.1.50")
        self.assertEqual(cfg["port"], 1884)
        self.assertEqual(cfg["username"], "kiki")
        self.assertEqual(cfg["password"], "secret")
        self.assertEqual(cfg["client_id"], "test-client")


class MqttPublishTest(unittest.TestCase):
    def test_publish_string_to_real_broker(self):
        broker = FakeBroker()
        try:
            ok = mqtt_client.publish(
                "test/topic", "hello", host="127.0.0.1", port=broker.port, timeout=2
            )
            self.assertTrue(ok)
            self.assertEqual(broker.received, [("test/topic", "hello")])
        finally:
            broker.close()

    def test_publish_dict_serialized_as_json(self):
        broker = FakeBroker()
        try:
            payload = {"callsign": "AFR123", "track": 270}
            ok = mqtt_client.publish(
                "awtrix/detection",
                payload,
                host="127.0.0.1",
                port=broker.port,
                timeout=2,
            )
            self.assertTrue(ok)
            topic, raw = broker.received[0]
            self.assertEqual(topic, "awtrix/detection")
            self.assertEqual(json.loads(raw), payload)
        finally:
            broker.close()

    def test_publish_with_credentials(self):
        broker = FakeBroker()
        try:
            ok = mqtt_client.publish(
                "t",
                "x",
                host="127.0.0.1",
                port=broker.port,
                username="user",
                password="pass",
                timeout=2,
            )
            self.assertTrue(ok)
            self.assertEqual(broker.received[0][0], "t")
        finally:
            broker.close()

    def test_connection_refused_returns_false(self):
        # Port très probablement fermé
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        ok = mqtt_client.publish("t", "x", host="127.0.0.1", port=port, timeout=1)
        self.assertFalse(ok)

    def test_never_raises_on_bad_host(self):
        ok = mqtt_client.publish(
            "t",
            "x",
            host="192.0.2.1",
            port=1883,
            timeout=1,  # TEST-NET, injoignable
        )
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
