# New Launcher

A modern, lightweight, and customizable Minecraft launcher built with Python.

## Features

*   **Multi-Loader Support**: Seamlessly launch **Vanilla**, **Forge**, and **Fabric** versions of Minecraft.
*   **Version Management**: Automatically detects your installed Minecraft versions. easily switch between different versions.
*   **Profile System**: 
    *   Create and manage multiple profiles.
    *   Supports **Offline/Developer Mode** accounts.
    *   Skin customization support (view your skin head in the launcher).
*   **Performance Control**:
    *   **RAM Allocation**: Adjust memory usage with a slider or precise manual entry (1GB - 16GB+).
    *   **Java Arguments**: Full control over JVM flags for optimization.
*   **Discord Integration**: Built-in **Discord Rich Presence (RPC)** to show your friends what you're playing.
*   **Customization**:
    *   Change your Minecraft installation directory.
    *   Dark mode UI with a clean, modern aesthetic.
*   **Diagnostics**: Integrated log viewer to troubleshoot issues easily.

## Installation

1.  Download the latest `alt.exe` from the releases page (or the `dist` folder if you built it yourself).
2.  Place the executable in a folder of your choice (e.g., on your Desktop or in a dedicated "Games" folder).
3.  Run `alt.exe`.

## Usage

### Getting Started
1.  **Select Loader**: Choose between Vanilla, Forge, or Fabric from the dropdown menu.
2.  **Select Version**: Pick the Minecraft version you want to play.
3.  **Launch**: Click the big green **PLAY** button to start the game.

### Managing Accounts
*   Click the user profile icon (or the name in the sidebar) to open the profile menu.
*   Select **Add Account** to create a new offline profile.
*   Enter your desired username and save.

### Settings
Navigate to the **SETTINGS** tab to configure:
*   **Memory (RAM)**: Use the slider to allocate more RAM if you are playing with heavy mods.
*   **Game Directory**: Change where Minecraft files are stored.
*   **Discord status**: Toggle Rich Presence on or off.

## Configuration
The launcher saves your preferences (profiles, RAM settings, etc.) in your AppData folder:
`%APPDATA%\.nlc\launcher_config.json`

## Requirements
*   A valid Minecraft installation (recommended).
*   Java runtime environment (JRE) installed for the versions of Minecraft you intend to play.

## Disclaimer
This launcher is an independent project and is not affiliated with Mojang Studios or Microsoft.
