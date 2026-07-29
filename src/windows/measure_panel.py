# -*- coding: utf-8 -*-
"""
测量面板 - 从 measure_panel.ui 加载
"""

import os
import json
import serial.tools.list_ports
from PyQt5.QtWidgets import (QWidget, QPushButton, QLineEdit, QLabel, QRadioButton,
                              QComboBox, QHBoxLayout, QListWidget,
                              QListWidgetItem, QAbstractItemView, QToolButton, QSizePolicy,
                              QMessageBox)
from PyQt5.QtCore import QObject, QThread, QTimer, Qt, pyqtSignal, pyqtSlot, QEvent, QPoint
from PyQt5.QtGui import QPainter, QColor, QIcon, QPixmap, QPolygon, QTransform
from PyQt5 import uic
from core.logger import get_logger
from core import get_config_manager
from core.config_manager import SENSOR_RANGE_OPTIONS, action_to_text
from core.offset_calibration_config import OFFSET_PROGRESS_SECONDS
from windows.plot_window import PlotWindow
from windows.wave_analysis import WaveAnalysis
from windows.analysis_detail_dialog import AnalysisDetailDialog
from windows.test_progress_dialog import TestProgressDialog
from windows.offset_calibration_dialog import OffsetCalibrationDialog

logger = get_logger('MeasurePanel')

STATUS_AUTO_RECOVER_MS = 2000
DEFAULT_PLOT_COLOR = '#e74c3c'
TESTER_HISTORY_CONFIG_KEY = "tester_history"
LAST_TESTER_CONFIG_KEY = "last_tester"
MAX_TESTER_HISTORY_COUNT = 20
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

