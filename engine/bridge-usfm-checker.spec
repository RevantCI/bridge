# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['usfm_checker_main.py'],
    pathex=['vendor/greekroom-usfm'],
    binaries=[],
    # Keep the pinned upstream files together. usfm_check.py resolves both
    # data files relative to its own __file__, and imports the vendored
    # ualign_utilities/greekroom modules from this same directory.
    datas=[('vendor/greekroom-usfm', 'greekroom-usfm')],
    # The upstream CLI is loaded with runpy so PyInstaller cannot discover
    # its imports statically. Keep this list aligned with usfm_check.py,
    # ualign_utilities.py, and greekroom/gr_utilities/general_util.py.
    hiddenimports=[
        'argparse', 'collections', 'datetime', 'json', 'math', 'os',
        'pathlib', 'regex', 'typing', 'unicodedata',
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
    name='bridge-usfm-checker',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # See bridge-engine.spec's comment: UPX isn't installed in this
    # project's build environment, and provides no benefit on a machine
    # where it is, once there's no large resources payload to shrink.
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
