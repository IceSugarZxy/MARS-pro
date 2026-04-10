# -*- coding: utf-8 -*-
"""
数据比对面板 - 从 compare_panel.ui 加载
"""

import os
from PyQt5.QtWidgets import (QWidget, QLabel, QPushButton, QLineEdit,
                              QTextEdit, QSplitter, QGroupBox, QGridLayout,
                              QFileDialog)
from PyQt5.QtCore import Qt
from PyQt5 import uic
from core.logger import get_logger

logger = get_logger('ComparePanel')


class ComparePanel(QWidget):
    """数据比对面板 - 从 compare_panel.ui 加载"""

    def __init__(self):
        super().__init__()

        # 加载 UI
        ui_file_path = os.path.join(os.path.dirname(__file__), "..", "ui", "compare_panel.ui")
        uic.loadUi(ui_file_path, self)

        # 连接按钮事件
        self._connect_buttons()

        logger.info("ComparePanel 初始化完成")

    def _connect_buttons(self):
        """连接按钮事件"""
        self.findChild(QPushButton, "file1_btn").clicked.connect(lambda: self._on_browse(1))
        self.findChild(QPushButton, "file2_btn").clicked.connect(lambda: self._on_browse(2))
        self.findChild(QPushButton, "compare_btn").clicked.connect(self._on_compare)

    def _on_browse(self, file_num):
        """浏览文件"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            f"选择文件{file_num}",
            "",
            "CSV Files (*.csv);;All Files (*)"
        )
        if file_path:
            if file_num == 1:
                self.findChild(QLineEdit, "file1_edit").setText(file_path)
            else:
                self.findChild(QLineEdit, "file2_edit").setText(file_path)
        logger.info(f"选择文件{file_num}: {file_path}")

    def _on_compare(self):
        """开始比对"""
        file1 = self.findChild(QLineEdit, "file1_edit").text().strip()
        file2 = self.findChild(QLineEdit, "file2_edit").text().strip()

        if not file1 or not file2:
            logger.warning("请选择两个文件进行比对")
            return

        logger.info(f"开始比对: {file1} vs {file2}")
