#!/bin/bash
set -e

# AppImage Builder Script for New Launcher
# Run this script on a Linux system (Ubuntu 20.04+ recommended) inside the repository root.

APP_NAME="NewLauncher"
BUILD_DIR="build_linux"
DIST_DIR="dist_linux"
APP_DIR="AppDir"

echo "=== Starting AppImage Build ==="

# 1. Verification
if [ ! -f "alt.py" ]; then
    echo "Error: alt.py not found. Please run this script from the repository root."
    exit 1
fi

# 2. Cleanup
echo "[*] Cleaning previous builds..."
rm -rf "$BUILD_DIR" "$DIST_DIR" "$APP_DIR" *.AppImage

# 3. Dependencies
echo "[*] Setting up Virtual Environment..."
if [ -d "venv_build" ]; then
    rm -rf venv_build
fi

if ! python3 -m venv venv_build; then
    echo "Error: Failed to create virtual environment."
    echo "Please install the venv package:"
    echo "  Debian/Ubuntu: sudo apt install python3-venv"
    echo "  Fedora: dnf install python3"
    exit 1
fi

source venv_build/bin/activate

echo "[*] Installing Python dependencies..."
pip install -r requirements.txt pyinstaller --quiet

# 4. Build Binary (PyInstaller)
echo "[*] Running PyInstaller..."
# We use the existing alt.spec. 
# PyInstaller on Linux will generate a Linux binary from it.
pyinstaller alt.spec --distpath "$DIST_DIR" --workpath "$BUILD_DIR" --noconfirm --clean

# Deactivate venv
deactivate
rm -rf venv_build

# 5. Prepare AppDir
echo "[*] Creating AppDir..."
mkdir -p "$APP_DIR/usr/bin"
mkdir -p "$APP_DIR/usr/share/icons/hicolor/256x256/apps"
mkdir -p "$APP_DIR/usr/share/applications"

# 6. Install Files
# Copy binary
echo "[*] Installing binary..."
# Note: Since alt.spec defines a One-File EXE, we take the single file
cp "$DIST_DIR/$APP_NAME" "$APP_DIR/usr/bin/$APP_NAME"
chmod +x "$APP_DIR/usr/bin/$APP_NAME"

# Copy Icon
echo "[*] Installing icon..."
cp logo.png "$APP_DIR/logo.png"
cp logo.png "$APP_DIR/usr/share/icons/hicolor/256x256/apps/logo.png"

# Copy Desktop File
echo "[*] Installing desktop file..."
cp linux/NewLauncher.desktop "$APP_DIR/NewLauncher.desktop"
# Fix potential Windows CRLF line endings
sed -i 's/\r$//' "$APP_DIR/NewLauncher.desktop"
cp "$APP_DIR/NewLauncher.desktop" "$APP_DIR/usr/share/applications/NewLauncher.desktop"

# 7. Create AppRun
# Since it's a single binary, we can just point AppRun to it, 
# but a script ensures environment variables (like PATH) are sane if needed.
echo "[*] Creating AppRun..."
cat > "$APP_DIR/AppRun" <<EOF
#!/bin/bash
HERE="\$(dirname "\$(readlink -f "\${0}")")"
export PATH="\${HERE}/usr/bin:\${PATH}"
exec "\${HERE}/usr/bin/$APP_NAME" "\$@"
EOF
chmod +x "$APP_DIR/AppRun"

# 8. Build AppImage
echo "[*] Downloading AppImageTool..."
if [ ! -f "appimagetool-x86_64.AppImage" ]; then
    wget -q -O appimagetool-x86_64.AppImage https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage
    chmod +x appimagetool-x86_64.AppImage
fi

echo "[*] Packaging AppImage..."
# ARCH=x86_64 covers most desktop linux users
export ARCH=x86_64
./appimagetool-x86_64.AppImage "$APP_DIR" "$APP_NAME-1.4-x86_64.AppImage"

echo "=== Build Complete ==="
echo "Generated: $APP_NAME-1.4-x86_64.AppImage"
