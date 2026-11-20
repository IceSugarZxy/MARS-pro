# -*- coding: utf-8 -*-
"""双码道解算面板：磁场 CSV → 32/31 相位码 → B12 SPO 表 → 残差评级。

界面在 `src/ui/dual_track_panel.ui`（uic 加载），本文件只负责状态与控制逻辑。
"""

import math
import os

import numpy as np
import pyqtgraph as pg
from PyQt5 import uic
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QMessageBox, QWidget

from core.dual_track_solver import (
    DEFAULT_MODE,
    MASTER_POLE_PAIRS,
    NONIUS_POLE_PAIRS,
    DualTrackError,
    describe_rating,
    solve_pair,
)
from core.logger import get_logger
from core.path_utils import get_project_root
from core.zero_crossing import (ZeroCrossingError, dual_track_difference,
                                same_direction_intervals,
                                zero_position_deviation)
from core.zero_node_judge import (LOWER_BOUND_DEG as ZERO_NODE_LOWER_BOUND,
                                  ZeroNodeError, judge_three_nodes)
from windows.csv_picker_dialog import pick_csv
from windows.plot_utils import DoubleClickReset

logger = get_logger('DualTrackPanel')

DLL_RELATIVE_PATH = os.path.join('vendor', 'iC-MU150', 'MU_3SL_INTERFACE_64.DLL')
RATING_LIMIT_CODES = 230.4
BOUNDARY_CODES = 256.0
Y_AXIS_STEP_CODES = 50.0
OUTER_COLOR = '#1f5b7a'
INNER_COLOR = '#8e44ad'
INTERVAL_NAME_OUTER = '外道 32 极对'
INTERVAL_NAME_INNER = '内道 31 极对'
DIFFERENCE_NAME = '外道 − 内道（插值）'
DIFFERENCE_COLOR = '#27ae60'
KPI_KEYS = ('verdict', 'rmin', 'rmax', 'peak', 'margin', 'worst')


def default_dll_path():
    """默认 DLL 路径：源码运行时为项目根，打包运行时为 exe 同级。"""
    return os.path.join(get_project_root(), DLL_RELATIVE_PATH)


def group_prefix(file_path):
    """文件名里时间戳之前的部分，例如 1-外_20261118_145326.csv → 1-外。"""
    stem = os.path.splitext(os.path.basename(file_path))[0]
    parts = stem.rsplit('_', 2)
    return parts[0] if len(parts) == 3 else stem


