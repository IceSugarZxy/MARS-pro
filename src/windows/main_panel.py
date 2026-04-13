# -*- coding: utf-8 -*-
"""
MARS 主面板 - 单窗口 + 侧边栏导航架构
UI 布局完全在 main_window.ui 中定义
"""

import os
from PyQt5.QtWidgets import QMainWindow, QWidget, QLabel, QStackedWidget
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5 import uic
from core.logger import get_logger
from ui.theme import get_base_stylesheet

logger = get_logger('MainPanel')


class MainPanel(QMainWindow):
    """主面板 - 单窗口架构"""

    # 信号：切换到指定面板
    signal_switch_to = pyqtSignal(str)

    def __init__(self):
        super().__init__()

        # 加载 UI（布局完全在 main_window.ui 中定义）
        ui_file_path = os.path.join(os.path.dirname(__file__), "..", "ui", "main_window.ui")
        uic.loadUi(ui_file_path, self)

        # 应用浅色主题样式
        self.setStyleSheet(get_base_stylesheet())

        # 面板存储
        self._panels = {}
        self._active_panel = None

        # 初始化界面
        self._init_nav_buttons()
        self._setup_statusbar()
        self._load_panels()
        self._center_on_screen()

        # 默认显示测量面板
        self._switch_panel("measure")

    def _init_nav_buttons(self):
        """初始化导航按钮（从 UI 文件加载）"""
        # 导航按钮映射：按钮 objectName -> 面板 ID
        self._nav_button_map = {
            "nav_button_measure": "measure",
            "nav_button_serial": "serial",
            "nav_button_position": "test_config",
            "nav_button_history": "history",
            "nav_button_compare": "compare",
        }

        # 连接按钮点击事件
        for btn_name, panel_id in self._nav_button_map.items():
            btn = self.findChild(QWidget, btn_name)
            if btn:
                btn.mousePressEvent = lambda e, pid=panel_id: self._on_nav_clicked(pid)
                logger.debug(f"连接导航按钮: {btn_name} -> {panel_id}")
            else:
                logger.warning(f"未找到导航按钮: {btn_name}")

        # 存储按钮引用
        self.nav_buttons = {
            panel_id: self.findChild(QWidget, btn_name)
            for btn_name, panel_id in self._nav_button_map.items()
        }

    def _on_nav_clicked(self, panel_id):
        """导航按钮点击"""
        self._switch_panel(panel_id)

    def _switch_panel(self, panel_id):
        """切换到指定面板"""
        if panel_id not in self._panels:
            logger.warning(f"面板不存在: {panel_id}")
            return

        # 更新按钮状态
        for pid, btn in self.nav_buttons.items():
            if btn:
                if pid == panel_id:
                    btn.setProperty("selected", True)
                else:
                    btn.setProperty("selected", False)
                btn.style().unpolish(btn)
                btn.style().polish(btn)

        # 切换面板
        content_stacked = self.findChild(QStackedWidget, "content_stacked")
        if content_stacked:
            panel = self._panels[panel_id]
            content_stacked.setCurrentWidget(panel)

        self._active_panel = panel_id
        logger.debug(f"切换到面板: {panel_id}")

    def _load_panels(self):
        """加载所有面板"""
        from windows.measure_panel import MeasurePanel
        from windows.serial_panel import SerialPanel
        from windows.test_config_panel import TestConfigPanel
        from windows.history_panel import HistoryPanel
        from windows.compare_panel import ComparePanel

        # 内容区 StackedWidget
        content_stacked = self.findChild(QStackedWidget, "content_stacked")

        # 创建面板实例并添加到 StackedWidget
        panels = [
            ("measure", MeasurePanel()),
            ("serial", SerialPanel()),
            ("test_config", TestConfigPanel()),
            ("history", HistoryPanel()),
            ("compare", ComparePanel()),
        ]

        for panel_id, panel in panels:
            self._panels[panel_id] = panel
            content_stacked.addWidget(panel)

        logger.info(f"已加载 {len(panels)} 个面板")

    def _setup_statusbar(self):
        """设置状态栏"""
        statusbar = self.statusBar()

        # 串口状态 - 从 UI 文件获取引用
        self._footer_serial_indicator = self.findChild(QLabel, "serial_status_indicator")
        self._footer_serial_label = self.findChild(QLabel, "serial_status_label")

        # 当前位置标签
        pos_label = QLabel("位置: X=-- Z=--")
        pos_label.setObjectName("status_position_label")
        statusbar.addPermanentWidget(pos_label)
        self._status_position_label = pos_label

    def _center_on_screen(self):
        """移动窗口到屏幕中央"""
        from PyQt5.QtWidgets import QDesktopWidget
        screen = QDesktopWidget().screenGeometry()
        window_geometry = self.geometry()
        x = (screen.width() - window_geometry.width()) // 2
        y = (screen.height() - window_geometry.height()) // 2
        self.move(x, y)
        logger.debug(f"窗口移动到 ({x}, {y})")

    def update_serial_status(self, connected, port=""):
        """更新串口状态"""
        if connected:
            self._footer_serial_indicator.setStyleSheet("background-color: #27ae60; border-radius: 5px;")
            self._footer_serial_label.setText(f"已连接 {port}")
        else:
            self._footer_serial_indicator.setStyleSheet("background-color: #e74c3c; border-radius: 5px;")
            self._footer_serial_label.setText("未连接")

    def update_position(self, x, z):
        """更新位置显示"""
        self._status_position_label.setText(f"位置: X={x} Z={z}")

    def get_panel(self, panel_id):
        """获取指定面板"""
        return self._panels.get(panel_id)

    def get_active_panel(self):
        """获取当前活动面板ID"""
        return self._active_panel
