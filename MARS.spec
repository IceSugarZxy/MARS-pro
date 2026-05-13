# -*- mode: python ; coding: utf-8 -*-
import sys
import os

SPEC_FILE = globals().get('__file__', os.path.join(os.getcwd(), 'MARS.spec'))
SPEC_DIR = os.path.dirname(os.path.abspath(SPEC_FILE))

block_cipher = None

icon_file = os.path.join(SPEC_DIR, 'src', 'icon.ico')

# Runtime assets that must sit next to MARS.exe in the onedir build.
datas = [
    (os.path.join(SPEC_DIR, 'src', 'ui'), 'ui'),
    (os.path.join(SPEC_DIR, 'src', 'windows'), 'windows'),
    (os.path.join(SPEC_DIR, 'src', 'core'), 'core'),
]

for relative_path in [
    os.path.join('src', 'configuration.txt'),
    os.path.join('src', 'configuration.example.txt'),
    os.path.join('src', 'icon.png'),
]:
    source_path = os.path.join(SPEC_DIR, relative_path)
    if os.path.exists(source_path):
        datas.append((source_path, '.'))

# Modules imported dynamically by PyQt, SciPy, pyqtgraph, and pyserial.
hiddenimports = [
    'PyQt5',
    'PyQt5.QtCore',
    'PyQt5.QtGui',
    'PyQt5.QtWidgets',
    'PyQt5.QtSerialPort',
    'pyqtgraph',
    'numpy',
    'scipy',
    'scipy.signal',
    'scipy.fft',
    'scipy.optimize',
    'serial',
    'serial.tools',
    'serial.tools.list_ports',
]

a = Analysis(
    [os.path.join(SPEC_DIR, 'src', 'main.py')],
    pathex=[SPEC_DIR],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
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
    [],
    exclude_binaries=True,
    name='MARS',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=icon_file,
    contents_directory='.',
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='MARS',
)
