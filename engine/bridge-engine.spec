# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_data_files


# Wildebeest is optional in development but its package data must accompany
# it whenever the real engine is installed in the release environment.
wildebeest_datas = collect_data_files('wildebeest')


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    # Unlike the USFM checker (a separate helper exe), tc_ai_bridge.versification
    # imports the vendored versification.py directly into this process at
    # runtime via sys.path + import, after bridge-engine.spec extracts it
    # here under sys._MEIPASS (see tc_ai_bridge/versification.py's
    # _vendor_root()). PyInstaller's static analysis cannot see that dynamic
    # import, so 'regex' (versification.py's one third-party dependency,
    # via the vendored ualign_utilities/general_util helpers) must be listed
    # explicitly below or a frozen build crashes with ModuleNotFoundError
    # the first time versification detection actually runs.
    datas=[
        ('resources', 'resources'),
        ('vendor/greekroom-versification', 'vendor/greekroom-versification'),
        *wildebeest_datas,
    ],
    hiddenimports=['regex'],
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
    name='bridge-engine',
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
