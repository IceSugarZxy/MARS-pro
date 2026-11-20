# -*- coding: utf-8 -*-
"""双码道解算面板：磁场 CSV → 32/31 相位码 → B12 SPO 表 → 残差评级 → 磁编码器算法裕度。

界面在 `src/ui/dual_track_panel.ui`（uic 加载），本文件只负责状态与控制逻辑。
页面上只有一张图「磁编码器算法裕度」（CC01 实际过零节点三点判断），评级放在顶部 KPI 栏：

    d前 / d中 / d后 = T内[i] − T外[最近节点的前 / 中 / 后]
    H[i] = min(d前, d中, d后) − 0.036°
"""
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
    solve_pair,
)
from core.logger import get_logger
from core.path_utils import get_project_root
from core.zero_crossing import ZeroCrossingError, same_direction_intervals
from core.zero_node_judge import (LOWER_BOUND_DEG as ZERO_NODE_LOWER_BOUND,
                                  ZeroNodeError, judge_three_nodes)
from windows.csv_picker_dialog import pick_csv
from windows.plot_utils import DoubleClickReset

logger = get_logger('DualTrackPanel')

DLL_RELATIVE_PATH = os.path.join('vendor', 'iC-MU150', 'MU_3SL_INTERFACE_64.DLL')
KPI_KEYS = ('verdict', 'rmin', 'rmax', 'peak', 'margin', 'worst')
VERDICT_COLORS = {'pass': '#2e8b57', 'fail': '#c0392b', 'boundary': '#e0b23c'}
JUDGE_DEFAULT_SPAN = 1.0
# 超下限点位最多画多少条竖向标线（再多就只靠红点，避免糊成一片）
MAX_FAILED_MARKERS = 12


def default_dll_path():
    """默认 DLL 路径：源码运行时为项目根，打包运行时为 exe 同级。"""
    return os.path.join(get_project_root(), DLL_RELATIVE_PATH)


def group_prefix(file_path):
    """文件名里时间戳之前的部分，例如 1-外_20261118_145326.csv → 1-外。"""
    stem = os.path.splitext(os.path.basename(file_path))[0]
    parts = stem.rsplit('_', 2)
    return parts[0] if len(parts) == 3 else stem


