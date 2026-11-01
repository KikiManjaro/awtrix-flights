# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Docker `HEALTHCHECK` via heartbeat file (`/tmp/awtrix-flights.heartbeat`)
- `HEARTBEAT_FILE` environment variable to customize heartbeat path

## [0.2.0] - 2026-08-14

### Added
- MQTT publishing for home-automation integration (`MQTT_ENABLED`, `MQTT_HOST`, etc.)
- Multi-display support (comma-separated `AWTRIX_HOST`)
- Custom airlines table via `AIRLINES_FILE`
- Colored text segments via `FIELD_COLORS`
- `AWTRIX_BEARING` for heading-oriented icon rotation
- GitHub Actions CI (tests, lint, Docker build) and GHCR publishing
- Dependabot for automated dependency updates

### Changed
- Icon rendering now uses single `db` draw command (firmware 0.98 compatibility)
- Default `ICON_ENABLED` is `false` (safety for firmware 0.98)

## [0.1.0] - 2026-08-10

### Added
- Initial release: live flight detection via OpenSky Network API
- AWTRIX 3 display integration with heading-oriented 8x8 plane icon
- Configurable detection radius and minimum altitude
- Anti-spam cooldown per callsign
- Docker and docker-compose deployment
- Unraid Community Apps template

[Unreleased]: https://github.com/KikiManjaro/awtrix-flights/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/KikiManjaro/awtrix-flights/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/KikiManjaro/awtrix-flights/releases/tag/v0.1.0
