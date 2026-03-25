# -*- mode: python ; coding: utf-8 -*-
import sys
import os

block_cipher = None

# 收集所有必要的模块
hiddenimports = [
    'PyQt5',
    'PyQt5.QtCore',
    'PyQt5.QtGui',
    'PyQt5.QtWidgets',
    'PyQt5.QtSerialPort',
    'PyQt5.QtSerialPort.QSerialPortInfo',
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
    ['src/main.py'],
    pathex=[os.getcwd()],
    binaries=[],
    datas=[
        ('src/ui', 'ui'),
        ('src/windows', 'windows'),
        ('src/core', 'core'),
    ],
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
