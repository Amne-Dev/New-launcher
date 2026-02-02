# Changelog

All notable changes to this project will be documented in this file.

## [1.6.1] - 2026-02-02

### Fixed
- **Reset Crash**: Fixed a critical `[Errno 2]` crash when using "Reset to Defaults". The restart mechanism now uses absolute paths and detached processes to guarantee a clean reboot.
- **Wallpaper Duplication**: Fixed a visual bug where default wallpapers (like "Island") would appear twice in the list if selected.
- **Factory Reset**: "Reset to Defaults" now correctly wipes the `config/wallpapers` directory, removing all custom user assets.

## [1.6] - 2026-02-02

### Added
- **Onboarding**: Integrated full Microsoft Device Code Flow login into the initial setup wizard (replacing the "Coming Soon" placeholder).

### Fixed
- **Onboarding Loop**: Fixed a bug where the Onboarding Wizard would reappear on every launch due to configuration saving race conditions.
- **Auto-Update**: Fixed a `[WinError 32]` (Failed to remove temporary directory) warning during auto-updates by properly detaching the new process on Windows.

## [1.5] - 2026-02-02

### Added
- **Skin Model Sync**: Implemented automatic synchronization of the skin model (Classic/Slim) with Minecraft servers on startup to ensure local state matches the server API.
- **Background Checks**: Added `_startup_ms_skin_check` to validate and update the skin configuration silently in the background.
- **Verbose Logging**: Enhanced debug logging for the `upload_ms_skin` function to print full request/response headers and bodies for easier troubleshooting.

### Changed
- **UI Overhaul**: Replaced all native Windows message boxes (`messagebox`) with a unified **Custom Message Box** (`CustomMessagebox`) system.
    - Dialogs now use the launcher's dark theme/color palette (`#3A3B3C`).
    - Standardized error, warning, and confirmation popups.
- **Error Handling**: 
    - Improved "Sync Error" feedback with specific guidance for users (e.g., prompt to re-upload if skin path is missing).
    - Fixed issues where the UI would desync from the actual server state.

### Fixed
- **Startup Crash**: Resolved `NameError: name 'root' is not defined` and `AttributeError` for `_default_root` in the new custom popup class.
- **Indentation**: Fixed logic formatting in the main `MinecraftLauncher` initialization.

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
