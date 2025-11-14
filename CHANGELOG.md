# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Changelog support for Home Assistant updates
- Terminus fonts support

### Fixed
- Retain user input when config flow fails
- Add translations for error strings

### Changed
- Use uv for test dependency installation in CI
- Updated entity documentation in README
- Removed autoDim references from codebase
- Removed enable_app and disable_app services

### Security
- Added "Verify SSL certificate" checkbox option for secure connections

## [0.0.1] - 2025-10-31

### Added
- Initial release of TronbytAssistant integration
- Support for Tronbyt device notifications from Home Assistant
- Brightness control via light entity
- Update interval configuration via number entity
- Pinned app selection via select entity
- Night mode toggle via switch entity
- Night mode start/end time configuration
- Night mode brightness and app selection
- Dim mode start time and brightness configuration
- Built-in notification service (Push)
- Custom text notification service (Text)
- App deletion service (Delete)
- Template support for dynamic content
- Argument passing to apps
- HACS integration support
- Configuration flow for easy setup
- Multi-language support (English and German translations)

### Features
- Local polling IoT class for reliable communication
- Single config entry design
- Multi-device support
- Service selectors that update automatically
- Template value support for dynamic content
- HTTP error handling and logging
- Pre-commit hooks for code quality
- Comprehensive test suite

[Unreleased]: https://github.com/tronbyt/TronbytAssistant/compare/v0.0.1...HEAD
[0.0.1]: https://github.com/tronbyt/TronbytAssistant/releases/tag/v0.0.1
