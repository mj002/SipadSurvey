# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['survey.py'],
    # Build with the dependency versions shipped in this repository.
    pathex=['Lib/site-packages'],
    datas=[],
    # Selenium exposes webdriver.Chrome through a lazy import. PyInstaller
    # cannot discover that module from the attribute access alone.
    hiddenimports=[
        'selenium.webdriver.chrome.webdriver',
        'selenium.webdriver.chrome.options',
    ],
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
    name='survey',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
