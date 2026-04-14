# -*- coding: utf-8 -*-
"""
测量类型选择弹窗
在开始测量前让用户选择测量类型：旋转测量或垂直测量
"""
from PyQt5.QtWidgets import QDialog, QPushButton
from PyQt5.QtCore import Qt, QPoint
from PyQt5 import uic
import os


class MeasureTypeDialog(QDialog):
    """测量类型选择弹窗"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.measure_type = None
        self.vertical_distance = None
        self.dragging = False
        self.drag_position = QPoint()

        ui_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ui", "measure_type_dialog.ui")
        uic.loadUi(ui_path, self)

        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setModal(True)

        self.pushButton_rotation.clicked.connect(self._on_rotation_clicked)
        self.pushButton_vertical.clicked.connect(self._on_vertical_clicked)
        self.findChild(QPushButton, 'btn_close').clicked.connect(self.reject)

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

    def _on_rotation_clicked(self):
        self.measure_type = "rotation"
        self.vertical_distance = None
        self.accept()

    def _on_vertical_clicked(self):
        distance_text = self.lineEdit_vertical_distance.text().strip()
        if not distance_text:
            self.lineEdit_vertical_distance.setPlaceholderText("请输入垂直测量距离")
            return
        try:
            self.vertical_distance = int(float(distance_text) * 360 / 1.8 * 8)
        except ValueError:
            self.lineEdit_vertical_distance.setPlaceholderText("请输入有效距离值")
            return
        self.measure_type = "vertical"
        self.accept()

    def get_measure_type(self):
        return self.measure_type

    def get_vertical_distance(self):
        return self.vertical_distance
