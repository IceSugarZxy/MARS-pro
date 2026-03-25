# 旋转体表磁测量分析系统

基于 PyQt5 的旋转体表磁测量分析系统，支持串口通信、数据采集、波形分析和图形界面。

**2026-03-25**: 新增自动右压功能、优化日志编码与状态显示、修复结果显示初始化

**2026-03-21**: 优化自检流程与位置数据处理 - check_self_detect位置数据识别增强、自检前清空队列、位置查询1.5s等待、无效位置重试机制、串口端口正确释放

## 功能特性

- 串口通信（自动连接、发送接收）
- 数据处理（低通滤波、偏置校准、零点校准）
- 实时波形显示
- 多窗口管理（主界面、测量、位置、串口等）
- 数据导出（CSV格式）
- 波形分析（峰值检测、过零点分析、面积计算、THD失真率）
- 历史数据查看与数据比对
- 旋转测量与垂直测量模式

## 环境要求

- Python 3.8+
- PyQt5
- numpy
- scipy
- pyqtgraph

## 安装

```bash
pip install -r requirements.txt
```

## 运行

```bash
python src/main.py
```

## 项目结构

```
MARS/
├── src/
│   ├── main.py              # 主程序入口
│   ├── core/                # 核心模块
│   │   ├── __init__.py
│   │   ├── logger.py        # 日志模块
│   │   ├── config_manager.py # 配置管理
│   │   ├── serial_manager.py # 串口管理
│   │   ├── serial_command.py # 串口命令
│   │   ├── data_process.py  # 数据处理
│   │   └── thread_manager.py # 线程管理
│   ├── windows/             # 窗口模块
│   │   ├── __init__.py
│   │   ├── home_window.py  # 主窗口
│   │   ├── serial_window.py # 串口设置
│   │   ├── position_window.py # 位置控制
│   │   ├── measure_window.py # 测量界面
│   │   ├── measure_type_dialog.py # 测量类型选择
│   │   ├── plot_window.py  # 绘图窗口
│   │   ├── compare_window.py # 数据比对
│   │   ├── history_window.py # 历史记录
│   │   └── wave_analysis.py # 波形分析
│   └── ui/                 # UI资源文件
│       ├── *.ui            # Qt Designer界面文件
│       └── window_operations.py # 窗口操作工具
├── logs/                   # 日志文件
├── data/                   # 数据存储
│   ├── raw_data/          # 原始数据
│   └── plot_data/         # 绘图数据
└── requirements.txt        # 依赖列表
```

## 核心模块说明

### core - 核心功能模块

| 模块 | 功能 |
|------|------|
| logger | 统一日志管理 |
| config_manager | 配置文件读写 |
| serial_manager | 串口连接和数据收发 |
| serial_command | 串口命令封装 |
| data_process | 数据处理算法 |
| thread_manager | 多线程协调 |

### windows - 窗口模块

| 窗口 | 功能 |
|------|------|
| home_window | 主界面，窗口导航 |
| serial_window | 串口参数设置 |
| position_window | 位置控制 |
| measure_window | 测量界面，方向控制 |
| measure_type_dialog | 测量类型选择（旋转/垂直） |
| plot_window | 实时绘图 |
| compare_window | 数据比对 |
| history_window | 历史数据查看 |
| wave_analysis | 波形分析算法 |

## 波形分析指标

- **N/S极值**: 最大值、最小值、平均值、误差
- **极间隔**: N极间隔、S极间隔的统计值
- **面积**: N极面积、S极面积、NS总面积
- **THD失真率**: 总谐波失真率
- **极对数**: FFT基波频率分析

## 串口命令

| 命令 | 功能 |
|------|------|
| B~ | 爪盘旋转（1.5圈） |
| S~ | 停止旋转 |
| X{pos}~ | X轴移动到位置 |
| Z{pos}~ | Z轴移动到位置 |
| N{distance}~ | Z轴相对移动 |
| P~ | Z轴自检（自动下压） |
| Y~ | X轴自检（左贴靠） |
| Y-~ | X轴反向自检（右贴靠） |
| I~ | 滑台复位（回原点） |
| K{sec}~ | 定时采集（偏置校准） |
| ?XZ~ | 查询双轴位置 |

## 配置文件

配置文件 `configuration.txt` 格式：
```
saved_x:0
saved_z:0
left:0
offset:0
COM:COM12
baudrate:921600
```

## 技术栈

- **GUI框架**: PyQt5
- **数据处理**: NumPy, SciPy
- **串口通信**: PyQt5 SerialPort
- **波形绘图**: pyqtgraph

## 许可证

MIT
