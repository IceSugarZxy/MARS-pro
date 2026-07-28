# -*- coding: utf-8 -*-
"""
偏置校准对话框
显示校准进度和结果
"""
from PyQt5.QtWidgets import QDialog, QMessageBox
from PyQt5.QtCore import Qt, QPoint, QTimer
from PyQt5 import uic
import os
from core.offset_calibration_config import OFFSET_PROGRESS_SECONDS


class OffsetCalibrationDialog(QDialog):
    """偏置校准对话框"""

    CALIBRATION_DURATION = OFFSET_PROGRESS_SECONDS

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("偏置校准")
        self.setFixedSize(400, 200)

        ui_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ui", "offset_calibration_dialog.ui")
        uic.loadUi(ui_path, self)

        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setModal(True)

        self.dragging = False
        self.drag_position = QPoint()

        # 进度更新定时器
        self._progress_timer = QTimer()
        self._progress_timer.timeout.connect(self._update_progress_by_time)
        self._progress_start_time = None

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

    def start_progress(self, duration=OFFSET_PROGRESS_SECONDS):
        """开始偏置校准"""
        self.CALIBRATION_DURATION = duration
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        self.label_status.setText("偏置校准进行中...")

    def _update_progress_by_time(self):
        """基于时间估算进度"""
        pass

    def stop_progress(self):
        """停止进度"""
        pass

    def set_progress(self, value, text=""):
        """设置进度条和状态文本"""
        if value >= 0:
            self.progress_bar.setMaximum(100)
            self.progress_bar.setValue(value)
        if text:
            self.label_status.setText(text)

    def show_result(self, success, offset_value=None):
        """显示校准结果"""
        if success:
            self.label_title.setText("偏置校准完成")
            self.label_title.setStyleSheet("color: #27ae60; font-size: 18px; font-weight: bold;")
            self.progress_bar.setMaximum(100)
            self.progress_bar.setValue(100)
            if offset_value is not None:
                self.label_status.setText(f"偏置值: {offset_value:.1f} ADC")
            else:
                self.label_status.setText("校准成功")
        else:
            self.label_title.setText("偏置校准失败")
            self.label_title.setStyleSheet("color: #e74c3c; font-size: 18px; font-weight: bold;")
            self.progress_bar.setMaximum(100)
            self.progress_bar.setValue(0)
            self.label_status.setText("未能获取有效偏置数据")

        self.btn_cancel.setText("确定")