class DualTrackPanel(QWidget):
    """双码道（32/31 游标）SPO 解算 + 磁编码器算法裕度页面。"""

    def __init__(self):
        super().__init__()

        ui_file_path = os.path.join(os.path.dirname(__file__), '..', 'ui',
                                    'dual_track_panel.ui')
        uic.loadUi(ui_file_path, self)

        self._result = None
        self._outer_path = ''
        self._inner_path = ''
        self._last_judge_text = ''
        self._last_judge_report = None
        self.kpi_labels = {key: getattr(self, f'kpi_value_{key}') for key in KPI_KEYS}

        self._init_judge_plot()
        self._connect_signals()
        self._apply_defaults()

    # ---------------------------------------------------------------- 初始化
    def _init_judge_plot(self):
        """磁编码器算法裕度图：内道每个起点的最小余量 H（差值下限 L=0.036° 已含在 H 里）。"""
        self.judge_plot = pg.PlotWidget()
        self.judge_plot.setBackground('#ffffff')
        self.judge_plot.showGrid(x=True, y=True, alpha=0.35)
        self.judge_plot.setLabel('bottom', '内道起点机械角', units='°')
        self.judge_plot.setLabel('left', '最小余量 H', units='°')
        self.judge_plot.plotItem.hideButtons()
        self.judge_legend = self.judge_plot.addLegend(offset=(10, 10))
        self.judge_legend.setVisible(False)
        self.judge_margin = self.judge_plot.plot(
            pen=pg.mkPen('#2c3e50', width=1.6), name='最小余量 H')
        self.judge_failed = pg.ScatterPlotItem(size=10, brush=pg.mkBrush('#c0392b'),
                                               pen=pg.mkPen('#7b241c'))
        self.judge_boundary = pg.ScatterPlotItem(size=8, brush=pg.mkBrush('#e0b23c'),
                                                 pen=pg.mkPen('#b7950b'))
        self.judge_plot.addItem(self.judge_failed)
        self.judge_plot.addItem(self.judge_boundary)
        self.judge_legend.addItem(self.judge_failed, '超下限点位')
        self._judge_markers = []  # 超下限点位上的竖向标线与角标
        self.judge_plot.addItem(pg.InfiniteLine(
            pos=0.0, angle=0, pen=pg.mkPen('#c0392b', width=1, style=Qt.SolidLine),
            label=f'判定线 H=0（插值下限 {ZERO_NODE_LOWER_BOUND:.3f}°）',
            labelOpts={'position': 0.995, 'anchors': ((1, 0), (1, 1)),
                       'color': '#c0392b'}))
        self.judge_grid.addWidget(self.judge_plot, 1, 0)
        self._reset_judge = DoubleClickReset(self.judge_plot)
        self._reset_judge_span()

    def _reset_judge_span(self):
        """磁编码器算法裕度图回到初始视窗。"""
        self.judge_plot.setXRange(0, 360, padding=0)
        self.judge_plot.setYRange(-JUDGE_DEFAULT_SPAN, JUDGE_DEFAULT_SPAN, padding=0)
        self._reset_judge.remember()

    def _track_intervals(self, result):
        """两条码道各自的同向过零结果（磁编码器算法裕度用）。"""
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

    def _show_judgement(self, result, data, errors):
        """磁编码器算法裕度：只画内道每个起点的最小余量 H。

        H[i] = min(d前, d中, d后) − L（L = 插值下限 0.036°）：H>0 通过、H<0 不通过、
        H=0 边界待核查；整盘取最小 H。判定规则见《CC01 实际过零节点三点判断_算法说明》。
        """
        self.judge_margin.setData([], [])
        self.judge_failed.setData([], [])
        self.judge_boundary.setData([], [])

        outer = data.get(MASTER_POLE_PAIRS)
        inner = data.get(NONIUS_POLE_PAIRS)
        if outer is None or inner is None:
            title = '；'.join(errors) if errors else '缺少某一码道的同向过零结果'
            self._last_judge_report = None
            self.judge_plot.setTitle('磁编码器算法裕度无法计算：' + title)
            self.judge_legend.setVisible(False)
            return ''

        try:
            report = judge_three_nodes(outer.cross_deg, outer.same_deg,
                                       inner.cross_deg, inner.same_deg)
        except ZeroNodeError as exc:
            self._last_judge_report = None
            self.judge_plot.setTitle('磁编码器算法裕度异常：' + str(exc))
            self.judge_legend.setVisible(False)
            return ''

        self._last_judge_report = report

        angle = inner.cross_deg
        margins = report['margins_deg']
        self.judge_margin.setPen(
            pg.mkPen(VERDICT_COLORS[report['judgement']], width=1.6))
        self.judge_margin.setData(angle, margins)
        if report['failed'].any():
            self.judge_failed.setData(angle[report['failed']],
                                      margins[report['failed']])
        else:
            self.judge_failed.setData([], [])
        if report['boundary'].any():
            self.judge_boundary.setData(angle[report['boundary']],
                                        margins[report['boundary']])
        else:
            self.judge_boundary.setData([], [])
        self._mark_failed_points(report)
        self.judge_legend.setVisible(True)
        self.judge_plot.setTitle(
            '%s：最小余量 %+.4f° @ %.3f°，不通过 %d/%d（%.1f%%）'
            % (report['judgement_text'], report['minimum_margin_deg'],
               report['worst_inner_angle_deg'], report['failed_count'],
               margins.size, report['failed_percent']))
        self.judge_plot.setXRange(0, 360, padding=0)

        low, high = float(margins.min()), float(margins.max())
        pad = max((high - low) * 0.15, 0.02)
        self.judge_plot.setYRange(min(low - pad, -pad), max(high + pad, pad),
                                  padding=0)
        self._reset_judge.remember()
        return ('磁编码器算法裕度%s，最小余量 %+.4f°（最差内道起点 %.3f°），不通过 %d/%d'
                % (report['judgement_text'], report['minimum_margin_deg'],
                   report['worst_inner_angle_deg'], report['failed_count'],
                   margins.size))

    def _mark_failed_points(self, report):
        """把超下限（H<0）的点位特别标出：竖向虚线 + 最差点的角标。"""
        for item in self._judge_markers:
            self.judge_plot.removeItem(item)
        self._judge_markers = []

        angles = report.get('failed_angles_deg')
        if angles is None:
            return
        for value in np.asarray(angles, dtype=float)[:MAX_FAILED_MARKERS]:
            line = pg.InfiniteLine(
                pos=float(value), angle=90,
                pen=pg.mkPen('#c0392b', width=1, style=Qt.DashLine))
            self.judge_plot.addItem(line)
            self._judge_markers.append(line)

        if report['failed_count']:
            label = pg.TextItem(
                '%.3f°  %+.4f°' % (report['worst_inner_angle_deg'],
                                   report['minimum_margin_deg']),
                color='#c0392b', anchor=(0.5, 1.2))
            label.setPos(float(report['worst_inner_angle_deg']),
                         float(report['minimum_margin_deg']))
            self.judge_plot.addItem(label)
            self._judge_markers.append(label)

    def _connect_signals(self):
        self.btn_pick_outer.clicked.connect(self._pick_outer)
        self.btn_pick_inner.clicked.connect(self._pick_inner)
        self.btn_solve.clicked.connect(self._on_solve)
        self.btn_clear.clicked.connect(self._on_clear)

    def _apply_defaults(self):
        dll = default_dll_path()
        if not os.path.exists(dll):
            logger.warning(f'未找到原厂 DLL: {dll}')
            self.judge_plot.setTitle(
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
            self.judge_plot.setTitle(message)
            QMessageBox.warning(self, '双码道解算', message)
            return

        mode = DEFAULT_MODE
        self.btn_solve.setEnabled(False)
        self.setCursor(Qt.WaitCursor)
        try:
            result = solve_pair(outer, inner, dll, mode)
        except DualTrackError as exc:
            logger.warning(f'双码道解算失败: {exc}')
            QMessageBox.warning(self, '双码道解算失败', str(exc))
            self.judge_plot.setTitle('解算失败：' + str(exc))
            return
        except Exception as exc:  # 未预期错误也要给用户可读提示
            logger.exception(f'双码道解算异常: {exc}')
            QMessageBox.critical(self, '双码道解算异常', str(exc))
            self.judge_plot.setTitle('解算异常：' + str(exc))
            return
        finally:
            self.btn_solve.setEnabled(True)
            self.unsetCursor()

        self._result = result
        self._show_result(result)
        summary = result.summary()
        logger.info(f'双码道解算完成: {os.path.basename(outer)} / {os.path.basename(inner)} '
                    f'模式={mode} R={summary["r_min"]}~{summary["r_max"]} '
                    f'{self._last_judge_text}')

    def _show_result(self, result):
        """刷新顶部评级 KPI 与磁编码器算法裕度图。

        结论（KPI 第一格）按「波形是否超下限」给：有任一 H<0 → 不良，否则合格；
        R 最小/最大/峰值占用/最小裕量/最差点角 仍是 MU150 残差评级数据。
        """
        data, errors = self._track_intervals(result)
        self._last_judge_text = self._show_judgement(result, data, errors)
        report = self._last_judge_report

        if report is None:
            self.kpi_labels['verdict'].setText('--')
            self.kpi_labels['verdict'].setStyleSheet('')
        else:
            verdict = '不良' if report['failed_count'] else '合格'
            self.kpi_labels['verdict'].setText(verdict)
            self.kpi_labels['verdict'].setStyleSheet(
                'color: %s; font-weight: 700;'
                % ('#c0392b' if verdict == '不良' else '#2e8b57'))

        summary = result.summary()
        self.kpi_labels['rmin'].setText(f'{summary["r_min"]:+d}')
        self.kpi_labels['rmax'].setText(f'{summary["r_max"]:+d}')
        self.kpi_labels['peak'].setText(f'{summary["peak"]}')
        self.kpi_labels['margin'].setText(f'{summary["margin_codes"]}')
        self.kpi_labels['worst'].setText(f'{summary["worst_angle_deg"]:.3f}')

    def _on_clear(self):
        """清屏：清空裕度曲线与评级，保留已选数据。"""
        self._result = None
        self._last_judge_text = ''
        self.judge_margin.setData([], [])
        self.judge_failed.setData([], [])
        self.judge_boundary.setData([], [])
        for item in self._judge_markers:
            self.judge_plot.removeItem(item)
        self._judge_markers = []
        self.judge_plot.setTitle(None)
        self._reset_judge_span()
        self._last_judge_report = None
        for key in KPI_KEYS:
            self.kpi_labels[key].setText('--')
        self.kpi_labels['verdict'].setStyleSheet('')
        self.judge_legend.setVisible(False)
        logger.info('双码道解算已清屏')
