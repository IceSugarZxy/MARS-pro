# -*- coding: utf-8 -*-
"""
MARS 窗口模块
"""
from .home_window import HomeWindow
from windows.serial_window import SerialWindow
from windows.position_window import PositionWindow
from windows.measure_window import MeasureWindow
from windows.plot_window import PlotWindow
from windows.compare_window import CompareWindow
from windows.history_window import HistoryWindow
from windows.wave_analysis import WaveAnalysis

__all__ = [
    'HomeWindow',
    'SerialWindow', 
    'PositionWindow',
    'MeasureWindow',
    'PlotWindow',
    'CompareWindow',
    'HistoryWindow',
    'WaveAnalysis',
]
