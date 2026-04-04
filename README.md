# NLC (neo) A Minecraft launcher designed to be lightweight
   
Its Simple. Fast. Customizable.

## ✨ What does it do?
*   **Play Everything**: Supports **Vanilla**, **Fabric**, and **Forge**.
*   **Looks Familiar**: A modern design that looks like the official launcher, but feels faster.
*   **Custom Icons**: Pick real **Minecraft Blocks** (like Diamond Block, TNT, or Workbench) for your installation icons!
*   **Discord Status**: Shows your friends exactly what you're playing with built-in Rich Presence.
*   **Offline Support**: Create offline ("Developer") accounts easily.

## � Documentation
For detailed guides, troubleshooting, and developer docs, check out our [**Project Wiki**](WIKI.md).

## 📥 How to Install

### Windows
1.  Download the latest `NLCSetup.exe` from the [Releases](https://github.com/Amne-Dev/New-launcher/releases) page.
2.  Run the installer and follow the prompts.
3.  Open **New Launcher** from the Start Menu or desktop shortcut.

### Linux
1.  Download the latest Linux `AppImage` from the [Releases](https://github.com/Amne-Dev/New-launcher/releases) page.
2.  Open a terminal in the folder containing the file.
3.  Make it executable:

```bash
chmod +x NewLauncher-*-x86_64.AppImage
```

4.  Launch it:

```bash
./NewLauncher-*-x86_64.AppImage
```

If your desktop does not launch AppImages directly, you can still run it from the terminal with the command above.

### Linux From Source
If you want to build the Linux AppImage yourself:

```bash
chmod +x linux/build_appimage.sh
./linux/build_appimage.sh
```

That script creates a portable Linux AppImage from the repository root.

## 🎮 How to Play
1.  **Create a Profile**: On the sidebar, click the profile name (e.g. "Steve") to add your own offline username.
2.  **Add a Version**: 
    *   Go to the **Installations** tab.
    *   Click **New Installation**.
    *   Pick a Version (like 1.20.1) and a Loader (Vanilla, Fabric, etc.).
    *   **Pro Tip**: Click the icon box to choose a cool block texture!
3.  **Launch**: Go back to the **Play** tab, select your version from the bottom list, and hit **PLAY**.

## ⚡ Power Users (RAM)
Need more memory for mods?
1.  Click **Settings** on the sidebar.
2.  Drag the **Java Memory** slider to the right.
3.  That's it!

## 📜 Credits
Huge thanks to the creators of the libraries used in this project: `minecraft-launcher-lib`, `requests`, `Pillow`, and `pypresence`.
See the full [CREDITS.md](CREDITS.md) file for details.

---
*This is an open-source project and is not affiliated with Mojang Studios or Microsoft.*
