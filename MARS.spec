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

# 随包附带的历史波形数据（打包进 dist/data/plot_data/<日期>，运行时"历史数据"面板可直接加载）
#   默认：打包"今天"的 plot_data
#   可用环境变量 MARS_BUNDLE_DATA 指定，多个日期用逗号分隔；
#   设为 none / 空字符串则不带任何历史数据
#   例：set MARS_BUNDLE_DATA=20260930,20260729
import datetime as _dt

_bundle_dates = os.environ.get('MARS_BUNDLE_DATA', _dt.date.today().strftime('%Y%m%d'))
_plot_root = os.path.join(SPEC_DIR, 'data', 'plot_data')
if _bundle_dates and _bundle_dates.strip().lower() != 'none' and os.path.isdir(_plot_root):
    for _date in [d.strip() for d in _bundle_dates.split(',') if d.strip()]:
        _src = os.path.join(_plot_root, _date)
        if os.path.isdir(_src):
            datas.append((_src, os.path.join('data', 'plot_data', _date)))

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

# 明确排除用不到的重型依赖：matplotlib/PIL 只是 pyqtgraph 的 exporter 子模块
# 被连带收集进来的（源码里没有任何地方 import matplotlib），排除后 dist 少约 35 MB。
# 如果以后真的要用 matplotlib 出图，把对应项从这里删掉即可。
excludes = [
    'matplotlib',
    'PIL',
    'contourpy',
    'kiwisolver',
    'dateutil',
    'pandas',
    'tkinter',
    'PyQt5.QtWebEngineWidgets',
    'PyQt5.QtQuick',
    'PyQt5.QtQml',
    'PyQt5.QtMultimedia',
    'PyQt5.QtBluetooth',
    'PyQt5.QtNetworkAuth',
    'PyQt5.QtWebSockets',
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
    excludes=excludes,
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
