# -*- coding: utf-8 -*-
"""
测量面板 - 从 measure_panel.ui 加载
"""

import os
import numpy as np
from PyQt5.QtWidgets import (QWidget, QPushButton, QLineEdit, QLabel, QRadioButton,
                              QDialog, QVBoxLayout, QComboBox, QHBoxLayout, QListWidget,
                              QListWidgetItem, QAbstractItemView, QToolButton, QSizePolicy)
from PyQt5.QtCore import QObject, QThread, QTimer, Qt, pyqtSignal, pyqtSlot
from PyQt5 import uic
import pyqtgraph as pg
from pyqtgraph import mkPen
from core.logger import get_logger
from core import get_config_manager
from core.config_manager import ACTION_TYPES
from core.offset_calibration_config import OFFSET_PROGRESS_SECONDS
from windows.plot_window import PlotWindow
from windows.wave_analysis import WaveAnalysis
from windows.test_progress_dialog import TestProgressDialog
from windows.offset_calibration_dialog import OffsetCalibrationDialog

logger = get_logger('MeasurePanel')

STATUS_AUTO_RECOVER_MS = 2000
DEFAULT_PLOT_COLOR = '#e74c3c'
RESULT_FIELD_DEFAULTS = {
    "n_max_edit": "0.00",
    "n_min_edit": "0.00",
    "n_mean_edit": "0.00",
    "s_max_edit": "0.00",
    "s_min_edit": "0.00",
    "s_mean_edit": "0.00",
    "n_error_edit": "0.00",
    "s_error_edit": "0.00",
    "ns_2_edit": "0.00",
    "n_interval_max_edit": "0.00",
    "n_interval_min_edit": "0.00",
    "n_interval_mean_edit": "0.00",
    "n_interval_error_edit": "0.00",
    "s_interval_max_edit": "0.00",
    "s_interval_min_edit": "0.00",
    "s_interval_mean_edit": "0.00",
    "s_interval_error_edit": "0.00",
    "n_area_edit": "0.00",
    "s_area_edit": "0.00",
    "ns_area_edit": "0.00",
    "single_polar_mean_edit": "0.00",
    "single_polar_error_edit": "0.00",
    "polar_error_sum_edit": "0.00",
    "thd_error_edit": "0.00",
    "polar_num_edit": "--",
}


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

        # 偏置校准对话框
        self._offset_dialog = None

        # 位置数据查询状态
        self.position_query_completed = False
        self.position_query_result = None

        # 初始化绘图窗口
        self.plot_window = None

        # 初始化波形分析数据
        self.angle_data = []
        self.mag_data = []
        self.analysis_results = None
        self._current_plot_color = DEFAULT_PLOT_COLOR
        self._persistent_status_message = ""
        self._persistent_status_is_error = False

        # 初始化波形分析器
        self.wave_analyzer = WaveAnalysis()

        # 测试状态管理
        self.is_testing = False
        self.test_progress_dialog = None

        # 初始化状态自动恢复定时器
        self._status_auto_recover_timer = QTimer(self)
        self._status_auto_recover_timer.setSingleShot(True)
        self._status_auto_recover_timer.timeout.connect(self._clear_status_message)

        # 连接按钮事件
        self._connect_buttons()

        # 初始化绘图显示
        self._init_plot_display()

        # 初始化配置显示
        self._init_config_display()

        logger.info("MeasurePanel 初始化完成")

    def _init_config_display(self):
        """初始化配置显示"""
        config = get_config_manager()

        # 测试类型 - 连接信号实现双向同步
        combo_test_type = self.findChild(QComboBox, "combo_test_type")
        if combo_test_type:
            combo_test_type.setCurrentIndex(config.test_type)
            combo_test_type.currentIndexChanged.connect(self._on_test_type_changed)
            # 连接配置管理器的信号
            config.signal_test_type_changed.connect(self._on_config_test_type_changed)

        # 更新位置显示
        self._update_config_position_display()

        # 更新配置位置显示
        self._update_config_position_display()

    def _update_config_position_display(self):
        """更新配置位置显示"""
        config = get_config_manager()

        # 测试位置
        test_pos_x = self.findChild(QLineEdit, "test_pos_x_edit")
        test_pos_z = self.findChild(QLineEdit, "test_pos_z_edit")
        if test_pos_x:
            test_pos_x.setText(str(config.test_x))
        if test_pos_z:
            test_pos_z.setText(str(config.test_z))

        # 挂起位置
        suspend_pos_x = self.findChild(QLineEdit, "suspend_pos_x_edit")
        suspend_pos_z = self.findChild(QLineEdit, "suspend_pos_z_edit")
        if suspend_pos_x:
            suspend_pos_x.setText(str(config.suspend_x))
        if suspend_pos_z:
            suspend_pos_z.setText(str(config.suspend_z))

    def _update_current_position_display(self, x, z):
        """更新当前位置显示"""
        current_x = self.findChild(QLineEdit, "current_x_edit")
        current_z = self.findChild(QLineEdit, "current_z_edit")
        if current_x:
            current_x.setText(str(x) if x != "--" else "--")
        if current_z:
            current_z.setText(str(z) if z != "--" else "--")

    def _on_test_type_changed(self, index):
        """测试类型改变"""
        config = get_config_manager()
        config.test_type = index
        logger.info(f"测试类型已更改: {index}")

    def _on_config_test_type_changed(self, index):
        """配置管理器测试类型改变，同步更新下拉框"""
        combo_test_type = self.findChild(QComboBox, "combo_test_type")
        if combo_test_type and combo_test_type.currentIndex() != index:
            combo_test_type.blockSignals(True)
            combo_test_type.setCurrentIndex(index)
            combo_test_type.blockSignals(False)

    def _init_plot_display(self):
        """初始化绘图显示窗口"""
        plot_display_widget = self.findChild(QWidget, "widget_plot_display")

        if plot_display_widget:
            # 创建绘图窗口实例
            self.plot_window = PlotWindow()

            # 使用plot_window的初始化方法
            self.plot_window.init_plot_display(plot_display_widget)

            # 连接双击信号 - 打开独立窗口
            self.plot_window.plot_double_clicked.connect(self._on_plot_double_click)

            logger.info("绘图窗口初始化完成")
        else:
            logger.warning("未找到widget_plot_display控件")

    def _on_plot_double_click(self):
        """双击绘图区域，打开独立窗口"""
        if not self.angle_data or not self.mag_data:
            return

        # 创建独立窗口
        dialog = QDialog(self)
        dialog.setWindowTitle("波形显示")
        dialog.resize(1000, 600)
        dialog.showMaximized()

        # 直接创建轻量级绘图控件
        plot_widget = pg.PlotWidget()
        plot_widget.setBackground('#ffffff')
        plot_widget.showGrid(x=True, y=True, alpha=0.5)
        plot_widget.setXRange(0, 360)
        plot_widget.plotItem.setLabel('bottom', '角度', units='°')
        plot_widget.plotItem.setLabel('left', '磁场', units='mT')

        curve = plot_widget.plot(pen=mkPen(self._current_plot_color, width=1.5))
        curve.setData(self.angle_data, self.mag_data)

        # 自动调整Y轴
        mag_arr = np.array(self.mag_data)
        min_val = np.min(mag_arr)
        max_val = np.max(mag_arr)
        margin = (max_val - min_val) * 0.1
        plot_widget.setYRange(min_val - margin, max_val + margin)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(plot_widget)

        dialog.exec_()

    def _connect_buttons(self):
        """连接按钮事件"""
        # 快捷操作按钮
        self.findChild(QPushButton, "btn_start_rotation").clicked.connect(self._start_rotation_button_clicked)
        self.findChild(QPushButton, "btn_stop_rotation").clicked.connect(self._stop_rotation_button_clicked)
        self.findChild(QPushButton, "btn_zeroing").clicked.connect(self._zeroing_button_clicked)
        self.findChild(QPushButton, "btn_offset").clicked.connect(self._offset_button_clicked)
        self.findChild(QPushButton, "btn_test_position").clicked.connect(self._test_position_button_clicked)
        self.findChild(QPushButton, "btn_suspend_position").clicked.connect(self._suspend_position_button_clicked)

        # 方向控制按钮
        self.findChild(QPushButton, "btn_up").clicked.connect(self._up_button_clicked)
        self.findChild(QPushButton, "btn_down").clicked.connect(self._down_button_clicked)
        self.findChild(QPushButton, "btn_left").clicked.connect(self._left_button_clicked)
        self.findChild(QPushButton, "btn_right").clicked.connect(self._right_button_clicked)

        # 底部按钮
        self.findChild(QPushButton, "btn_save").clicked.connect(self._save_data_button_clicked)

    def _clear_status_message(self):
        """清空状态消息"""
        self._status_auto_recover_timer.stop()
        if self._persistent_status_message:
            self._apply_status_message(
                self._persistent_status_message,
                self._persistent_status_is_error,
            )
            return

        status_label = self.findChild(QLabel, "status_label")
        if status_label:
            status_label.setText("")
            status_label.setToolTip("")
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

        self._reset_sample_inputs()
        self.data_process.measure_type = "rotation"

        sample_info = self._collect_sample_info_from_ui()
        self.data_process.set_sample_info(sample_info)

        self.is_testing = True
        self._reset_test_interface()
        self._disable_function_buttons()
        self.clear_plot()

        # 重置测量停止标志
        self.data_process._stop_measure_processing = False

        # 设置测量状态标志，停止位置查询，避免干扰测量数据
        if self.serial_command:
            self.serial_command._is_measuring = True
            self.serial_command.disable_position_query_timer()
            logger.info("已停止位置查询定时器")

        # 显示进度对话框
        self.test_progress_dialog = TestProgressDialog(self)
        self.test_progress_dialog.btn_cancel.clicked.connect(self._on_test_cancel)
        self.test_progress_dialog.show()
        self.test_progress_dialog.set_progress(0, "正在采集数据...")

        self._update_status("正在测量...")

        # 先清空数据队列
        self.data_process.clear_data_queue()

        # 先启动设备旋转，让设备开始发数据
        if self.serial_command and self.serial_manager.get_connection_status():
            self.serial_command.claw_rotate()

        # 再发送处理信号，启动数据处理流程
        logger.info("正在发送 signal_measure_data_process 信号...")
        self.data_process.signal_measure_data_process.emit()
        logger.info("signal_measure_data_process 信号已发送")

    def _on_test_cancel(self):
        """测试取消"""
        logger.info("测试被取消")
        if self.serial_command:
            self.serial_command.claw_stop()
        self._end_test()
        if self.test_progress_dialog:
            self.test_progress_dialog.close()
            self.test_progress_dialog = None

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

    def _offset_button_clicked(self):
        """偏置校准"""
        logger.info("偏置校准按钮被点击")
        if self.serial_command:
            logger.info(
                "Offset flow: MeasurePanel request received, "
                f"dialog_present={self._offset_dialog is not None}"
            )
            # 停止位置查询定时器，防止干扰偏置校准
            self.serial_command.disable_position_query_timer()
            logger.info("Offset flow: MeasurePanel disabled position query timer")

            # 显示校准对话框
            self._offset_dialog = OffsetCalibrationDialog(self)
            self._offset_dialog.start_progress(duration=OFFSET_PROGRESS_SECONDS)
            self._offset_dialog.show()
            logger.info("Offset flow: MeasurePanel progress dialog shown")
            self.serial_command.offset_calibration()
            logger.info("Offset flow: MeasurePanel command dispatched")

    def _on_offset_calibration_finished(self, success):
        """偏置校准完成"""
        logger.info(
            "Offset flow: MeasurePanel finished callback, "
            f"success={success}, dialog_present={self._offset_dialog is not None}"
        )
        # 重新启动位置查询定时器
        if self.serial_command:
            self.serial_command.enable_position_query_timer()
            logger.info("Offset flow: MeasurePanel re-enabled position query timer")
        if self._offset_dialog:
            config = get_config_manager()
            offset_value = getattr(config, 'offset', None)
            logger.info(f"Offset flow: MeasurePanel showing result, offset={offset_value}")
            self._offset_dialog.show_result(success, offset_value)
            self._offset_dialog.btn_cancel.clicked.connect(self._close_offset_dialog)
    def _close_offset_dialog(self):
        """关闭偏置校准对话框"""
        if self._offset_dialog:
            logger.info("Offset flow: MeasurePanel offset dialog closed")
            self._offset_dialog.close()
            self._offset_dialog = None

    def _test_position_button_clicked(self):
        """测试位置"""
        logger.info("测试位置按钮被点击")
        if self.serial_command:
            self.serial_command.test_position()

    def _suspend_position_button_clicked(self):
        """挂起位置"""
        logger.info("挂起位置按钮被点击")
        if self.serial_command:
            self.serial_command.suspend_position()

    def _up_button_clicked(self):
        """上"""
        logger.info("上按钮被点击")
        distance = self._get_distance_value()
        if distance is None:
            return
        self._update_status("向上移动...", auto_recover=True)
        self.serial_command.set_move_task('Z', -1, distance)
        self.serial_command.position_query(source="manual_move_up")

    def _down_button_clicked(self):
        """下"""
        logger.info("下按钮被点击")
        distance = self._get_distance_value()
        if distance is None:
            return
        self._update_status("向下移动...", auto_recover=True)
        self.serial_command.set_move_task('Z', 1, distance)
        self.serial_command.position_query(source="manual_move_down")

    def _left_button_clicked(self):
        """左"""
        logger.info("左按钮被点击")
        distance = self._get_distance_value()
        if distance is None:
            return
        self._update_status("向左移动...", auto_recover=True)
        self.serial_command.set_move_task('X', 1, distance)
        self.serial_command.position_query(source="manual_move_left")

    def _right_button_clicked(self):
        """右"""
        logger.info("右按钮被点击")
        distance = self._get_distance_value()
        if distance is None:
            return
        self._update_status("向右移动...", auto_recover=True)
        self.serial_command.set_move_task('X', -1, distance)
        self.serial_command.position_query(source="manual_move_right")

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
        sample_name_edit = self.findChild(QLineEdit, "sample_name_edit")
        if sample_name_edit and not sample_name_edit.text().strip():
            sample_name_edit.setText("测试样品")

        polar_num_edit = self.findChild(QLineEdit, "polar_num_edit")
        if polar_num_edit:
            polar_num_edit.setText("--")

    def _update_display_defaults(self):
        """更新显示默认值"""
        for name, default_value in RESULT_FIELD_DEFAULTS.items():
            edit = self.findChild(QLineEdit, name)
            if edit:
                edit.setText(default_value)

    def _reset_test_interface(self):
        """重置测试界面"""
        logger.info("重置测试界面")
        self.analysis_results = None
        self._persistent_status_message = ""
        self._persistent_status_is_error = False
        self._update_display_defaults()
        self.clear_plot()
        self.angle_data = []
        self.mag_data = []

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
        self._enable_function_buttons()

        # 停止测量数据处理
        if self.data_process:
            self.data_process.stop_measure_processing()

        # 恢复位置查询定时器
        if self.serial_command:
            self.serial_command._is_measuring = False
            self.serial_command.enable_position_query_timer()
            logger.info("已恢复位置查询定时器")

    def _apply_status_message(self, message, is_error=False):
        status_label = self.findChild(QLabel, "status_label")
        if status_label:
            status_label.setText(message)
            status_label.setToolTip(message)
            status_label.setStyleSheet(
                "color: red; font-weight: bold;" if is_error else "color: green; font-weight: bold;"
            )

    def _update_status(self, message, is_error=False, auto_recover=False):
        """更新状态"""
        if not auto_recover:
            self._persistent_status_message = ""
            self._persistent_status_is_error = False

        self._apply_status_message(message, is_error)
        if auto_recover:
            self._status_auto_recover_timer.start(STATUS_AUTO_RECOVER_MS)
        else:
            self._status_auto_recover_timer.stop()

    def show_history_file_status(self, file_path: str) -> None:
        filename = os.path.basename(file_path)
        message = f"当前显示文件：{filename}"
        self._persistent_status_message = message
        self._persistent_status_is_error = False
        self._status_auto_recover_timer.stop()
        self._apply_status_message(message)

    def _collect_sample_info_from_ui(self) -> dict:
        """收集样品信息"""
        airgap = self.findChild(QLineEdit, "airgap_edit").text().strip()
        polar_num = self.findChild(QLineEdit, "polar_num_edit").text().strip()
        return {
            'sample_name': self.findChild(QLineEdit, "sample_name_edit").text().strip(),
            'sample_code': self.findChild(QLineEdit, "sample_code_edit").text().strip(),
            'airgap': "" if airgap == "--" else airgap,
            'remark': self.findChild(QLineEdit, "remark_edit").text().strip(),
            'polar_num': "" if polar_num == "--" else polar_num,
            'tester': self.findChild(QLineEdit, "tester_edit").text().strip(),
        }

    def update_plot_data(self, angle_data=None, mag_data=None, color='r'):
        """更新绘图"""
        self._current_plot_color = color or DEFAULT_PLOT_COLOR
        if self.plot_window:
            self.plot_window.update_plot(angle_data, mag_data, color)

    def clear_plot(self):
        """清除绘图"""
        self._current_plot_color = DEFAULT_PLOT_COLOR
        if self.plot_window:
            self.plot_window.clear_plot()

    def save_plot_data(self):
        """保存数据"""
        try:
            if len(self.angle_data) == 0 or len(self.mag_data) == 0:
                return False

            if not self.data_process:
                logger.error("保存失败：数据处理器未初始化")
                return False

            sample_info = self._collect_sample_info_from_ui()
            self.data_process.set_sample_info(sample_info)
            file_path = self.data_process.save_plot_measure_data(
                self.angle_data,
                self.mag_data,
                self.analysis_results,
            )
            if not file_path:
                return False

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
        self._update_status("数据保存成功" if success else "数据保存失败", is_error=not success, auto_recover=True)

    def set_thread_manager(self, tm):
        """Set thread manager."""
        self.thread_manager = tm
        if not tm:
            return

        self.serial_manager = tm.serial_manager
        self.data_process = tm.data_process
        self.serial_command = tm.serial_command

        if hasattr(self.data_process, "signal_measure_analysis_finished"):
            self.data_process.signal_measure_analysis_finished.connect(
                self._on_measure_data_processed,
                Qt.QueuedConnection,
            )
        elif hasattr(self.data_process, "signal_measure_data_process_finished"):
            self.data_process.signal_measure_data_process_finished.connect(
                self._on_measure_data_processed_legacy,
                Qt.QueuedConnection,
            )

        if hasattr(self.data_process, "signal_measure_data_progress"):
            self.data_process.signal_measure_data_progress.connect(
                self._on_measure_progress,
                Qt.QueuedConnection,
            )

        if hasattr(tm.data_process, "signal_position_data_process_finished"):
            tm.data_process.signal_position_data_process_finished.connect(
                self._on_position_data_updated,
                Qt.QueuedConnection,
            )

        if hasattr(tm.data_process, "signal_offset_data_process_finished"):
            tm.data_process.signal_offset_data_process_finished.connect(
                self._on_offset_calibration_finished,
                Qt.QueuedConnection,
            )

    def _on_position_data_updated(self, position_data):
        """Update position display."""
        if not self.isVisible():
            return
        if position_data and len(position_data) >= 2:
            x, z = position_data[0], position_data[1]
            self._update_current_position_display(x, z)

    def _on_measure_progress(self, current, total):
        """Update measurement progress."""
        if self.test_progress_dialog:
            progress = int((current / total) * 100) if total > 0 else 0
            status_text = "正在处理数据..." if total > 0 and current >= total else "正在采集数据..."
            self.test_progress_dialog.set_progress(progress, status_text)

    def _on_measure_data_processed_legacy(self, angle_data, mag_data):
        analysis_results = None
        if angle_data and mag_data and self.data_process and self.data_process.measure_type != "vertical":
            radio = self.findChild(QRadioButton, "radio_concentricity")
            enable_concentricity = radio.isChecked() if radio else True
            analysis_results = self.wave_analyzer.analyze_waveform(
                angle_data,
                mag_data,
                enable_concentricity,
            )
        self._on_measure_data_processed(angle_data, mag_data, analysis_results)

    @pyqtSlot(object, object, object)
    def _on_measure_data_processed(self, angle_data, mag_data, analysis_results):
        """Handle measurement processing completion."""
        logger.info("测量数据处理完成")
        self.angle_data = angle_data or []
        self.mag_data = mag_data or []

        if self.test_progress_dialog:
            if self.angle_data and self.mag_data:
                self.test_progress_dialog.show_result(True, f"采集完成，共 {len(self.angle_data)} 个数据点")
            else:
                self.test_progress_dialog.show_result(False, "未能获取有效数据")

        if self.angle_data and self.mag_data:
            self.update_plot_data(self.angle_data, self.mag_data, "r")

            if self.data_process.measure_type == "vertical":
                sample_info = self._collect_sample_info_from_ui()
                self.data_process.set_sample_info(sample_info)
                self.analysis_results = None
                self._update_status("垂直测量完成")
            else:
                self._update_display_with_results(analysis_results)
                sample_info = self._collect_sample_info_from_ui()
                sample_info["polar_num"] = analysis_results.get("pole_num", "") if analysis_results else ""
                self.data_process.set_sample_info(sample_info)
                self._update_status(
                    "测试完成" if analysis_results else "测试完成，但波形分析未返回有效结果",
                    is_error=not bool(analysis_results),
                )

            if self.is_testing:
                self._end_test()
            if self.test_progress_dialog:
                QTimer.singleShot(1500, self._close_test_progress_dialog)
        else:
            self._update_status("警告：处理后的数据为空", is_error=True)
            if self.is_testing:
                self._end_test()
            if self.test_progress_dialog:
                QTimer.singleShot(1500, self._close_test_progress_dialog)

    def _close_test_progress_dialog(self):
        """Close test progress dialog."""
        if self.test_progress_dialog:
            self.test_progress_dialog.close()
            self.test_progress_dialog = None

    def _update_display_with_results(self, results):
        """更新显示结果"""
        if not results:
            self.analysis_results = None
            return
        try:
            self.analysis_results = dict(results)
            # N极/S极 基础值
            self.findChild(QLineEdit, "n_max_edit").setText(f"{results.get('N_max', 0):.2f}")
            self.findChild(QLineEdit, "n_min_edit").setText(f"{results.get('N_min', 0):.2f}")
            self.findChild(QLineEdit, "n_mean_edit").setText(f"{results.get('N_mean', 0):.2f}")
            self.findChild(QLineEdit, "s_max_edit").setText(f"{results.get('S_max', 0):.2f}")
            self.findChild(QLineEdit, "s_min_edit").setText(f"{results.get('S_min', 0):.2f}")
            self.findChild(QLineEdit, "s_mean_edit").setText(f"{results.get('S_mean', 0):.2f}")

            # N极/S极 误差
            self.findChild(QLineEdit, "n_error_edit").setText(f"{results.get('N_se', 0):.2f}")
            self.findChild(QLineEdit, "s_error_edit").setText(f"{results.get('S_se', 0):.2f}")

            # NS关系
            self.findChild(QLineEdit, "ns_2_edit").setText(f"{results.get('NS_2', 0):.2f}")

            # N极零交叉点间隔
            self.findChild(QLineEdit, "n_interval_max_edit").setText(f"{results.get('N_interval_max', 0):.2f}")
            self.findChild(QLineEdit, "n_interval_min_edit").setText(f"{results.get('N_interval_min', 0):.2f}")
            self.findChild(QLineEdit, "n_interval_mean_edit").setText(f"{results.get('N_interval_mean', 0):.2f}")
            self.findChild(QLineEdit, "n_interval_error_edit").setText(f"{results.get('N_interval_std', 0):.2f}")

            # S极零交叉点间隔
            self.findChild(QLineEdit, "s_interval_max_edit").setText(f"{results.get('S_interval_max', 0):.2f}")
            self.findChild(QLineEdit, "s_interval_min_edit").setText(f"{results.get('S_interval_min', 0):.2f}")
            self.findChild(QLineEdit, "s_interval_mean_edit").setText(f"{results.get('S_interval_mean', 0):.2f}")
            self.findChild(QLineEdit, "s_interval_error_edit").setText(f"{results.get('S_interval_std', 0):.2f}")

            # 面积
            self.findChild(QLineEdit, "n_area_edit").setText(f"{results.get('N_area', 0):.2f}")
            self.findChild(QLineEdit, "s_area_edit").setText(f"{results.get('S_area', 0):.2f}")
            self.findChild(QLineEdit, "ns_area_edit").setText(f"{results.get('NS_area', 0):.2f}")

            # 单极相关
            self.findChild(QLineEdit, "single_polar_mean_edit").setText(f"{results.get('SinglePolarMean', 0):.2f}")
            self.findChild(QLineEdit, "single_polar_error_edit").setText(f"{results.get('SinglePolarError', 0):.2f}")
            self.findChild(QLineEdit, "polar_error_sum_edit").setText(f"{results.get('PolarErrorSum', 0):.2f}")

            # THD失真率
            self.findChild(QLineEdit, "thd_error_edit").setText(f"{results.get('THD_error', 0):.2f}")

            # 极数
            pole_num = results.get('pole_num')
            if pole_num is not None:
                try:
                    self.findChild(QLineEdit, "polar_num_edit").setText(str(int(pole_num)))
                except (ValueError, TypeError):
                    self.findChild(QLineEdit, "polar_num_edit").setText("--")
        except Exception as e:
            logger.error(f"更新显示结果失败: {e}")
