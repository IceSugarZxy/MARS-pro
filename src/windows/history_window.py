# -*- coding: utf-8 -*-
"""
历史数据读取窗口
用于读取和显示历史测试数据文件
"""

import os
import csv
from PyQt5.QtWidgets import QMainWindow, QTableWidgetItem, QHeaderView, QLineEdit
from PyQt5.QtCore import Qt
from PyQt5 import uic
from ui.window_operations import WindowOperations
from ui.theme import get_base_stylesheet
from core.logger import get_logger
logger = get_logger('HistoryWindow')

class HistoryWindow(QMainWindow):
    """历史数据读取窗口"""
    
    def __init__(self, measure_window=None):
        super().__init__()
        
        # 保存测量窗口引用
        self.measure_window = measure_window

        # 文件路径存储字典（键：行号，值：文件路径）
        self._file_paths = {}
        
        # 从history_window.ui文件加载界面
        ui_file_path = os.path.join(os.path.dirname(__file__), "..", "ui", "history_window.ui")
        uic.loadUi(ui_file_path, self)

        # 应用深色主题样式
        self.setStyleSheet(get_base_stylesheet())

        # 初始化窗口操作功能
        self.window_operations = WindowOperations(self)
        
        # 初始化表格
        self._init_table()
        
        # 连接按钮事件
        self._connect_buttons()
        
        # 加载历史数据文件列表
        self._load_history_files()
    
    def _init_table(self):
        """初始化表格设置"""
        # 设置表格列宽
        header = self.tableWidget_files.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)            # 样品名称
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)  # 测试员
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)  # 保存时间
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)  # 极对数
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)  # 气隙
        header.setSectionResizeMode(5, QHeaderView.Stretch)            # 备注

        # 设置表格行高
        self.tableWidget_files.verticalHeader().setDefaultSectionSize(35)
    
    def _connect_buttons(self):
        """连接按钮事件"""
        # 连接打开按钮
        self.pushButton_open.clicked.connect(self._open_button_clicked)

        # 连接刷新按钮
        self.pushButton_refresh.clicked.connect(self._refresh_button_clicked)

        # 连接关闭按钮
        self.pushButton_close.clicked.connect(self._close_button_clicked)

        # 连接表格双击事件
        self.tableWidget_files.doubleClicked.connect(self._table_double_clicked)

        # 连接搜索框文本变化事件
        self.lineEdit_sample_name.textChanged.connect(self._on_search_text_changed)
        self.lineEdit_tester.textChanged.connect(self._on_search_text_changed)
        self.lineEdit_save_time.textChanged.connect(self._on_search_text_changed)
        self.lineEdit_pole_num.textChanged.connect(self._on_search_text_changed)
        self.lineEdit_air_gap.textChanged.connect(self._on_search_text_changed)
        self.lineEdit_remark.textChanged.connect(self._on_search_text_changed)
    
    def _load_history_files(self):
        """加载历史数据文件列表"""
        try:
            # 清空表格
            self.tableWidget_files.setRowCount(0)
            self._file_paths.clear()

            # 获取保存目录 (MARS/data/plot_data)
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            save_dir = os.path.join(project_root, "data", "plot_data")

            # 检查目录是否存在
            if not os.path.exists(save_dir):
                logger.info(f"保存目录不存在: {save_dir}")
                return

            # 获取所有CSV文件
            csv_files = [f for f in os.listdir(save_dir) if f.endswith('.csv')]

            if not csv_files:
                logger.info("未找到历史数据文件")
                return

            # 按修改时间排序（最新的在前）
            csv_files.sort(key=lambda x: os.path.getmtime(os.path.join(save_dir, x)), reverse=True)

            # 获取各列搜索关键词
            search_sample_name = self.lineEdit_sample_name.text().strip().lower()
            search_tester = self.lineEdit_tester.text().strip().lower()
            search_save_time = self.lineEdit_save_time.text().strip().lower()
            search_pole_num = self.lineEdit_pole_num.text().strip().lower()
            search_air_gap = self.lineEdit_air_gap.text().strip().lower()
            search_remark = self.lineEdit_remark.text().strip().lower()

            # 读取每个文件的信息并添加到表格
            for file_name in csv_files:
                file_path = os.path.join(save_dir, file_name)
                file_info = self._read_csv_file_info(file_path)

                if file_info:
                    # 筛选匹配的文件
                    if not self._matches_search(file_info, search_sample_name, search_tester,
                                                 search_save_time, search_pole_num,
                                                 search_air_gap, search_remark):
                        continue
                    self._add_file_to_table(file_info, file_path)

            logger.info(f"加载了 {self.tableWidget_files.rowCount()} 个历史数据文件")

        except Exception as e:
            logger.info(f"加载历史数据文件时发生错误: {e}")

    def _matches_search(self, file_info, search_sample_name, search_tester, search_save_time,
                        search_pole_num, search_air_gap, search_remark):
        """检查文件信息是否匹配所有搜索条件

        Args:
            file_info: 文件信息字典
            search_sample_name: 样品名称搜索关键词
            search_tester: 测试员搜索关键词
            search_save_time: 保存时间搜索关键词
            search_pole_num: 极对数搜索关键词
            search_air_gap: 气隙搜索关键词
            search_remark: 备注搜索关键词

        Returns:
            bool: 是否所有条件都匹配
        """
        # 如果搜索框为空，默认匹配；如果有内容，则检查是否包含
        if search_sample_name and search_sample_name not in file_info.get('sample_name', '').lower():
            return False
        if search_tester and search_tester not in file_info.get('tester', '').lower():
            return False
        if search_save_time and search_save_time not in file_info.get('save_time', '').lower():
            return False
        if search_pole_num and search_pole_num not in file_info.get('pole_num', '').lower():
            return False
        if search_air_gap and search_air_gap not in file_info.get('air_gap', '').lower():
            return False
        if search_remark and search_remark not in file_info.get('remark', '').lower():
            return False
        return True

    def _on_search_text_changed(self, _text):
        """搜索框文本变化事件"""
        self._load_history_files()
    
    def _read_csv_file_info(self, file_path):
        """读取CSV文件的基本信息
        
        Args:
            file_path: CSV文件路径
            
        Returns:
            dict: 文件信息字典，包含样品名称、测试员、保存时间
        """
        try:
            file_info = {
                'sample_name': '未知样品',
                'tester': '未知测试员',
                'save_time': '未知时间',
                'pole_num': '--',
                'air_gap': '--',
                'remark': '--'
            }
            
            with open(file_path, 'r', encoding='utf-8') as csvfile:
                reader = csv.reader(csvfile)
                
                # 读取头部信息
                for row in reader:
                    if not row:  # 空行跳过
                        continue
                    
                    if len(row) >= 2:
                        key = row[0].strip()
                        value = row[1].strip()
                        
                        if key == "样品名称":
                            file_info['sample_name'] = value
                        elif key == "测试员":
                            file_info['tester'] = value
                        elif key == "保存时间":
                            file_info['save_time'] = value
                        elif key == "极数":
                            file_info['pole_num'] = value
                        elif key == "气隙":
                            file_info['air_gap'] = value
                        elif key == "备注":
                            file_info['remark'] = value
                        
                        # 如果已经读取到数据标题行，停止读取
                        if key == "角度(度)":
                            break
            
            # 如果没有找到保存时间，从文件名中提取
            if file_info['save_time'] == '未知时间':
                # 尝试从文件名中提取时间戳
                import re
                match = re.search(r'(\d{8}_\d{6})', os.path.basename(file_path))
                if match:
                    timestamp = match.group(1)
                    # 格式化时间显示
                    file_info['save_time'] = f"{timestamp[:4]}-{timestamp[4:6]}-{timestamp[6:8]} {timestamp[9:11]}:{timestamp[11:13]}:{timestamp[13:15]}"
            
            return file_info
            
        except Exception as e:
            logger.info(f"读取CSV文件信息时发生错误: {e}")
            return None
    
    def _add_file_to_table(self, file_info, file_path):
        """添加文件信息到表格

        Args:
            file_info: 文件信息字典
            file_path: 文件路径
        """
        row_position = self.tableWidget_files.rowCount()
        self.tableWidget_files.insertRow(row_position)

        # 添加样品名称
        item_sample = QTableWidgetItem(file_info['sample_name'])
        item_sample.setFlags(item_sample.flags() & ~Qt.ItemIsEditable)
        self.tableWidget_files.setItem(row_position, 0, item_sample)

        # 添加测试员
        item_tester = QTableWidgetItem(file_info['tester'])
        item_tester.setFlags(item_tester.flags() & ~Qt.ItemIsEditable)
        self.tableWidget_files.setItem(row_position, 1, item_tester)

        # 添加保存时间
        item_time = QTableWidgetItem(file_info['save_time'])
        item_time.setFlags(item_time.flags() & ~Qt.ItemIsEditable)
        self.tableWidget_files.setItem(row_position, 2, item_time)

        # 添加极对数
        item_pole = QTableWidgetItem(file_info['pole_num'])
        item_pole.setFlags(item_pole.flags() & ~Qt.ItemIsEditable)
        self.tableWidget_files.setItem(row_position, 3, item_pole)

        # 添加气隙
        item_airgap = QTableWidgetItem(file_info['air_gap'])
        item_airgap.setFlags(item_airgap.flags() & ~Qt.ItemIsEditable)
        self.tableWidget_files.setItem(row_position, 4, item_airgap)

        # 添加备注
        item_remark = QTableWidgetItem(file_info['remark'])
        item_remark.setFlags(item_remark.flags() & ~Qt.ItemIsEditable)
        self.tableWidget_files.setItem(row_position, 5, item_remark)

        # 存储文件路径到内部字典
        self._file_paths[row_position] = file_path
    
    def _open_button_clicked(self):
        """打开按钮点击事件"""
        current_row = self.tableWidget_files.currentRow()
        if current_row >= 0:
            self._open_selected_file(current_row)
        else:
            logger.info("请先选择一个文件")
    
    def _refresh_button_clicked(self):
        """刷新按钮点击事件"""
        logger.info("刷新历史数据列表")
        self._load_history_files()
    
    def _close_button_clicked(self):
        """关闭按钮点击事件"""
        logger.info("关闭历史数据窗口")
        self.hide()
    
    def _table_double_clicked(self, index):
        """表格双击事件"""
        row = index.row()
        self._open_selected_file(row)
    
    def _open_selected_file(self, row):
        """打开选中的文件

        Args:
            row: 选中的行号
        """
        try:
            # 从内部字典获取文件路径
            file_path = self._file_paths.get(row)
            if not file_path:
                logger.info("无法获取文件路径")
                return

            # 读取CSV文件数据
            angle_data, mag_data, analysis_results = self._read_csv_data(file_path)

            if angle_data and mag_data:
                # 跳转到测试界面并显示数据
                self._show_in_measure_window(file_path, angle_data, mag_data, analysis_results)

                # 关闭历史数据窗口
                self.hide()
            else:
                logger.info("读取数据失败")

        except Exception as e:
            logger.info(f"打开文件时发生错误: {e}")
    
    def _read_csv_data(self, file_path):
        """读取CSV文件中的角度、磁场数据和已保存的分析结果

        Args:
            file_path: CSV文件路径

        Returns:
            tuple: (角度数据列表, 磁场数据列表, 分析结果字典)
        """
        try:
            angle_data = []
            mag_data = []
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
                            if key == "角度(度)":
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
                            elif key == "极数":
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

            logger.info(f"从文件读取数据: 角度数据 {len(angle_data)} 点, 磁场数据 {len(mag_data)} 点, 分析结果: {len(analysis_results)} 项")
            return angle_data, mag_data, analysis_results

        except Exception as e:
            logger.info(f"读取CSV数据时发生错误: {e}")
            return [], [], {}

    def _parse_float(self, value):
        """解析浮点数，支持空值和nan"""
        if not value or value == '' or value.lower() == 'nan':
            return None
        try:
            return float(value)
        except ValueError:
            return None
    
    def _show_in_measure_window(self, file_path, angle_data, mag_data, analysis_results):
        """在测量窗口中显示数据

        Args:
            file_path: 文件路径
            angle_data: 角度数据
            mag_data: 磁场数据
            analysis_results: 已保存的分析结果字典
        """
        if self.measure_window:
            # 设置测量窗口的数据
            self.measure_window.angle_data = angle_data
            self.measure_window.mag_data = mag_data

            # 更新绘图窗口
            self.measure_window.update_plot_data(angle_data, mag_data, 'b')

            # 使用保存的分析结果直接显示
            if analysis_results:
                self.measure_window._update_display_with_results(analysis_results)
                logger.info("使用保存的分析结果显示历史数据")
            else:
                # 如果没有保存的分析结果，进行分析
                logger.info("历史数据无分析结果，重新分析...")
                enable_concentricity = self.measure_window.radioButton_Concentricity.isChecked() if self.measure_window.radioButton_Concentricity else True
                results = self.measure_window.wave_analyzer.analyze_waveform(angle_data, mag_data, enable_concentricity)
                self.measure_window._update_display_with_results(results)

            # 显示测量窗口
            self.measure_window.show_window()

            # 更新状态
            self.measure_window._update_status(f"已加载历史数据: {os.path.basename(file_path)}")

            logger.info("历史数据已加载到测量窗口")
        else:
            logger.info("测量窗口引用未设置")
    
    def show_window(self):
        """显示窗口"""
        logger.info("显示历史数据窗口")
        
        # 刷新文件列表
        self._load_history_files()
        
        if not self.isVisible():
            self.show()
        else:
            self.raise_()
            self.activateWindow()