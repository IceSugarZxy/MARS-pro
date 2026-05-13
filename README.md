# MARS

MARS 是一个基于 PyQt5 的旋转体表磁测量分析系统，用于串口控制、位置贴靠、偏置校准、旋转测量、波形分析、历史数据管理和数据比对。

当前仓库根目录就是 `MARS/` 本身，下面的命令、路径和打包说明都以这个目录为基准。

## 功能概览

- 串口连接、参数配置、自动扫描串口和启动时自动连接
- 测试位置 / 挂起位置保存、移动和流程化执行
- 下压贴靠、左贴靠、右贴靠、贴靠回弹距离配置
- 偏置校准、零位校准
- 平面旋转、外侧面旋转、内侧面旋转、外侧面垂直四种测试类型
- 可编辑的测试 / 挂起移动方案，测量界面与测试配置界面同步显示当前流程
- 实时波形显示、双击恢复默认坐标、历史波形蓝色显示
- N/S 极峰值、极间隔、面积、THD、极对数等结果分析
- 历史数据自动刷新、筛选和双击加载
- 双文件波形比对和结果比对
- PyInstaller 打包，使用 `src/icon.png` 生成的图标

## 环境要求

- Windows 10/11
- Python 3.8+
- 串口硬件设备

安装依赖：

```powershell
pip install -r requirements.txt
```

## 启动

源码运行：

```powershell
python src/main.py
```

打包后运行：

```powershell
dist/MARS/MARS.exe
```

## 打包

```powershell
pyinstaller MARS.spec --clean --noconfirm
```

打包完成后，可执行文件输出在 `dist/MARS/MARS.exe`。`MARS.spec` 会导入：

- `src/ui/`
- `src/windows/`
- `src/core/`
- `src/configuration.txt`（本地文件存在时）
- `src/configuration.example.txt`
- `src/icon.png`

`src/icon.ico` 由 `src/icon.png` 生成，用于嵌入 `MARS.exe` 的 Windows 图标。

## 目录结构

```text
.
├─src/
│  ├─core/                      # 串口、配置、数据处理、线程管理
│  ├─ui/                        # Qt Designer .ui 文件和主题
│  ├─windows/                   # 各功能面板和对话框
│  ├─logs/                      # 源码运行时日志目录
│  ├─configuration.example.txt  # 示例配置
│  ├─configuration.txt          # 本地运行配置，不提交到 Git，首次运行会自动创建
│  ├─icon.png                   # 应用窗口图标源图
│  ├─icon.ico                   # PyInstaller 可执行文件图标
│  └─main.py                    # 程序入口
├─data/
│  ├─raw_data/                  # 原始测量数据
│  └─plot_data/                 # 波形与分析结果数据
├─logs/                         # 打包后程序运行日志目录
├─MARS.spec                     # PyInstaller 配置
├─requirements.txt              # Python 依赖
├─用户手册.md
├─命令集.md
└─软件通信手册.md
```

## 配置说明

配置文件按运行方式区分：

- 源码运行读取 `src/configuration.txt`
- 打包运行读取 `dist/MARS/configuration.txt`
- 如果配置文件不存在，程序会按默认值自动创建
- `configuration.txt` 和 `src/configuration.txt` 都作为本地配置处理，不提交到 Git
- 打包时如果 `src/configuration.txt` 存在，会复制为 `dist/MARS/configuration.txt`
- `src/configuration.example.txt` 是可提交的示例配置

常用字段：

```text
offset:0
COM:COM12
baudrate:921600
bytesize:8
stopbits:1
parity:无
test_x:0
test_z:0
suspend_x:0
suspend_z:0
test_type:0
test_movement_scheme:x_first
suspend_movement_scheme:z_first
inner_x_offset:5
inner_z_offset:1
retract_distance:0.3
```

移动方案会保存在 `test_type_schemes` 字段中，程序会在配置不存在或格式不合法时回退到默认方案。

## 数据与日志

源码运行：

- 测量数据保存到 `data/raw_data/` 和 `data/plot_data/`
- 日志写入 `src/logs/`

打包运行：

- 测量数据保存到 `dist/MARS/data/raw_data/` 和 `dist/MARS/data/plot_data/`
- 日志写入 `dist/MARS/logs/`

这些目录都按运行产物处理，默认不提交到 Git。

## 近期调整

- 2026-05-13：更新 README 和用户手册，补齐当前打包、图标、配置路径和操作说明
- 2026-05-13：打包改为使用 `icon.png` 生成 `icon.ico`，并将图标和配置文件导入 `dist/MARS/`
- 2026-05-08：测量界面测试配置区改为显示当前测试类型的测试 / 挂起流程，并与测试配置面板同步
- 2026-05-08：历史数据界面每次打开自动刷新列表，移除“打开并分析”按钮，保留双击打开历史数据
- 2026-05-08：测量波形区域双击改为恢复默认坐标范围，不再弹出放大窗口
- 2026-05-08：数据比对分析结果字号调整为 20
- 修复 PyInstaller 规格文件对工作目录的依赖，支持从仓库根直接打包
- 历史数据列表改为后台加载，避免界面卡顿

## 许可证

MIT
