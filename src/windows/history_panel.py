# -*- coding: utf-8 -*-
"""
历史数据面板
"""
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QGroupBox, QGridLayout, QPushButton, QTableWidget, QLineEdit, QHeaderView, QHBoxLayout
from PyQt5.QtCore import Qt
from core.logger import get_logger

logger = get_logger('HistoryPanel')


class HistoryPanel(QWidget):
    """历史数据面板"""

    def __init__(self):
        super().__init__()
        self._setup_ui()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(16)

        title = QLabel("历史数据")
        title.setObjectName("panel_title")
        main_layout.addWidget(title)

        # 搜索区
        search_group = QGroupBox("搜索条件")
        search_layout = QGridLayout(search_group)
        search_layout.addWidget(QLabel("样品名称:"), 0, 0)
        search_layout.addWidget(QLineEdit(), 0, 1)
        search_layout.addWidget(QLabel("测试人员:"), 0, 2)
        search_layout.addWidget(QLineEdit(), 0, 3)
        search_layout.addWidget(QLabel("极数:"), 1, 0)
        search_layout.addWidget(QLineEdit(), 1, 1)
        search_layout.addWidget(QLabel("气隙:"), 1, 2)
        search_layout.addWidget(QLineEdit(), 1, 3)
        main_layout.addWidget(search_group)

        # 数据列表
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["样品名称", "测试时间", "极数", "气隙", "备注", "文件路径"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        main_layout.addWidget(self.table, 1)

        # 按钮行
        btn_row = QHBoxLayout()
        btn_row.addWidget(QPushButton("刷新列表"))
        btn_row.addWidget(QPushButton("打开并分析"))
        btn_row.addStretch()
        main_layout.addLayout(btn_row)

        logger.info("HistoryPanel 初始化完成")
