# -*- coding: utf-8 -*-
"""
数据比对窗口
用于比对两个历史数据文件的波形和分析结果
"""

import os
import csv
import pyqtgraph as pg
from PyQt5.QtWidgets import QMainWindow, QFileDialog, QDialog, QVBoxLayout
from PyQt5.QtCore import Qt
from PyQt5 import uic
from ui.window_operations import WindowOperations
from ui.theme import get_base_stylesheet
from windows.wave_analysis import WaveAnalysis
from core.logger import get_logger
logger = get_logger('CompareWindow')

# 默认数据路径 (MARS/data/plot_data)
DEFAULT_DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "plot_data"
)

class CompareWindow(QMainWindow):
    """数据比对窗口"""
    
    def __init__(self, enable_concentricity_calibration=True):
        super().__init__()
        
        # 从compare_window.ui文件加载界面
        ui_file_path = os.path.join(os.path.dirname(__file__), "..", "ui", "compare_window.ui")
        uic.loadUi(ui_file_path, self)

        # 应用深色主题样式
        self.setStyleSheet(get_base_stylesheet())

        # 初始化窗口操作功能
        self.window_operations = WindowOperations(self)
        
        # 初始化波形分析器
        self.wave_analyzer = WaveAnalysis()
        
        # 初始化绘图区域
        self._init_plots()
        
        # 连接按钮事件
        self._connect_buttons()
        
        # 文件数据存储
        self.file1_data = None
        self.file2_data = None
        
        # 绘图对象
        self.plot1 = None
        self.plot2 = None
        
        # 窗口状态
        self.is_maximized = False
        
        # 同心度校准状态
        self.enable_concentricity_calibration = enable_concentricity_calibration
    
    def _init_plots(self):
        """初始化绘图区域"""
        # 创建单个绘图区域用于显示双波形
        self.plot_widget = pg.PlotWidget()
        
        # 基本显示设置
        self.plot_widget.setBackground('w')
        self.plot_widget.setLabel('left', '磁场强度')
        self.plot_widget.setLabel('bottom', '角度', units='度')
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        
        # 禁用鼠标交互，使绘图区域不可操作
        self.plot_widget.plotItem.setMouseEnabled(x=False, y=False)
        self.plot_widget.plotItem.setMenuEnabled(False)
        
        # 禁用自动范围调整
        self.plot_widget.enableAutoRange(False, False)
        
        # 设置初始显示范围
        self.plot_widget.setXRange(0, 360)
        self.plot_widget.setYRange(-70, 70)
        
        # 添加图例
        self.plot_widget.addLegend()
        
        # 连接双击事件
        self.plot_widget.scene().sigMouseClicked.connect(self._on_plot_double_click)
        
        # 将绘图区域添加到界面
        layout = self.widget_plot_display.layout()
        if layout is None:
            from PyQt5.QtWidgets import QVBoxLayout
            layout = QVBoxLayout()
            self.widget_plot_display.setLayout(layout)
        layout.addWidget(self.plot_widget)
    
    def _connect_buttons(self):
        """连接按钮事件"""
        # 连接文件选择按钮
        self.pushButton_select1.clicked.connect(self._select_file1)
        self.pushButton_select2.clicked.connect(self._select_file2)
        
        # 连接比对按钮
        self.pushButton_compare.clicked.connect(self._compare_files)
        
        # 连接窗口控制按钮
        self.minimize_button.clicked.connect(self._minimize_window)
        self.maximize_button.clicked.connect(self._toggle_maximize)
        self.close_button.clicked.connect(self._close_window)
    
    def _select_file1(self):
        """选择第一个文件"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, 
            "选择第一个比对文件", 
            DEFAULT_DATA_DIR,
            "CSV Files (*.csv)"
        )
        
        if file_path:
            # 只显示文件名，不显示完整路径
            file_name = os.path.basename(file_path)
            self.lineEdit_file1.setText(file_name)
            
            # 存储完整路径用于后续操作
            self.file1_data = self._read_csv_data(file_path)
            
            if self.file1_data:
                self._update_file_info(1, file_path)
                logger.info(f"文件1加载成功: {file_name}")
            else:
                logger.info("文件1加载失败")
    
    def _select_file2(self):
        """选择第二个文件"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, 
            "选择第二个比对文件", 
            DEFAULT_DATA_DIR,
            "CSV Files (*.csv)"
        )
        
        if file_path:
            # 只显示文件名，不显示完整路径
            file_name = os.path.basename(file_path)
            self.lineEdit_file2.setText(file_name)
            
            # 存储完整路径用于后续操作
            self.file2_data = self._read_csv_data(file_path)
            
            if self.file2_data:
                self._update_file_info(2, file_path)
                logger.info(f"文件2加载成功: {file_name}")
            else:
                logger.info("文件2加载失败")
    
    def _read_csv_data(self, file_path):
        """读取CSV文件中的角度、磁场数据和已保存的分析结果

        Args:
            file_path: CSV文件路径

        Returns:
            dict: 包含角度数据、磁场数据和分析结果的字典
        """
        try:
            angle_data = []
            mag_data = []
            file_info = {}
            analysis_results = {}

            with open(file_path, 'r', encoding='utf-8') as csvfile:
                reader = csv.reader(csvfile)

                # 状态机：读取样品信息、分析结果、数据
                section = 'info'  # info -> analysis -> data
                for row in reader:
                    if not row:  # 空行跳过
                        continue

                    if section == 'info':
                        if len(row) >= 2:
                            key = row[0].strip()
                            value = row[1].strip()

                            if key == "样品名称":
                                file_info['sample_name'] = value
                            elif key == "测试员":
                                file_info['tester'] = value
                            elif key == "保存时间":
                                file_info['save_time'] = value
                            elif key == "角度(度)":
                                section = 'data'
                                continue
                            elif key == "=== 分析结果 ===":
                                section = 'analysis'
                                continue
                    elif section == 'analysis':
                        if len(row) >= 2:
                            key = row[0].strip()
                            value = row[1].strip()
                            if key == "角度(度)":
                                section = 'data'
                                continue
                            # 解析分析结果字段
                            if key == "N极最大值":
                                analysis_results['N_max'] = self._parse_float(value)
                            elif key == "N极最小值":
                                analysis_results['N_min'] = self._parse_float(value)
                            elif key == "N极平均值":
                                analysis_results['N_mean'] = self._parse_float(value)
                            elif key == "N极误差":
                                analysis_results['N_se'] = self._parse_float(value)
                            elif key == "S极最大值":
                                analysis_results['S_max'] = self._parse_float(value)
                            elif key == "S极最小值":
                                analysis_results['S_min'] = self._parse_float(value)
                            elif key == "S极平均值":
                                analysis_results['S_mean'] = self._parse_float(value)
                            elif key == "S极误差":
                                analysis_results['S_se'] = self._parse_float(value)
                            elif key == "NS_2":
                                analysis_results['NS_2'] = self._parse_float(value)
                            elif key == "单极平均值":
                                analysis_results['SinglePolarMean'] = self._parse_float(value)
                            elif key == "单极误差":
                                analysis_results['SinglePolarError'] = self._parse_float(value)
                            elif key == "极误差和":
                                analysis_results['PolarErrorSum'] = self._parse_float(value)
                            elif key == "N极间隔最大值":
                                analysis_results['N_interval_max'] = self._parse_float(value)
                            elif key == "N极间隔最小值":
                                analysis_results['N_interval_min'] = self._parse_float(value)
                            elif key == "N极间隔平均值":
                                analysis_results['N_interval_mean'] = self._parse_float(value)
                            elif key == "N极间隔误差":
                                analysis_results['N_interval_std'] = self._parse_float(value)
                            elif key == "S极间隔最大值":
                                analysis_results['S_interval_max'] = self._parse_float(value)
                            elif key == "S极间隔最小值":
                                analysis_results['S_interval_min'] = self._parse_float(value)
                            elif key == "S极间隔平均值":
                                analysis_results['S_interval_mean'] = self._parse_float(value)
                            elif key == "S极间隔误差":
                                analysis_results['S_interval_std'] = self._parse_float(value)
                            elif key == "N极面积":
                                analysis_results['N_area'] = self._parse_float(value)
                            elif key == "S极面积":
                                analysis_results['S_area'] = self._parse_float(value)
                            elif key == "NS面积":
                                analysis_results['NS_area'] = self._parse_float(value)
                            elif key == "THD失真率":
                                analysis_results['THD_error'] = self._parse_float(value)
                            elif key == "极对数":
                                analysis_results['pole_num'] = self._parse_float(value)
                    elif section == 'data':
                        if len(row) >= 2:
                            try:
                                angle = float(row[0])
                                mag = float(row[1])
                                angle_data.append(angle)
                                mag_data.append(mag)
                            except ValueError:
                                continue  # 跳过无法转换的行

            return {
                'angle_data': angle_data,
                'mag_data': mag_data,
                'file_info': file_info,
                'analysis_results': analysis_results,
                'file_path': file_path
            }

        except Exception as e:
            logger.info(f"读取CSV数据时发生错误: {e}")
            return None

    def _parse_float(self, value):
        """解析浮点数，支持空值和nan"""
        if not value or value == '' or value.lower() == 'nan':
            return None
        try:
            return float(value)
        except ValueError:
            return None
    
    def _update_file_info(self, file_num, file_path):
        """更新文件信息显示
        
        Args:
            file_num: 文件编号（1或2）
            file_path: 文件路径
        """
        if file_num == 1:
            title_label = self.label_plot1_title
        else:
            title_label = self.label_plot2_title
        
        file_data = self.file1_data if file_num == 1 else self.file2_data
        if file_data and 'file_info' in file_data:
            info = file_data['file_info']
            sample_name = info.get('sample_name', '未知样品')
            save_time = info.get('save_time', '未知时间')
            
            title_label.setText(f"文件{file_num}: {sample_name} ({save_time})")
    
    def _compare_files(self):
        """开始比对两个文件"""
        if not self.file1_data or not self.file2_data:
            logger.info("请先选择两个文件进行比对")
            return
        
        logger.info("开始比对两个文件...")
        
        # 清空之前的绘图
        self._clear_plots()
        
        # 在同一张图上绘制两个文件的波形
        self._plot_both_waveforms()
        
        # 进行波形分析并显示结果
        self._analyze_and_display_results()
        
        logger.info("文件比对完成")
    
    def _clear_plots(self):
        """清空绘图区域"""
        if self.plot1:
            self.plot_widget.removeItem(self.plot1)
            self.plot1 = None
        if self.plot2:
            self.plot_widget.removeItem(self.plot2)
            self.plot2 = None
    
    def _on_plot_double_click(self, event):
        """处理绘图区域双击事件 - 弹出波形窗口"""
        if event.double():
            self._show_waveform_window()
    
    def _show_waveform_window(self):
        """显示波形窗口"""
        if not self.file1_data or not self.file2_data:
            logger.info("请先选择两个文件进行比对")
            return
        
        # 创建并显示波形窗口
        waveform_window = WaveformWindow(self.file1_data, self.file2_data)
        waveform_window.exec_()
    
    def _plot_both_waveforms(self):
        """在同一张图上绘制两个文件的波形"""
        # 清空绘图区域
        self.plot_widget.clear()
        
        # 获取文件信息
        info1 = self.file1_data['file_info']
        info2 = self.file2_data['file_info']
        
        sample_name1 = info1.get('sample_name', '未知样品1')
        sample_name2 = info2.get('sample_name', '未知样品2')
        
        # 设置标题
        self.plot_widget.setTitle(f"双波形对比图: {sample_name1} vs {sample_name2}", color='#333', size='12pt')
        
        # 绘制第一个文件的波形（红色）
        if self.file1_data['angle_data'] and self.file1_data['mag_data']:
            self.plot1 = self.plot_widget.plot(
                self.file1_data['angle_data'], 
                self.file1_data['mag_data'], 
                pen=pg.mkPen(color='#FF0000', width=2),
                name=f"{sample_name1}"
            )
        
        # 绘制第二个文件的波形（蓝色）
        if self.file2_data['angle_data'] and self.file2_data['mag_data']:
            self.plot2 = self.plot_widget.plot(
                self.file2_data['angle_data'], 
                self.file2_data['mag_data'], 
                pen=pg.mkPen(color='#2196F3', width=2),
                name=f"{sample_name2}"
            )
        
        # 自动调整坐标轴范围
        self.plot_widget.autoRange()
    
    def _analyze_and_display_results(self):
        """使用保存的分析结果或重新分析来显示结果"""
        # 处理第一个文件
        if self.file1_data:
            results1 = self.file1_data.get('analysis_results', {})
            if results1:
                # 使用保存的分析结果
                logger.info("使用文件1保存的分析结果")
            else:
                # 重新分析
                logger.info("文件1无保存分析结果，重新分析...")
                results1 = self.wave_analyzer.analyze_waveform(
                    self.file1_data['angle_data'],
                    self.file1_data['mag_data'],
                    self.enable_concentricity_calibration
                )
            self._display_results(1, results1)

        # 处理第二个文件
        if self.file2_data:
            results2 = self.file2_data.get('analysis_results', {})
            if results2:
                # 使用保存的分析结果
                logger.info("使用文件2保存的分析结果")
            else:
                # 重新分析
                logger.info("文件2无保存分析结果，重新分析...")
                results2 = self.wave_analyzer.analyze_waveform(
                    self.file2_data['angle_data'],
                    self.file2_data['mag_data'],
                    self.enable_concentricity_calibration
                )
            self._display_results(2, results2)
    
    def _display_results(self, file_num, results):
        """显示分析结果
        
        Args:
            file_num: 文件编号（1或2）
            results: 分析结果字典
        """
        if file_num == 1:
            text_edit = self.textEdit_result1
            color = '#FF0000'
        else:
            text_edit = self.textEdit_result2
            color = '#2196F3'
        
        # 构建结果显示文本
        result_text = f"<b><font color='{color}'>波形分析结果</font></b><br>"
        result_text += f"样品名称: {results.get('sample_name', '未知')}<br>"
        result_text += f"测试员: {results.get('tester', '未知')}<br>"
        result_text += f"保存时间: {results.get('save_time', '未知')}<br><br>"
        
        # 添加波形分析结果
        result_text += "<b>波形参数:</b><br>"
        result_text += f"N极最大值: {results.get('N_max', 0):.3f}<br>"
        result_text += f"N极最小值: {results.get('N_min', 0):.3f}<br>"
        result_text += f"N极平均值: {results.get('N_mean', 0):.3f}<br>"
        result_text += f"N极标准差: {results.get('N_se', 0):.3f}<br><br>"
        
        result_text += f"S极最大值: {results.get('S_max', 0):.3f}<br>"
        result_text += f"S极最小值: {results.get('S_min', 0):.3f}<br>"
        result_text += f"S极平均值: {results.get('S_mean', 0):.3f}<br>"
        result_text += f"S极标准差: {results.get('S_se', 0):.3f}<br><br>"
        
        result_text += f"NS差值: {results.get('NS_2', 0):.3f}<br>"
        result_text += f"单极平均值: {results.get('SinglePolarMean', 0):.3f}<br>"
        result_text += f"单极误差: {results.get('SinglePolarError', 0):.3f}<br>"
        result_text += f"极性误差和: {results.get('PolarErrorSum', 0):.3f}<br><br>"
        
        result_text += "<b>区间统计:</b><br>"
        result_text += f"N区间最大值: {results.get('N_interval_max', 0):.3f}<br>"
        result_text += f"N区间最小值: {results.get('N_interval_min', 0):.3f}<br>"
        result_text += f"N区间平均值: {results.get('N_interval_mean', 0):.3f}<br>"
        result_text += f"N区间标准差: {results.get('N_interval_std', 0):.3f}<br><br>"
        
        result_text += f"S区间最大值: {results.get('S_interval_max', 0):.3f}<br>"
        result_text += f"S区间最小值: {results.get('S_interval_min', 0):.3f}<br>"
        result_text += f"S区间平均值: {results.get('S_interval_mean', 0):.3f}<br>"
        result_text += f"S区间标准差: {results.get('S_interval_std', 0):.3f}<br><br>"
        
        result_text += "<b>面积计算:</b><br>"
        result_text += f"N极面积: {results.get('N_area', 0):.3f}<br>"
        result_text += f"S极面积: {results.get('S_area', 0):.3f}<br>"
        result_text += f"NS总面积: {results.get('NS_area', 0):.3f}<br><br>"
        
        result_text += "<b>失真分析:</b><br>"
        result_text += f"THD失真率: {results.get('THD_error', 0):.5f}%<br>"
        
        # 设置结果显示
        text_edit.setHtml(result_text)
    
    def _minimize_window(self):
        """最小化窗口"""
        self.showMinimized()
        logger.info("数据比对窗口已最小化")
    
    def _toggle_maximize(self):
        """切换最大化/还原窗口"""
        if self.is_maximized:
            self.showNormal()
            self.is_maximized = False
            logger.info("数据比对窗口已还原")
        else:
            self.showMaximized()
            self.is_maximized = True
            logger.info("数据比对窗口已最大化")
    

    
    def _close_window(self):
        """关闭窗口"""
        self.close()
        logger.info("数据比对窗口已关闭")
    
    def show_window(self):
        """显示窗口"""
        logger.info("显示数据比对窗口")
        
        if not self.isVisible():
            self.show()
        else:
            self.raise_()
            self.activateWindow()


