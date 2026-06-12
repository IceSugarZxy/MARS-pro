# -*- coding: utf-8 -*-
"""波形分析详情窗口。"""

import math
import numpy as np
import pyqtgraph as pg
from pyqtgraph import mkPen
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QGridLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
)
from PyQt5.QtCore import Qt


class AnalysisDetailDialog(QDialog):
    """显示过零点、极值点和周期误差详情。"""

    DETAIL_TITLES = {
        "zero_crossing": "过零点信息",
        "extreme_point": "极值点信息",
        "period_error": "周期误差信息",
    }

    def __init__(self, detail_type, angle_data, mag_data, analysis_results, parent=None):
        super().__init__(parent)
        self.detail_type = detail_type
        self.angle_data = list(angle_data or [])
        self.mag_data = list(mag_data or [])
        self.analysis_results = analysis_results or {}

        self.setWindowTitle(self.DETAIL_TITLES.get(detail_type, "分析详情"))
        self.resize(1200, 760)
        self._init_ui()
        self._populate()

    def _init_ui(self):
        layout = QGridLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        layout.setColumnStretch(0, 3)
        layout.setColumnStretch(1, 2)
        layout.setRowStretch(1, 3)
        layout.setRowStretch(2, 2)

        title = QLabel(self.windowTitle())
        title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        layout.addWidget(title, 0, 0, 1, 2)

        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground("#ffffff")
        self.plot_widget.showGrid(x=True, y=True, alpha=0.35)
        self.plot_widget.plotItem.setLabel("bottom", "角度", units="°")
        self.plot_widget.plotItem.setLabel("left", "磁场", units="mT")
        layout.addWidget(self.plot_widget, 1, 0)

        self.stats_table = QTableWidget()
        self.stats_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.stats_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.stats_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.stats_table, 2, 0)

        self.detail_table = QTableWidget()
        self.detail_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.detail_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.detail_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.detail_table, 1, 1, 2, 1)

    def _populate(self):
        if self.detail_type == "zero_crossing":
            self._populate_zero_crossing()
        elif self.detail_type == "extreme_point":
            self._populate_extreme_point()
        elif self.detail_type == "period_error":
            self._populate_period_error()

    def _plot_waveform(self):
        self.plot_widget.clear()
        if self.angle_data and self.mag_data:
            count = min(len(self.angle_data), len(self.mag_data))
            self.plot_widget.plot(
                self.angle_data[:count],
                self.mag_data[:count],
                pen=mkPen("#34495e", width=1),
            )
            self.plot_widget.setXRange(0, 360)
            mag_values = np.asarray(self.mag_data[:count], dtype=float)
            if len(mag_values) > 0:
                min_value = float(np.nanmin(mag_values))
                max_value = float(np.nanmax(mag_values))
                margin = max((max_value - min_value) * 0.1, 1.0)
                self.plot_widget.setYRange(min_value - margin, max_value + margin)

    def _populate_zero_crossing(self):
        details = list(self.analysis_results.get("zero_crossing_details", []))
        intervals = [item.get("interval_to_next") for item in details]
        mean_interval = self._mean(intervals)
        self._plot_zero_crossing_intervals(details, mean_interval)

        self._set_stats_table([
            ("过零点数量", len(details), "个"),
            ("平均间隔", mean_interval, "°"),
            ("最大间隔", self._max(intervals), "°"),
            ("最小间隔", self._min(intervals), "°"),
            ("间隔标准差", self._std(intervals), "°"),
            ("间隔峰峰值", self._peak_to_peak(intervals), "°"),
            ("N极间隔误差", self.analysis_results.get("N_interval_std"), "%"),
            ("S极间隔误差", self.analysis_results.get("S_interval_std"), "%"),
        ])
        self._set_detail_table(
            ["过零角度(°)", "下一过零间隔(°)", "区间极性"],
            [[
                item.get("angle"),
                item.get("interval_to_next"),
                item.get("pole", ""),
            ] for item in details]
        )

    def _plot_zero_crossing_intervals(self, details, mean_interval):
        self.plot_widget.clear()
        self.plot_widget.addLegend(offset=(10, 10))
        self.plot_widget.plotItem.setLabel("bottom", "过零点序号")
        self.plot_widget.plotItem.setLabel("left", "零点间隔", units="°")

        points = [
            (index + 1, float(item.get("interval_to_next")))
            for index, item in enumerate(details)
            if self._is_number(item.get("interval_to_next"))
        ]
        if not points:
            return

        indices = [point[0] for point in points]
        intervals = [point[1] for point in points]

        self.plot_widget.plot(
            indices,
            intervals,
            pen=mkPen("#2980b9", width=2),
            symbol="o",
            symbolSize=7,
            name="零点间隔变化",
        )

        if mean_interval is not None:
            mean_values = [mean_interval] * len(indices)
            self.plot_widget.plot(
                indices,
                mean_values,
                pen=mkPen("#27ae60", width=2, style=Qt.DashLine),
                name="平均间隔",
            )

            std_interval = self._std(intervals)
            if std_interval is not None:
                self.plot_widget.plot(
                    indices,
                    [mean_interval + std_interval] * len(indices),
                    pen=mkPen("#95a5a6", width=1, style=Qt.DashLine),
                    name="波动上限(+1σ)",
                )
                self.plot_widget.plot(
                    indices,
                    [mean_interval - std_interval] * len(indices),
                    pen=mkPen("#95a5a6", width=1, style=Qt.DotLine),
                    name="波动下限(-1σ)",
                )

        if intervals:
            min_value = min(intervals)
            max_value = max(intervals)
            margin = max((max_value - min_value) * 0.15, 0.1)
            self.plot_widget.setYRange(min_value - margin, max_value + margin)

    def _populate_extreme_point(self):
        self._plot_waveform()
        details = list(self.analysis_results.get("peak_details", []))
        if details:
            n_points = [item for item in details if item.get("pole") == "N"]
            s_points = [item for item in details if item.get("pole") == "S"]
            if n_points:
                self.plot_widget.addItem(pg.ScatterPlotItem(
                    x=[item.get("angle") for item in n_points],
                    y=[item.get("value") for item in n_points],
                    size=8,
                    brush=pg.mkBrush("#e74c3c"),
                    pen=pg.mkPen("#922b21", width=1),
                ))
            if s_points:
                self.plot_widget.addItem(pg.ScatterPlotItem(
                    x=[item.get("angle") for item in s_points],
                    y=[item.get("value") for item in s_points],
                    size=8,
                    brush=pg.mkBrush("#3498db"),
                    pen=pg.mkPen("#1f618d", width=1),
                ))

        self._set_stats_table([
            ("N极数量", len([item for item in details if item.get("pole") == "N"]), "个"),
            ("N极最大值", self.analysis_results.get("N_max"), "mT"),
            ("N极最小值", self.analysis_results.get("N_min"), "mT"),
            ("N极平均值", self.analysis_results.get("N_mean"), "mT"),
            ("N极误差", self.analysis_results.get("N_se"), "%"),
            ("S极数量", len([item for item in details if item.get("pole") == "S"]), "个"),
            ("S极最大值", self.analysis_results.get("S_max"), "mT"),
            ("S极最小值", self.analysis_results.get("S_min"), "mT"),
            ("S极平均值", self.analysis_results.get("S_mean"), "mT"),
            ("S极误差", self.analysis_results.get("S_se"), "%"),
            ("NS/2", self.analysis_results.get("NS_2"), "mT"),
        ])
        self._set_detail_table(
            ["极性", "角度(°)", "磁场值(mT)", "绝对峰值(mT)", "相对均值误差(%)"],
            [[
                item.get("pole", ""),
                item.get("angle"),
                item.get("value"),
                item.get("abs_value"),
                item.get("error_percent"),
            ] for item in details]
        )

    def _populate_period_error(self):
        self.plot_widget.clear()
        details = list(self.analysis_results.get("period_error_details", []))
        indices = [item.get("index") for item in details]
        errors = [item.get("error_percent") for item in details]
        cumulative_errors = [item.get("cumulative_error") for item in details]
        if details:
            self.plot_widget.addLegend(offset=(10, 10))
            self.plot_widget.plot(
                indices,
                errors,
                pen=mkPen("#e67e22", width=2),
                symbol="o",
                symbolSize=7,
                name="单周期误差",
            )
            self.plot_widget.plot(
                indices,
                cumulative_errors,
                pen=mkPen("#8e44ad", width=2),
                symbol="t",
                symbolSize=7,
                name="累计误差",
            )
            self.plot_widget.plotItem.setLabel("bottom", "周期序号")
            self.plot_widget.plotItem.setLabel("left", "误差", units="%")
            all_values = [value for value in errors + cumulative_errors if self._is_number(value)]
            if all_values:
                min_value = min(all_values)
                max_value = max(all_values)
                margin = max((max_value - min_value) * 0.15, 0.1)
                self.plot_widget.setYRange(min_value - margin, max_value + margin)

        self._set_stats_table([
            ("周期数量", len(details), "个"),
            ("单极平均值", self.analysis_results.get("SinglePolarMean"), "°"),
            ("最大单周期误差", self.analysis_results.get("SinglePolarError"), "%"),
            ("累计误差范围", self.analysis_results.get("PolarErrorSum"), "%"),
            ("平均周期", self._mean([item.get("period_angle") for item in details]), "°"),
            ("最大周期", self._max([item.get("period_angle") for item in details]), "°"),
            ("最小周期", self._min([item.get("period_angle") for item in details]), "°"),
        ])
        self._set_detail_table(
            ["周期角度(°)", "单周期误差(%)", "累计误差(%)"],
            [[
                item.get("period_angle"),
                item.get("error_percent"),
                item.get("cumulative_error"),
            ] for item in details]
        )

    def _set_stats_table(self, rows):
        self.stats_table.setColumnCount(2)
        self.stats_table.setHorizontalHeaderLabels(["统计项", "数值"])
        self.stats_table.setRowCount(len(rows))
        for row, (name, value, unit) in enumerate(rows):
            self.stats_table.setItem(row, 0, QTableWidgetItem(str(name)))
            self.stats_table.setItem(row, 1, QTableWidgetItem(self._format_value_with_unit(value, unit)))
        self.stats_table.resizeRowsToContents()

    def _set_detail_table(self, headers, rows):
        self.detail_table.setColumnCount(len(headers))
        self.detail_table.setHorizontalHeaderLabels(headers)
        self.detail_table.setRowCount(len(rows))
        for row_index, row_values in enumerate(rows):
            for column_index, value in enumerate(row_values):
                self.detail_table.setItem(row_index, column_index, QTableWidgetItem(self._format_value(value)))
        self.detail_table.resizeRowsToContents()

    def _mean(self, values):
        numbers = [float(value) for value in values if self._is_number(value)]
        return float(np.mean(numbers)) if numbers else None

    def _max(self, values):
        numbers = [float(value) for value in values if self._is_number(value)]
        return max(numbers) if numbers else None

    def _min(self, values):
        numbers = [float(value) for value in values if self._is_number(value)]
        return min(numbers) if numbers else None

    def _std(self, values):
        numbers = [float(value) for value in values if self._is_number(value)]
        return float(np.std(numbers, ddof=1)) if len(numbers) > 1 else None

    def _peak_to_peak(self, values):
        numbers = [float(value) for value in values if self._is_number(value)]
        return max(numbers) - min(numbers) if numbers else None

    @staticmethod
    def _is_number(value):
        try:
            return value is not None and math.isfinite(float(value))
        except (TypeError, ValueError):
            return False

    def _format_value(self, value):
        if value is None:
            return "--"
        if isinstance(value, str):
            return value
        if self._is_number(value):
            number = float(value)
            if abs(number) >= 100:
                return f"{number:.2f}"
            return f"{number:.5f}".rstrip("0").rstrip(".")
        return str(value)

    def _format_value_with_unit(self, value, unit):
        formatted_value = self._format_value(value)
        if not unit:
            return formatted_value
        if formatted_value == "--":
            return formatted_value
        return f"{formatted_value} {unit}"