class DualTrackPanel(QWidget):
    """双码道（32/31 游标）SPO 解算页面。"""

    def __init__(self):
        super().__init__()

        ui_file_path = os.path.join(os.path.dirname(__file__), '..', 'ui',
                                    'dual_track_panel.ui')
        uic.loadUi(ui_file_path, self)

        self._result = None
        self._outer_path = ''
        self._inner_path = ''
        self._last_judge_text = ''
        self.kpi_labels = {key: getattr(self, f'kpi_value_{key}') for key in KPI_KEYS}

        self._init_plot()
        self._init_interval_plot()
        self._init_position_plot()
        self._init_judge_plot()
        self._connect_signals()
        self._apply_defaults()

    # ---------------------------------------------------------------- 初始化
    def _init_plot(self):
        """把 pyqtgraph 画布放进 .ui 的 plot_grid 栅格（0,0 单元格）。"""
        self.plot = pg.PlotWidget()
        self.plot.setBackground('#ffffff')
        self.plot.showGrid(x=True, y=True, alpha=0.35)
        self.plot.setLabel('bottom', '机械角', units='°')
        self.plot.setLabel('left', '残差 R', units='码')
        self.plot.plotItem.hideButtons()  # 去掉左下角的自动量程 “A” 按钮
        self.residual_legend = self.plot.addLegend(offset=(10, 10))
        self.residual_legend.setVisible(False)
        self.residual_curve = self.plot.plot(pen=pg.mkPen('#1f5b7a', width=1.2),
                                             name='残差 R（MU150 B12）')
        self.worst_marker = self.plot.plot(
            pen=None, symbol='o', symbolSize=9, symbolBrush='#c0392b',
            symbolPen=pg.mkPen('#7b241c'), name='最差点')
        for value, color, label in (
                (BOUNDARY_CODES, '#c0392b', '±256 解码边界'),
                (-BOUNDARY_CODES, '#c0392b', None),
                (RATING_LIMIT_CODES, '#e0b23c', '±230（90% 评级线）'),
                (-RATING_LIMIT_CODES, '#e0b23c', None),
                (0.0, '#95a5a6', '0')):
            line = pg.InfiniteLine(pos=value, angle=0,
                                   pen=pg.mkPen(color, width=1,
                                                style=Qt.DashLine if value else Qt.SolidLine),
                                   label=label,
                                   labelOpts={'position': 0.995,
                                              'anchors': ((1, 0), (1, 1)),
                                              'color': color})
            self.plot.addItem(line)
        self.plot_grid.addWidget(self.plot, 0, 0)
        self._reset_residual = DoubleClickReset(self.plot)
        self._apply_y_span(0.0)

    @staticmethod
    def _axis_span(peak):
        """纵轴量程：按 ±256 边界线与峰值需求向上取 50 码一档，再留一档余量。

        留出的那一档让 ±256 / ±230 参考线的标注落在图例下方，初始状态和
        解算后都不会与左上角图例重叠。
        """
        need = max(BOUNDARY_CODES * 1.15, float(peak) * 1.15)
        steps = math.ceil(need / Y_AXIS_STEP_CODES)
        return (steps + 1) * Y_AXIS_STEP_CODES

    def _apply_y_span(self, peak):
        span = self._axis_span(peak)
        self.plot.setXRange(0, 360, padding=0)
        self.plot.setYRange(-span, span, padding=0)
        self._reset_residual.remember()

    def _init_interval_plot(self):
        """同向过零实际间距图：直接由扫描磁场取几何角间距，与 MU150 链路独立。"""
        self.interval_plot = pg.PlotWidget()
        self.interval_plot.setBackground('#ffffff')
        self.interval_plot.showGrid(x=True, y=True, alpha=0.35)
        self.interval_plot.setLabel('bottom', '起始过零机械角', units='°')
        self.interval_plot.setLabel('left', '同向间距 T', units='°')
        self.interval_plot.plotItem.hideButtons()
        self.interval_legend = self.interval_plot.addLegend(offset=(10, 10))
        self.interval_legend.setVisible(False)
        self.interval_outer = self.interval_plot.plot(
            pen=pg.mkPen(OUTER_COLOR, width=1.0), symbol='o', symbolSize=4,
            symbolBrush=OUTER_COLOR, symbolPen=None,
            name=INTERVAL_NAME_OUTER)
        self.interval_inner = self.interval_plot.plot(
            pen=pg.mkPen(INNER_COLOR, width=1.0), symbol='o', symbolSize=4,
            symbolBrush=INNER_COLOR, symbolPen=None,
            name=INTERVAL_NAME_INNER)
        outer_nominal = 360 / MASTER_POLE_PAIRS
        inner_nominal = 360 / NONIUS_POLE_PAIRS
        self._interval_nominal = (outer_nominal, inner_nominal)
        for value, color, label in ((outer_nominal, OUTER_COLOR,
                                     f'标称 {outer_nominal:.3f}°'),
                                    (inner_nominal, INNER_COLOR,
                                     f'标称 {inner_nominal:.3f}°')):
            self.interval_plot.addItem(pg.InfiniteLine(
                pos=value, angle=0,
                pen=pg.mkPen(color, width=1, style=Qt.DashDotLine),
                label=label,
                labelOpts={'position': 0.995, 'anchors': ((1, 0), (1, 1)),
                           'color': color}))
        self.interval_grid.addWidget(self.interval_plot, 0, 0)
        self._reset_interval = DoubleClickReset(self.interval_plot)
        self._reset_interval_span()

    def _reset_interval_span(self):
        """间距图纵轴回到标称值附近的初始范围。"""
        outer_nominal, inner_nominal = self._interval_nominal
        self.interval_plot.setXRange(0, 360, padding=0)
        self.interval_plot.setYRange(outer_nominal - 0.25, inner_nominal + 0.25,
                                     padding=0)
        self._reset_interval.remember()

    def _rename_interval_legend(self, curve, text):
        """同向过零图的图例名（pyqtgraph 的图例不会自动跟随 name 更新）。"""
        legend = self.interval_plot.plotItem.legend
        if legend is None:
            return
        for sample, label in legend.items:
            if sample.item is curve:
                label.setText(text)
                legend.updateSize()
                return
        legend.removeItem(curve)
        legend.addItem(curve, text)

    def _init_position_plot(self):
        """过零点位置偏差图：外道 / 内道各自偏差 + 外道减内道（绿）。"""
        self.position_plot = pg.PlotWidget()
        self.position_plot.setBackground('#ffffff')
        self.position_plot.showGrid(x=True, y=True, alpha=0.35)
        self.position_plot.setLabel('bottom', '机械角', units='°')
        self.position_plot.setLabel('left', '位置偏差 e', units='°')
        self.position_plot.plotItem.hideButtons()
        self.position_legend = self.position_plot.addLegend(offset=(10, 10))
        self.position_legend.setVisible(False)
        self.position_outer = self.position_plot.plot(
            pen=pg.mkPen(OUTER_COLOR, width=1.0), symbol='o', symbolSize=4,
            symbolBrush=OUTER_COLOR, symbolPen=None, name=INTERVAL_NAME_OUTER)
        self.position_inner = self.position_plot.plot(
            pen=pg.mkPen(INNER_COLOR, width=1.0), symbol='o', symbolSize=4,
            symbolBrush=INNER_COLOR, symbolPen=None, name=INTERVAL_NAME_INNER)
        self.position_difference = self.position_plot.plot(
            pen=pg.mkPen(DIFFERENCE_COLOR, width=1.2), name=DIFFERENCE_NAME)
        self.position_plot.addItem(pg.InfiniteLine(
            pos=0.0, angle=0, pen=pg.mkPen('#95a5a6', width=1)))
        self.position_plot.setXRange(0, 360, padding=0)
        self.position_plot.setYRange(-0.5, 0.5, padding=0)
        self.position_grid.addWidget(self.position_plot, 0, 0)
        self._reset_position = DoubleClickReset(self.position_plot)

    def _init_judge_plot(self):
        """三点判定图：内道每个起点与「外道前/中/后节点」的差值 + 最小余量 H。"""
        self.judge_plot = pg.PlotWidget()
        self.judge_plot.setBackground('#ffffff')
        self.judge_plot.showGrid(x=True, y=True, alpha=0.35)
        self.judge_plot.setLabel('bottom', '内道起点机械角', units='°')
        self.judge_plot.setLabel('left', '差值 / 最小余量 H', units='°')
        self.judge_plot.plotItem.hideButtons()
        self.judge_legend = self.judge_plot.addLegend(offset=(10, 10))
        self.judge_legend.setVisible(False)
        self.judge_front = self.judge_plot.plot(
            pen=pg.mkPen('#95a5a6', width=0.8, style=Qt.DotLine), name='差值 前节点')
        self.judge_middle = self.judge_plot.plot(
            pen=pg.mkPen('#7f8c8d', width=0.8, style=Qt.DotLine), name='差值 对应节点')
        self.judge_back = self.judge_plot.plot(
            pen=pg.mkPen('#b2bec3', width=0.8, style=Qt.DotLine), name='差值 后节点')
        self.judge_margin = self.judge_plot.plot(
            pen=pg.mkPen('#2c3e50', width=1.6), name='最小余量 H')
        self.judge_failed = pg.ScatterPlotItem(size=8, brush=pg.mkBrush('#c0392b'),
                                               pen=pg.mkPen('#7b241c'))
        self.judge_boundary = pg.ScatterPlotItem(size=8, brush=pg.mkBrush('#e0b23c'),
                                                 pen=pg.mkPen('#b7950b'))
        self.judge_plot.addItem(self.judge_failed)
        self.judge_plot.addItem(self.judge_boundary)
        self.judge_plot.addItem(pg.InfiniteLine(
            pos=0.0, angle=0, pen=pg.mkPen('#c0392b', width=1, style=Qt.SolidLine),
            label='判定线 H=0',
            labelOpts={'position': 0.995, 'anchors': ((1, 0), (1, 1)), 'color': '#c0392b'}))
        self.judge_plot.addItem(pg.InfiniteLine(
            pos=ZERO_NODE_LOWER_BOUND, angle=0,
            pen=pg.mkPen('#e0b23c', width=1, style=Qt.DashDotLine),
            label=f'差值下限 {ZERO_NODE_LOWER_BOUND:.3f}°',
            labelOpts={'position': 0.985, 'anchors': ((1, 0), (1, 1)), 'color': '#b7950b'}))
        self.judge_plot.setXRange(0, 360, padding=0)
        self.judge_plot.setYRange(-1.0, 1.0, padding=0)
        self.judge_grid.addWidget(self.judge_plot, 0, 0)
        self._reset_judge = DoubleClickReset(self.judge_plot)

    def _track_intervals(self, result):
        """两条码道各自的同向过零结果（间距图 / 位置偏差图 / 三点判定共用）。"""
        data = {}
        errors = []
        for pole_pairs, field_name in ((MASTER_POLE_PAIRS, 'master_field'),
                                       (NONIUS_POLE_PAIRS, 'nonius_field')):
            field = getattr(result, field_name, None)
            if field is None:
                data[pole_pairs] = None
                errors.append(f'{pole_pairs} 极对缺少原始磁场')
                continue
            try:
                data[pole_pairs] = same_direction_intervals(
                    result.angle, field, pole_pairs)
            except ZeroCrossingError as exc:
                data[pole_pairs] = None
                errors.append(f'{pole_pairs} 极对：{exc}')
        return data, errors

    def _track_file_name(self, result, pole_pairs):
        path = getattr(result, 'outer_path' if pole_pairs == MASTER_POLE_PAIRS
                       else 'inner_path', '')
        fallback = (INTERVAL_NAME_OUTER if pole_pairs == MASTER_POLE_PAIRS
                    else INTERVAL_NAME_INNER)
        return os.path.basename(path) or fallback

    def _rename_interval_legend(self, curve, text):
        """同向过零图的图例名（pyqtgraph 的图例不会自动跟随 name 更新）。"""
        legend = self.interval_plot.plotItem.legend
        if legend is None:
            return
        for sample, label in legend.items:
            if sample.item is curve:
                label.setText(text)
                legend.updateSize()
                return
        legend.removeItem(curve)
        legend.addItem(curve, text)

    def _rename_position_legend(self, curve, text):
        legend = self.position_plot.plotItem.legend
        if legend is None:
            return
        for sample, label in legend.items:
            if sample.item is curve:
                label.setText(text)
                legend.updateSize()
                return
        legend.removeItem(curve)
        legend.addItem(curve, text)

    def _show_intervals(self, result, data, errors):
        """同向过零实际间距（第二张图），返回一行摘要。"""
        self.interval_outer.setData([], [])
        self.interval_inner.setData([], [])
        pieces = []
        values = []
        for curve, pole_pairs in ((self.interval_outer, MASTER_POLE_PAIRS),
                                  (self.interval_inner, NONIUS_POLE_PAIRS)):
            intervals = data.get(pole_pairs)
            if intervals is None:
                continue
            curve.setData(intervals.cross_deg, intervals.same_deg)
            self._rename_interval_legend(
                curve, self._track_file_name(result, pole_pairs))
            values.append(intervals.same_deg)
            stats = intervals.stats()
            pieces.append('%d 极对 %.3f~%.3f°（峰峰 %.3f°）'
                          % (pole_pairs, stats['minimum_deg'],
                             stats['maximum_deg'], stats['peak_to_peak_deg']))

        if errors:
            self.interval_plot.setTitle('同向过零提取异常：' + '；'.join(errors))
            self.interval_legend.setVisible(bool(values))
            return ''
        self.interval_legend.setVisible(True)
        self.interval_plot.setTitle(None)
        if values:
            merged = np.concatenate(values)
            low, high = float(merged.min()), float(merged.max())
            pad = max((high - low) * 0.25, 0.02)
            self.interval_plot.setYRange(low - pad, high + pad, padding=0)
            self._reset_interval.remember()
        return '；'.join(pieces)

    def _show_positions(self, result, data, errors):
        """过零点位置偏差（第三张图）：两道各自偏差 + 外道减内道。"""
        self.position_outer.setData([], [])
        self.position_inner.setData([], [])
        self.position_difference.setData([], [])
        positions = {}
        values = []

        for curve, pole_pairs in ((self.position_outer, MASTER_POLE_PAIRS),
                                  (self.position_inner, NONIUS_POLE_PAIRS)):
            intervals = data.get(pole_pairs)
            if intervals is None:
                continue
            try:
                position = zero_position_deviation(intervals.cross_deg, pole_pairs)
            except ZeroCrossingError as exc:
                errors.append(f'{pole_pairs} 极对：{exc}')
                continue
            positions[pole_pairs] = position
            curve.setData(position.cross_deg, position.position_deg)
            self._rename_position_legend(
                curve, self._track_file_name(result, pole_pairs))
            values.append(position.position_deg)

        if errors or len(positions) != 2:
            title = '；'.join(errors) if errors else '缺少某一道的位置偏差结果'
            self.position_plot.setTitle('过零位置偏差提取异常：' + title)
            self.position_legend.setVisible(bool(values))
            return
        self.position_legend.setVisible(True)

        difference = dual_track_difference(result.angle,
                                           positions[MASTER_POLE_PAIRS],
                                           positions[NONIUS_POLE_PAIRS])
        self.position_difference.setData(result.angle, difference)
        self.position_plot.setTitle(None)
        self.position_plot.setXRange(0, 360, padding=0)

        merged = np.concatenate(values + [difference])
        low, high = float(merged.min()), float(merged.max())
        pad = max((high - low) * 0.15, 0.01)
        self.position_plot.setYRange(low - pad, high + pad, padding=0)
        self._reset_position.remember()

    def _show_judgement(self, result, data, errors):
        """三点判定（第四张图）：内道每个起点对「外道前/中/后节点」的差值与最小余量 H。

        判定规则见《CC01 实际过零节点三点判断_算法说明》：三项差值的最小值减下限
        L=0.036° 得到 H，H>0 通过、H<0 不通过、H=0 边界待核查；整盘取最小 H。
        """
        for curve in (self.judge_front, self.judge_middle, self.judge_back,
                      self.judge_margin):
            curve.setData([], [])
        self.judge_failed.setData([], [])
        self.judge_boundary.setData([], [])

        outer = data.get(MASTER_POLE_PAIRS)
        inner = data.get(NONIUS_POLE_PAIRS)
        if outer is None or inner is None:
            title = '；'.join(errors) if errors else '缺少某一码道的同向过零结果'
            self.judge_plot.setTitle('三点判定无法计算：' + title)
            self.judge_legend.setVisible(False)
            return ''

        try:
            report = judge_three_nodes(outer.cross_deg, outer.same_deg,
                                       inner.cross_deg, inner.same_deg)
        except ZeroNodeError as exc:
            self.judge_plot.setTitle('三点判定异常：' + str(exc))
            self.judge_legend.setVisible(False)
            return ''

        angle = inner.cross_deg
        differences = report['differences_deg']
        margins = report['margins_deg']
        self.judge_front.setData(angle, differences[:, 0])
        self.judge_middle.setData(angle, differences[:, 1])
        self.judge_back.setData(angle, differences[:, 2])
        color = {'pass': '#2e8b57', 'fail': '#c0392b',
                 'boundary': '#e0b23c'}[report['judgement']]
        self.judge_margin.setPen(pg.mkPen(color, width=1.6))
        self.judge_margin.setData(angle, margins)
        if report['failed'].any():
            self.judge_failed.setData(angle[report['failed']], margins[report['failed']])
        if report['boundary'].any():
            self.judge_boundary.setData(angle[report['boundary']],
                                        margins[report['boundary']])
        self.judge_legend.setVisible(True)
        self.judge_plot.setTitle(
            '%s：最小余量 %+.4f° @ %.3f°，不通过 %d/%d（%.1f%%）'
            % (report['judgement_text'], report['minimum_margin_deg'],
               report['worst_inner_angle_deg'], report['failed_count'],
               margins.size, report['failed_percent']))
        self.judge_plot.setXRange(0, 360, padding=0)

        merged = np.concatenate([differences.ravel(), margins])
        low, high = float(merged.min()), float(merged.max())
        pad = max((high - low) * 0.15, 0.02)
        self.judge_plot.setYRange(min(low - pad, -pad), max(high + pad, pad),
                                 padding=0)
        self._reset_judge.remember()
        return ('判定%s，最小余量 %+.4f°（最差内道起点 %.3f°），不通过 %d/%d'
                % (report['judgement_text'], report['minimum_margin_deg'],
                   report['worst_inner_angle_deg'], report['failed_count'],
                   margins.size))

    def _connect_signals(self):
        self.btn_pick_outer.clicked.connect(self._pick_outer)
        self.btn_pick_inner.clicked.connect(self._pick_inner)
        self.btn_solve.clicked.connect(self._on_solve)
        self.btn_clear.clicked.connect(self._on_clear)

    def _apply_defaults(self):
        dll = default_dll_path()
        if not os.path.exists(dll):
            logger.warning(f'未找到原厂 DLL: {dll}')
            self.status_label.setText(
                f'未找到原厂 DLL，请把 MU_3SL_INTERFACE_64.DLL 放到：{os.path.dirname(dll)}')

    @staticmethod
    def _set_path_text(edit, path):
        """输入框只放文件名（完整路径进 tooltip），保持顶部控件紧凑。"""
        edit.setText(os.path.basename(path) if path else '')
        edit.setCursorPosition(0)
        edit.setToolTip(path or '')

    # ---------------------------------------------------------------- 数据选择
    def _pick_outer(self):
        path = pick_csv(self, self._outer_path,
                        title='选择外圈数据（主轨 32 极对数）')
        if path:
            self._outer_path = path
            self._set_path_text(self.outer_edit, path)
            self._update_selection_label()

    def _pick_inner(self):
        path = pick_csv(self, self._inner_path,
                        title='选择内圈数据（游标轨 31 极对数）')
        if path:
            self._inner_path = path
            self._set_path_text(self.inner_edit, path)
            self._update_selection_label()

    def _update_selection_label(self):
        """只显示组号（文件名已在输入框里），避免撑宽顶部控件。"""
        outer = group_prefix(self._outer_path) if self._outer_path else '未选择'
        inner = group_prefix(self._inner_path) if self._inner_path else '未选择'
        match = '✓' if outer.replace('外', '内') == inner else '⚠'
        self.selection_label.setText(f'{match} {outer} ↔ {inner}')

    # ---------------------------------------------------------------- 解算
    def _on_solve(self):
        outer = self._outer_path
        inner = self._inner_path
        dll = default_dll_path()
        if not outer or not inner:
            QMessageBox.warning(self, '双码道解算', '请先选择外圈和内圈数据各一条')
            return
        if not os.path.exists(dll):
            message = f'找不到原厂 DLL，请把 MU_3SL_INTERFACE_64.DLL 放到：{os.path.dirname(dll)}'
            self.status_label.setText(message)
            QMessageBox.warning(self, '双码道解算', message)
            return

        mode = DEFAULT_MODE
        self.status_label.setText(f'解算中…（{mode}）')
        self.btn_solve.setEnabled(False)
        self.setCursor(Qt.WaitCursor)
        try:
            result = solve_pair(outer, inner, dll, mode)
        except DualTrackError as exc:
            logger.warning(f'双码道解算失败: {exc}')
            QMessageBox.warning(self, '双码道解算失败', str(exc))
            self.status_label.setText(f'解算失败：{exc}')
            return
        except Exception as exc:  # 未预期错误也要给用户可读提示
            logger.exception(f'双码道解算异常: {exc}')
            QMessageBox.critical(self, '双码道解算异常', str(exc))
            self.status_label.setText(f'解算异常：{exc}')
            return
        finally:
            self.btn_solve.setEnabled(True)
            self.unsetCursor()

        self._result = result
        interval_text = self._show_result(result)
        summary = result.summary()
        status = ('完成：R %.0f ~ %.0f 码，最小裕量 %d 码，%s'
                  % (summary['r_min'], summary['r_max'], summary['margin_codes'],
                     describe_rating(result.rating)))
        if interval_text:
            status += '；同向间距 ' + interval_text
        if self._last_judge_text:
            status += '；' + self._last_judge_text
        self.status_label.setText(status)
        logger.info(f'双码道解算完成: {os.path.basename(outer)} / {os.path.basename(inner)} '
                    f'模式={mode} R={summary["r_min"]}~{summary["r_max"]}')

    def _show_result(self, result):
        summary = result.summary()
        rating = result.rating
        self.kpi_labels['verdict'].setText('合格' if rating.within_rating else '超线')
        self.kpi_labels['verdict'].setStyleSheet(
            'color: #2e8b57; font-weight: 700;' if rating.within_rating
            else 'color: #c0392b; font-weight: 700;')
        self.kpi_labels['rmin'].setText(f'{summary["r_min"]:+d}')
        self.kpi_labels['rmax'].setText(f'{summary["r_max"]:+d}')
        self.kpi_labels['peak'].setText(f'{summary["peak"]}')
        self.kpi_labels['margin'].setText(f'{summary["margin_codes"]}')
        self.kpi_labels['worst'].setText(f'{summary["worst_angle_deg"]:.3f}')

        self.residual_legend.setVisible(True)
        angle = np.asarray(result.angle, dtype=float)
        residual = result.residual
        self.residual_curve.setData(angle, residual)
        self.worst_marker.setData([angle[result.worst_index]], [residual[result.worst_index]])
        self._apply_y_span(float(np.max(np.abs(residual))))

        data, errors = self._track_intervals(result)
        self._show_positions(result, data, errors)
        self._last_judge_text = self._show_judgement(result, data, errors)
        return self._show_intervals(result, data, errors)

    def _on_clear(self):
        """清屏：清空四条曲线与评级，保留已选数据。"""
        self._result = None
        self._last_judge_text = ''
        self.residual_curve.setData([], [])
        self.worst_marker.setData([], [])
        self._apply_y_span(0.0)
        self.interval_outer.setData([], [])
        self.interval_inner.setData([], [])
        self._rename_interval_legend(self.interval_outer, INTERVAL_NAME_OUTER)
        self._rename_interval_legend(self.interval_inner, INTERVAL_NAME_INNER)
        self.interval_plot.setTitle(None)
        self._reset_interval_span()
        self.position_outer.setData([], [])
        self.position_inner.setData([], [])
        self.position_difference.setData([], [])
        self._rename_position_legend(self.position_outer, INTERVAL_NAME_OUTER)
        self._rename_position_legend(self.position_inner, INTERVAL_NAME_INNER)
        self.position_plot.setTitle(None)
        self.position_plot.setYRange(-0.5, 0.5, padding=0)
        self._reset_position.remember()
        for curve in (self.judge_front, self.judge_middle, self.judge_back,
                      self.judge_margin):
            curve.setData([], [])
        self.judge_failed.setData([], [])
        self.judge_boundary.setData([], [])
        self.judge_plot.setTitle(None)
        self.judge_plot.setYRange(-1.0, 1.0, padding=0)
        self._reset_judge.remember()
        for key in KPI_KEYS:
            self.kpi_labels[key].setText('--')
        self.kpi_labels['verdict'].setStyleSheet('')
        self.residual_legend.setVisible(False)
        self.interval_legend.setVisible(False)
        self.position_legend.setVisible(False)
        self.judge_legend.setVisible(False)
        self.status_label.setText('待解算')
        logger.info('双码道解算已清屏')
