# -*- mode: python ; coding: utf-8 -*-

import sys
from pathlib import Path

block_cipher = None


def collect_ffmpeg_data():
    root = Path(__file__).parent / "resources" / "ffmpeg"
    datas = []
    for platform_dir in ["windows", "macos"]:
        path = root / platform_dir
        if path.exists():
            datas.append((str(path), f"resources/ffmpeg/{platform_dir}"))
    return datas


a = Analysis(
    ['src/main.py'],
    binaries=[],
    datas=collect_ffmpeg_data(),
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='video-converter',
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
)

