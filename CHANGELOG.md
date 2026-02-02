# Changelog

All notable changes to this project will be documented in this file.

## [1.4] - 2026-02-02

### Added
- **Java Auto-Discovery**: Implemented a robust Java runtime resolution system.
    - If no system Java is found, the launcher searches the `runtime/` folder.
    - **Fallback Mechanism**: If no Java is found locally, the launcher will automatically download and install a Vanilla version to acquire the bundled Java Runtime, fixing `[WinError 2]` for Modloader installs.
- **Network Resilience**: Added graceful error handling for connection failures (e.g., DNS resolution errors, `getaddrinfo failed`). Users now see a friendly "Network Error" message instead of a raw traceback.
- **Build Configuration**:
    - Updated `alt.spec` to correctly bundle `wallpapers/` and `icons/` directories.
    - Added hidden imports for `pypresence` and `pystray`.

### Changed
- **Code Refactoring**: Major codebase restructuring. The monolithic `alt.py` has been split into modules:
    - `auth.py`: Authentication logic (Ely.by, etc.)
    - `handlers.py`: HTTP handlers for skins and Microsoft login.
    - `utils.py`: Shared utilities and file management.
    - `config.py`: Global constants and configuration.
- **Assets**: Moved default background images to the `wallpapers/` directory.
- **Installer**: Updated Inno Setup script (`installer.iss`) to version 1.4.

### Fixed
- Fixed a startup crash caused by an indentation error in `setup_tray`.
- Fixed `RPC` variable initialization errors.
- Fixed a crash during Fabric/Forge installation where the installer could not find a valid Java executable.
