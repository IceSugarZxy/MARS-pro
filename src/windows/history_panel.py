# -*- coding: utf-8 -*-
"""
历史数据面板 - 从 history_panel.ui 加载
"""

import os
from PyQt5.QtWidgets import (QWidget, QLabel, QPushButton, QTableWidget,
                              QLineEdit, QHeaderView, QHBoxLayout)
from PyQt5.QtCore import Qt
from PyQt5 import uic
from core.logger import get_logger

logger = get_logger('HistoryPanel')


class HistoryPanel(QWidget):
    """历史数据面板 - 从 history_panel.ui 加载"""

    def __init__(self):
        super().__init__()

        # 加载 UI
        ui_file_path = os.path.join(os.path.dirname(__file__), "..", "ui", "history_panel.ui")
        uic.loadUi(ui_file_path, self)

        # 连接按钮事件
        self._connect_buttons()

        # 设置表格
        self._setup_table()

        logger.info("HistoryPanel 初始化完成")

    def _connect_buttons(self):
        """连接按钮事件"""
        self.findChild(QPushButton, "btn_refresh").clicked.connect(self._on_refresh)
        self.findChild(QPushButton, "btn_open").clicked.connect(self._on_open)

    def _setup_table(self):
        """设置表格"""
        table = self.findChild(QTableWidget, "data_table")
        if table:
            header = table.horizontalHeader()
            if header:
                header.setSectionResizeMode(QHeaderView.Stretch)
            table.setSelectionBehavior(QTableWidget.SelectRows)
            table.setEditTriggers(QTableWidget.NoEditTriggers)

    def _on_refresh(self):
        """刷新列表"""
        logger.info("刷新列表")

    def _on_open(self):
        """打开并分析"""
        logger.info("打开并分析")
