# -*- coding: utf-8 -*-
"""
测量面板 - 作为单窗口架构的测量界面
"""

import os
import queue
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QLabel, QPushButton, QLineEdit,
                              QHBoxLayout, QGridLayout, QGroupBox, QRadioButton, QDialog,
                              QFrame)
from PyQt5.QtCore import Qt, QTimer
from core.logger import get_logger
from windows.plot_window import PlotWindow
from windows.wave_analysis import WaveAnalysis
from windows.measure_type_dialog import MeasureTypeDialog

logger = get_logger('MeasurePanel')


class MeasurePanel(QWidget):
    """测量面板"""

    def __init__(self):
        super().__init__()
        self.thread_manager = None
        self.serial_manager = None
        self.data_process = None
        self.serial_command = None

        # 位置数据查询状态
        self.position_query_completed = False
        self.position_query_result = None

        # 初始化绘图窗口
        self.plot_window = None

        # 初始化测量数据队列
        self.measure_data_queue = queue.Queue()

        # 初始化波形分析数据
        self.angle_data = []
        self.mag_data = []

        # 初始化波形分析器
        self.wave_analyzer = WaveAnalysis()

        # 测试状态管理
        self.is_testing = False
        self.testing_label = None

        # 初始化状态自动恢复定时器
        self._status_auto_recover_timer = QTimer(self)
        self._status_auto_recover_timer.timeout.connect(self._clear_status_message)

        self._setup_ui()

    def _setup_ui(self):
        """构建UI"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(16)

        # 标题
        title = QLabel("测量界面")
        title.setObjectName("panel_title")
        main_layout.addWidget(title)

        # 快捷操作区
        action_group = QGroupBox("快捷操作")
        action_layout = QGridLayout(action_group)

        self.start_rotation_btn = QPushButton("开始测量")
        self.start_rotation_btn.setObjectName("btnSuccess")
        self.start_rotation_btn.clicked.connect(self._start_rotation_button_clicked)
        action_layout.addWidget(self.start_rotation_btn, 0, 0)

        self.stop_rotation_btn = QPushButton("停止测量")
        self.stop_rotation_btn.setObjectName("btnDanger")
        self.stop_rotation_btn.clicked.connect(self._stop_rotation_button_clicked)
        action_layout.addWidget(self.stop_rotation_btn, 0, 1)

        self.zeroing_btn = QPushButton("零位校准")
        self.zeroing_btn.clicked.connect(self._zeroing_button_clicked)
        action_layout.addWidget(self.zeroing_btn, 0, 2)

        self.test_position_btn = QPushButton("测试位置")
        self.test_position_btn.setObjectName("btnWarning")
        self.test_position_btn.clicked.connect(self._test_position_button_clicked)
        action_layout.addWidget(self.test_position_btn, 0, 3)

        main_layout.addWidget(action_group)

        # 方向控制区
        direction_group = QGroupBox("位置控制")
        direction_layout = QGridLayout(direction_group)

        direction_layout.addWidget(QLabel("距离(mm):"), 0, 0)
        self.distance_edit = QLineEdit()
        self.distance_edit.setText("1")
        self.distance_edit.setAlignment(Qt.AlignCenter)
        direction_layout.addWidget(self.distance_edit, 0, 1)

        direction_layout.addWidget(self._make_direction_btn("↑", self._up_button_clicked), 1, 1)
        direction_layout.addWidget(self._make_direction_btn("↓", self._down_button_clicked), 1, 2)
        direction_layout.addWidget(self._make_direction_btn("←", self._left_button_clicked), 2, 0)
        direction_layout.addWidget(self._make_direction_btn("→", self._right_button_clicked), 2, 3)

        main_layout.addWidget(direction_group)

        # 波形显示区
        plot_group = QGroupBox("波形显示")
        plot_layout = QVBoxLayout(plot_group)

        self.plot_placeholder = QLabel("波形显示区\n(PlotWindow 将嵌入此处)")
        self.plot_placeholder.setObjectName("plot_placeholder")
        self.plot_placeholder.setAlignment(Qt.AlignCenter)
        self.plot_placeholder.setMinimumHeight(250)
        self.plot_placeholder.setFrameStyle(QFrame.StyledPanel | QFrame.Raised)
        plot_layout.addWidget(self.plot_placeholder)
        main_layout.addWidget(plot_group, 1)

        # 同心度校准
        self.radioButton_Concentricity = QRadioButton("启用同心度校准")
        self.radioButton_Concentricity.setChecked(True)
        main_layout.addWidget(self.radioButton_Concentricity)

        # 数据显示区
        data_group = QGroupBox("数据分析结果")
        data_layout = QGridLayout(data_group)

        # N极
        data_layout.addWidget(QLabel("N极最大值:"), 0, 0)
        self.n_max_edit = QLineEdit("0.00")
        self.n_max_edit.setReadOnly(True)
        data_layout.addWidget(self.n_max_edit, 0, 1)

        data_layout.addWidget(QLabel("N极最小值:"), 0, 2)
        self.n_min_edit = QLineEdit("0.00")
        self.n_min_edit.setReadOnly(True)
        data_layout.addWidget(self.n_min_edit, 0, 3)

        data_layout.addWidget(QLabel("N极均值:"), 0, 4)
        self.n_mean_edit = QLineEdit("0.00")
        self.n_mean_edit.setReadOnly(True)
        data_layout.addWidget(self.n_mean_edit, 0, 5)

        # S极
        data_layout.addWidget(QLabel("S极最大值:"), 1, 0)
        self.s_max_edit = QLineEdit("0.00")
        self.s_max_edit.setReadOnly(True)
        data_layout.addWidget(self.s_max_edit, 1, 1)

        data_layout.addWidget(QLabel("S极最小值:"), 1, 2)
        self.s_min_edit = QLineEdit("0.00")
        self.s_min_edit.setReadOnly(True)
        data_layout.addWidget(self.s_min_edit, 1, 3)

        data_layout.addWidget(QLabel("S极均值:"), 1, 4)
        self.s_mean_edit = QLineEdit("0.00")
        self.s_mean_edit.setReadOnly(True)
        data_layout.addWidget(self.s_mean_edit, 1, 5)

        # NS关系
        data_layout.addWidget(QLabel("NS2:"), 2, 0)
        self.ns_2_edit = QLineEdit("0.00")
        self.ns_2_edit.setReadOnly(True)
        data_layout.addWidget(self.ns_2_edit, 2, 1)

        data_layout.addWidget(QLabel("单极均值:"), 2, 2)
        self.single_polar_mean_edit = QLineEdit("0.00")
        self.single_polar_mean_edit.setReadOnly(True)
        data_layout.addWidget(self.single_polar_mean_edit, 2, 3)

        data_layout.addWidget(QLabel("单极误差:"), 2, 4)
        self.single_polar_error_edit = QLineEdit("0.00")
        self.single_polar_error_edit.setReadOnly(True)
        data_layout.addWidget(self.single_polar_error_edit, 2, 5)

        main_layout.addWidget(data_group)

        # 样品信息
        info_group = QGroupBox("样品信息")
        info_layout = QGridLayout(info_group)

        info_layout.addWidget(QLabel("样品名称:"), 0, 0)
        self.sample_name_edit = QLineEdit("测试样品")
        info_layout.addWidget(self.sample_name_edit, 0, 1)

        info_layout.addWidget(QLabel("极数:"), 0, 2)
        self.polar_num_edit = QLineEdit()
        self.polar_num_edit.setReadOnly(True)
        info_layout.addWidget(self.polar_num_edit, 0, 3)

        info_layout.addWidget(QLabel("气隙:"), 0, 4)
        self.airgap_edit = QLineEdit("--")
        info_layout.addWidget(self.airgap_edit, 0, 5)

        info_layout.addWidget(QLabel("备注:"), 1, 0)
        self.remark_edit = QLineEdit("测试备注")
        info_layout.addWidget(self.remark_edit, 1, 1, 1, 5)

        main_layout.addWidget(info_group)

        # 状态栏
        self.status_label = QLabel("")
        self.status_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(self.status_label)

        # 按钮行
        btn_row = QHBoxLayout()
        btn_row.addWidget(QPushButton("串口设置"))
        btn_row.addWidget(QPushButton("历史数据"))
        btn_row.addWidget(QPushButton("数据比对"))
        btn_row.addStretch()
        btn_row.addWidget(QPushButton("保存数据"))
        main_layout.addLayout(btn_row)

        logger.info("MeasurePanel 初始化完成")

    def _make_direction_btn(self, text, callback):
        """创建方向按钮"""
        btn = QPushButton(text)
        btn.setMinimumSize(40, 40)
        btn.clicked.connect(callback)
        return btn

    def _clear_status_message(self):
        """清空状态消息"""
        if self.status_label:
            self.status_label.setText("")
            self.status_label.setStyleSheet("")

    def _start_rotation_button_clicked(self):
        """开始测量"""
        logger.info("测量开始按钮被点击")
        if not self.serial_manager or not self.serial_manager.get_connection_status():
            self._update_status("错误：串口未连接", is_error=True)
            return

        dialog = MeasureTypeDialog(self)
        result = dialog.exec_()
        if result != QDialog.Accepted or not dialog.get_measure_type():
            return

        measure_type = dialog.get_measure_type()
        vertical_distance = dialog.get_vertical_distance()
        self._reset_sample_inputs()
        self.data_process.measure_type = measure_type

        sample_info = self._collect_sample_info_from_ui()
        self.data_process.set_sample_info(sample_info)

        self.is_testing = True
        self._reset_test_interface()
        self._show_testing_indicator()
        self._disable_function_buttons()
        self.clear_plot()

        while not self.measure_data_queue.empty():
            try:
                self.measure_data_queue.get_nowait()
            except queue.Empty:
                break

        self._update_status("正在测量...")

        if measure_type == "vertical":
            if self.serial_command and self.serial_manager.get_connection_status():
                self.serial_command.vertical_move(vertical_distance)
        else:
            if self.serial_command and self.serial_manager.get_connection_status():
                self.serial_command.claw_rotate()

        self.data_process.clear_data_queue()
        self.data_process.signal_measure_data_process.emit()

    def _stop_rotation_button_clicked(self):
        """停止旋转"""
        logger.info("停止旋转按钮被点击")
        if self.serial_command:
            self.serial_command.claw_stop()
        self._end_test()

    def _zeroing_button_clicked(self):
        """零位校准"""
        logger.info("零位校准按钮被点击")
        if self.serial_command:
            self.serial_command.slider_reset()

    def _test_position_button_clicked(self):
        """测试位置"""
        logger.info("测试位置按钮被点击")
        if self.serial_command:
            self.serial_command.test_position()

    def _up_button_clicked(self):
        """上"""
        logger.info("上按钮被点击")
        distance = self._get_distance_value()
        if distance is None:
            return
        self._update_status("向上移动...", auto_recover=True)
        self.serial_command.set_move_task('Z', -1, distance)
        self.serial_command.position_query()

    def _down_button_clicked(self):
        """下"""
        logger.info("下按钮被点击")
        distance = self._get_distance_value()
        if distance is None:
            return
        self._update_status("向下移动...", auto_recover=True)
        self.serial_command.set_move_task('Z', 1, distance)
        self.serial_command.position_query()

    def _left_button_clicked(self):
        """左"""
        logger.info("左按钮被点击")
        distance = self._get_distance_value()
        if distance is None:
            return
        self._update_status("向左移动...", auto_recover=True)
        self.serial_command.set_move_task('X', 1, distance)
        self.serial_command.position_query()

    def _right_button_clicked(self):
        """右"""
        logger.info("右按钮被点击")
        distance = self._get_distance_value()
        if distance is None:
            return
        self._update_status("向右移动...", auto_recover=True)
        self.serial_command.set_move_task('X', -1, distance)
        self.serial_command.position_query()

    def _get_distance_value(self):
        """获取距离值"""
        if not self.distance_edit:
            return None
        try:
            distance_text = self.distance_edit.text().strip()
            if not distance_text:
                self._update_status("错误：距离值为空", is_error=True)
                return None
            mm_value = float(distance_text)
            if mm_value <= 0:
                self._update_status("错误：距离值必须大于0", is_error=True)
                return None
            return mm_value
        except ValueError:
            self._update_status("错误：距离值格式错误", is_error=True)
            return None

    def _reset_sample_inputs(self):
        """重置样品信息"""
        if self.sample_name_edit:
            self.sample_name_edit.setText("测试样品")
        if self.airgap_edit:
            self.airgap_edit.setText("--")
        if self.remark_edit:
            self.remark_edit.setText("测试备注")
        self._update_display_defaults()

    def _update_display_defaults(self):
        """更新显示默认值"""
        defaults = ["0.00"] * 6 + ["0.00"] * 6 + ["0.00"] * 3
        edits = [self.n_max_edit, self.n_min_edit, self.n_mean_edit,
                 self.s_max_edit, self.s_min_edit, self.s_mean_edit,
                 self.ns_2_edit, self.single_polar_mean_edit, self.single_polar_error_edit]
        for edit, default in zip(edits, defaults):
            if edit:
                edit.setText(default)

    def _reset_test_interface(self):
        """重置测试界面"""
        logger.info("重置测试界面")
        self._update_display_defaults()
        self.clear_plot()
        self.angle_data = []
        self.mag_data = []

    def _show_testing_indicator(self):
        """显示测试中提示"""
        self._hide_testing_indicator()
        self.testing_label = QLabel("测试中...", self)
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
        self.testing_label.setAlignment(Qt.AlignCenter)
        window_width = self.width()
        window_height = self.height()
        label_width = window_width // 3
        label_height = window_height // 6
        label_x = (window_width - label_width) // 2
        label_y = (window_height - label_height) // 2
        self.testing_label.setGeometry(label_x, label_y, label_width, label_height)
        self.testing_label.show()
        self.testing_label.raise_()

    def _hide_testing_indicator(self):
        """隐藏测试中提示"""
        if self.testing_label:
            self.testing_label.hide()
            self.testing_label.deleteLater()
            self.testing_label = None

    def _disable_function_buttons(self):
        """禁用功能按钮"""
        self.start_rotation_btn.setEnabled(False)
        self.zeroing_btn.setEnabled(False)
        self.test_position_btn.setEnabled(False)

    def _enable_function_buttons(self):
        """启用所有功能按钮"""
        self.start_rotation_btn.setEnabled(True)
        self.zeroing_btn.setEnabled(True)
        self.test_position_btn.setEnabled(True)

    def _end_test(self):
        """结束测试"""
        logger.info("结束测试")
        self.is_testing = False
        self._hide_testing_indicator()
        self._enable_function_buttons()

    def _update_status(self, message, is_error=False, auto_recover=False):
        """更新状态"""
        if self.status_label:
            self.status_label.setText(message)
            self.status_label.setStyleSheet("color: red; font-weight: bold;" if is_error else "color: green; font-weight: bold;")
            if auto_recover:
                self._status_auto_recover_timer.start(1000)

    def _collect_sample_info_from_ui(self) -> dict:
        """收集样品信息"""
        return {
            'sample_name': self.sample_name_edit.text().strip() if self.sample_name_edit else '',
            'coil_code': self.airgap_edit.text().strip() if self.airgap_edit else '',
            'remark': self.remark_edit.text().strip() if self.remark_edit else '',
            'polar_num': self.polar_num_edit.text().strip() if self.polar_num_edit else '',
        }

    def update_plot_data(self, angle_data=None, mag_data=None, color='r'):
        """更新绘图"""
        if self.plot_window:
            self.plot_window.update_plot(angle_data, mag_data, color)

    def clear_plot(self):
        """清除绘图"""
        if self.plot_window:
            self.plot_window.clear_plot()

    def save_plot_data(self):
        """保存数据"""
        import time
        try:
            if len(self.angle_data) == 0 or len(self.mag_data) == 0:
                return False

            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            save_dir = os.path.join(project_root, "data", "plot_data")
            os.makedirs(save_dir, exist_ok=True)

            sample_name = self.sample_name_edit.text().strip() if self.sample_name_edit else "未知样品"
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            filename = f"{sample_name}_{timestamp}.csv"
            file_path = os.path.join(save_dir, filename)

            import csv
            with open(file_path, 'w', encoding='utf-8', newline='') as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(["样品名称", sample_name])
                writer.writerow(["保存时间", timestamp])
                writer.writerow([])
                writer.writerow(["角度(度)", "磁场强度"])
                for angle, mag in zip(self.angle_data, self.mag_data):
                    writer.writerow([f"{angle:.6f}", f"{mag:.5f}"])

            logger.info(f"数据已保存: {file_path}")
            return True
        except Exception as e:
            logger.error(f"保存失败: {e}")
            return False

    def set_thread_manager(self, tm):
        """设置线程管理器"""
        self.thread_manager = tm
        if tm:
            self.serial_manager = tm.serial_manager
            self.data_process = tm.data_process
            self.serial_command = tm.serial_command

            if hasattr(self.data_process, 'signal_measure_data_processed'):
                self.data_process.signal_measure_data_processed.connect(self._on_measure_data_processed)

    def _on_measure_data_processed(self, angle_data, mag_data):
        """测量数据处理完成"""
        logger.info("测量数据处理完成")
        self.angle_data = angle_data
        self.mag_data = mag_data

        if angle_data and mag_data:
            self.update_plot_data(angle_data, mag_data, 'r')

            if self.data_process.measure_type == "vertical":
                self._update_status("垂直测量完成")
            else:
                self._update_status("数据处理中...")
                enable_concentricity = self.radioButton_Concentricity.isChecked()
                results = self.wave_analyzer.analyze_waveform(angle_data, mag_data, enable_concentricity)
                self._update_display_with_results(results)
                self._update_status("测试完成")

            self._end_test()
        else:
            self._update_status("警告：处理后的数据为空", is_error=True)
            self._end_test()

    def _update_display_with_results(self, results):
        """更新显示结果"""
        if not results:
            return
        try:
            self.n_max_edit.setText(f"{results.get('N_max', 0):.2f}")
            self.n_min_edit.setText(f"{results.get('N_min', 0):.2f}")
            self.n_mean_edit.setText(f"{results.get('N_mean', 0):.2f}")
            self.s_max_edit.setText(f"{results.get('S_max', 0):.2f}")
            self.s_min_edit.setText(f"{results.get('S_min', 0):.2f}")
            self.s_mean_edit.setText(f"{results.get('S_mean', 0):.2f}")
            self.ns_2_edit.setText(f"{results.get('NS_2', 0):.2f}")
            self.single_polar_mean_edit.setText(f"{results.get('SinglePolarMean', 0):.2f}")
            self.single_polar_error_edit.setText(f"{results.get('SinglePolarError', 0):.2f}")

            pole_num = results.get('pole_num')
            if pole_num is not None:
                try:
                    self.polar_num_edit.setText(str(int(pole_num)))
                except (ValueError, TypeError):
                    self.polar_num_edit.setText("--")
        except Exception as e:
            logger.error(f"更新显示结果失败: {e}")
