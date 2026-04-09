# -*- coding: utf-8 -*-
"""
旋转体表磁测量分析系统 - 主页面
使用.ui文件加载界面布局，深色工业风格
"""

import os
import sys
import subprocess
from PyQt5.QtWidgets import QMainWindow, QWidget
from PyQt5.QtCore import Qt, QEvent
from PyQt5 import uic
from ui.window_operations import WindowOperations
from ui.theme import get_base_stylesheet, COLOR_PRIMARY, COLOR_SUCCESS, COLOR_DANGER, COLOR_BG_PANEL_LIGHT, COLOR_BG_PANEL
from windows.serial_window import SerialWindow
from windows.position_window import PositionWindow
from windows.measure_window import MeasureWindow
from windows.history_window import HistoryWindow
from windows.compare_window import CompareWindow
from core import ThreadManager
from core.logger import get_logger

logger = get_logger('HomeWindow')


class HomeWindow(QMainWindow):
    """主页面窗口 - 深色工业风格"""

    def __init__(self):
        super().__init__()
        self.thread_manager = None

        # 窗口引用
        self.serial_window = SerialWindow()
        self.position_window = PositionWindow()
        self.measure_window = MeasureWindow(self.position_window, self)
        self.history_window = HistoryWindow(self.measure_window)

        enable_concentricity = self.measure_window.radioButton_Concentricity.isChecked() if hasattr(self.measure_window, 'radioButton_Concentricity') and self.measure_window.radioButton_Concentricity else True
        self.compare_window = CompareWindow(enable_concentricity)

        # 从ui文件加载界面
        ui_file_path = os.path.join(os.path.dirname(__file__), "..", "ui", "home_window.ui")
        uic.loadUi(ui_file_path, self)

        # 应用深色主题样式
        self.setStyleSheet(get_base_stylesheet())

        # 初始化窗口操作功能
        self.window_operations = WindowOperations(self)

        # 连接按钮事件
        self._connect_buttons()

        # 安装事件过滤器
        self.installEventFilter(self)

    def _connect_buttons(self):
        """连接导航栏按钮事件"""
        # 导航按钮
        self._setup_nav_button("test_button", self._test_button_clicked)
        self._setup_nav_button("serial_button", self._serial_button_clicked)
        self._setup_nav_button("position_button", self._position_button_clicked)
        self._setup_nav_button("history_button", self._history_button_clicked)
        self._setup_nav_button("compare_button", self._compare_button_clicked)
        self._setup_nav_button("exit_button", self._exit_button_clicked)

        # 内容区卡片（也可用作快捷入口）
        self._setup_card_button("card_measure", self._test_button_clicked)
        self._setup_card_button("card_history", self._history_button_clicked)
        self._setup_card_button("card_compare", self._compare_button_clicked)
        self._setup_card_button("card_position", self._position_button_clicked)

    def _setup_nav_button(self, name: str, handler):
        """设置导航按钮"""
        btn = self.findChild(QWidget, name)
        if btn:
            btn.mousePressEvent = handler

    def _setup_card_button(self, name: str, handler):
        """设置卡片按钮"""
        card = self.findChild(QWidget, name)
        if card:
            card.mousePressEvent = handler
            card.setCursor(Qt.PointingHandCursor)

    def _serial_button_clicked(self, event):
        """串口设置按钮点击"""
        if event.button() == Qt.LeftButton:
            if self.serial_window:
                if not self.serial_window.isVisible():
                    self.serial_window.show()
                else:
                    self.serial_window.raise_()
                    self.serial_window.activateWindow()

    def _position_button_clicked(self, event):
        """位置控制按钮点击"""
        if event.button() == Qt.LeftButton:
            if self.position_window:
                self.position_window.show_window()

    def _test_button_clicked(self, event):
        """测量界面按钮点击"""
        if event.button() == Qt.LeftButton:
            if self.measure_window:
                self.measure_window.show_window()

    def _exit_button_clicked(self, event):
        """退出按钮点击"""
        if event.button() == Qt.LeftButton:
            self.window_operations.close_window()

    def _history_button_clicked(self, event):
        """历史数据按钮点击"""
        if event.button() == Qt.LeftButton:
            if self.history_window:
                self.history_window.show_window()

    def _compare_button_clicked(self, event):
        """数据比对按钮点击"""
        if event.button() == Qt.LeftButton:
            if self.compare_window:
                self.compare_window.show_window()

    def update_serial_status(self, connected: bool, port: str = ""):
        """更新串口连接状态显示"""
        indicator = self.findChild(QWidget, "serial_status_indicator")
        label = self.findChild(QWidget, "serial_status_label")
        if indicator and label:
            if connected:
                indicator.setStyleSheet("background-color: #27ae60; border-radius: 5px; border: none;")
                label.setText(f"已连接 {port}")
                label.setStyleSheet("color: #27ae60; border: none; background: transparent;")
            else:
                indicator.setStyleSheet("background-color: #e74c3c; border-radius: 5px; border: none;")
                label.setText("未连接")
                label.setStyleSheet("color: #7f8c8d; border: none; background: transparent;")

    def mouseDoubleClickEvent(self, event):
        """双击标题区最大化/还原"""
        if event.button() == Qt.LeftButton:
            if event.pos().y() <= 30:
                self.window_operations.maximize_window()
        super().mouseDoubleClickEvent(event)

    def eventFilter(self, obj, event):
        """事件过滤器"""
        if obj is self and event.type() == QEvent.Close:
            self._cleanup_all_resources()
            return False
        return super().eventFilter(obj, event)

    def _cleanup_all_resources(self):
        """清理所有资源"""
        logger.info("开始清理所有资源...")

        if self.thread_manager:
            logger.info("清理线程管理器...")
            self.thread_manager.cleanup()
            self.thread_manager = None

        if self.serial_window:
            if self.serial_window.isVisible():
                self.serial_window.close()
            self.serial_window = None

        if self.position_window:
            if self.position_window.isVisible():
                self.position_window.close()
            self.position_window = None

        if self.measure_window:
            if self.measure_window.isVisible():
                self.measure_window.close()
            self.measure_window = None

        if self.history_window:
            if self.history_window.isVisible():
                self.history_window.close()
            self.history_window = None

        if self.compare_window:
            if self.compare_window.isVisible():
                self.compare_window.close()
            self.compare_window = None

        logger.info("资源清理完成")
