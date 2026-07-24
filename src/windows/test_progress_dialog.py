# -*- coding: utf-8 -*-
"""
测试进度对话框
显示测量进度
"""
from PyQt5.QtWidgets import QDialog
from PyQt5.QtCore import Qt, QPoint, QTimer
from PyQt5 import uic
import os


class TestProgressDialog(QDialog):
    """测试进度对话框"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("旋转测量")
        self.setFixedSize(400, 200)

        ui_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ui", "test_progress_dialog.ui")
        uic.loadUi(ui_path, self)

        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setModal(True)

        self.dragging = False
        self.drag_position = QPoint()

        self.btn_cancel.clicked.connect(self.reject)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and event.pos().y() <= 35:
            self.dragging = True
            self.drag_position = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton and self.dragging:
            self.move(event.globalPos() - self.drag_position)
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.dragging = False

    def set_progress(self, value, text=""):
        """设置状态文本"""
        if text:
            self.label_status.setText(text)

    def show_result(self, success, message=None):
        """显示测试结果"""
        if success:
            self.label_title.setText("测量完成")
            self.label_title.setStyleSheet("color: #27ae60; font-size: 18px; font-weight: bold;")
            self.label_status.setText(message or "数据采集完成")
        else:
            self.label_title.setText("测量失败")
            self.label_title.setStyleSheet("color: #e74c3c; font-size: 18px; font-weight: bold;")
            self.label_status.setText(message or "未能获取有效数据")

        self.btn_cancel.setText("确定")

    def set_title(self, text):
        """设置标题"""
        self.label_title.setText(text)

    def set_status(self, text):
        """设置状态文本"""
        self.label_status.setText(text)
