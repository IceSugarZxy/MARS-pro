# -*- coding: utf-8 -*-
"""
偏置校准对话框
显示校准进度和结果
"""
import os
import time

from PyQt5.QtWidgets import QDialog, QMessageBox
from PyQt5.QtCore import Qt, QPoint, QTimer, pyqtSignal
from PyQt5 import uic

from core.offset_calibration_config import OFFSET_PROGRESS_SECONDS


class OffsetCalibrationDialog(QDialog):
    """偏置校准对话框"""

    cancel_requested = pyqtSignal()
    CALIBRATION_DURATION = OFFSET_PROGRESS_SECONDS
    # 进度刷新间隔（ms）
    PROGRESS_INTERVAL_MS = 50

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("偏置校准")
        self.setFixedSize(400, 200)
        self._finished = False

        ui_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ui", "offset_calibration_dialog.ui")
        uic.loadUi(ui_path, self)

        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setModal(True)

        self.dragging = False
        self.drag_position = QPoint()

        # 进度更新定时器：偏置采集是固定时长窗口，进度按走时推进。
        # 不能按"已收点数/预期点数"算——H~ 实际速率随 ADCRATE 变化（约 8~31Hz），
        # 用标称 600Hz 估算会让进度条 5 秒只走到个位数百分比。
        self._progress_timer = QTimer(self)
        self._progress_timer.setInterval(self.PROGRESS_INTERVAL_MS)
        self._progress_timer.timeout.connect(self._update_progress_by_time)
        self._progress_start_time = None
        self._points_collected = 0

        self.btn_cancel.clicked.connect(self._on_cancel_clicked)

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
        """开始偏置校准：按采集窗口时长推进进度条。"""
        self.CALIBRATION_DURATION = max(0.1, float(duration))
        self._finished = False
        self._points_collected = 0
        self._progress_start_time = time.monotonic()
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        self.label_title.setText("偏置校准")
        self.label_title.setStyleSheet("font-size: 18px; font-weight: bold;")
        self.label_status.setText(f"正在采集 {self.CALIBRATION_DURATION:.0f}s 数据，请等待...")
        self.btn_cancel.setText("取消")
        self._progress_timer.start()

    def _update_progress_by_time(self):
        """基于采集窗口走时推进进度（上限 99%，完成时由 show_result 置 100）。"""
        if self._progress_start_time is None:
            return
        elapsed = time.monotonic() - self._progress_start_time
        ratio = min(1.0, elapsed / self.CALIBRATION_DURATION)
        value = min(99, int(ratio * 100))
        if value > self.progress_bar.value():
            self.progress_bar.setValue(value)

        remain = max(0.0, self.CALIBRATION_DURATION - elapsed)
        if self._points_collected > 0:
            self.label_status.setText(
                f"采集中... 剩余 {remain:.1f}s（已采集 {self._points_collected} 点）"
            )
        else:
            self.label_status.setText(f"采集中... 剩余 {remain:.1f}s")

    def stop_progress(self):
        """停止进度定时器。"""
        self._progress_timer.stop()
        self._progress_start_time = None

    def set_points_collected(self, count: int) -> None:
        """更新已采集点数（仅供状态文本显示，不参与进度条计算）。"""
        self._points_collected = max(0, int(count))

    def set_progress(self, value, text=""):
        """设置进度条和状态文本"""
        if value >= 0:
            self.progress_bar.setMaximum(100)
            self.progress_bar.setValue(value)
        if text:
            self.label_status.setText(text)

    def show_result(self, success, offset_value=None):
        """显示校准结果"""
        self.stop_progress()
        self._finished = True
        if success:
            self.label_title.setText("偏置校准完成")
            self.label_title.setStyleSheet("color: #27ae60; font-size: 18px; font-weight: bold;")
            self.progress_bar.setMaximum(100)
            self.progress_bar.setValue(100)
            if offset_value is not None:
                self.label_status.setText(f"偏置值: {offset_value:.4f} mT")
            else:
                self.label_status.setText("校准成功")
        else:
            self.label_title.setText("偏置校准失败")
            self.label_title.setStyleSheet("color: #e74c3c; font-size: 18px; font-weight: bold;")
            self.progress_bar.setMaximum(100)
            self.progress_bar.setValue(0)
            self.label_status.setText("未能获取有效偏置数据")

        self.btn_cancel.setText("确定")

    def _on_cancel_clicked(self):
        """校准中点击取消：通知调用方停止采集；完成态点击：关闭窗口。"""
        if self._finished:
            self.accept()
            return
        self.cancel_requested.emit()

    def closeEvent(self, event):
        self.stop_progress()
        super().closeEvent(event)
