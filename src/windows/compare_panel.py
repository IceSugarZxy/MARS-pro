# -*- coding: utf-8 -*-
"""数据比对面板 - 从 compare_panel.ui 加载。

流程：列表勾选（最多 5 条）→ 波形叠加预览 → 「分析比对」后台重算后弹出四标签页对话框。
"""

import os
import queue

import numpy as np
import pyqtgraph as pg
from pyqtgraph import mkPen
from PyQt5 import uic
from PyQt5.QtCore import QEvent, Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import (QAbstractItemView, QDialog, QHeaderView, QLabel,
                             QLineEdit, QMessageBox, QProgressDialog,
                             QPushButton, QTableWidget, QTableWidgetItem,
                             QVBoxLayout, QWidget)

from core.defect_fingerprint import MAX_RUNS, PALETTE, analyze_runs, compare_stats
from core.logger import get_logger
from core.path_utils import get_data_dir
from core.plot_data_reader import (TABLE_COLUMNS, read_plot_csv,
                                   scan_plot_data_records)
from windows.fingerprint_dialog import FingerprintResultDialog

logger = get_logger('ComparePanel')

MAX_PREVIEW = MAX_RUNS          # 预览上限与勾选上限一致
CHECK_COLUMN = 0


class LoadRecordsThread(QThread):
    """后台扫描 plot_data 下所有数据文件（只读元信息）。"""

    loaded = pyqtSignal(list)

    def __init__(self, plot_data_dir, parent=None):
        super().__init__(parent)
        self.plot_data_dir = plot_data_dir

    def run(self):
        try:
            records = scan_plot_data_records(self.plot_data_dir)
        except Exception as exc:
            logger.warning(f"扫描 plot_data 失败: {exc}")
            records = []
        self.loaded.emit(records)


class CurveLoadThread(QThread):
    """一次性读取单条数据的波形（避免勾选时界面卡顿）。"""

    curve_ready = pyqtSignal(str, object, object)

    def __init__(self, path, parent=None):
        super().__init__(parent)
        self.path = path

    def run(self):
        try:
            _info, angle, mag = read_plot_csv(self.path)
        except Exception as exc:
            logger.warning(f"读取波形失败 {self.path}: {exc}")
            angle, mag = [], []
        self.curve_ready.emit(self.path, angle, mag)


class AnalysisThread(QThread):
    """后台按软件同一套处理链重算各轮并做对齐统计。"""

    progress = pyqtSignal(int, int, str)
    completed = pyqtSignal(object, object)
    failed = pyqtSignal(str)
    cancelled = pyqtSignal()

    def __init__(self, paths, parent=None):
        super().__init__(parent)
        self.paths = list(paths)
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            from core.data_process import DataProcess
            from windows.wave_analysis import WaveAnalysis

            proc = DataProcess(queue.Queue())
            analyzer = WaveAnalysis()
            runs, failed_runs, was_cancelled = analyze_runs(
                self.paths,
                proc,
                analyzer,
                progress_cb=lambda done, total, label: self.progress.emit(done, total, label),
                cancel_cb=lambda: self._cancel,
            )
        except Exception as exc:
            logger.error(f"分析比对失败: {exc}")
            self.failed.emit(str(exc))
            return

        if was_cancelled:
            self.cancelled.emit()
            return
        self.completed.emit(runs, failed_runs)


