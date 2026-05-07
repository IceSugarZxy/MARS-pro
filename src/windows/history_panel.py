# -*- coding: utf-8 -*-
"""
历史数据面板 - 从 history_panel.ui 加载
"""

import os
import glob
import re
import csv
from datetime import datetime
from PyQt5.QtWidgets import (QWidget, QLabel, QPushButton, QTableWidget,
                              QTableWidgetItem, QLineEdit, QRadioButton,
                              QHeaderView, QHBoxLayout, QMessageBox)
from PyQt5.QtCore import Qt, pyqtSignal, QThread
from PyQt5 import uic
from core.logger import get_logger
from core.path_utils import get_data_dir

logger = get_logger('HistoryPanel')


def _read_plot_csv(file_path):
    """Read saved plot CSV metadata and waveform data."""
    sample_info = {}
    angle_data = []
    mag_data = []

    with open(file_path, 'r', encoding='utf-8') as f:
        rows = list(csv.reader(f))

    data_started = False
    for row in rows:
        if len(row) >= 2 and "角度" in row[0] and "磁场" in row[1]:
            data_started = True
            continue

        if not data_started:
            if len(row) < 2:
                continue

            key = row[0].strip()
            value = row[1].strip()
            if "样品名称" in key:
                sample_info['sample_name'] = value
            elif "样品编号" in key:
                sample_info['sample_code'] = value
            elif "材料" in key:
                sample_info['material'] = value
            elif "线圈编号" in key:
                sample_info['coil_code'] = value
            elif "备注" in key:
                sample_info['remark'] = value
            elif "保存时间" in key:
                sample_info['save_time'] = value
            elif "极数" in key:
                sample_info['polar_num'] = value
            elif "气隙" in key:
                sample_info['airgap'] = value
            elif "测试员" in key:
                sample_info['tester'] = value
            elif "磁化条件" in key:
                sample_info['mag_condition'] = value
            elif "探头" in key:
                sample_info['probe'] = value
            continue

        if len(row) >= 2 and row[0].strip():
            try:
                angle_data.append(float(row[0].strip()))
                mag_data.append(float(row[1].strip()))
            except (ValueError, IndexError):
                continue

    return sample_info, angle_data, mag_data


class LoadHistoryThread(QThread):
    """后台加载历史数据的线程"""
    finished = pyqtSignal(list)  # 加载完成信号，携带记录列表

    def __init__(self, plot_data_dir, parent=None):
        super().__init__(parent)
        self.plot_data_dir = plot_data_dir

    def run(self):
        """后台加载历史数据"""
        records = []

        csv_files = glob.glob(os.path.join(self.plot_data_dir, "*.csv"))
        csv_files.sort(key=lambda x: os.path.getmtime(x), reverse=True)

        for file_path in csv_files:
            filename = os.path.basename(file_path)
            # 解析文件名：样品名称_时间戳.csv
            match = re.match(r"(.+?)_(\d{8}_\d{6})\.csv", filename)
            if match:
                sample_name = match.group(1)
                timestamp_str = match.group(2)
                try:
                    timestamp = datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S")
                    time_str = timestamp.strftime("%Y-%m-%d %H:%M:%S")
                except:
                    time_str = timestamp_str

                try:
                    sample_info, _, _ = _read_plot_csv(file_path)
                except Exception as e:
                    logger.warning(f"读取CSV头信息失败: {e}")
                    sample_info = {}

                sample_name = sample_info.get('sample_name', sample_name)
                time_str = sample_info.get('save_time', time_str)

                record = {
                    'sample_name': sample_name,
                    'time_str': time_str,
                    'polar_num': sample_info.get('polar_num', ''),
                    'airgap': sample_info.get('airgap', ''),
                    'remark': sample_info.get('remark', ''),
                    'tester': sample_info.get('tester', ''),
                    'file_path': file_path
                }
                records.append(record)

        self.finished.emit(records)


