# -*- coding: utf-8 -*-
"""
MARS 窗口模块 - 单窗口架构
"""
from .main_panel import MainPanel
from .measure_panel import MeasurePanel
from .serial_panel import SerialPanel
from .position_panel import PositionPanel
from .history_panel import HistoryPanel
from .compare_panel import ComparePanel
from .plot_window import PlotWindow
from .wave_analysis import WaveAnalysis

__all__ = [
    'MainPanel',
    'MeasurePanel',
    'SerialPanel',
    'PositionPanel',
    'HistoryPanel',
    'ComparePanel',
    'PlotWindow',
    'WaveAnalysis',
]
