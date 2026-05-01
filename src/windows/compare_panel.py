# -*- coding: utf-8 -*-
"""
数据比对面板 - 从 compare_panel.ui 加载
"""

import os
import csv
import numpy as np
from PyQt5.QtWidgets import (QWidget, QLabel, QPushButton, QLineEdit,
                              QTextEdit, QSplitter, QGroupBox, QGridLayout,
                              QFileDialog, QMessageBox, QDialog, QVBoxLayout)
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
        # 找到占位符并替换为真正的绘图控件
        placeholder = self.findChild(QLabel, "plot_placeholder")
        if placeholder:
            # 创建绘图控件
            self.plot_widget = pg.PlotWidget()

            # 设置背景色为白色
            self.plot_widget.setBackground('#ffffff')

            # 显示网格
            self.plot_widget.showGrid(x=True, y=True, alpha=0.5)

            # 禁用自动范围调整
            self.plot_widget.enableAutoRange(False, False)

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
        """双击绘图区域，打开独立窗口显示两条曲线"""
        if not self.data1['angle'] and not self.data2['angle']:
            return

        # 创建独立窗口
        dialog = QDialog(self)
        dialog.setWindowTitle("波形比对")
        dialog.resize(1000, 600)
        dialog.showMaximized()

        # 创建新的绘图控件
        full_plot = pg.PlotWidget()
        full_plot.setBackground('#ffffff')
        full_plot.showGrid(x=True, y=True, alpha=0.5)
        full_plot.setXRange(0, 360)
        full_plot.plotItem.setLabel('bottom', '角度', units='°')
        full_plot.plotItem.setLabel('left', '磁场', units='mT')

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

        dialog.exec_()

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

    def _format_results(self, results):
        """格式化分析结果为文本"""
        if not results:
            return "无分析结果"

        text = []
        text.append("=== N极/S极基础值 ===")
        text.append(f"N极最大值: {results.get('N_max', 0):.2f}")
        text.append(f"N极最小值: {results.get('N_min', 0):.2f}")
        text.append(f"N极均值: {results.get('N_mean', 0):.2f}")
        text.append(f"N极误差%: {results.get('N_se', 0):.2f}")
        text.append(f"S极最大值: {results.get('S_max', 0):.2f}")
        text.append(f"S极最小值: {results.get('S_min', 0):.2f}")
        text.append(f"S极均值: {results.get('S_mean', 0):.2f}")
        text.append(f"S极误差%: {results.get('S_se', 0):.2f}")
        text.append(f"NS/2: {results.get('NS_2', 0):.2f}")
        text.append("")
        text.append("=== N极间隔 ===")
        text.append(f"N间隔最大值: {results.get('N_interval_max', 0):.2f}")
        text.append(f"N间隔最小值: {results.get('N_interval_min', 0):.2f}")
        text.append(f"N间隔均值: {results.get('N_interval_mean', 0):.2f}")
        text.append(f"N间隔误差: {results.get('N_interval_std', 0):.2f}")
        text.append("")
        text.append("=== S极间隔 ===")
        text.append(f"S间隔最大值: {results.get('S_interval_max', 0):.2f}")
        text.append(f"S间隔最小值: {results.get('S_interval_min', 0):.2f}")
        text.append(f"S间隔均值: {results.get('S_interval_mean', 0):.2f}")
        text.append(f"S间隔误差: {results.get('S_interval_std', 0):.2f}")
        text.append("")
        text.append("=== 面积 ===")
        text.append(f"N极面积: {results.get('N_area', 0):.2f}")
        text.append(f"S极面积: {results.get('S_area', 0):.2f}")
        text.append(f"NS总面积: {results.get('NS_area', 0):.2f}")
        text.append("")
        text.append("=== 其他 ===")
        text.append(f"单极均值: {results.get('SinglePolarMean', 0):.2f}")
        text.append(f"单极误差: {results.get('SinglePolarError', 0):.5f}")
        text.append(f"累计误差: {results.get('PolarErrorSum', 0):.5f}")
        text.append(f"THD失真率: {results.get('THD_error', 0):.5f}")
        text.append(f"极对数: {results.get('pole_num', 'N/A')}")

        return "\n".join(text)

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

        # 更新结果文本
        result1_text = self.findChild(QTextEdit, "result1_text")
        result2_text = self.findChild(QTextEdit, "result2_text")

        sample1_name = self.data1['sample_info'].get('sample_name', os.path.basename(file1))
        sample2_name = self.data2['sample_info'].get('sample_name', os.path.basename(file2))

        if result1_text:
            header1 = f"【{sample1_name}】\n"
            result1_text.setPlainText(header1 + self._format_results(self.data1['results']))

        if result2_text:
            header2 = f"【{sample2_name}】\n"
            result2_text.setPlainText(header2 + self._format_results(self.data2['results']))

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
