# -*- coding: utf-8 -*-
"""
Main application window and panel navigation.
"""

import os

from PyQt5 import uic
from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QDesktopWidget, QLabel, QMainWindow, QPushButton, QStackedWidget, QWidget

from core.logger import get_logger
from ui.theme import get_base_stylesheet

logger = get_logger("MainPanel")


class MainPanel(QMainWindow):
    """Single-window application shell."""

    signal_switch_to = pyqtSignal(str)

    def __init__(self):
        super().__init__()

        ui_file_path = os.path.join(os.path.dirname(__file__), "..", "ui", "main_window.ui")
        uic.loadUi(ui_file_path, self)

        self.setStyleSheet(get_base_stylesheet())

        self._panels = {}
        self._active_panel = None

        self._init_nav_buttons()
        self._setup_statusbar()
        self._load_panels()
        self._center_on_screen()

        self._switch_panel("measure")

    def _init_nav_buttons(self):
        self._nav_button_map = {
            "nav_button_measure": "measure",
            "nav_button_serial": "serial",
            "nav_button_position": "test_config",
            "nav_button_history": "history",
            "nav_button_compare": "compare",
        }

        for btn_name, panel_id in self._nav_button_map.items():
            btn = self.findChild(QWidget, btn_name)
            if btn:
                btn.mousePressEvent = lambda e, pid=panel_id: self._on_nav_clicked(pid)
                logger.debug(f"Connect nav button: {btn_name} -> {panel_id}")
            else:
                logger.warning(f"Nav button not found: {btn_name}")

        self.nav_buttons = {
            panel_id: self.findChild(QWidget, btn_name)
            for btn_name, panel_id in self._nav_button_map.items()
        }

        exit_btn = self.findChild(QPushButton, "btn_exit")
        if exit_btn:
            exit_btn.clicked.connect(self.close)
            logger.debug("Connect exit button")

    def _on_nav_clicked(self, panel_id):
        self._switch_panel(panel_id)

    def _switch_panel(self, panel_id):
        if panel_id not in self._panels:
            logger.warning(f"Panel does not exist: {panel_id}")
            return

        for pid, btn in self.nav_buttons.items():
            if btn:
                btn.setProperty("selected", pid == panel_id)
                btn.style().unpolish(btn)
                btn.style().polish(btn)

        content_stacked = self.findChild(QStackedWidget, "content_stacked")
        if content_stacked:
            content_stacked.setCurrentWidget(self._panels[panel_id])

        self._active_panel = panel_id
        logger.debug(f"Switch panel: {panel_id}")

    def _load_panels(self):
        from windows.compare_panel import ComparePanel
        from windows.history_panel import HistoryPanel
        from windows.measure_panel import MeasurePanel
        from windows.serial_panel import SerialPanel
        from windows.test_config_panel import TestConfigPanel

        content_stacked = self.findChild(QStackedWidget, "content_stacked")

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

        logger.info(f"Loaded {len(panels)} panels")

    def _setup_statusbar(self):
        statusbar = self.statusBar()

        self._footer_serial_indicator = self.findChild(QLabel, "serial_status_indicator")
        self._footer_serial_label = self.findChild(QLabel, "serial_status_label")

        pos_label = QLabel("位置: X=-- Z=--")
        pos_label.setObjectName("status_position_label")
        statusbar.addPermanentWidget(pos_label)
        self._status_position_label = pos_label

    def _center_on_screen(self):
        screen = QDesktopWidget().screenGeometry()
        window_geometry = self.geometry()
        x = (screen.width() - window_geometry.width()) // 2
        y = (screen.height() - window_geometry.height()) // 2
        self.move(x, y)
        logger.debug(f"Move window to ({x}, {y})")

    def update_serial_status(self, connected, port=""):
        if connected:
            self._footer_serial_indicator.setStyleSheet("background-color: #27ae60; border-radius: 5px;")
            self._footer_serial_label.setText(f"已连接 {port}")
        else:
            self._footer_serial_indicator.setStyleSheet("background-color: #e74c3c; border-radius: 5px;")
            self._footer_serial_label.setText("未连接")

    def update_position_from_tuple(self, position_data):
        """Update the footer position label from a `(x, z)` payload."""
        if not position_data or len(position_data) < 2:
            return
        self.update_position(position_data[0], position_data[1])

    def update_position(self, x, z):
        self._status_position_label.setText(f"位置: X={x} Z={z}")

    def get_panel(self, panel_id):
        return self._panels.get(panel_id)

    def get_active_panel(self):
        return self._active_panel