class WaveformWindow(QDialog):
    """波形显示窗口"""
    
    def __init__(self, file1_data, file2_data, parent=None):
        super().__init__(parent)
        
        self.file1_data = file1_data
        self.file2_data = file2_data
        
        # 窗口状态
        self.is_maximized = False
        
        # 设置窗口属性
        self.setWindowTitle("波形详细显示")
        self.setGeometry(100, 100, 1000, 700)
        
        # 设置窗口标志，隐藏默认标题栏，使用自定义标题栏
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        
        # 创建主布局
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)  # 减少边距
        main_layout.setSpacing(0)  # 减少间距
        
        # 创建标题栏
        title_widget = self._create_title_bar()
        main_layout.addWidget(title_widget)
        
        # 创建绘图控件
        self.plot_widget = pg.PlotWidget()
        
        # 设置绘图控件
        self.plot_widget.setBackground('w')
        self.plot_widget.setLabel('left', '磁场强度')
        self.plot_widget.setLabel('bottom', '角度', units='度')
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        
        # 启用鼠标交互
        self.plot_widget.plotItem.setMouseEnabled(x=True, y=True)
        self.plot_widget.plotItem.setMenuEnabled(True)
        
        # 性能优化设置
        self.plot_widget.plotItem.setClipToView(True)  # 只绘制可见区域
        self.plot_widget.plotItem.setDownsampling(auto=True, mode='peak')  # 自动降采样
        self.plot_widget.plotItem.setCacheMode(True)  # 启用缓存
        
        # 禁用不必要的功能
        self.plot_widget.plotItem.hideButtons()  # 隐藏缩放按钮
        self.plot_widget.enableAutoRange(False, False)  # 禁用自动范围调整
        
        # 设置初始显示范围
        self.plot_widget.setXRange(0, 360)
        self.plot_widget.setYRange(-70, 70)
        
        # 添加图例
        self.plot_widget.addLegend()
        
        # 连接双击事件
        self.plot_widget.scene().sigMouseClicked.connect(self._on_plot_double_click)
        
        # 添加到布局
        main_layout.addWidget(self.plot_widget)
        
        # 延迟绘制波形，避免窗口初始化时的卡顿
        from PyQt5.QtCore import QTimer
        QTimer.singleShot(100, self._plot_waveforms)  # 延迟100ms绘制
    
    def _create_title_bar(self):
        """创建标题栏"""
        from PyQt5.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton
        
        title_widget = QWidget()
        title_widget.setStyleSheet("""
            QWidget {
                background-color: #f0f0f0;
                border-bottom: 1px solid #cccccc;
            }
        """)
        title_layout = QHBoxLayout(title_widget)
        title_layout.setContentsMargins(10, 5, 10, 5)
        
        # 标题
        title_label = QLabel("波形详细显示")
        title_label.setStyleSheet("""
            QLabel {
                font-size: 16px;
                font-weight: bold;
                color: #333;
            }
        """)
        
        # 弹性空间
        from PyQt5.QtWidgets import QSpacerItem, QSizePolicy
        spacer = QSpacerItem(40, 20, QSizePolicy.Expanding, QSizePolicy.Minimum)
        
        # 最大化按钮
        self.maximize_button = QPushButton("□")
        self.maximize_button.setFixedSize(30, 30)
        self.maximize_button.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                border: none;
                border-radius: 3px;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
        """)
        self.maximize_button.clicked.connect(self._toggle_maximize)
        
        # 关闭按钮
        close_button = QPushButton("×")
        close_button.setFixedSize(30, 30)
        close_button.setStyleSheet("""
            QPushButton {
                background-color: #f44336;
                color: white;
                border: none;
                border-radius: 3px;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #d32f2f;
            }
        """)
        close_button.clicked.connect(self.close)
        
        title_layout.addWidget(title_label)
        title_layout.addSpacerItem(spacer)
        title_layout.addWidget(self.maximize_button)
        title_layout.addWidget(close_button)
        
        # 启用标题栏拖动功能
        title_widget.mousePressEvent = self._title_mouse_press
        title_widget.mouseMoveEvent = self._title_mouse_move
        
        return title_widget
    
    def _toggle_maximize(self):
        """切换最大化/还原窗口"""
        if self.is_maximized:
            self.showNormal()
            self.is_maximized = False
            self.maximize_button.setText("□")
            logger.info("波形窗口已还原")
        else:
            self.showMaximized()
            self.is_maximized = True
            self.maximize_button.setText("❐")
            logger.info("波形窗口已最大化")
    
    def _title_mouse_press(self, event):
        """标题栏鼠标按下事件"""
        if event.button() == Qt.LeftButton:
            self.drag_position = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()
    
    def _title_mouse_move(self, event):
        """标题栏鼠标移动事件"""
        if event.buttons() == Qt.LeftButton and hasattr(self, 'drag_position'):
            self.move(event.globalPos() - self.drag_position)
            event.accept()
    
    def _plot_waveforms(self):
        """绘制波形"""
        # 清空之前的绘图
        self.plot_widget.clear()
        
        # 获取文件信息
        sample_name1 = '未知样品1'
        sample_name2 = '未知样品2'
        
        if self.file1_data and 'file_info' in self.file1_data:
            info1 = self.file1_data['file_info']
            sample_name1 = info1.get('sample_name', '未知样品1')
        
        if self.file2_data and 'file_info' in self.file2_data:
            info2 = self.file2_data['file_info']
            sample_name2 = info2.get('sample_name', '未知样品2')
        
        # 设置标题
        self.plot_widget.setTitle(f"双波形对比图: {sample_name1} vs {sample_name2}", color='#333', size='12pt')
        
        # 绘制文件1波形（红色）
        if self.file1_data and 'angle_data' in self.file1_data and 'mag_data' in self.file1_data:
            angle_data1 = self.file1_data['angle_data']
            mag_data1 = self.file1_data['mag_data']
            if len(angle_data1) > 0 and len(mag_data1) > 0:
                min_len = min(len(angle_data1), len(mag_data1))
                # 使用更细的线条和优化设置
                self.plot_widget.plot(angle_data1[:min_len], mag_data1[:min_len], 
                                    pen=pg.mkPen('r', width=1), name=sample_name1,
                                    antialias=False)  # 禁用抗锯齿提高性能
        
        # 绘制文件2波形（蓝色）
        if self.file2_data and 'angle_data' in self.file2_data and 'mag_data' in self.file2_data:
            angle_data2 = self.file2_data['angle_data']
            mag_data2 = self.file2_data['mag_data']
            if len(angle_data2) > 0 and len(mag_data2) > 0:
                min_len = min(len(angle_data2), len(mag_data2))
                # 使用更细的线条和优化设置
                self.plot_widget.plot(angle_data2[:min_len], mag_data2[:min_len], 
                                    pen=pg.mkPen('b', width=1), name=sample_name2,
                                    antialias=False)  # 禁用抗锯齿提高性能
    
    def _on_plot_double_click(self, event):
        """处理绘图区域双击事件 - 重置视图"""
        if event.double():
            self.plot_widget.setXRange(0, 360)
            self.plot_widget.setYRange(-70, 70)
            logger.info("波形视图已重置到默认范围")