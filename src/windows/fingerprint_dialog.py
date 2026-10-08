# -*- coding: utf-8 -*-
"""分析比对结果对话框。

四个标签页（缺陷指纹 / 过零点差异 / 幅值差异 / 周期差异），每个标签页上下两张曲线图：

    上：各轮原始曲线（未对齐）        下：折算到基准轮坐标系（对齐后）

每张图画各轮曲线 + 基准轮加粗 + 多轮均值曲线与 ±1σ 阴影带；图下一行为统计说明。
只显示，不写文件、不导出报告。
"""

import numpy as np
import pyqtgraph as pg
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QDialog, QLabel, QTabWidget, QVBoxLayout, QWidget)
from pyqtgraph import mkPen

from core.defect_fingerprint import BIN_DEG, CURVES, PALETTE, grid_angles

BAND_BRUSH = (52, 152, 219, 38)
MEAN_COLOR = "#2c3e50"


class FingerprintResultDialog(QDialog):
    """缺陷指纹比对结果：四个标签页的曲线与统计。"""

    def __init__(self, runs, stats, parent=None):
        super().__init__(parent)
        self.runs = list(runs or [])
        self.stats = stats or {}

        self.setWindowTitle("分析比对结果")
        self.resize(1280, 860)
        self.setSizeGripEnabled(True)

        self._build_ui()
        self._populate()

    # ------------------------------------------------------------------ 构建
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self.header_label = QLabel()
        self.header_label.setWordWrap(True)
        self.header_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.header_label.setStyleSheet(
            "font-size: 13px; color: #2c3e50; background: #f7f9fb;"
            "border: 1px solid #e0e0e0; border-radius: 4px; padding: 8px;"
        )
        layout.addWidget(self.header_label)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)

        self._tab_widgets = {}
        for key, name in CURVES:
            page = QWidget()
            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(6, 8, 6, 6)
            page_layout.setSpacing(6)

            plot_raw = self._make_plot("未对齐（各轮报告坐标系）")
            plot_aligned = self._make_plot("折算到基准轮坐标系（对齐后）")
            page_layout.addWidget(plot_raw, 1)
            page_layout.addWidget(plot_aligned, 1)

            stats_label = QLabel()
            stats_label.setWordWrap(True)
            stats_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            stats_label.setStyleSheet(
                "font-size: 12px; color: #34495e; background: #fbfbfb;"
                "border: 1px solid #ececec; border-radius: 4px; padding: 6px;"
            )
            page_layout.addWidget(stats_label)

            self._tab_widgets[key] = (plot_raw, plot_aligned, stats_label)
            self.tabs.addTab(page, name)

    @staticmethod
    def _make_plot(title):
        plot = pg.PlotWidget()
        plot.setBackground("#ffffff")
        plot.showGrid(x=True, y=True, alpha=0.3)
        plot.setXRange(0, 360, padding=0)
        plot.plotItem.setLabel("bottom", "角度", units="°")
        plot.plotItem.setLabel("left", "相对偏差", units="%")
        plot.setTitle(title, size="10pt", color="#7f8c8d")
        plot.addLegend(offset=(10, 10))
        return plot

    # ------------------------------------------------------------------ 填数据
    def _populate(self):
        if not self.runs or not self.stats:
            return

        self.header_label.setText(self._header_text())
        grid = grid_angles()

        for key, _name in CURVES:
            curve = self.stats["per_curve"][key]
            plot_raw, plot_aligned, stats_label = self._tab_widgets[key]

            self._draw_curves(plot_raw, grid, curve["raw"],
                              self.stats["labels"], self.stats["ref_index"],
                              aligned=False)
            self._draw_curves(plot_aligned, grid, curve["aligned"],
                              self.stats["labels"], self.stats["ref_index"],
                              aligned=True, curve=curve)

            self._apply_y_range(plot_raw, curve["raw"])
            self._apply_y_range(plot_aligned, curve["aligned"],
                                extra=[curve["mean"] - curve["std"],
                                       curve["mean"] + curve["std"]])
            stats_label.setText(self._stats_text(key, curve))

    def _draw_curves(self, plot, grid, matrix, labels, ref_index, aligned, curve=None):
        """画各轮曲线；aligned=True 时额外画均值 ±1σ。"""
        for index, label in enumerate(labels):
            is_ref = (index == ref_index)
            name = label + ("（基准轮）" if is_ref else "")
            plot.plot(
                grid,
                matrix[index],
                pen=mkPen(PALETTE[index % len(PALETTE)],
                          width=2.6 if is_ref else 1.2),
                name=name,
            )

        if aligned and len(matrix) > 1 and curve is not None:
            mean = curve["mean"]
            band = curve["std"]
            upper = pg.PlotCurveItem(grid, mean + band, pen=pg.mkPen(None))
            lower = pg.PlotCurveItem(grid, mean - band, pen=pg.mkPen(None))
            plot.addItem(upper, ignoreBounds=True)
            plot.addItem(lower, ignoreBounds=True)
            fill = pg.FillBetweenItem(upper, lower, brush=pg.mkBrush(*BAND_BRUSH))
            plot.addItem(fill, ignoreBounds=True)
            plot.plot(grid, mean, pen=mkPen(MEAN_COLOR, width=1.6, style=Qt.DashLine),
                      name="多轮均值±1σ")

    @staticmethod
    def _apply_y_range(plot, matrix, extra=None):
        values = [np.asarray(matrix, dtype=float)]
        if extra:
            values.extend(np.asarray(item, dtype=float) for item in extra)
        stacked = np.concatenate([np.ravel(item) for item in values])
        if not len(stacked):
            return
        lo = float(np.nanmin(stacked))
        hi = float(np.nanmax(stacked))
        if not np.isfinite(lo) or not np.isfinite(hi):
            return
        margin = max((hi - lo) * 0.12, 0.05)
        plot.setYRange(lo - margin, hi + margin, padding=0)

    # ------------------------------------------------------------------ 文本
    def _header_text(self):
        stats = self.stats
        parts = [
            "基准轮 <b>%s</b>" % stats.get("ref_label", "-"),
            "参与轮数 <b>%d</b>" % len(self.runs),
            "极对数 <b>%d</b>（极距 %.1f°）" % (stats.get("pole_pairs", 0),
                                              stats.get("pole_pitch_deg", 0.0)),
        ]

        rotations = stats.get("rotations") or []
        corrs = stats.get("align_corr") or []
        labels = stats.get("labels") or []
        pairs = []
        for i, label in enumerate(labels):
            deg = rotations[i] if i < len(rotations) else float("nan")
            corr = corrs[i] if i < len(corrs) else float("nan")
            pairs.append("%s %+.1f°(相关度 %.2f)" % (label, deg, corr))
        line = "各轮相对基准轮转角（缺陷指纹互相关，四张曲线共用）：" + "；".join(pairs)

        html = parts[0] + " ｜ " + parts[1] + " ｜ " + parts[2] + "<br/>" + line

        outliers = stats.get("field_outliers") or []
        if outliers:
            html += ("<br/><span style='color:#c0392b'>提示：%s 的 N 极均值与中位数相差超过 "
                     "25%%，可能不是同一个样品</span>" % "、".join(outliers))
        return html

    def _stats_text(self, key, curve):
        stats = self.stats
        corrs = [c for c in curve["corr"] if np.isfinite(c)]
        corr_text = ("%.2f~%.2f" % (min(corrs), max(corrs))) if corrs else "-"
        lines = [
            "轮间离散度（各角度格上轮间标准差的中位数）：未对齐 %.3f%% → 对齐后 %.3f%%"
            "（下降 %.0f%%）" % (curve["spread_before"], curve["spread_after"],
                              curve["gain_pct"]),
            "对齐后各轮与基准轮的相关系数：%s（曲线间隔分辨率 %.1f°）" % (corr_text, BIN_DEG),
        ]
        if key == "period":
            lines.append("周期由相邻两段过零间隔相加得到，参与统计的单极周期 "
                         "%d 个（极距 %.1f°）"
                         % (stats.get("pole_pairs", 0), stats.get("pole_pitch_deg", 0.0)))
        elif key == "cross":
            lines.append("过零间隔按修正后过零点角度插值到 0.5° 网格，半周期 %.1f°"
                         % stats.get("half_pitch_deg", 0.0))
        return "<br/>".join(lines)
