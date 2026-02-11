# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['installer_app.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('logo.ico', '.'),
        ('logo.png', '.'),
        ('logo.ico', 'payload'),
        ('logo.png', 'payload'),
        ('dist/NewLauncher.exe', 'payload'),
        ('dist/agent.exe', 'payload'),
    ],
    hiddenimports=['PIL', 'PIL.Image', 'PIL.ImageTk'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='NLCSetup',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['logo.ico'],
)
