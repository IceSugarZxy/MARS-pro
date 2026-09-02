# -*- mode: python ; coding: utf-8 -*-
"""
MARS Pro — PyInstaller 打包配置 (onedir 文件夹分发)
"""

import os

SPEC_FILE = globals().get('__file__', os.path.join(os.getcwd(), 'MARS.spec'))
SPEC_DIR = os.path.dirname(os.path.abspath(SPEC_FILE))

block_cipher = None
APP_NAME = 'MARS_Pro'

icon_file = os.path.join(SPEC_DIR, 'src', 'icon.ico')

# ============================================================================
# Data files
# ============================================================================
datas = [
    (os.path.join(SPEC_DIR, 'src', 'ui'), 'ui'),
    (os.path.join(SPEC_DIR, 'src', 'windows'), 'windows'),
    (os.path.join(SPEC_DIR, 'src', 'core'), 'core'),
]

# 根目录配置文件
for relative_path in [
    os.path.join('src', 'configuration.txt'),
    os.path.join('src', 'configuration.example.txt'),
    os.path.join('src', 'icon.png'),
]:
    source_path = os.path.join(SPEC_DIR, relative_path)
    if os.path.exists(source_path):
        datas.append((source_path, '.'))

# 仅包含 7/29 的波形数据，raw_data 不复制
plot_data_0729 = os.path.join(SPEC_DIR, 'data', 'plot_data', '20260729')
if os.path.isdir(plot_data_0729):
    datas.append((plot_data_0729, os.path.join('data', 'plot_data', '20260729')))

# 日志目录（运行时自动创建，此处仅保留占位）
logs_dir = os.path.join(SPEC_DIR, 'logs')
if os.path.isdir(logs_dir):
    datas.append((logs_dir, 'logs'))

# 一致性测试脚本
test_dir = os.path.join(SPEC_DIR, '一致性测试')
if os.path.isdir(test_dir):
    datas.append((test_dir, '一致性测试'))

# ============================================================================
# Hidden imports
# ============================================================================
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

# ============================================================================
# Build
# ============================================================================
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
    name=APP_NAME,
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
    name=APP_NAME,
)
