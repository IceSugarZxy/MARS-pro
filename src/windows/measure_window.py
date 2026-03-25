# -*- coding: utf-8 -*-
"""
测试界面窗口
使用Measure.ui文件加载界面布局
"""

import os
import time
import queue
from PyQt5.QtWidgets import QMainWindow, QLabel, QPushButton, QLineEdit, QWidget, QRadioButton, QDialog
from PyQt5.QtCore import Qt, QEventLoop, QTimer
from PyQt5 import uic
from ui.window_operations import WindowOperations
from windows.plot_window import PlotWindow
from windows.wave_analysis import WaveAnalysis
from windows.measure_type_dialog import MeasureTypeDialog
from core.logger import get_logger

logger = get_logger('MeasureWindow')

class MeasureWindow(QMainWindow):
    """测试界面窗口"""
    
    def __init__(self, position_window=None, home_window=None):
        super().__init__()
        
        # 保存组件引用
        self.thread_manager = None
        self.serial_manager = None
        self.data_process = None
        self.serial_command = None
        self.position_window = position_window  # 保存position_window引用
        self.home_window = home_window  # 保存home_window引用
        
        # 位置数据查询状态
        self.position_query_completed = False
        self.position_query_result = None

        # 从measure_window.ui文件加载界面
        ui_file_path = os.path.join(os.path.dirname(__file__), "..", "ui", "measure_window.ui")
        uic.loadUi(ui_file_path, self)
        
        # 初始化窗口操作功能
        self.window_operations = WindowOperations(self)
        
        # 初始化绘图窗口
        self.plot_window = None
        self._init_plot_display()
        
        # 初始化测量数据队列（与data_process模块共享）
        self.measure_data_queue = queue.Queue()
        
        # 初始化波形分析数据
        self.angle_data = []
        self.mag_data = []
        
        # 初始化波形分析器
        self.wave_analyzer = WaveAnalysis()
        
        # 测试状态管理
        self.is_testing = False
        self.testing_label = None
        
        # 连接位置数据处理完成信号
        self._connect_position_data_signal()
        
        # 连接按钮事件
        self._connect_buttons()
        
        # 初始化显示控件
        self._init_display_controls()

        # 初始化状态自动恢复定时器（用于瞬时操作提示2秒后自动清空）
        self._status_auto_recover_timer = QTimer(self)
        self._status_auto_recover_timer.timeout.connect(self._clear_status_message)

    def _clear_status_message(self):
        """清空状态消息，恢复默认状态"""
        if self.status_label:
            self.status_label.setText("")
            self.status_label.setStyleSheet("")

    def _connect_position_data_signal(self):
        """连接位置数据处理完成信号
        
        注意：此信号连接已在 thread_manager 中处理，
        此处仅作为备用或调试使用
        """
        # 信号连接已移至 thread_manager.connect_thread_signal 中处理
        pass
    
    def _connect_buttons(self):
        """连接按钮事件"""
        # 连接标题栏按钮
        minimize_button = self.findChild(QPushButton, "pushButton_minimize")
        minimize_button.clicked.connect(self._minimize_button_clicked)
        
        maximize_button = self.findChild(QPushButton, "pushButton_maximize")
        maximize_button.clicked.connect(self._maximize_button_clicked)
        
        title_close_button = self.findChild(QPushButton, "pushButton_titleClose")
        title_close_button.clicked.connect(self._title_close_button_clicked)
        
        # 连接测量开始按钮 - 绿色
        start_rotation_button = self.findChild(QPushButton, "pushButton_startRotation")
        start_rotation_button.clicked.connect(self._start_rotation_button_clicked)
        
        # 连接停止旋转按钮 - 红色
        stop_rotation_button = self.findChild(QPushButton, "pushButton_stopRotation")
        stop_rotation_button.clicked.connect(self._stop_rotation_button_clicked)
        
        # 连接位置控制按钮 - 蓝色
        zeroing_button = self.findChild(QPushButton, "pushButton_zeroing")
        zeroing_button.clicked.connect(self._zeroing_button_clicked)
        
        # 连接测试位置按钮 - 橙色
        test_position_button = self.findChild(QPushButton, "pushButton_testPosition")
        test_position_button.clicked.connect(self._test_position_button_clicked)

        # 连接挂起位置按钮
        suspend_position_button = self.findChild(QPushButton, "pushButton_suspendPosition")
        if suspend_position_button:
            suspend_position_button.clicked.connect(self._suspend_position_button_clicked)

        # 连接保存数据按钮
        save_data_button = self.findChild(QPushButton, "pushButton_save")
        if save_data_button:
            save_data_button.clicked.connect(self._save_data_button_clicked)

        # 连接测量功能按钮
        measure_serial_button = self.findChild(QPushButton, "pushButton_measure_serial")
        if measure_serial_button:
            measure_serial_button.clicked.connect(self._measure_serial_button_clicked)

        # 连接历史记录按钮
        measure_history_button = self.findChild(QPushButton, "pushButton_measure_history")
        if measure_history_button:
            measure_history_button.clicked.connect(self._measure_history_button_clicked)

        # 连接设置按钮
        measure_setting_button = self.findChild(QPushButton, "pushButton_measure_setting")
        if measure_setting_button:
            measure_setting_button.clicked.connect(self._measure_setting_button_clicked)

        # 连接对比按钮
        measure_compare_button = self.findChild(QPushButton, "pushButton_measure_compare")
        if measure_compare_button:
            measure_compare_button.clicked.connect(self._measure_compare_button_clicked)

        # 连接方向控制按钮
        up_button = self.findChild(QPushButton, "pushButton_up")
        if up_button:
            up_button.clicked.connect(self._up_button_clicked)

        down_button = self.findChild(QPushButton, "pushButton_down")
        if down_button:
            down_button.clicked.connect(self._down_button_clicked)

        left_button = self.findChild(QPushButton, "pushButton_left")
        if left_button:
            left_button.clicked.connect(self._left_button_clicked)

        right_button = self.findChild(QPushButton, "pushButton_right")
        if right_button:
            right_button.clicked.connect(self._right_button_clicked)

        # 初始化同心度校准控件
        self.radioButton_Concentricity = self.findChild(QRadioButton, "radioButton_Concentricity")
    
    
    def _init_display_controls(self):
        """初始化显示控件"""
        # 测试员
        self.tester_edit = self.findChild(QLineEdit, "lineEdit_tester")
        # 磁化条件
        self.mag_condition_edit = self.findChild(QLineEdit, "lineEdit_magCondition")
        # 探头
        self.probe_edit = self.findChild(QLineEdit, "lineEdit_probe")
        # 样品编号
        self.sample_code_edit = self.findChild(QLineEdit, "lineEdit_sampleCode")
        # 样品名称
        self.sample_name_edit = self.findChild(QLineEdit, "lineEdit_sampleName")
        # 材料
        self.material_edit = self.findChild(QLineEdit, "lineEdit_material")
        # 极数
        self.polar_num_edit = self.findChild(QLineEdit, "lineEdit_polarNum")
        # 备注
        self.remark_edit = self.findChild(QLineEdit, "lineEdit_remark")
        # 气隙
        self.airgap_edit = self.findChild(QLineEdit, "lineEdit_arigap")
        # 磁强计（默认值）
        self.magnetometer_edit = None
        # 磁化器（默认值）
        self.magnetizer_edit = None
        
        # 状态显示标签
        self.status_label = self.findChild(QLabel, "label_status")
        
        # 测量结果显示控件（按照指定顺序）
        # N极相关
        self.n_max_edit = self.findChild(QLineEdit, "lineEdit_NmaxValue")
        self.n_min_edit = self.findChild(QLineEdit, "lineEdit_NminValue")
        self.n_mean_edit = self.findChild(QLineEdit, "lineEdit_NmeanValue")
        self.n_se_edit = self.findChild(QLineEdit, "lineEdit_NerrorValue")
        
        # S极相关
        self.s_max_edit = self.findChild(QLineEdit, "lineEdit_SmaxValue")
        self.s_min_edit = self.findChild(QLineEdit, "lineEdit_SminValue")
        self.s_mean_edit = self.findChild(QLineEdit, "lineEdit_SmeanValue")
        self.s_se_edit = self.findChild(QLineEdit, "lineEdit_SerrorValue")
        
        # NS相关
        self.ns_2_edit = self.findChild(QLineEdit, "lineEdit_NS2")
        self.single_polar_mean_edit = self.findChild(QLineEdit, "lineEdit_SinglePolarMean")
        self.single_polar_error_edit = self.findChild(QLineEdit, "lineEdit_SinglePolarError")
        self.polar_error_sum_edit = self.findChild(QLineEdit, "lineEdit_PolarErrorSum")
        
        # 极间隔统计
        self.n_interval_max_edit = self.findChild(QLineEdit, "lineEdit_NmaxValue_2")
        self.n_interval_min_edit = self.findChild(QLineEdit, "lineEdit_NminValue_2")
        self.n_interval_mean_edit = self.findChild(QLineEdit, "lineEdit_NmeanValue_2")
        self.n_interval_std_edit = self.findChild(QLineEdit, "lineEdit_NerrorValue_2")
        
        self.s_interval_max_edit = self.findChild(QLineEdit, "lineEdit_SmaxValue_2")
        self.s_interval_min_edit = self.findChild(QLineEdit, "lineEdit_SminValue_2")
        self.s_interval_mean_edit = self.findChild(QLineEdit, "lineEdit_SmeanValue_2")
        self.s_interval_std_edit = self.findChild(QLineEdit, "lineEdit_SerrorValue_2")
        
        # 面积相关
        self.n_area_edit = self.findChild(QLineEdit, "lineEdit_NareaValue")
        self.s_area_edit = self.findChild(QLineEdit, "lineEdit_SareaValue")
        self.thd_error_edit = self.findChild(QLineEdit, "lineEdit_THDerrorValue")
        self.ns_area_edit = self.findChild(QLineEdit, "lineEdit_NSareaValue")
        
        # 距离输入框
        self.distance_edit = self.findChild(QLineEdit, "lineEdit_distance")

        # 初始化样品信息默认值
        self._set_input_defaults()

        # 初始化结果显示默认值
        self._update_display_defaults()

    def _set_input_defaults(self):
        """设置输入框的默认值（仅在初始化时调用）"""
        self.tester_edit.setText("测试员")
        self.mag_condition_edit.setText("标准条件")
        self.probe_edit.setText("标准探头")
        self.sample_code_edit.setText("样品")
        self.sample_name_edit.setText("测试样品")
        self.material_edit.setText("磁性材料")
        self.polar_num_edit.setText("")
        self.remark_edit.setText("测试备注")
        self.airgap_edit.setText("--")

    def _update_display_defaults(self):
        """更新显示默认值 - 只重置结果显示区域，不重置样品信息输入框"""
        # 设置距离输入框默认值（单位：mm）
        if self.distance_edit:
            self.distance_edit.setText("1")

        # 设置结果显示默认值（按照指定顺序）
        # N极相关
        self.n_max_edit.setText("0.00")
        self.n_min_edit.setText("0.00")
        self.n_mean_edit.setText("0.00")
        self.n_se_edit.setText("0.00")

        # S极相关
        self.s_max_edit.setText("0.00")
        self.s_min_edit.setText("0.00")
        self.s_mean_edit.setText("0.00")
        self.s_se_edit.setText("0.00")

        # NS相关
        self.ns_2_edit.setText("0.00")
        self.single_polar_mean_edit.setText("0.00")
        self.single_polar_error_edit.setText("0.00")
        self.polar_error_sum_edit.setText("0.00")

        # 极间隔统计
        self.n_interval_max_edit.setText("0.00")
        self.n_interval_min_edit.setText("0.00")
        self.n_interval_mean_edit.setText("0.00")
        self.n_interval_std_edit.setText("0.00")

        self.s_interval_max_edit.setText("0.00")
        self.s_interval_min_edit.setText("0.00")
        self.s_interval_mean_edit.setText("0.00")
        self.s_interval_std_edit.setText("0.00")

        # 面积相关
        self.n_area_edit.setText("0.00")
        self.s_area_edit.setText("0.00")
        self.thd_error_edit.setText("0.00")
        self.ns_area_edit.setText("0.00")

    def _reset_sample_inputs(self):
        """重置样品信息输入框为默认值"""
        self.sample_code_edit.setText("样品")
        self.sample_name_edit.setText("测试样品")
        self.material_edit.setText("磁性材料")
        self.airgap_edit.setText("--")
        self.remark_edit.setText("测试备注")
        self.tester_edit.setText("测试员")
        self.mag_condition_edit.setText("标准条件")
        self.probe_edit.setText("标准探头")
        self.polar_num_edit.setText("")

        # 设置结果显示默认值（按照指定顺序）
        # N极相关
        self.n_max_edit.setText("0.00")
        self.n_min_edit.setText("0.00")
        self.n_mean_edit.setText("0.00")
        self.n_se_edit.setText("0.00")
        
        # S极相关
        self.s_max_edit.setText("0.00")
        self.s_min_edit.setText("0.00")
        self.s_mean_edit.setText("0.00")
        self.s_se_edit.setText("0.00")
        
        # NS相关
        self.ns_2_edit.setText("0.00")
        self.single_polar_mean_edit.setText("0.00")
        self.single_polar_error_edit.setText("0.00")
        self.polar_error_sum_edit.setText("0.00")
        
        # 极间隔统计
        self.n_interval_max_edit.setText("0.00")
        self.n_interval_min_edit.setText("0.00")
        self.n_interval_mean_edit.setText("0.00")
        self.n_interval_std_edit.setText("0.00")
        
        self.s_interval_max_edit.setText("0.00")
        self.s_interval_min_edit.setText("0.00")
        self.s_interval_mean_edit.setText("0.00")
        self.s_interval_std_edit.setText("0.00")
        
        # 面积相关
        self.n_area_edit.setText("0.00")
        self.s_area_edit.setText("0.00")
        self.thd_error_edit.setText("0.00")
        self.ns_area_edit.setText("0.00")
    
    def _minimize_button_clicked(self):
        """最小化按钮点击事件"""
        logger.info("最小化按钮被点击")
        self.showMinimized()
    
    def _maximize_button_clicked(self):
        """最大化按钮点击事件"""
        logger.info("最大化按钮被点击")
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()
    
    def _title_close_button_clicked(self):
        """标题栏关闭按钮点击事件"""
        logger.info("标题栏关闭按钮被点击")
        self.close()
    
    def _start_rotation_button_clicked(self):
        """测量开始按钮点击事件"""
        logger.info("测量开始按钮被点击")

        # 检查串口是否连接
        if not self.serial_manager or not self.serial_manager.get_connection_status():
            error_msg = "错误：串口未连接，请先连接串口"
            logger.error(error_msg)
            self._update_status(error_msg, is_error=True)
            # 测试失败，恢复界面
            self._end_test()
            return

        # 弹出测量类型选择对话框
        dialog = MeasureTypeDialog(self)
        result = dialog.exec_()

        if result != QDialog.Accepted or not dialog.get_measure_type():
            logger.info("用户取消选择测量类型")
            return

        measure_type = dialog.get_measure_type()
        vertical_distance = dialog.get_vertical_distance()

        # 重置样品信息输入框
        self._reset_sample_inputs()

        # 设置测量类型到数据处理器
        self.data_process.measure_type = measure_type

        # 设置样品信息到数据处理器
        sample_info = {
            'sample_code': self.sample_code_edit.text().strip() if self.sample_code_edit else '',
            'sample_name': self.sample_name_edit.text().strip() if self.sample_name_edit else '',
            'material': self.material_edit.text().strip() if self.material_edit else '',
            'coil_code': self.airgap_edit.text().strip() if self.airgap_edit else '',
            'remark': self.remark_edit.text().strip() if self.remark_edit else '',
            'tester': self.tester_edit.text().strip() if self.tester_edit else '',
            'mag_condition': self.mag_condition_edit.text().strip() if self.mag_condition_edit else '',
            'probe': self.probe_edit.text().strip() if self.probe_edit else '',
            'polar_num': self.polar_num_edit.text().strip() if self.polar_num_edit else '',
            'magnetometer': self.magnetometer_edit if self.magnetometer_edit else '',
            'magnetizer': self.magnetizer_edit if self.magnetizer_edit else '',
        }
        self.data_process.set_sample_info(sample_info)

        # 设置测试状态
        self.is_testing = True
        
        # 重置界面
        self._reset_test_interface()
        
        # 显示测试中提示
        self._show_testing_indicator()
        
        # 禁用功能按钮（除停止按钮外）
        self._disable_function_buttons()
        
        # 清除绘图数据
        self.clear_plot()
        
        # 清空数据队列
        while not self.measure_data_queue.empty():
            try:
                self.measure_data_queue.get_nowait()
            except queue.Empty:
                break
        
        # 更新状态
        self._update_status("正在测量...")

        # 根据测量类型发送不同指令
        if measure_type == "vertical":
            # 垂直测量：发送Z轴相对脉冲移动指令 N<num>~
            if self.serial_command and self.serial_manager.get_connection_status():
                self.serial_command.vertical_move(vertical_distance)
                logger.info(f"已发送垂直移动指令: N{vertical_distance}~")
            else:
                logger.info("串口未连接，跳过指令发送，直接测试数据处理")
        else:
            # 旋转测量：发送爪盘旋转指令 "B~"
            if self.serial_command and self.serial_manager.get_connection_status():
                self.serial_command.claw_rotate()
                logger.info("已发送爪盘旋转指令")
            else:
                logger.info("串口未连接，跳过指令发送，直接测试数据处理")
            
        # 清空队列，确保之前的数据不会干扰
        self.data_process.clear_data_queue()

        # 触发测量数据处理信号
        self.data_process.signal_measure_data_process.emit()
    
    def _stop_rotation_button_clicked(self):
        """停止旋转按钮点击事件"""
        logger.info("停止旋转按钮被点击")
        if self.serial_command:
            self.serial_command.claw_stop()
        
        # 结束测试并恢复界面
        self._end_test()
    
    def _close_button_clicked(self):
        """关闭窗口按钮点击事件"""
        logger.info("关闭测试窗口")
        self.hide()
    
    def _zeroing_button_clicked(self):
        """零位校准按钮点击事件"""
        logger.info("零位校准按钮被点击")
        if self.serial_command:
            self.serial_command.slider_reset()
    
    def _test_position_button_clicked(self):
        """测试位置按钮点击事件"""
        logger.info("测试位置按钮被点击")
        if self.serial_command:
            self.serial_command.test_position()

    def _suspend_position_button_clicked(self):
        """挂起位置按钮点击事件"""
        logger.info("挂起位置按钮被点击")
        if self.serial_command:
            self.serial_command.suspend_position(self)

    def _save_data_button_clicked(self):
        """保存数据按钮点击事件"""
        logger.info("保存数据按钮被点击")
        self._update_status("正在保存数据...", auto_recover=True)
        success = self.save_plot_data()
        if success:
            logger.info("数据保存成功")
            self._update_status("数据保存成功", is_error=False)
        else:
            logger.info("数据保存失败")
            self._update_status("数据保存失败", is_error=True)
    
    def _measure_serial_button_clicked(self):
        """串口按钮点击事件 - 同步home界面的串口设置功能"""
        logger.info("串口按钮被点击")
        self._update_status("打开串口设置...", auto_recover=True)
        
        if self.home_window and hasattr(self.home_window, 'serial_window'):
            if self.home_window.serial_window:
                if not self.home_window.serial_window.isVisible():
                    self.home_window.serial_window.show()
                else:
                    # 如果窗口已经显示，则将其置顶
                    self.home_window.serial_window.raise_()
                    self.home_window.serial_window.activateWindow()
        else:
            logger.info("串口窗口引用未设置")
        
    def _measure_history_button_clicked(self):
        """数据按钮点击事件 - 同步home界面的历史数据功能"""
        logger.info("数据按钮被点击")
        self._update_status("打开数据历史...", auto_recover=True)
        
        if self.home_window and hasattr(self.home_window, 'history_window'):
            if self.home_window.history_window:
                # 调用历史数据窗口的show_window方法
                self.home_window.history_window.show_window()
            else:
                logger.info("历史数据窗口引用未设置")
        else:
            logger.info("home_window引用未设置")
        
    def _measure_setting_button_clicked(self):
        """设置按钮点击事件 - 同步home界面的测试位置功能"""
        logger.info("设置按钮被点击")
        self._update_status("打开测试位置...", auto_recover=True)
        
        if self.home_window and hasattr(self.home_window, 'position_window'):
            if self.home_window.position_window:
                # 调用位置窗口的show_window方法，该方法会启动定时器
                self.home_window.position_window.show_window()
            else:
                logger.info("位置窗口引用未设置")
        else:
            logger.info("home_window引用未设置")
        
    def _measure_compare_button_clicked(self):
        """对比按钮点击事件 - 同步home界面的数据比对功能"""
        logger.info("对比按钮被点击")
        self._update_status("打开数据对比...", auto_recover=True)
        
        if self.home_window and hasattr(self.home_window, 'compare_window'):
            if self.home_window.compare_window:
                # 调用数据比对窗口的show_window方法
                self.home_window.compare_window.show_window()
            else:
                logger.info("数据比对窗口引用未设置")
        else:
            logger.info("home_window引用未设置")
    
    def _up_button_clicked(self):
        """上按钮点击事件 - Z轴向上移动"""
        logger.info("上按钮被点击")

        distance = self._get_distance_value()
        if distance is None:
            return

        self._update_status("向上移动...", auto_recover=True)
        # 设置任务并发送位置查询，等位置处理完成后再执行移动
        self.serial_command.set_move_task('Z', -1, distance)
        self.serial_command.position_query()

    def _down_button_clicked(self):
        """下按钮点击事件 - Z轴向下移动"""
        logger.info("下按钮被点击")

        distance = self._get_distance_value()
        if distance is None:
            return

        self._update_status("向下移动...", auto_recover=True)
        self.serial_command.set_move_task('Z', 1, distance)
        self.serial_command.position_query()

    def _left_button_clicked(self):
        """左按钮点击事件 - X轴向左移动"""
        logger.info("左按钮被点击")

        distance = self._get_distance_value()
        if distance is None:
            return

        self._update_status("向左移动...", auto_recover=True)
        self.serial_command.set_move_task('X', 1, distance)
        self.serial_command.position_query()

    def _right_button_clicked(self):
        """右按钮点击事件 - X轴向右移动"""
        logger.info("右按钮被点击")

        distance = self._get_distance_value()
        if distance is None:
            return

        self._update_status("向右移动...", auto_recover=True)
        self.serial_command.set_move_task('X', -1, distance)
        self.serial_command.position_query()

    def _get_distance_value(self):
        """获取距离输入框的值（单位：mm）

        Returns:
            float: 距离值，单位mm
        """
        if not self.distance_edit:
            logger.info("距离输入框未初始化")
            return None

        try:
            # 获取输入文本
            distance_text = self.distance_edit.text().strip()

            if not distance_text:
                logger.info("距离值为空，请先输入距离值")
                self._update_status("错误：距离值为空", is_error=True)
                return None

            # 输入为mm单位
            mm_value = float(distance_text)

            if mm_value <= 0:
                logger.info(f"距离值必须大于0，当前值: {mm_value}")
                self._update_status("错误：距离值必须大于0", is_error=True)
                return None

            logger.info(f"获取距离值: {mm_value}mm")
            return mm_value

        except ValueError:
            logger.info(f"距离值格式错误: {self.distance_edit.text()}")
            self._update_status("错误：距离值格式错误", is_error=True)
            return None
    
    def _reset_test_interface(self):
        """重置测试界面"""
        logger.info("重置测试界面")
        
        # 重置结果显示为默认值
        self._update_display_defaults()
        
        # 清除绘图数据
        self.clear_plot()
        
        # 清空波形分析数据
        self.angle_data = []
        self.mag_data = []
    
    def _show_testing_indicator(self):
        """在窗口上层显示测试中提示"""
        # 清除之前的提示
        self._hide_testing_indicator()
        
        # 创建QLabel显示"测试中..."文字
        self.testing_label = QLabel("测试中...", self)
        
        # 设置样式
        self.testing_label.setStyleSheet("""
            QLabel {
                background-color: rgba(255, 255, 255, 200);
                color: red;
                font-size: 24px;
                font-weight: bold;
                border: 2px solid red;
                border-radius: 10px;
                padding: 20px;
            }
        """)
        
        # 设置对齐方式
        self.testing_label.setAlignment(Qt.AlignCenter)
        
        # 根据窗口尺寸确定位置和大小
        window_width = self.width()
        window_height = self.height()
        
        # 设置标签大小（约为窗口的1/3）
        label_width = window_width // 3
        label_height = window_height // 6
        
        # 计算居中位置
        label_x = (window_width - label_width) // 2
        label_y = (window_height - label_height) // 2
        
        # 设置位置和大小
        self.testing_label.setGeometry(label_x, label_y, label_width, label_height)
        
        # 显示标签
        self.testing_label.show()
        self.testing_label.raise_()  # 置顶显示
        
        logger.info("显示测试中提示")
    
    def _hide_testing_indicator(self):
        """隐藏测试中提示"""
        if self.testing_label:
            self.testing_label.hide()
            self.testing_label.deleteLater()
            self.testing_label = None
            logger.info("隐藏测试中提示")
    
    def _disable_function_buttons(self):
        """禁用功能按钮（除停止旋转按钮外）"""
        logger.info("禁用功能按钮")
        
        # 获取所有需要禁用的按钮
        buttons_to_disable = [
            "pushButton_startRotation",  # 开始旋转
            "pushButton_zeroing",         # 零位校准
            "pushButton_testPosition",    # 测试位置
            "pushButton_suspendPosition", # 挂起位置
            "pushButton_save"            # 保存数据
        ]
        
        for button_name in buttons_to_disable:
            button = self.findChild(QPushButton, button_name)
            if button:
                button.setEnabled(False)
    
    def _enable_function_buttons(self):
        """启用所有功能按钮"""
        logger.info("启用功能按钮")
        
        # 获取所有需要启用的按钮
        buttons_to_enable = [
            "pushButton_startRotation",  # 开始旋转
            "pushButton_zeroing",         # 零位校准
            "pushButton_testPosition",    # 测试位置
            "pushButton_suspendPosition", # 挂起位置
            "pushButton_save"            # 保存数据
        ]
        
        for button_name in buttons_to_enable:
            button = self.findChild(QPushButton, button_name)
            if button:
                button.setEnabled(True)
    
    def _end_test(self):
        """结束测试并恢复界面"""
        logger.info("结束测试")
        
        # 重置测试状态
        self.is_testing = False
        
        # 隐藏测试中提示
        self._hide_testing_indicator()
        
        # 启用所有功能按钮
        self._enable_function_buttons()
    
    def _update_status(self, message, is_error=False, auto_recover=False):
        """更新状态标签显示

        Args:
            message: 要显示的消息
            is_error: 是否为错误信息
            auto_recover: 是否自动恢复（1秒后清空），用于瞬时操作提示
        """
        if self.status_label:
            # 设置消息文本
            self.status_label.setText(message)

            # 根据消息类型设置样式
            if is_error:
                self.status_label.setStyleSheet("color: red; font-weight: bold;")
            else:
                self.status_label.setStyleSheet("color: green; font-weight: bold;")

            # 停止之前的自动恢复定时器（除非明确要求自动恢复）
            if not auto_recover:
                if hasattr(self, '_status_auto_recover_timer') and self._status_auto_recover_timer.isActive():
                    self._status_auto_recover_timer.stop()

            # 如果设置了自动恢复，启动定时器
            if auto_recover:
                if hasattr(self, '_status_auto_recover_timer') and self._status_auto_recover_timer.isActive():
                    self._status_auto_recover_timer.stop()
                self._status_auto_recover_timer.start(1000)
            # logger.info(f"状态更新: {message}")
        else:
            logger.info(f"状态标签未找到，消息: {message}")

    def _collect_sample_info_from_ui(self) -> dict:
        """
        从界面收集样品信息

        Returns:
            包含所有样品信息的字典
        """
        return {
            'sample_code': self.sample_code_edit.text().strip() if self.sample_code_edit else '',
            'sample_name': self.sample_name_edit.text().strip() if self.sample_name_edit else '',
            'material': self.material_edit.text().strip() if self.material_edit else '',
            'coil_code': self.airgap_edit.text().strip() if self.airgap_edit else '',
            'remark': self.remark_edit.text().strip() if self.remark_edit else '',
            'tester': self.tester_edit.text().strip() if self.tester_edit else '',
            'mag_condition': self.mag_condition_edit.text().strip() if self.mag_condition_edit else '',
            'probe': self.probe_edit.text().strip() if self.probe_edit else '',
            'polar_num': self.polar_num_edit.text().strip() if self.polar_num_edit else '',
        }

    def _get_lift_value(self):
        """获取提离值"""
        try:
            # 使用已存在的position_window实例来获取提离值
            if self.position_window:
                # 获取提离值（position_window已经计算了实际提离参数）
                actual_lift_parameter = self.position_window._get_lift_value()
                
                if actual_lift_parameter is not None:
                    return actual_lift_parameter
                else:
                    logger.info("无法获取有效的提离值，使用默认值1000.0")
                    return 1000.0
            else:
                logger.info("position_window实例未设置，使用默认值1000.0")
                return 1000.0
                
        except Exception as e:
            logger.info(f"获取提离值时出错: {e}, 使用默认值1000.0")
            return 1000.0
    
    def show_window(self):
        """显示窗口"""
        logger.info(f"显示测试窗口，当前窗口可见性: {self.isVisible()}")
        
        # 检查线程管理器是否已设置
        if not self.thread_manager:
            logger.info("警告：线程管理器未设置，窗口将显示但部分功能可能不可用")
            # 即使线程管理器未设置，也允许显示窗口
        else:
            # 初始化组件引用
            if not self.serial_manager:
                self.serial_manager = self.thread_manager.serial_manager
            if not self.data_process:
                self.data_process = self.thread_manager.data_process
            if not self.serial_command:
                self.serial_command = self.thread_manager.serial_command
        
        if not self.isVisible():
            self.show()
            logger.info("测试窗口已显示")
        else:
            self.raise_()
            self.activateWindow()
        
        # 设置距离输入框居中显示
        if self.distance_edit:
            self.distance_edit.setAlignment(Qt.AlignCenter)
            logger.info("测试窗口已置顶")

    def _init_plot_display(self):
        """初始化绘图显示窗口"""
        # 查找widget_plot_display控件
        plot_display_widget = self.findChild(QWidget, "widget_plot_display")
        
        if plot_display_widget:
            # 创建绘图窗口实例
            self.plot_window = PlotWindow()
            
            # 使用plot_window的初始化方法
            self.plot_window.init_plot_display(plot_display_widget)
            
            # 连接绘图窗口的信号
            self.plot_window.plot_double_clicked.connect(self._on_plot_double_clicked)
            
            logger.info("绘图窗口初始化完成")
        else:
            logger.info("未找到widget_plot_display控件")
    
    def _on_plot_double_clicked(self):
        """处理绘图区域双击事件"""
        logger.info("绘图区域被双击，视图已重置")
    
    def update_plot_data(self, angle_data=None, mag_data=None, color='r'):
        """更新绘图数据
        
        Args:
            angle_data: 角度数据列表
            mag_data: 磁场数据列表
            color: 曲线颜色
        """
        if self.plot_window:
            self.plot_window.update_plot(angle_data, mag_data, color)
    
    def clear_plot(self):
        """清除绘图数据"""
        if self.plot_window:
            self.plot_window.clear_plot()
    
    def reset_plot_view(self):
        """重置绘图视图到初始状态"""
        if self.plot_window:
            self.plot_window.reset_plot_view()

    def _process_measure_data(self):
        """处理测量数据"""
        logger.info("开始处理测量数据...")
        
        # 连接数据接收状态信号
        self.measure_data_processor.data_receiving.connect(self._on_data_receiving_status_changed)
        
        # 使用持续数据处理方法
        angle_data, mag_data = self.measure_data_processor.process_raw_data_continuous(
            self.measure_data_queue, 
            self._on_new_data_received
        )
        
        # 发射数据处理完成信号
        self.measure_data_processor.data_processed.emit(angle_data, mag_data)
    
    def _on_measure_data_progress(self, current_count, total_count):
        """测量数据进度信号处理"""
        # 计算百分比
        if total_count > 0:
            percentage = min(100, round(current_count / total_count * 100, 1))
            status_msg = f"正在测量... {percentage}%"
        else:
            status_msg = f"正在测量... 已处理数据量: {current_count}"
        self._update_status(status_msg)
    
    def _on_measure_data_processed(self, angle_data, mag_data):
        """测量数据处理完成信号处理"""
        status_msg = f"测量数据处理完成"
        logger.info(status_msg)
        self._update_status(status_msg)

        # 保存数据用于波形分析
        self.angle_data = angle_data
        self.mag_data = mag_data

        # 更新绘图窗口
        if angle_data and mag_data:
            self.update_plot_data(angle_data, mag_data, 'r')
            logger.info("绘图数据已更新")

            # 根据测量类型决定是否进行波形分析
            if self.data_process.measure_type == "vertical":
                # 垂直测量：直接完成，不做分析，不保存数据
                sample_info = self._collect_sample_info_from_ui()
                self.data_process.set_sample_info(sample_info)
                success_msg = "垂直测量完成"
                self._update_status(success_msg)
            else:
                # 旋转测量：进行波形分析
                self._update_status("数据处理中...")
                enable_concentricity = self.radioButton_Concentricity.isChecked() if self.radioButton_Concentricity else True
                results = self.wave_analyzer.analyze_waveform(angle_data, mag_data, enable_concentricity)

                # 更新显示结果
                self._update_display_with_results(results)

                # 更新样品信息（从界面获取最新值，包含分析后的极对数等）
                sample_info = self._collect_sample_info_from_ui()
                sample_info['polar_num'] = results.get('pole_num', '') if results else ''
                self.data_process.set_sample_info(sample_info)

                # 波形绘制和数据分析全部完成，结束测试
                success_msg = "测试完成，数据已分析并显示"
                self._update_status(success_msg)

            self._end_test()
        else:
            warning_msg = "警告：处理后的数据为空"
            logger.warning(warning_msg)
            self._update_status(warning_msg, is_error=True)
            # 数据为空，也结束测试
            self._end_test()


    
    def _update_display_with_results(self, results):
        """使用分析结果更新显示控件
        
        Args:
            results: 波形分析结果字典
        """
        if not results:
            error_msg = "波形分析结果为空，无法更新显示"
            logger.error(error_msg)
            self._update_status(error_msg, is_error=True)
            return
        
        try:
            # 按照指定顺序更新显示控件
            # N极相关
            self.n_max_edit.setText(f"{results['N_max']:.2f}")
            self.n_min_edit.setText(f"{results['N_min']:.2f}")
            self.n_mean_edit.setText(f"{results['N_mean']:.2f}")
            self.n_se_edit.setText(f"{results['N_se']:.2f}")
            
            # S极相关
            self.s_max_edit.setText(f"{results['S_max']:.2f}")
            self.s_min_edit.setText(f"{results['S_min']:.2f}")
            self.s_mean_edit.setText(f"{results['S_mean']:.2f}")
            self.s_se_edit.setText(f"{results['S_se']:.2f}")
            
            # NS相关
            self.ns_2_edit.setText(f"{results['NS_2']:.2f}")
            self.single_polar_mean_edit.setText(f"{results['SinglePolarMean']:.2f}")
            self.single_polar_error_edit.setText(f"{results['SinglePolarError']:.2f}")
            self.polar_error_sum_edit.setText(f"{results['PolarErrorSum']:.2f}")
            
            # 极间隔统计
            self.n_interval_max_edit.setText(f"{results['N_interval_max']:.2f}")
            self.n_interval_min_edit.setText(f"{results['N_interval_min']:.2f}")
            self.n_interval_mean_edit.setText(f"{results['N_interval_mean']:.2f}")
            self.n_interval_std_edit.setText(f"{results['N_interval_std']:.2f}")
            
            self.s_interval_max_edit.setText(f"{results['S_interval_max']:.2f}")
            self.s_interval_min_edit.setText(f"{results['S_interval_min']:.2f}")
            self.s_interval_mean_edit.setText(f"{results['S_interval_mean']:.2f}")
            self.s_interval_std_edit.setText(f"{results['S_interval_std']:.2f}")
            
            # 面积相关
            self.n_area_edit.setText(f"{results['N_area']:.2f}")
            self.s_area_edit.setText(f"{results['S_area']:.2f}")
            self.thd_error_edit.setText(f"{results['THD_error']:.5f}")
            self.ns_area_edit.setText(f"{results['NS_area']:.2f}")

            # 极对数
            pole_num = results.get('pole_num')
            if pole_num is not None and isinstance(pole_num, (int, float)):
                try:
                    self.polar_num_edit.setText(str(int(pole_num)))
                except (ValueError, TypeError):
                    self.polar_num_edit.setText("--")
            else:
                self.polar_num_edit.setText("--")

            success_msg = "波形分析结果显示已更新"
            logger.info(success_msg)
            self._update_status(success_msg)
            
        except Exception as e:
            error_msg = f"更新显示结果时发生错误: {e}"
            logger.error(error_msg)
            self._update_status(error_msg, is_error=True)
    
    def _query_position(self):
        """查询位置信息"""
        # 检查窗口是否显示
        if not self.isVisible():
            logger.info("位置查询触发，但测试窗口已隐藏")
            return
        
        # 检查串口是否连接
        if not self.serial_manager or not self.serial_manager.get_connection_status():
            logger.info("位置查询触发，但串口未连接")
            return
        
        # 发送位置查询命令
        if self.serial_command:
            self.serial_command.position_query()
            logger.info("位置查询指令已发送")
        else:
            logger.info("串口命令管理器未初始化，无法查询位置")

    def save_plot_data(self):
        """保存绘图数据到CSV文件
        
        将当前绘制的角度和磁场数据保存到data/plot_data目录中
        文件命名格式：样品名称_时间戳.csv
        """
        try:
            # 检查是否有数据可保存
            if len(self.angle_data) == 0 or len(self.mag_data) == 0:
                warning_msg = "警告：没有绘图数据可保存"
                logger.warning(warning_msg)
                self._update_status(warning_msg, is_error=True)
                return False
            
            # 创建保存目录（项目根目录/MARS/data/plot_data）
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            save_dir = os.path.join(project_root, "data", "plot_data")
            os.makedirs(save_dir, exist_ok=True)
            
            # 获取样品名称
            sample_name = self.sample_name_edit.text().strip()
            if not sample_name:
                sample_name = "未知样品"
            
            # 生成时间戳（精确到秒）
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            
            # 生成文件名
            filename = f"{sample_name}_{timestamp}.csv"
            file_path = os.path.join(save_dir, filename)
            
            # 获取当前界面输入值
            tester = self.tester_edit.text()
            mag_condition = self.mag_condition_edit.text()
            probe = self.probe_edit.text()
            sample_code = self.sample_code_edit.text()
            material = self.material_edit.text()
            polar_num = self.polar_num_edit.text()
            remark = self.remark_edit.text()
            coil_code = self.airgap_edit.text()

            # 写入CSV文件
            with open(file_path, 'w', encoding='utf-8', newline='') as csvfile:
                import csv
                writer = csv.writer(csvfile)

                # 写入头部信息
                writer.writerow(["样品名称", sample_name])
                writer.writerow(["测试员", tester])
                writer.writerow(["磁化条件", mag_condition])
                writer.writerow(["探头", probe])
                writer.writerow(["样品编号", sample_code])
                writer.writerow(["材料", material])
                writer.writerow(["极数", polar_num])
                writer.writerow(["备注", remark])
                writer.writerow(["气隙", coil_code])
                writer.writerow(["保存时间", timestamp])
                writer.writerow([])  # 空行分隔
                
                # 写入数据标题
                writer.writerow(["角度(度)", "磁场强度"])
                
                # 写入数据
                for angle, mag in zip(self.angle_data, self.mag_data):
                    writer.writerow([f"{angle:.6f}", f"{mag:.5f}"])
            
            success_msg = f"绘图数据已保存到: {file_path}"
            logger.info(success_msg)
            logger.info(f"数据点数: {len(self.angle_data)}")
            self._update_status(success_msg)
            return True
            
        except Exception as e:
            error_msg = f"保存绘图数据时发生错误: {e}"
            logger.error(error_msg)
            self._update_status(error_msg, is_error=True)
            return False