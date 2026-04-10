# -*- coding: utf-8 -*-
"""
位置控制面板
"""
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QGroupBox, QGridLayout, QPushButton, QLineEdit
from PyQt5.QtCore import Qt
from core.logger import get_logger

logger = get_logger('PositionPanel')


class PositionPanel(QWidget):
    """位置控制面板"""

    def __init__(self):
        super().__init__()
        self._setup_ui()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(16)

        title = QLabel("位置控制")
        title.setObjectName("panel_title")
        main_layout.addWidget(title)

        # 当前位置显示
        pos_group = QGroupBox("当前位置")
        pos_layout = QGridLayout(pos_group)
        pos_layout.addWidget(QLabel("X轴:"), 0, 0)
        self.x_display = QLabel("--")
        self.x_display.setObjectName("position_value")
        pos_layout.addWidget(self.x_display, 0, 1)
        pos_layout.addWidget(QLabel("Z轴:"), 0, 2)
        self.z_display = QLabel("--")
        self.z_display.setObjectName("position_value")
        pos_layout.addWidget(self.z_display, 0, 3)
        main_layout.addWidget(pos_group)

        # 快捷操作
        action_group = QGroupBox("快捷操作")
        action_layout = QGridLayout(action_group)

        action_layout.addWidget(self._make_btn("零位校准"), 0, 0)
        action_layout.addWidget(self._make_btn("偏置校准"), 0, 1)
        action_layout.addWidget(self._make_btn("下压贴靠(Z轴)"), 1, 0)
        action_layout.addWidget(self._make_btn("左贴靠(X轴)"), 1, 1)
        action_layout.addWidget(self._make_btn("右贴靠(X轴)"), 1, 2)
        action_layout.addWidget(self._make_btn("测试位置"), 2, 0)
        action_layout.addWidget(self._make_btn("挂起位置"), 2, 1)
        action_layout.addWidget(self._make_btn("滑台复位"), 2, 2)

        main_layout.addWidget(action_group)

        # 位置设置
        set_group = QGroupBox("位置设置")
        set_layout = QGridLayout(set_group)
        set_layout.addWidget(QLabel("测试位置 X:"), 0, 0)
        set_layout.addWidget(QLineEdit(), 0, 1)
        set_layout.addWidget(QLabel("Z:"), 0, 2)
        set_layout.addWidget(QLineEdit(), 0, 3)
        set_layout.addWidget(QLabel("挂起位置 X:"), 1, 0)
        set_layout.addWidget(QLineEdit(), 1, 1)
        set_layout.addWidget(QLabel("Z:"), 1, 2)
        set_layout.addWidget(QLineEdit(), 1, 3)
        main_layout.addWidget(set_group)

        # 手动控制
        manual_group = QGroupBox("手动控制")
        manual_layout = QGridLayout(manual_group)

        manual_layout.addWidget(self._make_btn("↑"), 0, 1)
        manual_layout.addWidget(self._make_btn("←"), 1, 0)
        manual_layout.addWidget(self._make_btn("→"), 1, 2)
        manual_layout.addWidget(self._make_btn("↓"), 2, 1)

        manual_layout.addWidget(QLabel("距离(mm):"), 3, 0)
        dist_input = QLineEdit()
        dist_input.setText("1")
        manual_layout.addWidget(dist_input, 3, 1, 1, 2)

        main_layout.addWidget(manual_group)

        main_layout.addStretch()

        logger.info("PositionPanel 初始化完成")

    def _make_btn(self, text):
        btn = QPushButton(text)
        btn.setMinimumHeight(36)
        return btn

    def update_position(self, x, z):
        self.x_display.setText(str(x))
        self.z_display.setText(str(z))