class HistoryPanel(QWidget):
    """历史数据面板 - 从 history_panel.ui 加载"""

    # 信号：请求切换到测量面板并加载历史数据
    signal_load_history = pyqtSignal(str)  # 文件路径

    def __init__(self):
        super().__init__()

        # 加载 UI
        ui_file_path = os.path.join(os.path.dirname(__file__), "..", "ui", "history_panel.ui")
        uic.loadUi(ui_file_path, self)

        # 存储所有历史记录数据
        self._all_records = []

        # 后台加载线程
        self._load_thread = None

        # 连接按钮事件
        self._connect_buttons()

        # 设置表格
        self._setup_table()

        # 后台加载历史数据
        self._start_load_history()

        logger.info("HistoryPanel 初始化完成")

    def _connect_buttons(self):
        """连接按钮事件"""
        self.findChild(QPushButton, "btn_refresh").clicked.connect(self._on_refresh)
        self.findChild(QPushButton, "btn_open").clicked.connect(self._on_open)

        # 连接搜索输入框的文本变化事件
        sample_name_edit = self.findChild(QLineEdit, "sample_name_edit")
        if sample_name_edit:
            sample_name_edit.textChanged.connect(self._on_search_changed)

        tester_edit = self.findChild(QLineEdit, "tester_edit")
        if tester_edit:
            tester_edit.textChanged.connect(self._on_search_changed)

        polar_num_edit = self.findChild(QLineEdit, "polar_num_edit")
        if polar_num_edit:
            polar_num_edit.textChanged.connect(self._on_search_changed)

        airgap_edit = self.findChild(QLineEdit, "airgap_edit")
        if airgap_edit:
            airgap_edit.textChanged.connect(self._on_search_changed)

    def _setup_table(self):
        """设置表格"""
        table = self.findChild(QTableWidget, "data_table")
        if table:
            header = table.horizontalHeader()
            if header:
                header.setSectionResizeMode(QHeaderView.Stretch)
            table.setSelectionBehavior(QTableWidget.SelectRows)
            table.setEditTriggers(QTableWidget.NoEditTriggers)
            # 连接双击事件
            table.itemDoubleClicked.connect(self._on_table_double_clicked)

    def _get_plot_data_dir(self):
        """获取plot_data目录路径"""
        return get_data_dir("plot_data")

    def _start_load_history(self):
        """启动后台加载历史数据"""
        plot_data_dir = self._get_plot_data_dir()
        logger.info(f"后台加载历史数据目录: {plot_data_dir}")

        if not os.path.exists(plot_data_dir):
            os.makedirs(plot_data_dir, exist_ok=True)
            logger.info(f"创建目录: {plot_data_dir}")

        # 先清空表格
        table = self.findChild(QTableWidget, "data_table")
        if table:
            table.setRowCount(0)
        self._all_records.clear()

        # 启动后台线程
        self._load_thread = LoadHistoryThread(plot_data_dir, self)
        self._load_thread.finished.connect(self._on_load_history_finished)
        self._load_thread.start()

    def _on_load_history_finished(self, records):
        """后台加载完成，填充表格"""
        logger.info(f"后台加载完成，共 {len(records)} 条记录")

        table = self.findChild(QTableWidget, "data_table")
        if not table:
            return

        self._all_records = records

        for record in records:
            row = table.rowCount()
            table.insertRow(row)
            item_sample = QTableWidgetItem(record['sample_name'])
            item_sample.setData(Qt.UserRole, record['file_path'])
            table.setItem(row, 0, item_sample)
            table.setItem(row, 1, QTableWidgetItem(record['time_str']))
            table.setItem(row, 2, QTableWidgetItem(record['tester']))
            table.setItem(row, 3, QTableWidgetItem(record['polar_num']))
            table.setItem(row, 4, QTableWidgetItem(record['airgap']))
            table.setItem(row, 5, QTableWidgetItem(record['remark']))

        logger.info(f"填充了 {len(records)} 条历史记录到表格")
        self._load_thread = None

    def _on_search_changed(self):
        """搜索条件变化，执行筛选"""
        table = self.findChild(QTableWidget, "data_table")
        if not table:
            return

        # 获取搜索条件
        sample_name_edit = self.findChild(QLineEdit, "sample_name_edit")
        tester_edit = self.findChild(QLineEdit, "tester_edit")
        polar_num_edit = self.findChild(QLineEdit, "polar_num_edit")
        airgap_edit = self.findChild(QLineEdit, "airgap_edit")

        search_sample = sample_name_edit.text().strip().lower() if sample_name_edit else ""
        search_tester = tester_edit.text().strip().lower() if tester_edit else ""
        search_polar = polar_num_edit.text().strip() if polar_num_edit else ""
        search_airgap = airgap_edit.text().strip() if airgap_edit else ""

        # 筛选记录
        filtered_records = []
        for record in self._all_records:
            # 样品名称筛选
            if search_sample and search_sample not in record['sample_name'].lower():
                continue
            # 测试员筛选
            if search_tester and search_tester not in record['tester'].lower():
                continue
            # 极数筛选
            if search_polar and search_polar not in record['polar_num']:
                continue
            # 气隙筛选
            if search_airgap and search_airgap not in record['airgap']:
                continue

            filtered_records.append(record)

        # 更新表格
        table.setRowCount(0)
        for record in filtered_records:
            row = table.rowCount()
            table.insertRow(row)
            item_sample = QTableWidgetItem(record['sample_name'])
            item_sample.setData(Qt.UserRole, record['file_path'])
            table.setItem(row, 0, item_sample)
            table.setItem(row, 1, QTableWidgetItem(record['time_str']))
            table.setItem(row, 2, QTableWidgetItem(record['tester']))
            table.setItem(row, 3, QTableWidgetItem(record['polar_num']))
            table.setItem(row, 4, QTableWidgetItem(record['airgap']))
            table.setItem(row, 5, QTableWidgetItem(record['remark']))

        logger.info(f"筛选结果: {len(filtered_records)} 条记录")

    def _on_refresh(self):
        """刷新列表"""
        logger.info("刷新历史数据列表")
        # 清空搜索条件
        sample_name_edit = self.findChild(QLineEdit, "sample_name_edit")
        tester_edit = self.findChild(QLineEdit, "tester_edit")
        polar_num_edit = self.findChild(QLineEdit, "polar_num_edit")
        airgap_edit = self.findChild(QLineEdit, "airgap_edit")

        if sample_name_edit:
            sample_name_edit.setText("")
        if tester_edit:
            tester_edit.setText("")
        if polar_num_edit:
            polar_num_edit.setText("")
        if airgap_edit:
            airgap_edit.setText("")

        self._start_load_history()

    def _on_table_double_clicked(self, item):
        """表格双击事件"""
        table = self.findChild(QTableWidget, "data_table")
        if not table:
            return

        row = item.row()
        file_path = table.item(row, 0).data(Qt.UserRole)
        if not file_path or not os.path.exists(file_path):
            QMessageBox.warning(self, "错误", "文件不存在")
            return

        logger.info(f"双击打开历史数据: {file_path}")
        self._load_history_to_measure(file_path)

    def _on_open(self):
        """打开并分析"""
        table = self.findChild(QTableWidget, "data_table")
        if not table:
            return

        selected_rows = table.selectionModel().selectedRows()
        if not selected_rows:
            QMessageBox.warning(self, "提示", "请先选择一条历史数据")
            return

        # 获取选中的文件路径
        row = selected_rows[0].row()
        file_path = table.item(row, 0).data(Qt.UserRole)
        if not file_path or not os.path.exists(file_path):
            QMessageBox.warning(self, "错误", "文件不存在")
            return

        logger.info(f"打开历史数据: {file_path}")
        self._load_history_to_measure(file_path)

    def _load_history_to_measure(self, file_path):
        """加载历史数据到测量界面"""
        try:
            sample_info, angle_data, mag_data = _read_plot_csv(file_path)

            if not angle_data or not mag_data:
                QMessageBox.warning(self, "错误", "数据文件格式错误，无法解析")
                return

            logger.info(f"读取历史数据: {len(angle_data)} 个数据点")

            # 切换到测量面板并加载数据
            self._switch_to_measure_and_load(angle_data, mag_data, sample_info, file_path)

        except Exception as e:
            logger.error(f"加载历史数据失败: {e}")
            QMessageBox.warning(self, "错误", f"加载历史数据失败: {e}")

    def _switch_to_measure_and_load(self, angle_data, mag_data, sample_info, file_path):
        """切换到测量面板并加载数据"""
        # 查找主窗口并切换面板
        from PyQt5.QtWidgets import QApplication
        for widget in QApplication.topLevelWidgets():
            if hasattr(widget, '_switch_panel'):
                # 切换到测量面板
                widget._switch_panel("measure")

                # 获取测量面板并加载数据
                measure_panel = widget.get_panel("measure")
                if measure_panel:
                    # 设置波形数据
                    measure_panel.angle_data = angle_data
                    measure_panel.mag_data = mag_data

                    # 更新绘图
                    measure_panel.update_plot_data(angle_data, mag_data, '#1f77b4')

                    # 更新样品信息
                    if sample_info.get('sample_name'):
                        sample_name_edit = measure_panel.findChild(QLineEdit, "sample_name_edit")
                        if sample_name_edit:
                            sample_name_edit.setText(sample_info['sample_name'])
                    if sample_info.get('sample_code'):
                        sample_code_edit = measure_panel.findChild(QLineEdit, "sample_code_edit")
                        if sample_code_edit:
                            sample_code_edit.setText(sample_info['sample_code'])
                    if sample_info.get('polar_num'):
                        polar_num_edit = measure_panel.findChild(QLineEdit, "polar_num_edit")
                        if polar_num_edit:
                            polar_num_edit.setText(sample_info['polar_num'])
                    if sample_info.get('airgap'):
                        airgap_edit = measure_panel.findChild(QLineEdit, "airgap_edit")
                        if airgap_edit:
                            airgap_edit.setText(sample_info['airgap'])
                    if sample_info.get('remark'):
                        remark_edit = measure_panel.findChild(QLineEdit, "remark_edit")
                        if remark_edit:
                            remark_edit.setText(sample_info['remark'])
                    if sample_info.get('tester'):
                        tester_edit = measure_panel.findChild(QLineEdit, "tester_edit")
                        if tester_edit:
                            tester_edit.setText(sample_info['tester'])

                    # 进行波形分析
                    from windows.wave_analysis import WaveAnalysis
                    wave_analyzer = WaveAnalysis()
                    radio = measure_panel.findChild(QRadioButton, "radio_concentricity")
                    enable_concentricity = radio.isChecked() if radio else True
                    results = wave_analyzer.analyze_waveform(angle_data, mag_data, enable_concentricity)
                    measure_panel._update_display_with_results(results)

                    if hasattr(measure_panel, "show_history_file_status"):
                        measure_panel.show_history_file_status(file_path)
                    else:
                        measure_panel._update_status(f"当前显示文件：{os.path.basename(file_path)}")

                    logger.info("历史数据已加载到测量界面")

                break
