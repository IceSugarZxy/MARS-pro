# -*- coding: utf-8 -*-
"""
MARS 窗口模块
"""
# 单窗口架构主面板
from .main_panel import MainPanel

# 面板类（单窗口架构使用）
from .measure_panel import MeasurePanel
from .serial_panel import SerialPanel
from .position_panel import PositionPanel
from .history_panel import HistoryPanel
from .compare_panel import ComparePanel

# 传统窗口类（保留以支持旧架构）
from .home_window import HomeWindow
from .serial_window import SerialWindow
from .position_window import PositionWindow
from .measure_window import MeasureWindow
from .plot_window import PlotWindow
from .compare_window import CompareWindow
from .history_window import HistoryWindow
from .wave_analysis import WaveAnalysis

__all__ = [
    # 单窗口架构
    'MainPanel',
    'MeasurePanel',
    'SerialPanel',
    'PositionPanel',
    'HistoryPanel',
    'ComparePanel',
    # 传统窗口（过渡期保留）
    'HomeWindow',
    'SerialWindow',
    'PositionWindow',
    'MeasureWindow',
    'PlotWindow',
    'CompareWindow',
    'HistoryWindow',
    'WaveAnalysis',
]
