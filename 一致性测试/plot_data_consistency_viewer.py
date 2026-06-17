# -*- coding: utf-8 -*-
"""plot_data 一致性可视化分析工具。

运行方式：
    python 一致性测试/plot_data_consistency_viewer.py
"""

import csv
import math
import os
import sys
import warnings
from dataclasses import dataclass
from typing import Dict, Iterable, List, Sequence, Tuple

warnings.filterwarnings(
    "ignore",
    category=DeprecationWarning,
    message=r"sipPyTypeDict\(\) is deprecated.*",
)

import numpy as np
import pyqtgraph as pg
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QBrush
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
SRC_DIR = os.path.join(PROJECT_DIR, "src")
PLOT_DATA_DIR = os.path.join(PROJECT_DIR, "data", "plot_data")

if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from windows.wave_analysis import WaveAnalysis  # noqa: E402


@dataclass
class FileAnalysis:
    file_path: str
    display_name: str
    sample_info: Dict[str, str]
    angle_data: List[float]
    mag_data: List[float]
    results: Dict[str, object]


def _is_number(value) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _to_float(value) -> float:
    return float(value) if _is_number(value) else float("nan")


def read_plot_data_csv(file_path: str) -> Tuple[List[float], List[float], Dict[str, str]]:
    angle_data: List[float] = []
    mag_data: List[float] = []
    sample_info: Dict[str, str] = {}

    with open(file_path, "r", encoding="utf-8-sig", newline="") as csvfile:
        rows = list(csv.reader(csvfile))

    for row in rows[:20]:
        if len(row) < 2:
            continue
        key = row[0].strip()
        value = row[1].strip()
        if "样品名称" in key:
            sample_info["sample_name"] = value
        elif "样品编号" in key:
            sample_info["sample_code"] = value
        elif "保存时间" in key:
            sample_info["save_time"] = value
        elif "极数" in key:
            sample_info["polar_num"] = value
        elif "备注" in key:
            sample_info["remark"] = value

    data_start = -1
    for index, row in enumerate(rows):
        if len(row) >= 2 and "角度" in row[0] and "磁场" in row[1]:
            data_start = index + 1
            break

    if data_start < 0:
        raise ValueError("未找到角度/磁场数据段")

    for row in rows[data_start:]:
        if len(row) < 2 or not row[0].strip():
            continue
        try:
            angle_data.append(float(row[0].strip()))
            mag_data.append(float(row[1].strip()))
        except ValueError:
            continue

    if not angle_data or not mag_data:
        raise ValueError("角度/磁场数据为空")

    return angle_data, mag_data, sample_info


RESULT_LABEL_MAP = {
    "N极误差": "N_se",
    "S极误差": "S_se",
    "N极间隔误差": "N_interval_std",
    "S极间隔误差": "S_interval_std",
    "单极误差": "SinglePolarError",
    "极误差和": "PolarErrorSum",
    "累计误差": "PolarErrorSum",
    "过零点个数": "zero_crossing_count",
}

REQUIRED_RESULT_KEYS = {
    "N_se",
    "S_se",
    "N_interval_std",
    "S_interval_std",
    "SinglePolarError",
    "PolarErrorSum",
    "zero_crossing_count",
}


def read_saved_analysis_results(file_path: str) -> Tuple[Dict[str, str], Dict[str, object]]:
    sample_info: Dict[str, str] = {}
    results: Dict[str, object] = {}

    with open(file_path, "r", encoding="utf-8-sig", newline="") as csvfile:
        reader = csv.reader(csvfile)
        for row in reader:
            if len(row) >= 2 and "角度" in row[0] and "磁场" in row[1]:
                break
            if len(row) < 2:
                continue

            key = row[0].strip()
            value = row[1].strip()
            if "样品名称" in key:
                sample_info["sample_name"] = value
            elif "样品编号" in key:
                sample_info["sample_code"] = value
            elif "保存时间" in key:
                sample_info["save_time"] = value
            elif "极数" in key:
                sample_info["polar_num"] = value
            elif "备注" in key:
                sample_info["remark"] = value

            result_key = RESULT_LABEL_MAP.get(key)
            if result_key:
                results[result_key] = _to_float(value)

    return sample_info, results


def analyze_files(file_paths: Iterable[str]) -> List[FileAnalysis]:
    analyzer = WaveAnalysis()
    analyses: List[FileAnalysis] = []
    for file_path in file_paths:
        sample_info, results = read_saved_analysis_results(file_path)
        angle_data: List[float] = []
        mag_data: List[float] = []

        if not all(_is_number(results.get(key)) for key in REQUIRED_RESULT_KEYS):
            angle_data, mag_data, sample_info = read_plot_data_csv(file_path)
            results = analyzer.analyze_waveform(
                angle_data,
                mag_data,
                enable_concentricity_calibration=True,
            )
            if not results:
                raise ValueError(f"{os.path.basename(file_path)} 分析结果为空")

        display_name = os.path.basename(file_path)
        analyses.append(FileAnalysis(file_path, display_name, sample_info, angle_data, mag_data, results))
    return analyses


class ConsistencyWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("plot_data 一致性测试")
        self.resize(1400, 860)
        self.analyses: List[FileAnalysis] = []
        self.file_paths: List[str] = []

        pg.setConfigOptions(antialias=True)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        self.setCentralWidget(central)

        button_layout = QHBoxLayout()
        layout.addLayout(button_layout)

        self.add_files_button = QPushButton("添加文件")
        self.add_files_button.setMinimumHeight(34)
        self.add_files_button.clicked.connect(self.add_files)
        button_layout.addWidget(self.add_files_button)

        self.select_all_button = QPushButton("全选")
        self.select_all_button.setMinimumHeight(34)
        self.select_all_button.clicked.connect(self.select_all_files)
        button_layout.addWidget(self.select_all_button)

        self.clear_selection_button = QPushButton("全不选")
        self.clear_selection_button.setMinimumHeight(34)
        self.clear_selection_button.clicked.connect(self.clear_file_selection)
        button_layout.addWidget(self.clear_selection_button)

        self.start_button = QPushButton("开始分析")
        self.start_button.setMinimumHeight(34)
        self.start_button.clicked.connect(self.start_analysis)
        button_layout.addWidget(self.start_button)

        self.status_label = QLabel("请添加 plot_data CSV 文件，勾选需要参与分析的文件后点击开始分析。")
        self.status_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        layout.addWidget(self.status_label)

        splitter = QSplitter(Qt.Horizontal)
        layout.addWidget(splitter, 1)

        self.file_list = QListWidget()
        self.file_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        splitter.addWidget(self.file_list)

        # 右侧：上方 2×2 绘图区 + 下方表格
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(4)

        self.plot_area = pg.GraphicsLayoutWidget()
        self.plot_area.setBackground("#ffffff")
        right_layout.addWidget(self.plot_area, 3)

        self.info_table = QTableWidget(0, 3)
        self.info_table.setHorizontalHeaderLabels(["文件序号", "极对数", "过零点个数"])
        self.info_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.info_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.info_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.info_table.setMinimumHeight(120)
        right_layout.addWidget(self.info_table, 1)

        splitter.addWidget(right_panel)
        splitter.setSizes([360, 1040])

        self.plots = {
            "peak": self._add_plot(0, 0, "极值误差"),
            "zero": self._add_plot(0, 1, "过零点误差"),
            "single": self._add_plot(1, 0, "单极误差"),
            "sum": self._add_plot(1, 1, "累计误差"),
        }

    def _add_plot(self, row: int, col: int, title: str):
        plot = self.plot_area.addPlot(row=row, col=col, title=title)
        plot.showGrid(x=True, y=True, alpha=0.3)
        plot.setLabel("bottom", "文件序号")
        plot.setLabel("left", "误差", units="%")
        return plot

    def add_files(self):
        default_dir = PLOT_DATA_DIR if os.path.isdir(PLOT_DATA_DIR) else PROJECT_DIR
        file_paths, _ = QFileDialog.getOpenFileNames(
            self,
            "选择 plot_data CSV 文件",
            default_dir,
            "CSV Files (*.csv);;All Files (*)",
        )
        if not file_paths:
            return

        added_count = 0
        for file_path in file_paths:
            normalized_path = os.path.normpath(file_path)
            if normalized_path in self.file_paths:
                continue
            self.file_paths.append(normalized_path)
            item = QListWidgetItem(os.path.basename(normalized_path))
            item.setToolTip(normalized_path)
            item.setData(Qt.UserRole, normalized_path)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            self.file_list.addItem(item)
            added_count += 1

        self.status_label.setText(f"已添加 {self.file_list.count()} 个文件，本次新增 {added_count} 个。")

    def select_all_files(self):
        self._set_all_file_checks(Qt.Checked)

    def clear_file_selection(self):
        self._set_all_file_checks(Qt.Unchecked)

    def _set_all_file_checks(self, check_state):
        for index in range(self.file_list.count()):
            self.file_list.item(index).setCheckState(check_state)

    def _selected_file_paths(self) -> List[str]:
        selected_paths = []
        for index in range(self.file_list.count()):
            item = self.file_list.item(index)
            if item.checkState() == Qt.Checked:
                selected_paths.append(item.data(Qt.UserRole))
        return selected_paths

    def start_analysis(self):
        file_paths = self._selected_file_paths()
        if len(file_paths) < 2:
            QMessageBox.warning(self, "文件数量不足", "请至少勾选两个 CSV 文件用于一致性分析。")
            return

        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            self.analyses = analyze_files(file_paths)
        except Exception as exc:
            QMessageBox.critical(self, "分析失败", str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()

        self.status_label.setText(f"已分析 {len(self.analyses)} 个选中文件。")
        self.refresh_plots()

    def refresh_plots(self):
        file_indices = self._file_indices()
        self._plot_dual_error_series(self.plots["peak"], file_indices, "极值误差",
                                     self._result_series("N_se"), self._result_series("S_se"),
                                     "N极", "S极", "#e74c3c", "#3498db")
        self._plot_dual_error_series(self.plots["zero"], file_indices, "过零点误差",
                                     self._result_series("N_interval_std"), self._result_series("S_interval_std"),
                                     "N间隔", "S间隔", "#e74c3c", "#3498db")
        self._plot_error_series(self.plots["single"], file_indices, "单极误差", self._result_series("SinglePolarError"))
        self._plot_error_series(self.plots["sum"], file_indices, "累计误差", self._result_series("PolarErrorSum"))
        self._refresh_info_table()

    def _file_indices(self) -> List[int]:
        return list(range(1, len(self.analyses) + 1))

    def _result_series(self, key: str) -> List[float]:
        return [_to_float(analysis.results.get(key)) for analysis in self.analyses]

    def _plot_dual_error_series(
        self,
        plot: pg.PlotWidget,
        x_values: Sequence[int],
        title: str,
        series_a: Sequence[float],
        series_b: Sequence[float],
        label_a: str,
        label_b: str,
        color_a: str,
        color_b: str,
    ) -> None:
        plot.clear()
        plot.setTitle(title)
        plot.setLabel("bottom", "文件序号")
        plot.setLabel("left", "误差", units="%")
        plot.showGrid(x=True, y=True, alpha=0.3)
        plot.addLegend()

        for series, label, color, symbol in [
            (series_a, label_a, color_a, "o"),
            (series_b, label_b, color_b, "t1"),
        ]:
            clean_x = []
            clean_y = []
            for x_value, y_value in zip(x_values, series):
                if _is_number(y_value):
                    clean_x.append(x_value)
                    clean_y.append(float(y_value))
            if clean_x:
                plot.plot(
                    clean_x, clean_y,
                    pen=pg.mkPen(color, width=2),
                    symbol=symbol, symbolSize=7,
                    symbolBrush=pg.mkBrush(color),
                    name=label,
                )

    def _refresh_info_table(self):
        # 先收集所有值
        pole_nums = []
        zero_counts = []
        for analysis in self.analyses:
            pole_nums.append(str(analysis.sample_info.get("polar_num", "")))
            details = analysis.results.get("zero_crossing_details")
            if isinstance(details, list):
                zero_counts.append(str(len(details)))
            else:
                zero_counts.append(str(analysis.results.get("zero_crossing_count", "")))

        # 找众数（出现最多的值）
        def _mode(values):
            return max(set(values), key=values.count) if values else ""

        mode_pole = _mode(pole_nums)
        mode_zero = _mode(zero_counts)

        red_brush = QBrush(QColor("#ffe0e0"))
        self.info_table.setRowCount(len(self.analyses))
        for row_idx, analysis in enumerate(self.analyses):
            self.info_table.setItem(row_idx, 0, QTableWidgetItem(str(row_idx + 1)))

            pole_item = QTableWidgetItem(pole_nums[row_idx])
            if pole_nums[row_idx] != mode_pole:
                pole_item.setBackground(red_brush)
            self.info_table.setItem(row_idx, 1, pole_item)

            zero_item = QTableWidgetItem(zero_counts[row_idx])
            if zero_counts[row_idx] != mode_zero:
                zero_item.setBackground(red_brush)
            self.info_table.setItem(row_idx, 2, zero_item)

    def _plot_error_series(
        self,
        plot: pg.PlotWidget,
        x_values: Sequence[int],
        title: str,
        values: Sequence[float],
    ) -> None:
        plot.clear()
        plot.setTitle(title)
        plot.setLabel("bottom", "文件序号")
        plot.setLabel("left", "误差", units="%")
        plot.showGrid(x=True, y=True, alpha=0.3)

        clean_x = []
        clean_y = []
        for x_value, y_value in zip(x_values, values):
            if _is_number(y_value):
                clean_x.append(x_value)
                clean_y.append(float(y_value))

        if not clean_x:
            return

        plot.plot(
            clean_x,
            clean_y,
            pen=pg.mkPen("#1f77b4", width=2),
            symbol="o",
            symbolSize=7,
            symbolBrush=pg.mkBrush("#1f77b4"),
        )

        mean_value = float(np.mean(clean_y))
        mean_line = pg.InfiniteLine(
            pos=mean_value,
            angle=0,
            pen=pg.mkPen("#d62728", width=2, style=Qt.DashLine),
            label=f"均值 {mean_value:.5f}%",
            labelOpts={"position": 0.95, "color": "#d62728"},
        )
        plot.addItem(mean_line)
        plot.setXRange(0.8, max(clean_x) + 0.2, padding=0.03)


def main() -> int:
    app = QApplication(sys.argv)
    window = ConsistencyWindow()
    window.show()
    app.exec_()
    return 0


if __name__ == "__main__":
    sys.exit(main())