# -*- coding: utf-8 -*-
"""
全量程偏置校准对话框

风格与“偏置校准 / 测量进度”对话框一致（无边框、可拖拽、主题进度条），
增加 8 档结果表格，每档偏置校准完成后实时写入。
"""

from PyQt5.QtCore import Qt, QPoint, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QAbstractItemView,
)

from core.config_manager import PGA_OPTION_TEXTS


class FullOffsetCalibrationDialog(QDialog):
    """全量程偏置校准对话框：表格 + 进度条 + 状态文本。"""

    cancel_requested = pyqtSignal()

    COLOR_RUNNING = "#3498db"
    COLOR_OK = "#27ae60"
    COLOR_FAIL = "#e74c3c"
    COLOR_WAIT = "#7f8c8d"

    def __init__(self, parent=None, total=8):
        super().__init__(parent)
        self.setWindowTitle("全量程偏置校准")
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setModal(True)
        self.setFixedSize(660, 520)
        self.setStyleSheet("QDialog { border: 1px solid #555555; }")

        self._total = int(total)
        self._finished = False
        self.dragging = False
        self.drag_position = QPoint()

        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(10)

        self.label_title = QLabel("全量程偏置校准")
        self.label_title.setAlignment(Qt.AlignCenter)
        self.label_title.setStyleSheet(
            "font-size: 18px; font-weight: bold; color: #000000;"
        )
        layout.addWidget(self.label_title)

        self.progress_bar = QProgressBar(self)
        self.progress_bar.setMaximum(self._total)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("进度 %v / %m 档")
        layout.addWidget(self.progress_bar)

        self.label_status = QLabel("准备开始…")
        self.label_status.setAlignment(Qt.AlignCenter)
        self.label_status.setStyleSheet("color: #333333; font-size: 12px;")
        layout.addWidget(self.label_status)

        self.table_results = QTableWidget(self._total, 4, self)
        self.table_results.setHorizontalHeaderLabels(
            ["量程", "状态", "偏置 (ADC)", "偏置 (mT)"]
        )
        self.table_results.verticalHeader().setVisible(False)
        self.table_results.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table_results.setSelectionMode(QAbstractItemView.NoSelection)
        self.table_results.setFocusPolicy(Qt.NoFocus)
        header = self.table_results.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table_results.setAlternatingRowColors(True)

        for index in range(self._total):
            text = PGA_OPTION_TEXTS[index] if index < len(PGA_OPTION_TEXTS) else f"PGA{index}"
            self.table_results.setItem(index, 0, QTableWidgetItem(text))
            self.table_results.setItem(index, 1, QTableWidgetItem("等待"))
            self.table_results.setItem(index, 2, QTableWidgetItem("-"))
            self.table_results.setItem(index, 3, QTableWidgetItem("-"))
            self._color_row(index, 1, self.COLOR_WAIT)
        layout.addWidget(self.table_results)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.btn_cancel = QPushButton("取消", self)
        self.btn_cancel.setMinimumWidth(110)
        self.btn_cancel.clicked.connect(self._on_cancel_clicked)
        btn_row.addWidget(self.btn_cancel)
        layout.addLayout(btn_row)

    # ---- 窗口拖拽（与偏置校准对话框一致） ----

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

    # ---- 对外接口 ----

    def set_progress(self, value: int, text: str = ""):
        """设置量程进度（0~total）与状态文本。"""
        value = max(0, min(int(value), self._total))
        self.progress_bar.setValue(value)
        if text:
            self.label_status.setText(text)

    def set_status_text(self, text: str):
        self.label_status.setText(text)

    def set_gain_state(self, index: int, state: str, color: str = COLOR_RUNNING):
        """更新某档“状态”列（等待/切换中/校准中…）。"""
        if 0 <= index < self._total:
            self._color_row(index, 1, color)
            self.table_results.item(index, 1).setText(state)

    def show_gain_result(
        self,
        index: int,
        ok: bool,
        offset_adc=None,
        offset_mt=None,
    ):
        """某档偏置校准结束：写入状态与偏置值。"""
        if not (0 <= index < self._total):
            return
        if ok:
            self._color_row(index, 1, self.COLOR_OK)
            self.table_results.item(index, 1).setText("成功")
            if offset_adc is not None:
                self.table_results.item(index, 2).setText(f"{offset_adc:.2f}")
            if offset_mt is not None:
                self.table_results.item(index, 3).setText(f"{offset_mt:.3f}")
        else:
            self._color_row(index, 1, self.COLOR_FAIL)
            self.table_results.item(index, 1).setText("失败")
            self.table_results.item(index, 2).setText("-")
            self.table_results.item(index, 3).setText("-")

    def finish(self, ok_count: int, fail_count: int):
        """全部结束后显示汇总并切换按钮为“关闭”。"""
        self._finished = True
        self.label_title.setText("全量程偏置校准完成")
        self.label_title.setStyleSheet(
            "color: #000000; font-size: 18px; font-weight: bold;"
        )
        self.progress_bar.setValue(self._total)
        self.label_status.setText(
            f"完成：成功 {ok_count} 个，失败 {fail_count} 个"
        )
        self.btn_cancel.setText("关闭")

    def abort_status(self, text: str = "正在停止（当前量程完成后结束）…"):
        self.label_title.setText("全量程偏置校准已取消")
        self.label_title.setStyleSheet(
            "color: #000000; font-size: 18px; font-weight: bold;"
        )
        self.label_status.setText(text)

    # ---- 内部 ----

    def _color_row(self, row: int, column: int, color: str):
        item = self.table_results.item(row, column)
        if item is not None:
            item.setForeground(QColor(color))

    def _on_cancel_clicked(self):
        if self._finished:
            self.accept()
            return
        self.cancel_requested.emit()
