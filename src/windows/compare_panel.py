# -*- coding: utf-8 -*-
"""
数据比对面板 - 从 compare_panel.ui 加载
"""

import os
import csv
import numpy as np
from PyQt5.QtWidgets import (QWidget, QLabel, QPushButton, QLineEdit,
                              QTextEdit, QSplitter, QGroupBox, QGridLayout,
                              QFileDialog, QMessageBox, QDialog, QVBoxLayout,
                              QTableWidget, QTableWidgetItem, QHeaderView)
from PyQt5.QtCore import QObject, QEvent
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5 import uic
import pyqtgraph as pg
from pyqtgraph import mkPen
from PyQt5.QtGui import QPen
from core.logger import get_logger
from core.path_utils import get_data_dir
from windows.wave_analysis import WaveAnalysis

logger = get_logger('ComparePanel')


class ComparePanel(QWidget):
    """数据比对面板 - 从 compare_panel.ui 加载"""

    def __init__(self):
        super().__init__()

        # 加载 UI
        ui_file_path = os.path.join(os.path.dirname(__file__), "..", "ui", "compare_panel.ui")
        uic.loadUi(ui_file_path, self)

        # 存储两条曲线的数据
        self.data1 = {'angle': [], 'mag': [], 'sample_info': {}, 'results': {}}
        self.data2 = {'angle': [], 'mag': [], 'sample_info': {}, 'results': {}}

        # 初始化绘图控件
        self._init_plot_widget()

        # 连接按钮事件
        self._connect_buttons()

        logger.info("ComparePanel 初始化完成")

    def _connect_buttons(self):
        """连接按钮事件"""
        self.findChild(QPushButton, "file1_btn").clicked.connect(lambda: self._on_browse(1))
        self.findChild(QPushButton, "file2_btn").clicked.connect(lambda: self._on_browse(2))
        self.findChild(QPushButton, "compare_btn").clicked.connect(self._on_compare)

    def _init_plot_widget(self):
        """初始化绘图控件"""
        placeholder = self.findChild(QLabel, "plot_placeholder")
        if placeholder:
            # 创建绘图控件（启用 OpenGL 加速和自动降采样）
            self.plot_widget = pg.PlotWidget(useOpenGL=True)
            self.plot_widget.setBackground('#ffffff')
            self.plot_widget.showGrid(x=True, y=True, alpha=0.5)
            self.plot_widget.enableAutoRange(False, False)
            self.plot_widget.plotItem.setClipToView(True)
            self.plot_widget.setDownsampling(auto=True, mode='peak')

            # 创建两条曲线
            self.curve1 = self.plot_widget.plot(pen=mkPen('#e74c3c', width=1.5))  # 红色
            self.curve2 = self.plot_widget.plot(pen=mkPen('#3498db', width=1.5))  # 蓝色

            # 设置坐标轴
            self.plot_widget.setXRange(0, 360)
            self.plot_widget.setYRange(-70, 70)
            self.plot_widget.plotItem.setLabel('bottom', '角度', units='°')
            self.plot_widget.plotItem.setLabel('left', '磁场', units='mT')

            # 安装事件过滤器处理双击
            self.plot_widget.scene().installEventFilter(self)

            # 获取占位符的父布局
            parent = placeholder.parent()
            if parent:
                # 找到占位符在布局中的位置并替换
                layout = parent.layout()
                if layout:
                    # 找到placeholder的索引
                    index = layout.indexOf(placeholder)
                    if index >= 0:
                        layout.removeWidget(placeholder)
                        placeholder.close()
                        layout.insertWidget(index, self.plot_widget)

            logger.info("绘图控件初始化完成")

    def eventFilter(self, obj, event):
        """事件过滤器 - 处理双击事件"""
        if obj == self.plot_widget.scene():
            if event.type() == QEvent.GraphicsSceneMouseDoubleClick:
                self._on_plot_double_click()
                return True
        return super().eventFilter(obj, event)

    def _on_plot_double_click(self):
        """双击绘图区域，在独立窗口查看两条曲线。"""
        if not self.data1['angle'] and not self.data2['angle']:
            return

        # 创建独立窗口（非模态，避免嵌套事件循环卡顿）
        dialog = QDialog(self)
        dialog.setWindowTitle("波形比对")
        dialog.resize(1000, 600)
        dialog.setAttribute(Qt.WA_DeleteOnClose)

        # 创建绘图控件，启用 OpenGL 加速和自动降采样
        full_plot = pg.PlotWidget(useOpenGL=True)
        full_plot.setBackground('#ffffff')
        full_plot.showGrid(x=True, y=True, alpha=0.5)
        full_plot.setXRange(0, 360)
        full_plot.plotItem.setLabel('bottom', '角度', units='°')
        full_plot.plotItem.setLabel('left', '磁场', units='mT')
        full_plot.plotItem.setClipToView(True)
        full_plot.setDownsampling(auto=True, mode='peak')

        # 绘制两条曲线
        curve1_full = full_plot.plot(pen=mkPen('#e74c3c', width=1.5))
        curve2_full = full_plot.plot(pen=mkPen('#3498db', width=1.5))

        if self.data1['angle'] and self.data1['mag']:
            min_len = min(len(self.data1['angle']), len(self.data1['mag']))
            if min_len > 0:
                curve1_full.setData(self.data1['angle'][:min_len], self.data1['mag'][:min_len])

        if self.data2['angle'] and self.data2['mag']:
            min_len = min(len(self.data2['angle']), len(self.data2['mag']))
            if min_len > 0:
                curve2_full.setData(self.data2['angle'][:min_len], self.data2['mag'][:min_len])

        # 自动调整Y轴
        all_mag = []
        if self.data1['mag']:
            all_mag.extend(self.data1['mag'])
        if self.data2['mag']:
            all_mag.extend(self.data2['mag'])
        if all_mag:
            min_val = min(all_mag)
            max_val = max(all_mag)
            margin = (max_val - min_val) * 0.1
            full_plot.setYRange(min_val - margin, max_val + margin)

        # 设置布局
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(full_plot)

        dialog.showMaximized()

    def _on_browse(self, file_num):
        """浏览文件"""
        # 默认打开 plot_data 目录
        default_dir = self._get_plot_data_dir()

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            f"选择文件{file_num}",
            default_dir,
            "CSV Files (*.csv);;All Files (*)"
        )
        if file_path:
            if file_num == 1:
                self.findChild(QLineEdit, "file1_edit").setText(file_path)
            else:
                self.findChild(QLineEdit, "file2_edit").setText(file_path)
            logger.info(f"选择文件{file_num}: {file_path}")

    def _get_plot_data_dir(self):
        """获取plot_data目录路径"""
        return get_data_dir("plot_data")

    def _read_csv_file(self, file_path):
        """读取CSV文件"""
        try:
            angle_data = []
            mag_data = []
            sample_info = {}

            with open(file_path, 'r', encoding='utf-8') as f:
                reader = csv.reader(f)
                lines = list(reader)

                # 解析头部信息
                for line in lines[:15]:
                    if len(line) >= 2:
                        key = line[0].strip()
                        value = line[1].strip()
                        if "样品名称" in key:
                            sample_info['sample_name'] = value
                        elif "样品编号" in key:
                            sample_info['sample_code'] = value
                        elif "保存时间" in key:
                            sample_info['save_time'] = value
                        elif "极数" in key:
                            sample_info['polar_num'] = value
                        elif "气隙" in key:
                            sample_info['airgap'] = value
                        elif "备注" in key:
                            sample_info['remark'] = value

                # 找到数据起始位置
                data_start = -1
                for i, line in enumerate(lines):
                    if len(line) >= 2 and "角度" in line[0] and "磁场" in line[1]:
                        data_start = i + 1
                        break

                # 解析数据
                if data_start >= 0 and data_start < len(lines):
                    for i in range(data_start, len(lines)):
                        if len(lines[i]) >= 2 and lines[i][0].strip():
                            try:
                                angle = float(lines[i][0].strip())
                                mag = float(lines[i][1].strip())
                                angle_data.append(angle)
                                mag_data.append(mag)
                            except (ValueError, IndexError):
                                continue

            if not angle_data or not mag_data:
                return None, None, {}

            return angle_data, mag_data, sample_info

        except Exception as e:
            logger.error(f"读取CSV文件失败: {e}")
            return None, None, {}

    def _analyze_data(self, angle_data, mag_data):
        """分析数据"""
        try:
            wave_analyzer = WaveAnalysis()
            results = wave_analyzer.analyze_waveform(angle_data, mag_data, enable_concentricity_calibration=True)
            return results
        except Exception as e:
            logger.error(f"分析数据失败: {e}")
            return {}

    def _update_result_table(self, results1, results2, name1, name2):
        """将比对结果填入表格"""
        table = self.findChild(QTableWidget, "result_table")
        if not table:
            return

        rows = [
            ("N极最大值", "N_max", ".2f"),
            ("N极最小值", "N_min", ".2f"),
            ("N极均值", "N_mean", ".2f"),
            ("N极误差%", "N_se", ".2f"),
            ("S极最大值", "S_max", ".2f"),
            ("S极最小值", "S_min", ".2f"),
            ("S极均值", "S_mean", ".2f"),
            ("S极误差%", "S_se", ".2f"),
            ("NS/2", "NS_2", ".2f"),
            ("N间隔最大值", "N_interval_max", ".2f"),
            ("N间隔最小值", "N_interval_min", ".2f"),
            ("N间隔均值", "N_interval_mean", ".2f"),
            ("N间隔误差", "N_interval_std", ".2f"),
            ("S间隔最大值", "S_interval_max", ".2f"),
            ("S间隔最小值", "S_interval_min", ".2f"),
            ("S间隔均值", "S_interval_mean", ".2f"),
            ("S间隔误差", "S_interval_std", ".2f"),
            ("N极面积", "N_area", ".2f"),
            ("S极面积", "S_area", ".2f"),
            ("NS总面积", "NS_area", ".2f"),
            ("单极均值", "SinglePolarMean", ".2f"),
            ("单极误差", "SinglePolarError", ".5f"),
            ("累计误差", "PolarErrorSum", ".5f"),
            ("THD失真率", "THD_error", ".5f"),
            ("极对数", "pole_num", ""),
        ]

        table.setRowCount(len(rows))
        table.setColumnCount(3)
        table.setHorizontalHeaderLabels(["指标", name1, name2])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        table.verticalHeader().setVisible(False)

        for row_idx, (label, key, fmt) in enumerate(rows):
            table.setItem(row_idx, 0, QTableWidgetItem(label))

            val1 = results1.get(key, "")
            if fmt and isinstance(val1, (int, float)):
                val1_str = format(val1, fmt) if not (isinstance(val1, float) and val1 != val1) else "-"
            else:
                val1_str = str(val1) if val1 != "" else "-"
            table.setItem(row_idx, 1, QTableWidgetItem(val1_str))

            val2 = results2.get(key, "")
            if fmt and isinstance(val2, (int, float)):
                val2_str = format(val2, fmt) if not (isinstance(val2, float) and val2 != val2) else "-"
            else:
                val2_str = str(val2) if val2 != "" else "-"
            table.setItem(row_idx, 2, QTableWidgetItem(val2_str))

    def _on_compare(self):
        """开始比对"""
        file1 = self.findChild(QLineEdit, "file1_edit").text().strip()
        file2 = self.findChild(QLineEdit, "file2_edit").text().strip()

        if not file1:
            QMessageBox.warning(self, "提示", "请选择文件1")
            return
        if not file2:
            QMessageBox.warning(self, "提示", "请选择文件2")
            return

        if not os.path.exists(file1):
            QMessageBox.warning(self, "错误", f"文件1不存在: {file1}")
            return
        if not os.path.exists(file2):
            QMessageBox.warning(self, "错误", f"文件2不存在: {file2}")
            return

        logger.info(f"开始比对: {file1} vs {file2}")

        # 读取文件1
        self.data1['angle'], self.data1['mag'], self.data1['sample_info'] = self._read_csv_file(file1)
        if self.data1['angle'] is None:
            QMessageBox.warning(self, "错误", f"文件1读取失败: {file1}")
            return

        # 读取文件2
        self.data2['angle'], self.data2['mag'], self.data2['sample_info'] = self._read_csv_file(file2)
        if self.data2['angle'] is None:
            QMessageBox.warning(self, "错误", f"文件2读取失败: {file2}")
            return

        # 分析数据
        self.data1['results'] = self._analyze_data(self.data1['angle'], self.data1['mag'])
        self.data2['results'] = self._analyze_data(self.data2['angle'], self.data2['mag'])

        # 更新绘图
        self._update_plot()

        # 更新结果表格（表头使用文件名）
        self._update_result_table(self.data1['results'], self.data2['results'],
                                  os.path.basename(file1), os.path.basename(file2))

        logger.info("比对完成")

    def _update_plot(self):
        """更新绘图"""
        if not hasattr(self, 'plot_widget'):
            return

        self.plot_widget.clear()

        # 重新创建曲线
        self.curve1 = self.plot_widget.plot(pen=mkPen('#e74c3c', width=1.5))  # 红色
        self.curve2 = self.plot_widget.plot(pen=mkPen('#3498db', width=1.5))  # 蓝色

        # 绘制文件1数据（红色）
        if self.data1['angle'] and self.data1['mag']:
            min_len = min(len(self.data1['angle']), len(self.data1['mag']))
            if min_len > 0:
                self.curve1.setData(
                    self.data1['angle'][:min_len],
                    self.data1['mag'][:min_len]
                )

        # 绘制文件2数据（蓝色）
        if self.data2['angle'] and self.data2['mag']:
            min_len = min(len(self.data2['angle']), len(self.data2['mag']))
            if min_len > 0:
                self.curve2.setData(
                    self.data2['angle'][:min_len],
                    self.data2['mag'][:min_len]
                )

        # 自动调整Y轴范围
        all_mag = []
        if self.data1['mag']:
            all_mag.extend(self.data1['mag'])
        if self.data2['mag']:
            all_mag.extend(self.data2['mag'])

        if all_mag:
            min_val = min(all_mag)
            max_val = max(all_mag)
            margin = (max_val - min_val) * 0.1
            self.plot_widget.setYRange(min_val - margin, max_val + margin)

        # X轴固定0-360
        self.plot_widget.setXRange(0, 360)

        logger.info("绘图已更新")
