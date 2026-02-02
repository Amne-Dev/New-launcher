# New Launcher — Project Wiki

Welcome to the project wiki. This file provides a centralized, human-readable overview of the project and links to canonical documentation and website pages.

## Overview
New Launcher is a lightweight, open-source Minecraft launcher supporting Vanilla, Fabric, and Forge. It focuses on speed, simplicity, and local-first privacy.

## Quick links (hosted)
- Website: https://amne-dev.github.io/New-launcher/
- Changelog: https://amne-dev.github.io/New-launcher/changelog.html
- Privacy Policy: https://amne-dev.github.io/New-launcher/privacy.html
- Terms: https://amne-dev.github.io/New-launcher/terms.html
- FAQ: https://amne-dev.github.io/New-launcher/faq.html
- Getting Started: https://amne-dev.github.io/New-launcher/getting-started.html
- Download & Verification: https://amne-dev.github.io/New-launcher/download.html
- Support: https://amne-dev.github.io/New-launcher/support.html
- Contributing: https://amne-dev.github.io/New-launcher/contributing.html
- Security: https://amne-dev.github.io/New-launcher/security.html
- Credits: https://amne-dev.github.io/New-launcher/credits.html
- Roadmap: https://amne-dev.github.io/New-launcher/roadmap.html
- Gallery: https://amne-dev.github.io/New-launcher/gallery.html
- Wiki (site): https://amne-dev.github.io/New-launcher/wiki.html

## Getting Started
1. Download the latest installer from the Releases page on GitHub: https://github.com/Amne-Dev/New-launcher/releases
2. Run the installer for your platform (Windows installer provided). See `web/getting-started.html` (when available).

## User Guide

### 1. Managing Accounts
The launcher supports three types of accounts:
*   **Microsoft Account**: Click "Add Profile" -> "Microsoft". A browser window will open to authenticate with your Microsoft account. Once logged in, your skin and username will sync automatically.
*   **Ely.by**: Click "Add Profile" -> "Ely.by". Enter your username and password. This supports skin injection automatically.
*   **Offline**: Click "Add Profile" -> "Offline". Just enter a username.
    *   *Note*: In offline mode, you can upload a custom skin file (.png) in the profile settings, which will be injected locally using an integrated auth server.

### 2. Creating Installations
Navigate to the **Installations** tab to manage your game versions.
*   **Create New**: Click the "+" button.
    *   **Name**: Give your installation a name (e.g., "Survival 1.20").
    *   **Version**: Select the Minecraft version.
    *   **Loader**: Choose between **Vanilla**, **Fabric**, or **Forge**. The launcher handles the installation of the modloader automatically.
    *   **Icon**: Select a block icon or a custom `.png` image.

### 3. Settings & Customization
Click the **Gear Icon** to access settings.
*   **RAM Allocation**: Use the slider to increase memory for modded instances (Default is 4GB).
*   **Wallpapers**: Customize the launcher background. You can select pre-loaded images or import your own from the `wallpapers/` folder.
*   **Rich Presence**: Toggle Discord RPC integration to show your game status ("Playing Minecraft 1.21").
*   **Java Arguments**: Advanced users can supply custom JVM arguments (e.g., G1GC flags).

### 4. Custom Skins (Offline/Ely.by)
*   **Ely.by**: Skins are managed on the Ely.by website.
*   **Offline**: Go to your profile settings, click **"Select Skin"**, and choose a valid skin `.png` file. The launcher will start a local server to inject this skin into your game session transparently.

## Developer Documentation
For those looking to contribute or understand the codebase, the project has recently been refactored (v1.4) into modular components:

*   **`alt.py`**: The entry point and main application controller. Handles UI rendering and launch orchestration.
*   **`auth.py`**: Authentication logic for various services (Ely.by local auth, etc.).
*   **`handlers.py`**: Contains `http.server` handlers for local skin injection and Microsoft login callbacks.
*   **`utils.py`**: Shared utility functions, file path management (resource_path), and image helpers.
*   **`config.py`**: Global constants (Version, Client IDs, Defaults).

### Building from Source
To build the executable, use PyInstaller with the provided spec file:
```bash
pyinstaller alt.spec
```

### Skin System Architecture

The launcher implements three distinct methods for handling player skins, depending on the account type.

#### 1. Microsoft/Mojang (Official)
*   **Mechanism**: Reference client behavior. The launcher authenticates with Microsoft OAuth2.
*   **Game Launch**: The access token and UUID are passed to the game.
*   **Skin Resolution**: The game client contacts official Mojang Session Servers (`sessionserver.mojang.com`) using the provided token to retrieve the skin assigned to that UUID in the official database.

#### 2. Ely.by (Third-Party Service)
*   **Mechanism**: Authlib Injection via Remote Server.
*   **Authorization**: The launcher authenticates the user against Ely.by's API to get a valid token.
*   **Game Launch**: The launcher adds `-javaagent:authlib-injector.jar=https://authserver.ely.by/api/authlib-injector` to the JVM arguments.
*   **Skin Resolution**: `authlib-injector` redirects all internal game requests for profile data to Ely.by's servers instead of Mojang's. Ely.by returns the skin texture associated with the user's account on their platform.

#### 3. Offline Mode (Local Injection)
This is a custom implementation allowing offline users to see their own skins without modifying the game JAR.

**The Workflow:**
1.  **Server Startup**: When launching an offline profile with a custom skin selected, `handlers.py` starts a `ThreadingTCPServer` on a random free port (e.g., `127.0.0.1:54321`).
2.  **Authlib Configuration**: The launcher calls `authlib-injector` pointing to this local address: `-javaagent:authlib-injector.jar=http://127.0.0.1:54321`.
3.  **Request Highjacking**: When the game client attempts to load the player's profile:
    *   It requests the Profile Data from the configured auth server (our local one).
    *   **Endpoint**: `/sessionserver/session/minecraft/profile/<UUID>`
    *   **Response**: The local server constructs a valid Yggdrasil-compatible JSON response. This response mimics a signed profile but contains a texture property pointing to `http://127.0.0.1:54321/textures/skin.png`.
4.  **Texture Delivery**:
    *   The game client reads the JSON response and sees the texture URL.
    *   It makes a GET request to `/textures/skin.png`.
    *   The local server reads the `.png` file specified in the Launcher Profile from the disk and renders it to the game.

**Why this matters**: This allows "Offline" skins to work seamlessly and be visible to the player (and potentially others on LAN if they shared the spoofing setup, though currently designed for local-only).

## Privacy
The launcher does not collect, transmit, or aggregate user data. See `web/privacy.html` for details.

## Troubleshooting / FAQ
See `web/faq.html` (to be added) for common issues. For immediate help, open an issue on GitHub: https://github.com/Amne-Dev/New-launcher/issues

## Contributing
Please read `CONTRIBUTING.md` (or `web/contributing.html` once added) for build and PR guidance. Basic steps:
1. Fork the repo
2. Create a feature branch
3. Open a pull request with a clear description

## Security
Report vulnerabilities via a GitHub issue or private contact if available. See `web/security.html` when added.

## Credits
See `CREDITS.md` for contributors and third-party libraries.

---
This wiki is intentionally concise. Expand any section by adding site pages under `web/` and linking them here.