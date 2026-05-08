# MARS

MARS 是一个基于 PyQt5 的旋转体表磁测量分析系统，集成了串口通信、位置控制、偏置校准、实时波形显示、历史数据查看和波形分析能力。

当前仓库根目录就是 `MARS/` 本身，下面的命令、路径和打包说明都以这个目录为基准。

## 功能概览

- 串口连接、参数配置和自动重连
- 测试位置 / 挂起位置控制
- 偏置校准、零位校准
- 平面旋转、外侧面旋转、内侧面旋转、外侧面垂直四种测试类型
- 可编辑的测试 / 挂起移动方案
- 实时波形显示与结果分析
- 历史数据加载和波形比对
- PyInstaller 打包

## 环境要求

- Python 3.8+
- Windows
- 支持 PyQt5 QtSerialPort 的运行环境

## 安装

```bash
pip install -r requirements.txt
```

## 启动

```bash
python src/main.py
```

## 打包

```bash
pyinstaller MARS.spec --clean
```

打包完成后，可执行文件输出在 `dist/MARS/`。

## 目录结构

```text
.
├─src/
│  ├─core/                      # 串口、配置、数据处理、线程管理
│  ├─ui/                        # Qt Designer .ui 文件和主题
│  ├─windows/                   # 各功能面板和对话框
│  ├─logs/                      # 源码运行时日志目录
│  ├─configuration.example.txt  # 示例配置
│  ├─configuration.txt          # 本地运行配置，首次运行会自动生成
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

- 程序运行时读取 `src/configuration.txt`
- 如果文件不存在，程序会自动按默认值创建
- `src/configuration.txt` 和根目录 `configuration.txt` 都作为本地配置处理，不再纳入 Git 跟踪
- 可以参考 `src/configuration.example.txt` 了解常用字段

示例：

```text
offset:0
COM:COM12
baudrate:921600
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

## 数据与日志

- 测量数据默认保存到 `data/raw_data/` 和 `data/plot_data/`
- 源码运行时日志默认写入 `src/logs/`
- 打包后的程序日志默认写入可执行文件同级的 `logs/`

这些目录都按运行产物处理，默认不提交到 Git。

## 近期调整

- 2026-05-08：测量界面测试配置区改为显示当前测试类型的测试 / 挂起流程，并与测试配置面板同步
- 2026-05-08：历史数据界面每次打开自动刷新列表，移除“打开并分析”按钮，保留双击打开历史数据
- 2026-05-08：测量波形区域双击改为恢复默认坐标范围，不再弹出放大窗口
- 2026-05-08：数据比对分析结果字号调整为 20
- 修复 PyInstaller 规格文件对工作目录的依赖，支持从仓库根直接打包
- 测试配置面板支持编辑移动方案，测试类型可以与测量界面联动
- 历史数据列表改为后台加载，避免界面卡顿

## 许可证

MIT
