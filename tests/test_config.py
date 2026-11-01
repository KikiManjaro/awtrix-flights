#!/usr/bin/env python3
"""Tests for config.py centralized validation."""

import unittest

import config


class LoadConfigTest(unittest.TestCase):
    def _env(self, **overrides):
        base = {"HOME_LAT": "48.85", "HOME_LON": "2.35"}
        base.update(overrides)
        return base

    def test_valid_minimal(self):
        cfg = config.load_config(self._env())
        self.assertEqual(cfg.home_lat, 48.85)
        self.assertEqual(cfg.home_lon, 2.35)
        self.assertEqual(cfg.radius_km, 5.0)
        self.assertEqual(cfg.awtrix_port, 80)

    def test_missing_home_lat_raises(self):
        with self.assertRaises(config.ConfigError):
            config.load_config({"HOME_LON": "2.35"})

    def test_missing_home_lon_raises(self):
        with self.assertRaises(config.ConfigError):
            config.load_config({"HOME_LAT": "48.85"})

    def test_home_lat_out_of_range(self):
        for bad in ["-91", "91", "999"]:
            with self.assertRaises(config.ConfigError, msg=bad):
                config.load_config(self._env(HOME_LAT=bad))

    def test_home_lon_out_of_range(self):
        for bad in ["-181", "181", "999"]:
            with self.assertRaises(config.ConfigError, msg=bad):
                config.load_config(self._env(HOME_LON=bad))

    def test_non_numeric_home(self):
        with self.assertRaises(config.ConfigError):
            config.load_config(self._env(HOME_LAT="abc"))

    def test_radius_bounds(self):
        with self.assertRaises(config.ConfigError):
            config.load_config(self._env(RADIUS_KM="0"))
        with self.assertRaises(config.ConfigError):
            config.load_config(self._env(RADIUS_KM="-1"))
        cfg = config.load_config(self._env(RADIUS_KM="10"))
        self.assertEqual(cfg.radius_km, 10)

    def test_min_alt_bounds(self):
        with self.assertRaises(config.ConfigError):
            config.load_config(self._env(MIN_ALT_M="-1"))
        cfg = config.load_config(self._env(MIN_ALT_M="0"))
        self.assertEqual(cfg.min_alt_m, 0)

    def test_poll_interval_bounds(self):
        with self.assertRaises(config.ConfigError):
            config.load_config(self._env(POLL_INTERVAL_SEC="0.5"))
        with self.assertRaises(config.ConfigError):
            config.load_config(self._env(POLL_INTERVAL_SEC="abc"))
        cfg = config.load_config(self._env(POLL_INTERVAL_SEC="30"))
        self.assertEqual(cfg.poll_interval_s, 30)

    def test_notify_cooldown_zero_allowed(self):
        cfg = config.load_config(self._env(NOTIFY_COOLDOWN_SEC="0"))
        self.assertEqual(cfg.notify_cooldown_s, 0)

    def test_awtrix_port_bounds(self):
        with self.assertRaises(config.ConfigError):
            config.load_config(self._env(AWTRIX_PORT="0"))
        with self.assertRaises(config.ConfigError):
            config.load_config(self._env(AWTRIX_PORT="99999"))
        with self.assertRaises(config.ConfigError):
            config.load_config(self._env(AWTRIX_PORT="abc"))

    def test_log_level_validation(self):
        cfg = config.load_config(self._env(LOG_LEVEL="debug"))
        self.assertEqual(cfg.log_level, "DEBUG")
        with self.assertRaises(config.ConfigError):
            config.load_config(self._env(LOG_LEVEL="VERBOSE"))

    def test_log_format_validation(self):
        cfg = config.load_config(self._env(LOG_FORMAT="json"))
        self.assertEqual(cfg.log_format, "json")
        with self.assertRaises(config.ConfigError):
            config.load_config(self._env(LOG_FORMAT="xml"))

    def test_mqtt_bool_parsing(self):
        for truthy in ["1", "true", "YES", "on"]:
            cfg = config.load_config(self._env(MQTT_ENABLED=truthy))
            self.assertTrue(cfg.mqtt_enabled, msg=truthy)
        for falsy in ["0", "false", "no", "off"]:
            cfg = config.load_config(self._env(MQTT_ENABLED=falsy))
            self.assertFalse(cfg.mqtt_enabled, msg=falsy)

    def test_mqtt_port_bounds(self):
        with self.assertRaises(config.ConfigError):
            config.load_config(self._env(MQTT_PORT="0"))

    def test_awtrix_host_normalization(self):
        cfg = config.load_config(self._env(AWTRIX_HOST=" 192.168.1.1 , 192.168.1.2 "))
        self.assertEqual(cfg.awtrix_host, "192.168.1.1,192.168.1.2")

    def test_config_is_frozen(self):
        cfg = config.load_config(self._env())
        with self.assertRaises(AttributeError):
            cfg.home_lat = 0  # type: ignore

    def test_env_none_uses_os_environ(self):
        import os
        from unittest import mock
        with mock.patch.dict(os.environ, self._env(HOME_LAT="47.0", HOME_LON="2.0"), clear=False):
            cfg = config.load_config(None)
            self.assertEqual(cfg.home_lat, 47.0)


if __name__ == "__main__":
    unittest.main()
