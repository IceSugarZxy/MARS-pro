# -*- coding: utf-8 -*-
"""
位置控制面板 - 从 position_panel.ui 加载
"""

import os
from PyQt5.QtWidgets import (QWidget, QLabel, QPushButton, QLineEdit,
                              QGroupBox, QGridLayout)
from PyQt5.QtCore import Qt
from PyQt5 import uic
from core.logger import get_logger

logger = get_logger('PositionPanel')


class PositionPanel(QWidget):
    """位置控制面板 - 从 position_panel.ui 加载"""

    def __init__(self):
        super().__init__()

        # 加载 UI
        ui_file_path = os.path.join(os.path.dirname(__file__), "..", "ui", "position_panel.ui")
        uic.loadUi(ui_file_path, self)

        # 连接按钮事件
        self._connect_buttons()

        logger.info("PositionPanel 初始化完成")

    def _connect_buttons(self):
        """连接按钮事件"""
        # 快捷操作
        self.findChild(QPushButton, "btn_zeroing").clicked.connect(self._on_zeroing)
        self.findChild(QPushButton, "btn_offset").clicked.connect(self._on_offset)
        self.findChild(QPushButton, "btn_press_z").clicked.connect(self._on_press_z)
        self.findChild(QPushButton, "btn_left_x").clicked.connect(self._on_left_x)
        self.findChild(QPushButton, "btn_right_x").clicked.connect(self._on_right_x)
        self.findChild(QPushButton, "btn_test_pos").clicked.connect(self._on_test_pos)
        self.findChild(QPushButton, "btn_suspend").clicked.connect(self._on_suspend)
        self.findChild(QPushButton, "btn_reset").clicked.connect(self._on_reset)

        # 手动控制
        self.findChild(QPushButton, "btn_up").clicked.connect(self._on_up)
        self.findChild(QPushButton, "btn_down").clicked.connect(self._on_down)
        self.findChild(QPushButton, "btn_left").clicked.connect(self._on_left)
        self.findChild(QPushButton, "btn_right").clicked.connect(self._on_right)

    def _get_distance(self):
        """获取距离值"""
        dist_edit = self.findChild(QLineEdit, "dist_edit")
        if not dist_edit:
            return 1.0
        try:
            return float(dist_edit.text().strip() or "1")
        except ValueError:
            return 1.0

    def _on_zeroing(self):
        logger.info("零位校准")

    def _on_offset(self):
        logger.info("偏置校准")

    def _on_press_z(self):
        logger.info("下压贴靠(Z轴)")

    def _on_left_x(self):
        logger.info("左贴靠(X轴)")

    def _on_right_x(self):
        logger.info("右贴靠(X轴)")

    def _on_test_pos(self):
        logger.info("测试位置")

    def _on_suspend(self):
        logger.info("挂起位置")

    def _on_reset(self):
        logger.info("滑台复位")

    def _on_up(self):
        logger.info("上")

    def _on_down(self):
        logger.info("下")

    def _on_left(self):
        logger.info("左")

    def _on_right(self):
        logger.info("右")

    def update_position(self, x, z):
        """更新位置显示"""
        x_display = self.findChild(QLabel, "x_display")
        z_display = self.findChild(QLabel, "z_display")
        if x_display:
            x_display.setText(str(x))
        if z_display:
            z_display.setText(str(z))