MEASUREMENT_LOCKED_BUTTONS = (
    "btn_start_rotation",
    "btn_zeroing",
    "btn_offset",
    "btn_test_position",
    "btn_suspend_position",
)


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
        self._analysis_detail_dialogs = []

        self._init_stage_picture()
        self._connect_stage_buttons()

        # 初始化波形分析器
        self.wave_analyzer = WaveAnalysis()

        # 测试状态管理
        self.is_testing = False
        self.test_progress_dialog = None

        # 初始化状态自动恢复定时器
        self._status_auto_recover_timer = QTimer(self)
        self._status_auto_recover_timer.setSingleShot(True)
        self._status_auto_recover_timer.timeout.connect(self._clear_status_message)

        self._pending_connection_port = None
        self._connection_timeout_timer = QTimer(self)
        self._connection_timeout_timer.setSingleShot(True)
        self._connection_timeout_timer.timeout.connect(self._on_connection_timeout)

        self._port_refresh_timer = QTimer(self)
        self._port_refresh_timer.setInterval(2000)
        self._port_refresh_timer.timeout.connect(self._refresh_ports)

        # 连接按钮事件
        self._connect_buttons()

        # 初始化绘图显示
        self._init_plot_display()

        # 初始化配置显示
        self._init_config_display()
        self._init_serial_controls()
        self._init_sample_info_inputs()

        # 初始化时显示提示文字
        self._clear_status_message()

        logger.info("MeasurePanel 初始化完成")

    def _init_sample_info_inputs(self):
        """Initialize the sample info combo boxes."""
        self._init_tester_combo()
        self._init_sensor_combo()

    def _init_tester_combo(self):
        combo = self.findChild(QComboBox, "comboBox_tester_edit")
        if not combo:
            return

        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.NoInsert)

        config = get_config_manager()
        history = self._load_tester_history()
        last_tester = (config.get(LAST_TESTER_CONFIG_KEY, "") or "").strip()
        if last_tester:
            history = self._merge_tester_history(last_tester, history)

        self._set_combo_items(combo, history, last_tester)

    def _init_sensor_combo(self):
        combo = self.findChild(QComboBox, "comboBox_sensor_edit")
        if not combo:
            return

        config = get_config_manager()
        combo.blockSignals(True)
        combo.clear()
        combo.addItems(SENSOR_RANGE_OPTIONS)
        combo.setCurrentIndex(config.sensor_range)
        combo.blockSignals(False)
        combo.currentIndexChanged.connect(self._on_sensor_range_changed)
        config.signal_sensor_range_changed.connect(self._on_config_sensor_range_changed)

    def _on_sensor_range_changed(self, index):
        config = get_config_manager()
        config.sensor_range = index
        logger.info(f"探头量程已更改: {SENSOR_RANGE_OPTIONS[config.sensor_range]}")

    def _on_config_sensor_range_changed(self, index):
        combo = self.findChild(QComboBox, "comboBox_sensor_edit")
        if combo and combo.currentIndex() != index:
            combo.blockSignals(True)
            combo.setCurrentIndex(index)
            combo.blockSignals(False)

    def _sync_sensor_range_from_ui(self):
        combo = self.findChild(QComboBox, "comboBox_sensor_edit")
        if combo:
            get_config_manager().sensor_range = combo.currentIndex()

    def _load_tester_history(self):
        config = get_config_manager()
        raw_value = (config.get(TESTER_HISTORY_CONFIG_KEY, "") or "").strip()
        if not raw_value:
            return []

        try:
            parsed = json.loads(raw_value)
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
        except (TypeError, ValueError):
            pass

        return [item.strip() for item in raw_value.split("|") if item.strip()]

    def _merge_tester_history(self, latest, history):
        merged = []
        for item in [latest, *history]:
            item = str(item).strip()
            if item and item not in merged:
                merged.append(item)
        return merged[:MAX_TESTER_HISTORY_COUNT]

    def _set_combo_items(self, combo, items, current_text=""):
        combo.blockSignals(True)
        combo.clear()
        combo.addItems(items)
        if current_text:
            combo.setCurrentText(current_text)
        elif combo.count() > 0:
            combo.setCurrentIndex(0)
        else:
            combo.setCurrentText("")
        combo.blockSignals(False)

    def _combo_text(self, combo_name, fallback_line_edit_name=None):
        combo = self.findChild(QComboBox, combo_name)
        if combo:
            return combo.currentText().strip()

        if fallback_line_edit_name:
            line_edit = self.findChild(QLineEdit, fallback_line_edit_name)
            if line_edit:
                return line_edit.text().strip()
        return ""

    def _save_tester_history(self, tester):
        tester = (tester or "").strip()
        if not tester:
            return

        config = get_config_manager()
        history = self._merge_tester_history(tester, self._load_tester_history())
        config.set(TESTER_HISTORY_CONFIG_KEY, json.dumps(history))
        config.set(LAST_TESTER_CONFIG_KEY, tester)

        combo = self.findChild(QComboBox, "comboBox_tester_edit")
        if combo:
            self._set_combo_items(combo, history, tester)

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
            config.signal_scheme_changed.connect(self._on_config_scheme_changed)

        combo_test_speed = self.findChild(QComboBox, "combo_test_speed")
        if combo_test_speed:
            combo_test_speed.setCurrentIndex(config.test_speed)
            combo_test_speed.currentIndexChanged.connect(self._on_test_speed_changed)
            config.signal_test_speed_changed.connect(self._on_config_test_speed_changed)
        # 更新移动方案显示
        self._update_scheme_display(config.test_type)

    def _update_scheme_display(self, test_type):
        """根据测试类型更新移动方案显示"""
        config = get_config_manager()

        test_scheme = config.get_active_test_scheme(test_type)
        suspend_scheme = config.get_active_suspend_scheme(test_type)
        test_steps_text = " → ".join(action_to_text(s) for s in test_scheme.get("steps", [])) or "--"
        suspend_steps_text = " → ".join(action_to_text(s) for s in suspend_scheme.get("steps", [])) or "--"

        test_scheme_edit = self.findChild(QLineEdit, "test_scheme_edit")
        if test_scheme_edit:
            test_scheme_edit.setText(test_steps_text)

        suspend_scheme_edit = self.findChild(QLineEdit, "suspend_scheme_edit")
        if suspend_scheme_edit:
            suspend_scheme_edit.setText(suspend_steps_text)

    def _on_test_type_changed(self, index):
        """测试类型改变"""
        config = get_config_manager()
        config.test_type = index
        logger.info(f"测试类型已更改: {index}")
        self._update_scheme_display(index)

    def _on_test_speed_changed(self, index):
        """测试速度改变 → 同步发送 MODE 指令到固件"""
        config = get_config_manager()
        config.test_speed = index
        logger.info(f"测试速度已更改: {index}")
        if self.serial_command and self.serial_manager and self.serial_manager.get_connection_status():
            self.serial_command.set_mode_from_test_speed(index)

    def _on_config_test_type_changed(self, index):
        """配置管理器测试类型改变，同步更新下拉框"""
        combo_test_type = self.findChild(QComboBox, "combo_test_type")
        if combo_test_type and combo_test_type.currentIndex() != index:
            combo_test_type.blockSignals(True)
            combo_test_type.setCurrentIndex(index)
            combo_test_type.blockSignals(False)
        self._update_scheme_display(index)

    def _on_config_test_speed_changed(self, index):
        """配置管理器测试速度改变，同步更新下拉框"""
        combo_test_speed = self.findChild(QComboBox, "combo_test_speed")
        if combo_test_speed and combo_test_speed.currentIndex() != index:
            combo_test_speed.blockSignals(True)
            combo_test_speed.setCurrentIndex(index)
            combo_test_speed.blockSignals(False)

    def _on_config_scheme_changed(self, test_type):
        """配置管理器移动方案改变，同步更新当前测试类型流程。"""
        config = get_config_manager()
        if test_type == config.test_type:
            self._update_scheme_display(test_type)

    def _init_plot_display(self):
        """初始化绘图显示窗口"""
        plot_display_widget = self.findChild(QWidget, "widget_plot_display")

        if plot_display_widget:
            # 创建绘图窗口实例
            self.plot_window = PlotWindow()

            # 使用plot_window的初始化方法
            self.plot_window.init_plot_display(plot_display_widget)

            logger.info("绘图窗口初始化完成")
        else:
            logger.warning("未找到widget_plot_display控件")

    def _init_serial_controls(self):
        """Initialize serial controls embedded in the test configuration area."""
        self._refresh_ports()
        self._apply_serial_port_to_ui(get_config_manager().com_port)
        self._set_serial_status("未连接", "#e74c3c")
        self._set_serial_button_state(False)

        port_combo = self.findChild(QComboBox, "port_combo")
        if port_combo:
            port_combo.currentTextChanged.connect(self._on_port_combo_changed)

    def _set_combo_text(self, combo_name: str, value: str) -> None:
        combo = self.findChild(QComboBox, combo_name)
        if not combo:
            return

        index = combo.findText(str(value))
        if index >= 0:
            combo.setCurrentIndex(index)

    def _get_serial_port_from_ui(self) -> str:
        port_combo = self.findChild(QComboBox, "port_combo")
        return port_combo.currentText() if port_combo else ""

    def _apply_serial_port_to_ui(self, com_port: str) -> None:
        self._set_combo_text("port_combo", com_port)

    def _set_serial_status(self, text: str, color: str) -> None:
        status_label = self.findChild(QLabel, "serial_status_label")
        if status_label:
            status_label.setText(text)
            status_label.setStyleSheet(f"color: {color}; font-weight: bold; font-size: 14px;")

    def _set_serial_button_state(self, connected: bool = False, connecting: bool = False) -> None:
        connect_btn = self.findChild(QPushButton, "btnSuccess")
        if not connect_btn:
            return

        connect_btn.setEnabled(True)
        if connecting:
            connect_btn.setText("连接中...")
            connect_btn.setStyleSheet(
                "QPushButton { background-color: #3498db; color: white; }"
            )
        elif connected:
            connect_btn.setText("断开")
            connect_btn.setStyleSheet(
                "QPushButton { background-color: #e74c3c; color: white; }"
            )
        else:
            connect_btn.setText("连接")
            connect_btn.setStyleSheet(
                "QPushButton { background-color: #27ae60; color: white; }"
            )

    def _save_serial_port(self, com_port: str) -> None:
        config = get_config_manager()
        config.com_port = com_port or config.com_port

    def _on_port_combo_changed(self, text: str) -> None:
        """下拉框选项变更时保存到配置"""
        if text and text not in ("无可用串口", "刷新失败"):
            self._save_serial_port(text)

    def _refresh_ports(self):
        port_combo = self.findChild(QComboBox, "port_combo")
        if port_combo is None:
            logger.error("port_combo not found")
            return

        current_port = port_combo.currentText() or get_config_manager().com_port
        is_connected = bool(self.serial_manager and self.serial_manager.get_connection_status())

        port_combo.blockSignals(True)
        port_combo.clear()
        try:
            ports = list(serial.tools.list_ports.comports())
            for port in ports:
                port_combo.addItem(port.device)

            if current_port:
                index = port_combo.findText(current_port)
                if index >= 0:
                    port_combo.setCurrentIndex(index)

            if port_combo.count() == 0:
                port_combo.addItem("无可用串口")
                port_combo.setEnabled(False)
            else:
                port_combo.setEnabled(not is_connected)
        except Exception as e:
            logger.error(f"Refresh serial ports failed: {e}")
            port_combo.addItem("刷新失败")
        finally:
            port_combo.blockSignals(False)

    def _start_connect(self, com_port: str, status_text: str) -> bool:
        if not self.thread_manager or not self.thread_manager.serial_manager:
            logger.error("Serial manager is not initialized.")
            return False

        if self.thread_manager.serial_manager.get_connection_status():
            logger.info("Serial port is already connected.")
            return True

        if not com_port or com_port == "无可用串口":
            logger.error("Please select a valid serial port.")
            return False

        self._pending_connection_port = com_port
        self._apply_serial_port_to_ui(com_port)
        self._set_serial_status(status_text, "#3498db")
        self._set_serial_button_state(connecting=True)
        self._connection_timeout_timer.start(2000)

        logger.info(f"Connecting serial port {com_port}...")
        self.thread_manager.signal_connect.emit(com_port)
        return True

    def _set_port_refresh_enabled(self, enabled: bool) -> None:
        if enabled:
            if not self._port_refresh_timer.isActive():
                self._port_refresh_timer.start()
            self._refresh_ports()
            return

        if self._port_refresh_timer.isActive():
            self._port_refresh_timer.stop()

    def showEvent(self, event):
        super().showEvent(event)
        self._set_port_refresh_enabled(True)
        self._refresh_ports()
        self._apply_serial_port_to_ui(get_config_manager().com_port)

    def hideEvent(self, event):
        self._set_port_refresh_enabled(False)
        super().hideEvent(event)

    def _on_connect_clicked(self):
        if self.thread_manager and self.thread_manager.serial_manager:
            if self.thread_manager.serial_manager.get_connection_status():
                self.thread_manager.signal_disconnect.emit()
                logger.info("Serial port disconnected.")
                return

        self._start_connect(self._get_serial_port_from_ui(), "正在连接...")

    def _on_connection_timeout(self):
        self._set_serial_status("连接超时", "#e74c3c")
        self._set_serial_button_state(False)
        self._pending_connection_port = None
        logger.warning("Serial connection timed out.")

    def _on_serial_status_changed(self, connected):
        self._connection_timeout_timer.stop()

        if connected:
            port = ""
            if self.serial_manager and getattr(self.serial_manager, "serial_port", None):
                port = self.serial_manager.serial_port.portName()

            self._set_serial_button_state(True)

            com_port = str(port or self._pending_connection_port or self._get_serial_port_from_ui()).strip().strip('"')
            self._save_serial_port(com_port)
            self._apply_serial_port_to_ui(com_port)
            self._set_serial_status("已连接", "#27ae60")

            port_combo = self.findChild(QComboBox, "port_combo")
            if port_combo:
                port_combo.setEnabled(False)

            if self.thread_manager and getattr(self.thread_manager, "serial_command", None):
                self.thread_manager.serial_command.enable_position_query_timer()

            # 串口连接后同步当前采集模式
            if self.serial_command:
                self.serial_command.set_mode_from_test_speed(get_config_manager().test_speed)

            logger.info(f"Serial connected: {com_port}")
        else:
            self._set_serial_button_state(False)

            if self.thread_manager and getattr(self.thread_manager, "serial_command", None):
                self.thread_manager.serial_command.disable_position_query_timer()

            port_combo = self.findChild(QComboBox, "port_combo")
            if port_combo and port_combo.count() > 0:
                port_combo.setEnabled(True)

            self._set_serial_status("未连接", "#e74c3c")
            logger.info("Serial disconnected.")

        self._pending_connection_port = None

    def auto_connect_from_config(self):
        try:
            com_port = get_config_manager().com_port
            if not com_port:
                logger.info("No COM port found in configuration.")
                return False

            ports = list(serial.tools.list_ports.comports())
            available_ports = [port.device for port in ports]
            if com_port not in available_ports:
                logger.info(f"Configured serial port {com_port} is unavailable.")
                return False

            return self._start_connect(com_port, "自动连接中...")
        except Exception as e:
            logger.error(f"Auto connect failed: {e}")
            return False

    def _connect_buttons(self):
        """连接按钮事件"""
        connect_btn = self.findChild(QPushButton, "btnSuccess")
        if connect_btn:
            connect_btn.clicked.connect(self._on_connect_clicked)

        # 快捷操作按钮
        self.findChild(QPushButton, "btn_start_rotation").clicked.connect(self._start_rotation_button_clicked)
        self.findChild(QPushButton, "btn_stop_rotation").clicked.connect(self._stop_rotation_button_clicked)
        self.findChild(QPushButton, "btn_zeroing").clicked.connect(self._zeroing_button_clicked)
        self.findChild(QPushButton, "btn_offset").clicked.connect(self._offset_button_clicked)
        self.findChild(QPushButton, "btn_test_position").clicked.connect(self._test_position_button_clicked)
        self.findChild(QPushButton, "btn_suspend_position").clicked.connect(self._suspend_position_button_clicked)

        # 底部按钮
        self.findChild(QPushButton, "btn_save").clicked.connect(self._save_data_button_clicked)

        detail_button_map = {
            "btn_zero_crossing_info": "zero_crossing",
            "btn_extreme_point_info": "extreme_point",
            "btn_period_error_info": "period_error",
        }
        for button_name, detail_type in detail_button_map.items():
            button = self.findChild(QPushButton, button_name)
            if button:
                button.clicked.connect(lambda checked=False, item_type=detail_type: self._show_analysis_detail(item_type))

    def _has_current_waveform_analysis(self):
        return bool(
            self.angle_data
            and self.mag_data
            and len(self.angle_data) > 0
            and len(self.mag_data) > 0
            and self.analysis_results
        )

    def _show_analysis_detail(self, detail_type):
        """显示当前波形的分析详情。"""
        if not self._has_current_waveform_analysis():
            QMessageBox.information(self, "提示", "当前没有打开或测量完成的有效波形数据")
            return

        detail_key_map = {
            "zero_crossing": "zero_crossing_details",
            "extreme_point": "peak_details",
            "period_error": "period_error_details",
        }
        detail_key = detail_key_map.get(detail_type)
        if detail_key and not self.analysis_results.get(detail_key):
            QMessageBox.information(self, "提示", "当前波形没有可显示的分析明细")
            return

        dialog = AnalysisDetailDialog(
            detail_type,
            self.angle_data,
            self.mag_data,
            self.analysis_results,
            self,
        )
        self._analysis_detail_dialogs.append(dialog)
        dialog.finished.connect(lambda _result, item=dialog: self._remove_analysis_detail_dialog(item))
        dialog.show()

    def _remove_analysis_detail_dialog(self, dialog):
        if dialog in self._analysis_detail_dialogs:
            self._analysis_detail_dialogs.remove(dialog)

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
            status_label.setText("状态提示信息")
            status_label.setToolTip("")
            status_label.setStyleSheet("color: #b0b0b0; font-style: italic;")

    def _start_rotation_button_clicked(self):
        """开始测量"""
        logger.info("测量开始按钮被点击")
        if not self.serial_manager or not self.serial_manager.get_connection_status():
            self._update_status("错误：串口未连接", is_error=True)
            return

        self._sync_sensor_range_from_ui()
        self._reset_sample_inputs()
        self.data_process.measure_type = "rotation"
        raw_checkbox = self.findChild(QRadioButton, "radio_save_raw_data")
        self.data_process.save_raw_data_enabled = bool(raw_checkbox and raw_checkbox.isChecked())
        logger.info(f"原始数据自动保存: {self.data_process.save_raw_data_enabled}")

        sample_info = self._collect_sample_info_from_ui()
        self.data_process.set_sample_info(sample_info)

        self.is_testing = True
        self._reset_test_interface()
        self._disable_function_buttons()
        self.clear_plot()

        # 重置测量停止标志
        self.data_process._stop_measure_processing = False

        # ① 先设标志，阻止 M~ 查询和文本解析
        if self.serial_command:
            self.serial_command._is_measuring = True
            self.serial_command.disable_position_query_timer()
        if self.data_process:
            self.data_process._measurement_active = True
            logger.info("测量模式已激活，文本解析器已屏蔽")

        # ② 再清队列，确保之前可能泄露的数据被丢弃
        self.data_process.clear_data_queue()

        # 显示进度对话框
        self.test_progress_dialog = TestProgressDialog(self)
        self.test_progress_dialog.btn_cancel.clicked.connect(self._on_test_cancel)
        self.test_progress_dialog.show()
        self.test_progress_dialog.set_progress(0, "正在采集数据...")

        self._update_status("正在测量...")

        # 延迟 300ms 确保 MODE 切换等指令已被固件处理完毕
        QTimer.singleShot(300, self._send_rotate_command)

    def _send_rotate_command(self):
        """延迟发送 B~，然后启动数据处理。"""
        if self.serial_command and self.serial_manager.get_connection_status():
            self.data_process.clear_data_queue()  # B~ 发送前最后清一次队列
            self.serial_command.claw_rotate()
            logger.info("B~ 采集指令已发送（延迟 300ms）")
        else:
            logger.error(
                f"无法发送 B~: serial_command={self.serial_command is not None}, "
                f"connected={self.serial_manager.get_connection_status() if self.serial_manager else False}"
            )
        # B~ 发出后再启动数据处理器，不浪费超时窗口
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
            self._sync_sensor_range_from_ui()
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

    def _on_offset_progress(self, current, total):
        """更新偏置校准进度条"""
        if self._offset_dialog:
            pct = int(current / total * 100) if total > 0 else 0
            self._offset_dialog.set_progress(min(pct, 99), "偏置校准进行中...")

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
            offset_adc = getattr(config, 'offset', None)
            offset_mt = offset_adc / 73.35 if offset_adc else None
            logger.info(f"Offset flow: MeasurePanel showing result, offset={offset_adc} ADC ({offset_mt} mT)")
            self._offset_dialog.show_result(success, offset_mt)
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

    # ========================================================================
    # 台控按钮（QPainter 三角图标 + 按住移动/松手停止）
    # ========================================================================

    def _init_stage_picture(self):
        """widget_control 背景图 + 6 个方向键用 QPainter 三角 Icon。"""
        pic = self.findChild(QWidget, "widget_control")
        if pic is None:
            return

        img_path = os.path.join(os.path.dirname(__file__), "..", "ui", "stage.png")
        if os.path.exists(img_path):
            bg = QLabel(pic)
            bg.setScaledContents(True)
            bg.setPixmap(QPixmap(img_path))
            bg.lower()
            bg.setGeometry(0, 0, pic.width(), pic.height())
            class _PicResizer(QObject):
                def eventFilter(self, obj, event):
                    if event.type() == QEvent.Resize:
                        bg.setGeometry(0, 0, obj.width(), obj.height())
                    return False
            pic.installEventFilter(_PicResizer(pic))

        size = 24
        color = QColor("#2c3e50")

        base = QPixmap(size, size)
        base.fill(Qt.transparent)
        p = QPainter(base)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(color)
        p.setPen(Qt.NoPen)
        p.drawPolygon(QPolygon([QPoint(12, 3), QPoint(3, 18), QPoint(21, 18)]))
        p.end()

        def _icon(angle):
            t = QTransform().rotate(angle)
            return QIcon(base.transformed(t, Qt.SmoothTransformation))

        icons = {
            "stage_btn_up":      QIcon(base),
            "stage_btn_down":    _icon(180),
            "stage_btn_left":    _icon(-90),
            "stage_btn_right":   _icon(90),
            "stage_btn_forward": _icon(45),
            "stage_btn_back":    _icon(-135),
        }

        for name, icon in icons.items():
            btn = self.findChild(QPushButton, name)
            if btn:
                btn.setIcon(icon)
                btn.setIconSize(btn.size())
                btn.setText("")

        style = (
            "QPushButton { border:1px solid #999; border-radius:4px; background:rgba(255,255,255,220); }"
            "QPushButton:hover { background-color:rgb(224,224,224); }"
        )
        for name in icons:
            btn = self.findChild(QPushButton, name)
            if btn:
                btn.setStyleSheet(style)

    def _connect_stage_buttons(self):
        """台控：按发送 ±500000 步，松停止。"""
        moves = {
            "stage_btn_up":      "Y-500000",
            "stage_btn_down":    "Y+500000",
            "stage_btn_left":    "X-500000",
            "stage_btn_right":   "X+500000",
            "stage_btn_forward": "Z-500000",
            "stage_btn_back":    "Z+500000",
        }
        for name, cmd in moves.items():
            btn = self.findChild(QPushButton, name)
            if btn:
                btn.pressed.connect(self._make_send(cmd))
                btn.released.connect(self._make_stop())

    def _make_send(self, cmd):
        def handler():
            if self.serial_command:
                self.serial_command.send_data(f"{cmd}~", source="stage_press")
        return handler

    def _make_stop(self):
        def handler():
            if self.serial_command:
                self.serial_command.send_data("O~", source="stage_release")
        return handler

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
        self._set_measurement_locked_buttons_enabled(False)
        raw_checkbox = self.findChild(QRadioButton, "radio_save_raw_data")
        if raw_checkbox:
            raw_checkbox.setEnabled(False)

    def _enable_function_buttons(self):
        """启用所有功能按钮"""
        self._set_measurement_locked_buttons_enabled(True)
        raw_checkbox = self.findChild(QRadioButton, "radio_save_raw_data")
        if raw_checkbox:
            raw_checkbox.setEnabled(True)

    def _set_measurement_locked_buttons_enabled(self, enabled):
        for button_name in MEASUREMENT_LOCKED_BUTTONS:
            button = self.findChild(QPushButton, button_name)
            if button:
                button.setEnabled(enabled)

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
        if self.data_process:
            self.data_process._measurement_active = False
            logger.info("测量模式已关闭，文本解析器已恢复")

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
            'tester': self._combo_text("comboBox_tester_edit", "tester_edit"),
            'probe': self._combo_text("comboBox_sensor_edit"),
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

            self._save_tester_history(sample_info.get('tester', ''))
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

        if hasattr(tm.data_process, "signal_offset_data_progress"):
            tm.data_process.signal_offset_data_progress.connect(
                self._on_offset_progress,
                Qt.QueuedConnection,
            )

        if hasattr(self.serial_manager, "signal_connection_status_changed"):
            self.serial_manager.signal_connection_status_changed.connect(
                self._on_serial_status_changed,
                Qt.QueuedConnection,
            )

    def _on_position_data_updated(self, position_data):
        """保留位置数据槽函数，测量配置区不再显示当前位置。"""
        return

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

    def _on_measure_progress(self, current, total):
        """更新测量进度条"""
        if self.test_progress_dialog:
            pct = int(current / total * 100) if total > 0 else 0
            self.test_progress_dialog.set_progress(min(pct, 99), "正在采集数据...")

    @pyqtSlot(object, object, object)
    def _on_measure_data_processed(self, angle_data, mag_data, analysis_results):
        """Handle measurement processing completion."""
        logger.info("测量数据处理完成")
        self.angle_data = angle_data or []
        self.mag_data = mag_data or []

        # 无数据时自动重试 1 次
        if not self.angle_data and self.is_testing:
            retry = getattr(self, '_measure_retry_count', 0) + 1
            if retry <= 1:
                self._measure_retry_count = retry
                logger.warning(f"测量无数据，自动重试 {retry}/1")
                QTimer.singleShot(300, self._send_rotate_command)
                return
            self._measure_retry_count = 0

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
        else:
            self._update_status("警告：处理后的数据为空", is_error=True)
            if self.is_testing:
                self._end_test()

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
