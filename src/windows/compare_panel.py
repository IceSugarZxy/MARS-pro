# -*- coding: utf-8 -*-
"""
数据比对面板
"""
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QGroupBox, QGridLayout, QPushButton, QLineEdit, QTextEdit, QSplitter, QFileDialog
from PyQt5.QtCore import Qt
from core.logger import get_logger

logger = get_logger('ComparePanel')


class ComparePanel(QWidget):
    """数据比对面板"""

    def __init__(self):
        super().__init__()
        self._setup_ui()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(16)

        title = QLabel("数据比对")
        title.setObjectName("panel_title")
        main_layout.addWidget(title)

        # 文件选择区
        file_group = QGroupBox("选择文件")
        file_layout = QGridLayout(file_group)

        file_layout.addWidget(QLabel("文件1 (红色):"), 0, 0)
        self.file1_edit = QLineEdit()
        self.file1_btn = QPushButton("浏览...")
        file_layout.addWidget(self.file1_edit, 0, 1)
        file_layout.addWidget(self.file1_btn, 0, 2)

        file_layout.addWidget(QLabel("文件2 (蓝色):"), 1, 0)
        self.file2_edit = QLineEdit()
        self.file2_btn = QPushButton("浏览...")
        file_layout.addWidget(self.file2_edit, 1, 1)
        file_layout.addWidget(self.file2_btn, 1, 2)

        compare_btn = QPushButton("开始比对")
        file_layout.addWidget(compare_btn, 2, 0, 1, 3)

        main_layout.addWidget(file_group)

        # 波形显示区
        plot_placeholder = QLabel("波形对比显示区\n(两条曲线叠加显示)")
        plot_placeholder.setObjectName("plot_placeholder")
        plot_placeholder.setAlignment(Qt.AlignCenter)
        plot_placeholder.setMinimumHeight(250)
        main_layout.addWidget(plot_placeholder, 1)

        # 结果显示
        splitter = QSplitter(Qt.Horizontal)
        self.result1_text = QTextEdit()
        self.result1_text.setReadOnly(True)
        self.result1_text.setPlaceholderText("文件1 分析结果")
        self.result2_text = QTextEdit()
        self.result2_text.setReadOnly(True)
        self.result2_text.setPlaceholderText("文件2 分析结果")
        splitter.addWidget(self.result1_text)
        splitter.addWidget(self.result2_text)
        main_layout.addWidget(splitter, 1)

        logger.info("ComparePanel 初始化完成")
