# Changelog

All notable changes to this project will be documented in this file.

## [1.8] - 2026-02-04

### Added
- **Background Agent**: Introduced a separate `agent.exe` process to handle heavy tasks (Modrinth searches, skin syncing) without freezing the main UI.
- **GitHub Skin Sync**: New feature in the "Addons" tab allowing users to link a GitHub repository to upload their skin and automatically download skins from friends/others in the repo.
- **Installer Improvements**: The installer now intelligently detects if it's a fresh install or an update, hiding the "Create Desktop Shortcut" checkbox for updates.
- **Data Persistence**: Ensured all local data (like cached skins) is saved to the `%AppData%\.nlc` directory, even when installed in restricted folders.

### Fixed
- **Scroll Glitch**: Fixed an issue where the Mods and Addons tabs would scroll infinitely upwards when using the mouse wheel.
- **Updater Launch**: Fixed a bug where the launcher wouldn't restart automatically after an update; switched to `os.startfile` for better UAC handling.
- **Installer Permissions**: The "Launch New Launcher" checkbox in the installer now starts the app with standard user privileges instead of inheriting Admin rights, preventing permission issues with configuration files.

## [1.7] - 2026-02-03

### Added
- **Addons System**: New "Addons" tab in the main sidebar for experimental features.
- **Persona 3 Reload Menu**: A new "Addons" option to replace the standard main menu with a stylized, animated interface inspired by Persona 3 Reload.
- **Download Manager**: A centralized system to handle all downloads with configurable concurrency limits (defaults to 1 Modpack, 3 Mods at a time) and speed throttling options in Settings.
- **Modrinth Toggle**: Mod support is now optional and disabled by default to improve startup performance. Users are prompted to enable it via the sidebar, with warnings about resource usage.
- **Downloads Settings**: A new section in the Settings tab to control download speeds and parallel limits.
- **Global Crash Handler**: A robust exception catcher that logs full tracebacks to file and displays a user-friendly error dialog instead of silently closing.
- **Lazy Loading**: The Modrinth/Mods tab is now initialized only upon first access, reducing initial memory footprint and load time.

### Changed
- **Logging System**: Completely rewrote logging to use Python's standard `logging` module. Logs are now saved to the configuration directory (`.nlc/logs` or local `logs/`) for better accessibility and diagnostics.
- **Modpack UX**: The "Create Modpack" button's "+" action now intelligently falls back to a local file picker if Modrinth integration is disabled.
- **Sidebar Navigation**: Reordered buttons for better flow; disabled features trigger helpful dialogs instead of being hidden.

### Fixed
- **Dialog Crashes**: Fixed a `TclError` caused by an invalid cursor property in the Modrinth enabling dialog.
- **Modpack Installation**: Refactored the "Create Matching Installation" logic to use the internal profile list directly, preventing sync issues with `launcher_config.json`.

## [1.6.4] - 2026-02-03

### Added
- **Wallpaper Injection**: Creating a seamless experience, the launcher now automatically injects your active wallpaper into the Minecraft Main Menu as a static background (replacing the spinning panorama).
- **Discord RPC Upgrade**: Rich Presence now displays the actual player's head (fetched via UUID) instead of the default "Steve" icon, falling back gracefully if offline.
- **Resource Pack Generation**: Implemented a dynamic `LauncherTheme.zip` generator that creates a valid resource pack for modern Minecraft versions (1.21+), handling icon resizing and format compatibility automatically.

### Fixed
- **Profile Persistence**: Fixed a critical bug where restarting the launcher would reset the active profile to "Steve". Valid Microsoft/Ely.by sessions now persist correctly.
- **Resource Reload Errors**: Solved "Resource Reload Failed" errors in Minecraft 1.21 by enforcing strict image dimensions (1024x1024) for panorama injection and removing invalid metadata ranges.
- **Config Race Condition**: Fixed a logic error where UI updates during profile switching would accidentally overwrite the saved configuration with default values.

## [1.6.2] - 2026-02-02

### Added
- **Progress Overlay**: A unified, persistent progress bar overlay now covers the bottom action bar during long tasks (Game Launch, Auto-Updates). This replaces inconsistent floating popups.
- **Custom Update Options**: The startup "Update Available" prompt now features 3 custom buttons: "Yes, Update", "I'll do it myself" (opens GitHub), and "No".

### Changed
- **Update Logic**: Updates are now downloaded to a persistent `config/updates` folder instead of the system Temp folder, resolving "Failed to load Python DLL" errors during self-updates.
- **Restart Mechanism**: Hardened the restart process for updates and factory resets to fully detach from the parent process, preventing file locking issues and `[WinError 32]`.

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