class ComparePanel(QWidget):
    """数据比对面板 - 从 compare_panel.ui 加载。"""

    def __init__(self):
        super().__init__()

        ui_file_path = os.path.join(os.path.dirname(__file__), "..", "ui", "compare_panel.ui")
        uic.loadUi(ui_file_path, self)

        # 全部记录 / 已勾选记录（按勾选顺序）
        self._records = []
        self._record_by_path = {}
        self._checked = {}
        self._check_order = []

        # 已加载的预览波形 {path: (angle, mag)}
        self._curves = {}
        self._pending_paths = set()
        self._populating = False

        self._load_thread = None
        self._curve_threads = []
        self._analysis_thread = None
        self._progress_dialog = None
        self._result_dialogs = []

        self._init_plot_widget()
        self._setup_table()
        self._connect_buttons()

        logger.info("ComparePanel 初始化完成")

    # ================================================================ 初始化
    def _init_plot_widget(self):
        placeholder = self.findChild(QLabel, "plot_placeholder")
        if not placeholder:
            return

        self.plot_widget = pg.PlotWidget(useOpenGL=True)
        self.plot_widget.setBackground('#ffffff')
        self.plot_widget.showGrid(x=True, y=True, alpha=0.5)
        self.plot_widget.enableAutoRange(False, False)
        self.plot_widget.plotItem.setClipToView(True)
        self.plot_widget.setDownsampling(auto=True, mode='peak')
        self.plot_widget.setXRange(0, 360, padding=0)
        self.plot_widget.setYRange(-70, 70)
        self.plot_widget.plotItem.setLabel('bottom', '角度', units='°')
        self.plot_widget.plotItem.setLabel('left', '磁场', units='mT')
        self.plot_widget.addLegend(offset=(10, 10))
        self.plot_widget.scene().installEventFilter(self)

        parent = placeholder.parent()
        layout = parent.layout() if parent else None
        if layout:
            index = layout.indexOf(placeholder)
            if index >= 0:
                layout.removeWidget(placeholder)
                placeholder.close()
                layout.insertWidget(index, self.plot_widget)

    def _setup_table(self):
        table = self.findChild(QTableWidget, "data_table")
        if not table:
            return
        table.setRowCount(0)
        table.verticalHeader().setVisible(False)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        header = table.horizontalHeader()
        header.setSectionResizeMode(CHECK_COLUMN, QHeaderView.Fixed)
        table.setColumnWidth(CHECK_COLUMN, 64)
        for column in range(1, table.columnCount()):
            header.setSectionResizeMode(column, QHeaderView.Stretch)
        table.itemChanged.connect(self._on_item_changed)

    def _connect_buttons(self):
        refresh = self.findChild(QPushButton, "btn_refresh")
        if refresh:
            refresh.clicked.connect(self.refresh)
        select_all = self.findChild(QPushButton, "btn_select_all")
        if select_all:
            select_all.clicked.connect(self._on_select_all)
        clear = self.findChild(QPushButton, "btn_clear")
        if clear:
            # clicked 信号会附带一个 bool；_on_clear_checked 的第二个参数是 redraw，
            # 直接被 Qt 透传会把 False 当成 redraw，导致清空后预览不重绘，故用 lambda 吞掉。
            clear.clicked.connect(lambda: self._on_clear_checked())
        analyze = self.findChild(QPushButton, "analyze_btn")
        if analyze:
            analyze.clicked.connect(self._on_analyze)

        for name in ("sample_name_edit", "tester_edit", "polar_num_edit",
                     "airgap_edit", "sample_code_edit"):
            edit = self.findChild(QLineEdit, name)
            if edit:
                edit.textChanged.connect(self._on_search_changed)

    def showEvent(self, event):
        """每次打开数据比对界面时刷新列表（同时清空搜索条件）。"""
        super().showEvent(event)
        if not self._records:
            self.refresh()

    # ================================================================ 列表加载
    def refresh(self):
        """清空筛选条件并重新扫描列表（勾选状态保留仍存在的文件）。"""
        for name in ("sample_name_edit", "tester_edit", "polar_num_edit",
                     "airgap_edit", "sample_code_edit"):
            edit = self.findChild(QLineEdit, name)
            if edit:
                edit.setText("")

        if self._load_thread and self._load_thread.isRunning():
            logger.info("数据列表正在加载中，跳过重复刷新")
            return

        plot_data_dir = get_data_dir("plot_data")
        if not os.path.exists(plot_data_dir):
            os.makedirs(plot_data_dir, exist_ok=True)

        self._set_status("正在读取数据列表…")
        self._load_thread = LoadRecordsThread(plot_data_dir, self)
        self._load_thread.loaded.connect(self._on_records_loaded)
        self._load_thread.finished.connect(self._on_load_thread_finished)
        self._load_thread.start()

    def _on_load_thread_finished(self):
        self._load_thread = None

    def _on_records_loaded(self, records):
        self._records = list(records or [])
        self._record_by_path = {r['file_path']: r for r in self._records}
        self._populate_table(self._records)
        self._set_status("共 %d 条数据，已勾选 %d/%d 条"
                         % (len(self._records), len(self._checked), MAX_RUNS))
        logger.info(f"数据列表加载完成，共 {len(self._records)} 条")

    def _populate_table(self, records):
        """填充表格（首列勾选框，其后为主列）。"""
        table = self.findChild(QTableWidget, "data_table")
        if not table:
            return

        self._populating = True
        try:
            table.setRowCount(0)
            for record in records:
                row = table.rowCount()
                table.insertRow(row)

                path = record.get('file_path', '')
                check_item = QTableWidgetItem()
                check_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled
                                    | Qt.ItemIsSelectable)
                check_item.setCheckState(Qt.Checked if path in self._checked else Qt.Unchecked)
                check_item.setData(Qt.UserRole, path)
                table.setItem(row, CHECK_COLUMN, check_item)

                for offset, field in enumerate(TABLE_COLUMNS):
                    item = QTableWidgetItem(str(record.get(field, '') or ''))
                    item.setData(Qt.UserRole, path)
                    table.setItem(row, CHECK_COLUMN + 1 + offset, item)
        finally:
            self._populating = False

    def _on_search_changed(self):
        """按筛选条件重填表格（勾选状态保留）。"""
        if not self._records:
            return

        def text(name):
            edit = self.findChild(QLineEdit, name)
            return edit.text().strip() if edit else ""

        sample = text("sample_name_edit").lower()
        tester = text("tester_edit").lower()
        polar = text("polar_num_edit")
        airgap = text("airgap_edit")
        code = text("sample_code_edit").lower()

        filtered = []
        for record in self._records:
            if sample and sample not in str(record.get('sample_name', '')).lower():
                continue
            if tester and tester not in str(record.get('tester', '')).lower():
                continue
            if polar and polar not in str(record.get('polar_num', '')):
                continue
            if airgap and airgap not in str(record.get('airgap', '')):
                continue
            if code and code not in str(record.get('sample_code', '')).lower():
                continue
            filtered.append(record)

        self._populate_table(filtered)
        self._set_status("筛选结果 %d 条，已勾选 %d/%d 条"
                         % (len(filtered), len(self._checked), MAX_RUNS))

    # ================================================================ 勾选
    def _on_item_changed(self, item):
        if self._populating or item.column() != CHECK_COLUMN:
            return

        path = item.data(Qt.UserRole)
        if not path:
            return

        checked = item.checkState() == Qt.Checked
        if checked:
            if path in self._checked:
                return
            if len(self._checked) >= MAX_RUNS:
                self._set_item_checked(item, False)
                self._set_status("最多只能勾选 %d 条，请先取消其它勾选" % MAX_RUNS)
                QMessageBox.information(self, "提示",
                                        "最多只能勾选 %d 条数据，请先取消其它勾选。" % MAX_RUNS)
                return
            record = self._record_by_path.get(path)
            if not record:
                return
            self._checked[path] = record
            self._check_order.append(path)
            self._request_curve(path)
        else:
            if path not in self._checked:
                return
            self._checked.pop(path, None)
            if path in self._check_order:
                self._check_order.remove(path)
            self._curves.pop(path, None)
            self._redraw_preview()

        self._set_status("已勾选 %d/%d 条" % (len(self._checked), MAX_RUNS))

    def _set_item_checked(self, item, checked):
        """回滚勾选状态（避免触发 itemChanged 递归）。"""
        self._populating = True
        try:
            item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
        finally:
            self._populating = False

    def _on_select_all(self):
        """勾选当前筛选结果里时间最新的 MAX_RUNS 条。"""
        table = self.findChild(QTableWidget, "data_table")
        if not table or table.rowCount() == 0:
            self._set_status("列表为空，没有可勾选的数据")
            return

        self._on_clear_checked(redraw=False)
        # 先清空预览，避免旧曲线在新波形加载完成前残留
        self._redraw_preview()
        selected = 0
        self._populating = True
        try:
            for row in range(table.rowCount()):
                if selected >= MAX_RUNS:
                    break
                item = table.item(row, CHECK_COLUMN)
                path = item.data(Qt.UserRole) if item else None
                if not path or path in self._checked:
                    continue
                record = self._record_by_path.get(path)
                if not record:
                    continue
                item.setCheckState(Qt.Checked)
                self._checked[path] = record
                self._check_order.append(path)
                selected += 1
        finally:
            self._populating = False

        for path in list(self._check_order):
            self._request_curve(path)
        self._set_status("已勾选 %d/%d 条（按筛选结果中时间最新的数据）"
                         % (len(self._checked), MAX_RUNS))

    def _on_clear_checked(self, redraw=True):
        table = self.findChild(QTableWidget, "data_table")
        self._populating = True
        try:
            if table:
                for row in range(table.rowCount()):
                    item = table.item(row, CHECK_COLUMN)
                    if item and item.checkState() == Qt.Checked:
                        item.setCheckState(Qt.Unchecked)
        finally:
            self._populating = False

        self._checked.clear()
        self._check_order.clear()
        self._curves.clear()
        if redraw:
            self._redraw_preview()
            self._set_status("已清空勾选")

    # ================================================================ 预览
    def _request_curve(self, path):
        if path in self._curves or path in self._pending_paths:
            return
        self._pending_paths.add(path)
        thread = CurveLoadThread(path, self)
        thread.curve_ready.connect(self._on_curve_ready)
        thread.finished.connect(lambda p=path: self._on_curve_thread_finished(p))
        self._curve_threads.append(thread)
        thread.start()

    def _on_curve_thread_finished(self, path):
        self._pending_paths.discard(path)
        self._curve_threads = [t for t in self._curve_threads if t.isRunning()]

    def _on_curve_ready(self, path, angle, mag):
        if path not in self._checked:
            return
        if not angle or not mag:
            self._set_status("读取波形失败：%s" % os.path.basename(path))
            return
        self._curves[path] = (angle, mag)
        self._redraw_preview()

    def _redraw_preview(self):
        if not hasattr(self, 'plot_widget'):
            return

        self.plot_widget.clear()
        legend = self.plot_widget.plotItem.legend
        if legend is not None:
            legend.clear()

        drawn = 0
        all_values = []
        for index, path in enumerate(self._check_order[:MAX_PREVIEW]):
            curve = self._curves.get(path)
            if not curve:
                continue
            angle, mag = curve
            count = min(len(angle), len(mag))
            if count <= 0:
                continue
            record = self._checked.get(path, {})
            label = "%s %s" % (record.get('sample_name', ''),
                               os.path.basename(path).split('_')[-1].replace('.csv', ''))
            self.plot_widget.plot(angle[:count], mag[:count],
                                  pen=mkPen(PALETTE[index % len(PALETTE)], width=1.2),
                                  name=label)
            all_values.extend(mag[:count])
            drawn += 1

        if all_values:
            values = np.asarray(all_values, dtype=float)
            lo, hi = float(np.nanmin(values)), float(np.nanmax(values))
            margin = max((hi - lo) * 0.1, 1.0)
            self.plot_widget.setYRange(lo - margin, hi + margin, padding=0)
        self.plot_widget.setXRange(0, 360, padding=0)

        if drawn:
            self._set_status("预览 %d 条，已勾选 %d/%d 条"
                             % (drawn, len(self._checked), MAX_RUNS))

    def eventFilter(self, obj, event):
        """双击预览区域，在独立窗口查看已勾选的全部曲线。"""
        if hasattr(self, 'plot_widget') and obj == self.plot_widget.scene():
            if event.type() == QEvent.GraphicsSceneMouseDoubleClick:
                self._on_plot_double_click()
                return True
        return super().eventFilter(obj, event)

    def _on_plot_double_click(self):
        if not self._check_order:
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("波形对比")
        dialog.resize(1000, 600)
        dialog.setAttribute(Qt.WA_DeleteOnClose)

        full_plot = pg.PlotWidget(useOpenGL=True)
        full_plot.setBackground('#ffffff')
        full_plot.showGrid(x=True, y=True, alpha=0.5)
        full_plot.setXRange(0, 360, padding=0)
        full_plot.plotItem.setLabel('bottom', '角度', units='°')
        full_plot.plotItem.setLabel('left', '磁场', units='mT')
        full_plot.plotItem.setClipToView(True)
        full_plot.setDownsampling(auto=True, mode='peak')
        full_plot.addLegend(offset=(10, 10))

        all_values = []
        for index, path in enumerate(self._check_order[:MAX_PREVIEW]):
            curve = self._curves.get(path)
            if not curve:
                continue
            angle, mag = curve
            count = min(len(angle), len(mag))
            if count <= 0:
                continue
            record = self._checked.get(path, {})
            label = "%s %s" % (record.get('sample_name', ''),
                               os.path.basename(path).split('_')[-1].replace('.csv', ''))
            full_plot.plot(angle[:count], mag[:count],
                           pen=mkPen(PALETTE[index % len(PALETTE)], width=1.2),
                           name=label)
            all_values.extend(mag[:count])

        if all_values:
            values = np.asarray(all_values, dtype=float)
            lo, hi = float(np.nanmin(values)), float(np.nanmax(values))
            margin = max((hi - lo) * 0.1, 1.0)
            full_plot.setYRange(lo - margin, hi + margin, padding=0)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(full_plot)
        dialog.showMaximized()

    # ================================================================ 分析比对
    def _on_analyze(self):
        paths = [p for p in self._check_order if p in self._checked]
        if len(paths) < 2:
            QMessageBox.warning(self, "提示", "请至少勾选 2 条数据后再分析比对。")
            return
        if len(paths) > MAX_RUNS:
            QMessageBox.warning(self, "提示",
                                "最多只能比对 %d 条数据，请先取消多余的勾选。" % MAX_RUNS)
            return
        if self._analysis_thread and self._analysis_thread.isRunning():
            QMessageBox.information(self, "提示", "上一次分析还在进行中，请稍候。")
            return

        # 预校验：CSV 元信息里都填了极数时先比一遍，避免白跑
        polars = {}
        for path in paths:
            value = str(self._checked[path].get('polar_num', '') or '').strip()
            if value:
                polars[path] = value
        if len(polars) == len(paths) and len(set(polars.values())) > 1:
            detail = "\n".join("%s：极数 %s" % (os.path.basename(p), polars[p]) for p in paths)
            QMessageBox.warning(self, "极数不一致",
                                "勾选的数据极数不一致，无法比对：\n\n" + detail)
            return

        # 基准轮 = 时间最早的一轮
        ordered = sorted(paths, key=lambda p: str(self._checked[p].get('save_time') or ''))
        self._start_analysis(ordered)

    def _start_analysis(self, paths):
        logger.info(f"开始分析比对: {[os.path.basename(p) for p in paths]}")

        dialog = QProgressDialog("正在分析数据…", "取消", 0, len(paths), self)
        dialog.setWindowTitle("分析比对")
        dialog.setWindowModality(Qt.WindowModal)
        dialog.setMinimumDuration(0)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        dialog.setValue(0)
        self._progress_dialog = dialog

        button = self.findChild(QPushButton, "analyze_btn")
        if button:
            button.setEnabled(False)

        thread = AnalysisThread(paths, self)
        thread.progress.connect(self._on_analysis_progress)
        thread.completed.connect(self._on_analysis_completed)
        thread.failed.connect(self._on_analysis_failed)
        thread.cancelled.connect(self._on_analysis_cancelled)
        thread.finished.connect(self._on_analysis_thread_finished)
        dialog.canceled.connect(thread.cancel)
        self._analysis_thread = thread
        thread.start()

    def _on_analysis_thread_finished(self):
        self._analysis_thread = None
        button = self.findChild(QPushButton, "analyze_btn")
        if button:
            button.setEnabled(True)

    def _on_analysis_progress(self, done, total, label):
        # 注意：QProgressDialog.setValue() 内部会处理事件，可能在此期间收到
        # “分析完成”信号并把 _progress_dialog 置空，因此这里用局部引用。
        dialog = self._progress_dialog
        if dialog is None:
            return
        dialog.setValue(done)
        dialog.setLabelText("正在分析数据…（%d/%d）%s" % (done, total, label))

    def _close_progress(self):
        dialog = self._progress_dialog
        self._progress_dialog = None
        if dialog is None:
            return
        # 关闭进度框会触发 canceled，先断开，避免误取消/误报
        try:
            dialog.canceled.disconnect()
        except TypeError:
            pass
        dialog.setValue(dialog.maximum())
        dialog.close()

    def _on_analysis_cancelled(self):
        self._close_progress()
        self._set_status("分析比对已取消")
        logger.info("分析比对已取消")

    def _on_analysis_failed(self, message):
        self._close_progress()
        self._set_status("分析比对失败")
        QMessageBox.warning(self, "错误", "分析比对失败：%s" % message)

    def _on_analysis_completed(self, runs, failed_runs):
        self._close_progress()

        if failed_runs:
            detail = "\n".join("%s：%s" % (os.path.basename(r['path']), r.get('error', '失败'))
                               for r in failed_runs)
            QMessageBox.information(self, "部分数据未参与比对",
                                    "以下数据无法参与比对，已自动剔除：\n\n" + detail)

        if len(runs) < 2:
            self._set_status("有效数据不足 2 轮，已放弃比对")
            QMessageBox.warning(self, "提示", "有效数据不足 2 轮，无法比对。")
            return

        poles = sorted({r['pole_pairs'] for r in runs})
        if len(poles) > 1:
            detail = "\n".join("%s：%d 极对" % (r['label'], r['pole_pairs']) for r in runs)
            self._set_status("极对数不一致，已放弃比对")
            QMessageBox.warning(self, "极对数不一致",
                                "勾选数据的极对数不一致，无法比对：\n\n" + detail)
            return

        stats = compare_stats(runs)
        self._set_status("比对完成：%d 轮，极对数 %d" % (len(runs), runs[0]['pole_pairs']))
        logger.info(f"分析比对完成: {len(runs)} 轮，极对数 {runs[0]['pole_pairs']}，"
                    f"转角 {[round(v, 1) for v in stats.get('rotations', [])]}")

        dialog = FingerprintResultDialog(runs, stats, self)
        self._result_dialogs.append(dialog)
        dialog.finished.connect(
            lambda _result, d=dialog: self._remove_result_dialog(d))
        dialog.show()

    def _remove_result_dialog(self, dialog):
        if dialog in self._result_dialogs:
            self._result_dialogs.remove(dialog)

    # ================================================================ 杂项
    def _set_status(self, message):
        label = self.findChild(QLabel, "status_label")
        if label:
            label.setText(message)
