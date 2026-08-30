# QML launcher

Run the first PySide6/QML screen with:

```powershell
python qt_launcher/app.py
```

It uses the same `launcher_config.json` and modpack storage as the existing
launcher. The QML build can select installations and offline profiles, persist
the selected wallpaper, synchronise a linked modpack immediately before play,
and launch Vanilla, Fabric, or Forge without blocking the interface.

Installations and modpacks use focused modal editors. The Modrinth page keeps
discovery and installed-mod management together: browse mods, textures,
shaders, or modpacks, then install compatible files in the background. Local
and imported modpacks retain isolated storage and sync to their linked
installation immediately before launch.

It supports offline, Microsoft device-flow, and Ely.by accounts. Microsoft
credentials stay in the system browser/device flow; Ely.by passwords are used
only for the sign-in request and are not written to the launcher config.
