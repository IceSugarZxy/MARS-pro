# -*- coding: utf-8 -*-
"""
测量面板 - 从 measure_panel.ui 加载
"""

import os
import queue
from PyQt5.QtWidgets import QWidget, QPushButton, QLineEdit, QLabel, QRadioButton, QDialog
from PyQt5.QtCore import QTimer
from PyQt5.QtCore import Qt
from PyQt5 import uic
from core.logger import get_logger
from windows.plot_window import PlotWindow
from windows.wave_analysis import WaveAnalysis
from windows.measure_type_dialog import MeasureTypeDialog

logger = get_logger('MeasurePanel')


class MeasurePanel(QWidget):
    """测量面板 - 从 measure_panel.ui 加载"""

    def __init__(self):
        super().__init__()

        # 加载 UI
        ui_file_path = os.path.join(os.path.dirname(__file__), "..", "ui", "measure_panel.ui")
        uic.loadUi(ui_file_path, self)

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

        # 连接按钮事件
        self._connect_buttons()

        logger.info("MeasurePanel 初始化完成")

    def _connect_buttons(self):
        """连接按钮事件"""
        # 快捷操作按钮
        self.findChild(QPushButton, "btn_start_rotation").clicked.connect(self._start_rotation_button_clicked)
        self.findChild(QPushButton, "btn_stop_rotation").clicked.connect(self._stop_rotation_button_clicked)
        self.findChild(QPushButton, "btn_zeroing").clicked.connect(self._zeroing_button_clicked)
        self.findChild(QPushButton, "btn_test_position").clicked.connect(self._test_position_button_clicked)

        # 方向控制按钮
        self.findChild(QPushButton, "btn_up").clicked.connect(self._up_button_clicked)
        self.findChild(QPushButton, "btn_down").clicked.connect(self._down_button_clicked)
        self.findChild(QPushButton, "btn_left").clicked.connect(self._left_button_clicked)
        self.findChild(QPushButton, "btn_right").clicked.connect(self._right_button_clicked)

        # 底部按钮
        self.findChild(QPushButton, "btn_save").clicked.connect(self._save_data_button_clicked)
        self.findChild(QPushButton, "btn_serial").clicked.connect(self._on_serial_clicked)
        self.findChild(QPushButton, "btn_history").clicked.connect(self._on_history_clicked)
        self.findChild(QPushButton, "btn_compare").clicked.connect(self._on_compare_clicked)

    def _clear_status_message(self):
        """清空状态消息"""
        status_label = self.findChild(QLabel, "status_label")
        if status_label:
            status_label.setText("")
            status_label.setStyleSheet("")

    def _on_serial_clicked(self):
        """跳转到串口设置"""
        from PyQt5.QtWidgets import QApplication
        for widget in QApplication.topLevelWidgets():
            if hasattr(widget, '_switch_panel'):
                widget._switch_panel("serial")
                break

    def _on_history_clicked(self):
        """跳转到历史数据"""
        from PyQt5.QtWidgets import QApplication
        for widget in QApplication.topLevelWidgets():
            if hasattr(widget, '_switch_panel'):
                widget._switch_panel("history")
                break

    def _on_compare_clicked(self):
        """跳转到数据比对"""
        from PyQt5.QtWidgets import QApplication
        for widget in QApplication.topLevelWidgets():
            if hasattr(widget, '_switch_panel'):
                widget._switch_panel("compare")
                break

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
        distance_edit = self.findChild(QLineEdit, "distance_edit")
        if not distance_edit:
            return None
        try:
            text = distance_edit.text().strip()
            if not text:
                self._update_status("错误：距离值为空", is_error=True)
                return None
            value = float(text)
            if value <= 0:
                self._update_status("错误：距离值必须大于0", is_error=True)
                return None
            return value
        except ValueError:
            self._update_status("错误：距离值格式错误", is_error=True)
            return None

    def _reset_sample_inputs(self):
        """重置样品信息"""
        self.findChild(QLineEdit, "sample_name_edit").setText("测试样品")
        self.findChild(QLineEdit, "airgap_edit").setText("--")
        self.findChild(QLineEdit, "remark_edit").setText("测试备注")
        self._update_display_defaults()

    def _update_display_defaults(self):
        """更新显示默认值"""
        for name in ["n_max_edit", "n_min_edit", "n_mean_edit", "s_max_edit", "s_min_edit",
                     "s_mean_edit", "ns_2_edit", "single_polar_mean_edit", "single_polar_error_edit"]:
            edit = self.findChild(QLineEdit, name)
            if edit:
                edit.setText("0.00")

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
        w, h = self.width(), self.height()
        self.testing_label.setGeometry(w // 3, h // 3, w // 3, h // 6)
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
        self.findChild(QPushButton, "btn_start_rotation").setEnabled(False)
        self.findChild(QPushButton, "btn_zeroing").setEnabled(False)
        self.findChild(QPushButton, "btn_test_position").setEnabled(False)

    def _enable_function_buttons(self):
        """启用所有功能按钮"""
        self.findChild(QPushButton, "btn_start_rotation").setEnabled(True)
        self.findChild(QPushButton, "btn_zeroing").setEnabled(True)
        self.findChild(QPushButton, "btn_test_position").setEnabled(True)

    def _end_test(self):
        """结束测试"""
        logger.info("结束测试")
        self.is_testing = False
        self._hide_testing_indicator()
        self._enable_function_buttons()

    def _update_status(self, message, is_error=False, auto_recover=False):
        """更新状态"""
        status_label = self.findChild(QLabel, "status_label")
        if status_label:
            status_label.setText(message)
            status_label.setStyleSheet("color: red; font-weight: bold;" if is_error else "color: green; font-weight: bold;")
            if auto_recover:
                self._status_auto_recover_timer.start(1000)

    def _collect_sample_info_from_ui(self) -> dict:
        """收集样品信息"""
        return {
            'sample_name': self.findChild(QLineEdit, "sample_name_edit").text().strip(),
            'coil_code': self.findChild(QLineEdit, "airgap_edit").text().strip(),
            'remark': self.findChild(QLineEdit, "remark_edit").text().strip(),
            'polar_num': self.findChild(QLineEdit, "polar_num_edit").text().strip(),
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

            sample_name = self.findChild(QLineEdit, "sample_name_edit").text().strip()
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            filename = f"{sample_name}_{timestamp}.csv"
            file_path = os.path.join(save_dir, filename)

            import csv
            with open(file_path, 'w', encoding='utf-8', newline='') as f:
                writer = csv.writer(f)
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

    def _save_data_button_clicked(self):
        """保存数据"""
        logger.info("保存数据按钮被点击")
        self._update_status("正在保存数据...", auto_recover=True)
        success = self.save_plot_data()
        self._update_status("数据保存成功" if success else "数据保存失败", is_error=not success)

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
                radio = self.findChild(QRadioButton, "radio_concentricity")
                enable_concentricity = radio.isChecked() if radio else True
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
            self.findChild(QLineEdit, "n_max_edit").setText(f"{results.get('N_max', 0):.2f}")
            self.findChild(QLineEdit, "n_min_edit").setText(f"{results.get('N_min', 0):.2f}")
            self.findChild(QLineEdit, "n_mean_edit").setText(f"{results.get('N_mean', 0):.2f}")
            self.findChild(QLineEdit, "s_max_edit").setText(f"{results.get('S_max', 0):.2f}")
            self.findChild(QLineEdit, "s_min_edit").setText(f"{results.get('S_min', 0):.2f}")
            self.findChild(QLineEdit, "s_mean_edit").setText(f"{results.get('S_mean', 0):.2f}")
            self.findChild(QLineEdit, "ns_2_edit").setText(f"{results.get('NS_2', 0):.2f}")
            self.findChild(QLineEdit, "single_polar_mean_edit").setText(f"{results.get('SinglePolarMean', 0):.2f}")
            self.findChild(QLineEdit, "single_polar_error_edit").setText(f"{results.get('SinglePolarError', 0):.2f}")

            pole_num = results.get('pole_num')
            if pole_num is not None:
                try:
                    self.findChild(QLineEdit, "polar_num_edit").setText(str(int(pole_num)))
                except (ValueError, TypeError):
                    self.findChild(QLineEdit, "polar_num_edit").setText("--")
        except Exception as e:
            logger.error(f"更新显示结果失败: {e}")
