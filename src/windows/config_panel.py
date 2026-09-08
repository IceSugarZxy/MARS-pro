# -*- coding: utf-8 -*-
"""
配置面板 - 从 config_panel.ui 加载
"""

import os
import re
import serial.tools.list_ports
from PyQt5.QtCore import Qt, QTimer, QObject, QEvent
from PyQt5.QtGui import QTextCursor
from PyQt5.QtWidgets import (
    QWidget,
    QPushButton,
    QLineEdit,
    QLabel,
    QComboBox,
    QToolButton,
    QDoubleSpinBox,
    QPlainTextEdit,
    QMessageBox,
)
from PyQt5 import uic
from core.logger import get_logger
from core import get_config_manager
from core.config_manager import (
    PGA_OPTION_TEXTS,
    action_to_text,
    get_pga_mag_conversion_factor,
)
from windows.full_offset_calibration_dialog import FullOffsetCalibrationDialog
from windows.scheme_edit_dialog import SchemeEditDialog

logger = get_logger('ConfigPanel')

STAGE_LONG_PRESS_MS = 500


class ConfigPanel(QWidget):
    """配置面板 - 从 config_panel.ui 加载"""

    def __init__(self):
        super().__init__()

        # 加载 UI
        ui_file_path = os.path.join(os.path.dirname(__file__), "..", "ui", "config_panel.ui")
        uic.loadUi(ui_file_path, self)

        # 线程管理器引用
        self.thread_manager = None
        self.serial_manager = None
        self.serial_command = None
        self._pending_connection_port = None
        self._serial_rx_update_enabled = False

        self._connection_timeout_timer = QTimer(self)
        self._connection_timeout_timer.setSingleShot(True)
        self._connection_timeout_timer.timeout.connect(self._on_connection_timeout)

        self._port_refresh_timer = QTimer(self)
        self._port_refresh_timer.setInterval(2000)
        self._port_refresh_timer.timeout.connect(self._refresh_ports)

        # 连接按钮事件
        self._connect_buttons()
        self._init_stage_distance()
        self._init_serial_controls()
        self._init_serial_rx_display()

        # 初始化快捷操作配置
        self._init_quick_action_settings()

        # 全量程偏置校准自动流程状态
        self._offset_all_active = False
        self._offset_all_gains = list(range(len(PGA_OPTION_TEXTS)))
        self._offset_all_cursor = 0
        self._offset_all_original_pga = None
        self._offset_all_wait_pga = False
        self._offset_all_wait_offset = False
        self._offset_all_pga_retries = 0
        self._offset_all_pga_buffer = ""
        self._offset_all_cancel_pending = False
        self._offset_all_results = []
        self._offset_all_progress = None
        self._offset_all_pga_timer = QTimer(self)
        self._offset_all_pga_timer.setSingleShot(True)
        self._offset_all_pga_timer.setInterval(2500)
        self._offset_all_pga_timer.timeout.connect(self._on_offset_all_pga_timeout)

        # 加载台控示意图
        self._init_stage_picture()

        logger.info("ConfigPanel 初始化完成")

    def _init_stage_picture(self):
        """widget_picture 背景图 + 所有箭头按钮用 QPainter 三角 Icon。"""
        pic = self.findChild(QWidget, "widget_picture")
        if pic is None:
            return

        img_path = os.path.join(os.path.dirname(__file__), "..", "ui", "stage.png")
        if os.path.exists(img_path):
            from PyQt5.QtGui import QPixmap
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

        from PyQt5.QtGui import QPainter, QColor, QIcon, QPixmap, QPolygon, QTransform
        from PyQt5.QtCore import QPoint
        size = 32
        color = QColor("#2c3e50")

        # 只画朝上三角，其余方向旋转
        base = QPixmap(size, size)
        base.fill(Qt.transparent)
        p = QPainter(base)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(color)
        p.setPen(Qt.NoPen)
        p.drawPolygon(QPolygon([QPoint(16,4), QPoint(4,24), QPoint(28,24)]))
        p.end()

        def _icon(angle):
            t = QTransform().rotate(angle)
            return QIcon(base.transformed(t, Qt.SmoothTransformation))

        icons = {
            "stage_btn_up":      QIcon(base),          # 0°
            "stage_btn_down":    _icon(180),            # 180°
            "stage_btn_left":    _icon(-90),            # ←
            "stage_btn_right":   _icon(90),             # →
            "stage_btn_forward": _icon(45),             # ↗
            "stage_btn_back":    _icon(-135),            # ↙
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

    def set_thread_manager(self, tm):
        """设置线程管理器"""
        self.thread_manager = tm
        if tm:
            self.serial_manager = tm.serial_manager
            self.serial_command = tm.serial_command
            self.data_process = tm.data_process
            self.serial_manager.signal_connection_status_changed.connect(
                self._on_serial_status_changed,
                Qt.QueuedConnection,
            )
            self.serial_manager.signal_data_received.connect(
                self._on_serial_data_received,
                Qt.QueuedConnection,
            )
            # 连接位置数据处理完成信号
            tm.data_process.signal_position_data_process_finished.connect(
                self._on_position_data_updated,
                Qt.QueuedConnection,
            )
            # 全量程偏置校准完成信号
            tm.data_process.signal_offset_data_process_finished.connect(
                self._on_offset_all_offset_finished,
                Qt.QueuedConnection,
            )
            logger.info("测试配置面板已绑定线程管理器，位置查询由 SerialCommand 管理")

        # 加载保存的配置值
        self._load_saved_positions()
        # 初始化测试模式和移动方案
        self._init_test_mode_and_scheme()

    def _init_test_mode_and_scheme(self):
        """初始化测试模式和移动方案"""
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

        combo_sensor_range = self.findChild(QComboBox, "combo_sensor_range")
        if combo_sensor_range:
            combo_sensor_range.blockSignals(True)
            combo_sensor_range.clear()
            combo_sensor_range.addItems(PGA_OPTION_TEXTS)
            combo_sensor_range.setCurrentIndex(config.pga_gain)
            combo_sensor_range.blockSignals(False)
            combo_sensor_range.currentIndexChanged.connect(self._on_pga_gain_changed)
            config.signal_pga_gain_changed.connect(self._on_config_pga_gain_changed)

        # 更新方案显示
        self._update_scheme_display(config.test_type)

    def _update_scheme_display(self, test_type):
        """根据测试类型更新方案显示"""
        config = get_config_manager()

        # 获取当前活动的方案
        test_scheme = config.get_active_test_scheme(test_type)
        suspend_scheme = config.get_active_suspend_scheme(test_type)

        # 转换为显示文本
        test_steps_text = " → ".join([action_to_text(s) for s in test_scheme['steps']])
        suspend_steps_text = " → ".join([action_to_text(s) for s in suspend_scheme['steps']])

        test_scheme_edit = self.findChild(QLineEdit, "test_scheme_edit")
        if test_scheme_edit:
            test_scheme_edit.setText(test_steps_text)

        suspend_scheme_edit = self.findChild(QLineEdit, "suspend_scheme_edit")
        if suspend_scheme_edit:
            suspend_scheme_edit.setText(suspend_steps_text)

    def _on_edit_test_scheme(self):
        """编辑测试方案"""
        config = get_config_manager()
        test_type = config.test_type
        schemes = config.get_test_schemes(test_type)
        if schemes:
            scheme = schemes[0].copy()
            dialog = SchemeEditDialog(scheme, self)
            if dialog.exec_():
                result = dialog.get_result()
                config.update_scheme(test_type, True, 0, result)
                self._update_scheme_display(test_type)
                logger.info(f"测试方案已更新: {result}")

    def _on_suspend_edit_scheme(self):
        """编辑挂起方案"""
        config = get_config_manager()
        test_type = config.test_type
        schemes = config.get_suspend_schemes(test_type)
        if schemes:
            scheme = schemes[0].copy()
            dialog = SchemeEditDialog(scheme, self)
            if dialog.exec_():
                result = dialog.get_result()
                config.update_scheme(test_type, False, 0, result)
                self._update_scheme_display(test_type)
                logger.info(f"挂起方案已更新: {result}")

    def _on_test_type_changed(self, index):
        """测试类型改变"""
        config = get_config_manager()
        config.test_type = index
        logger.info(f"测试类型已更改: {index}")

        # 更新方案显示
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
        # 更新方案显示
        self._update_scheme_display(index)

    def _on_config_test_speed_changed(self, index):
        """配置管理器测试速度改变，同步更新下拉框"""
        combo_test_speed = self.findChild(QComboBox, "combo_test_speed")
        if combo_test_speed and combo_test_speed.currentIndex() != index:
            combo_test_speed.blockSignals(True)
            combo_test_speed.setCurrentIndex(index)
            combo_test_speed.blockSignals(False)

    def _on_pga_gain_changed(self, index):
        """用户修改 PGA 量程：写入配置（发送与回信确认由测量面板统一处理）。"""
        config = get_config_manager()
        config.pga_gain = index
        logger.info(f"PGA 量程已更改: {PGA_OPTION_TEXTS[config.pga_gain]}")

    def _on_config_pga_gain_changed(self, index):
        """配置管理器 PGA 量程改变，同步更新下拉框"""
        combo_sensor_range = self.findChild(QComboBox, "combo_sensor_range")
        if combo_sensor_range and combo_sensor_range.currentIndex() != index:
            combo_sensor_range.blockSignals(True)
            combo_sensor_range.setCurrentIndex(index)
            combo_sensor_range.blockSignals(False)

    def _on_config_scheme_changed(self, test_type):
        """配置管理器移动方案改变，同步更新当前测试类型流程。"""
        config = get_config_manager()
        if test_type == config.test_type:
            self._update_scheme_display(test_type)

    def _load_saved_positions(self):
        """从配置文件加载保存的位置"""
        try:
            config = get_config_manager()
            # 更新测试位置显示
            test_x_display = self.findChild(QLineEdit, "test_x_value")
            test_y_display = self.findChild(QLineEdit, "test_y_value")
            if test_x_display:
                test_x_display.setText(str(config.test_x))
            if test_y_display:
                test_y_display.setText(str(config.test_z))

            # 更新挂起位置显示
            suspend_x_display = self.findChild(QLineEdit, "suspend_x_value")
            suspend_y_display = self.findChild(QLineEdit, "suspend_y_value")
            if suspend_x_display:
                suspend_x_display.setText(str(config.suspend_x))
            if suspend_y_display:
                suspend_y_display.setText(str(config.suspend_z))

            logger.info(f"已加载保存的位置: 水平({config.test_x}, {config.test_z}), 挂起({config.suspend_x}, {config.suspend_z})")
        except Exception as e:
            logger.error(f"加载保存位置失败: {e}")

    def _init_serial_controls(self):
        """初始化测试配置页顶部的串口号连接控件。"""
        self._refresh_ports()
        self._apply_serial_port_to_ui(get_config_manager().com_port)
        self._set_serial_status("未连接", "#e74c3c")
        self._set_serial_button_state(False)

        port_combo = self.findChild(QComboBox, "port_combo")
        if port_combo:
            port_combo.currentTextChanged.connect(self._on_port_combo_changed)

    def _init_serial_rx_display(self) -> None:
        serial_rx_text = self.findChild(QPlainTextEdit, "serial_rx_text")
        if serial_rx_text:
            serial_rx_text.document().setMaximumBlockCount(500)

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

        if not com_port or com_port in ("无可用串口", "刷新失败"):
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
        self._serial_rx_update_enabled = True
        self._set_port_refresh_enabled(True)
        self._refresh_ports()
        self._apply_serial_port_to_ui(get_config_manager().com_port)

    def hideEvent(self, event):
        self._set_port_refresh_enabled(False)
        self._serial_rx_update_enabled = False
        super().hideEvent(event)

    def _on_serial_data_received(self, data: bytes) -> None:
        # 全量程偏置校准进行中且等待 PGA 回信时，先喂给自动流程解析
        if self._offset_all_active and self._offset_all_wait_pga:
            self._feed_offset_all_pga_rx(data)

        if not self._serial_rx_update_enabled:
            return

        serial_rx_text = self.findChild(QPlainTextEdit, "serial_rx_text")
        if not serial_rx_text:
            return

        text = data.decode("utf-8", errors="replace")
        text = text.replace("\r", "\\r").replace("\n", "\\n\n")
        serial_rx_text.moveCursor(QTextCursor.End)
        serial_rx_text.insertPlainText(text)
        serial_rx_text.moveCursor(QTextCursor.End)

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

            # 串口断开时中止进行中的全量程偏置校准
            if self._offset_all_active:
                self._offset_all_force_stop()

            port_combo = self.findChild(QComboBox, "port_combo")
            if port_combo and port_combo.count() > 0:
                port_combo.setEnabled(True)

            self._set_serial_status("未连接", "#e74c3c")
            logger.info("Serial disconnected.")

        self._pending_connection_port = None

    def _connect_buttons(self):
        """连接按钮事件"""
        connect_btn = self.findChild(QPushButton, "btnSuccess")
        if connect_btn:
            connect_btn.clicked.connect(self._on_connect_clicked)

        # 快捷操作
        self.findChild(QPushButton, "btn_zeroing").clicked.connect(self._on_zeroing)
        btn_offset_all = self.findChild(QPushButton, "btn_offset_all")
        if btn_offset_all:
            btn_offset_all.clicked.connect(self._on_offset_all)
        self.findChild(QPushButton, "btn_test_pos").clicked.connect(self._on_test_pos)
        self.findChild(QPushButton, "btn_suspend").clicked.connect(self._on_suspend)
        self.findChild(QPushButton, "btn_test_pos_save").clicked.connect(self._on_test_pos_save)
        self.findChild(QPushButton, "btn_suspend_save").clicked.connect(self._on_suspend_save)
        # 方案编辑
        self.findChild(QToolButton, "btn_test_edit_scheme").clicked.connect(self._on_edit_test_scheme)
        self.findChild(QToolButton, "btn_suspend_edit_scheme").clicked.connect(self._on_suspend_edit_scheme)
        # 台控方向按钮
        self._connect_stage_buttons()

    def _connect_stage_buttons(self):
        """台控：按发送 ±500000 步，松停止。
        
        使用事件过滤器接管 press/release，确保鼠标移出按钮后松手也能发送 O~。
        Qt 原生 released 信号仅在鼠标位于按钮区域内松手时触发，不可靠。
        """
        stage_specs = {
            "stage_btn_up":      ("Y-500000", "Y", -1, "向上"),
            "stage_btn_down":    ("Y+500000", "Y", 1,  "向下"),
            "stage_btn_left":    ("X-500000", "X", -1, "向左"),
            "stage_btn_right":   ("X+500000", "X", 1,  "向右"),
            "stage_btn_forward": ("Z-500000", "Z", -1, "向后"),
            "stage_btn_back":    ("Z+500000", "Z", 1,  "向前"),
        }
        # 追踪当前按下的按钮，确保松手时发送正确的停止指令
        self._stage_pressed_button: Optional[QPushButton] = None
        self._stage_long_pressed = False
        self._stage_press_timer = QTimer(self)
        self._stage_press_timer.setSingleShot(True)
        self._stage_press_timer.setInterval(STAGE_LONG_PRESS_MS)
        self._stage_press_timer.timeout.connect(self._on_stage_press_timeout)

        for name, (cmd, axis, direction, label) in stage_specs.items():
            btn = self.findChild(QPushButton, name)
            if btn:
                btn._stage_cmd = cmd
                btn._stage_axis = axis
                btn._stage_direction = direction
                btn._stage_label = label
                btn.installEventFilter(self)

    def eventFilter(self, obj, event):
        """拦截台控按钮的 press/release，确保 O~ 可靠发送。"""
        from PyQt5.QtCore import QEvent
        if isinstance(obj, QPushButton) and hasattr(obj, '_stage_cmd'):
            if event.type() == QEvent.MouseButtonPress:
                self._stage_press_timer.stop()
                self._stage_pressed_button = obj
                self._stage_long_pressed = False
                self._stage_press_timer.start()
                obj.grabMouse()  # 捕获鼠标，确保 release 事件不丢失
                return True
            elif event.type() == QEvent.MouseButtonRelease:
                self._stage_press_timer.stop()
                btn = self._stage_pressed_button
                was_long = self._stage_long_pressed
                self._stage_pressed_button = None
                self._stage_long_pressed = False
                if btn is not None:
                    btn.releaseMouse()
                if self.serial_command:
                    if was_long:
                        self.serial_command.send_data("O~", source="stage_release")
                    elif btn is not None:
                        self._execute_short_press(btn)
                return True
        return super().eventFilter(obj, event)

    def _on_stage_press_timeout(self):
        """长按判定成立：开始连续移动。"""
        btn = self._stage_pressed_button
        if btn is None or not hasattr(btn, '_stage_cmd'):
            return
        self._stage_long_pressed = True
        if self.serial_command:
            self.serial_command.send_data(f"{btn._stage_cmd}~", source="stage_press")

    def _execute_short_press(self, btn):
        """短按：按输入距离沿对应轴方向移动一次。"""
        distance = self._get_distance_value()
        if distance is None or self.serial_command is None:
            return
        self.serial_command.set_move_task(btn._stage_axis, btn._stage_direction, distance)
        self.serial_command.position_query(source="stage_short_press")

    def _get_distance_value(self):
        """读取短按距离(mm)，非法时提示并返回 None。"""
        distance_edit = self.findChild(QLineEdit, "distance_edit")
        if not distance_edit:
            return None
        text = distance_edit.text().strip()
        if not text:
            self._set_serial_status("错误：距离值为空", "#e74c3c")
            return None
        try:
            value = float(text)
        except ValueError:
            self._set_serial_status("错误：距离值格式错误", "#e74c3c")
            return None
        if value <= 0:
            self._set_serial_status("错误：距离值必须大于 0", "#e74c3c")
            return None
        return value

    def _init_stage_distance(self):
        """从配置载入短按距离，并连接编辑结束校验保存。"""
        config = get_config_manager()
        distance_edit = self.findChild(QLineEdit, "distance_edit")
        if distance_edit:
            distance_edit.setText(f"{config.stage_step_distance:g}")
            distance_edit.editingFinished.connect(self._on_stage_distance_edited)

    def _on_stage_distance_edited(self):
        """校验输入的距离值，合法则持久化，非法则回退为配置值。"""
        config = get_config_manager()
        distance_edit = self.findChild(QLineEdit, "distance_edit")
        if not distance_edit:
            return
        value = self._get_distance_value()
        if value is None:
            distance_edit.setText(f"{config.stage_step_distance:g}")
            return
        config.stage_step_distance = value
        distance_edit.setText(f"{value:g}")

    def _init_quick_action_settings(self):
        """初始化快捷操作配置"""
        config = get_config_manager()

        self._bind_double_spin(
            "spin_x_offset",
            config.inner_x_offset,
            self._on_x_offset_changed,
        )
        self._bind_double_spin(
            "spin_z_offset",
            config.inner_z_offset,
            self._on_z_offset_changed,
        )

    def _bind_double_spin(self, object_name, value, handler):
        """Load a double spin box from config and persist user changes."""
        spin = self.findChild(QDoubleSpinBox, object_name)
        if not spin:
            logger.warning(f"未找到数值输入控件: {object_name}")
            return

        spin.blockSignals(True)
        spin.setValue(float(value))
        spin.blockSignals(False)
        spin.valueChanged.connect(handler)

    def _on_x_offset_changed(self, value):
        """更新X轴偏移量"""
        config = get_config_manager()
        config.inner_x_offset = value
        logger.info(f"X轴偏移量已更新: {value:.2f} mm")

    def _on_z_offset_changed(self, value):
        """更新Z轴偏移量"""
        config = get_config_manager()
        config.inner_z_offset = value
        logger.info(f"Z轴偏移量已更新: {value:.2f} mm")

    def _on_position_data_updated(self, position_data):
        """位置数据更新（M~ 响应解析后的 (x, y, z) 三元组）"""
        if not self.isVisible():
            return
        if position_data and len(position_data) >= 3:
            x, y, z = position_data[0], position_data[1], position_data[2]
            self.update_position(x, y, z)

    def update_position(self, x, y, z):
        """更新位置显示（水平=X, 竖直=Y）"""
        x_display = self.findChild(QLineEdit, "position_x")
        y_display = self.findChild(QLineEdit, "position_y")
        if x_display:
            x_display.setText(str(x) if x is not None else "--")
        if y_display:
            y_display.setText(str(y) if y is not None else "--")

    def _on_zeroing(self):
        """零位校准"""
        if self.serial_command:
            self.serial_command.slider_reset()
            logger.info("零位校准")
        else:
            logger.warning("串口命令未初始化")

    # ==================== 全量程偏置校准 ====================

    def _on_offset_all(self):
        """全量程偏置校准：自动切换 8 个 PGA 量程并逐个执行偏置校准。"""
        if self._offset_all_active:
            return
        connected = bool(
            self.serial_command
            and self.serial_manager
            and self.serial_manager.get_connection_status()
        )
        if not connected:
            QMessageBox.warning(self, "全量程偏置校准", "请先连接串口")
            return
        if getattr(self.serial_command, '_offset_calibrating', False):
            QMessageBox.warning(self, "全量程偏置校准", "当前已有偏置校准进行中，请稍后再试")
            return

        config = get_config_manager()
        self._offset_all_active = True
        self._offset_all_original_pga = config.pga_gain
        self._offset_all_cursor = 0
        self._offset_all_cancel_pending = False
        self._offset_all_results = []
        self._offset_all_wait_pga = False
        self._offset_all_wait_offset = False
        self._offset_all_pga_buffer = ""
        self._offset_all_pga_retries = 0
        self._offset_all_set_buttons_enabled(False)

        progress = FullOffsetCalibrationDialog(
            self, total=len(self._offset_all_gains)
        )
        progress.cancel_requested.connect(self._offset_all_on_cancel_requested)
        progress.show()
        self._offset_all_progress = progress

        logger.info("全量程偏置校准开始，共 %d 个量程", len(self._offset_all_gains))
        self._offset_all_start_gain(0)

    def _offset_all_set_buttons_enabled(self, enabled: bool):
        """自动校准期间禁用/恢复偏置相关按钮，避免并发操作。"""
        for name in ("btn_offset_all",):
            btn = self.findChild(QPushButton, name)
            if btn:
                btn.setEnabled(enabled)
        combo = self.findChild(QComboBox, "combo_sensor_range")
        if combo:
            combo.setEnabled(enabled)

    def _offset_all_on_cancel_requested(self):
        """用户点击取消：立即关闭界面；若正在采集则停止并丢弃本轮数据。"""
        if not self._offset_all_active:
            return
        self._offset_all_cancel_pending = True
        # 立即关闭对话框，不等当前轮结束
        if self._offset_all_progress is not None:
            self._offset_all_progress.accept()
            self._offset_all_progress = None

        if self._offset_all_wait_pga:
            # 正在切换量程，无采集进行中，直接收尾
            self._offset_all_wait_pga = False
            self._offset_all_pga_timer.stop()
            self._offset_all_pga_buffer = ""
            self._offset_all_finish()
            return
        if self._offset_all_wait_offset:
            # 正在偏置采集：立即停止并丢弃残缺数据，finished 到达后收尾
            if self.serial_command is not None:
                self.serial_command.cancel_offset_calibration()
            return
        # 其他间隙：直接收尾
        self._offset_all_finish()

    def _offset_all_update_progress(self, text: str, value: int):
        if self._offset_all_progress is not None:
            self._offset_all_progress.set_progress(value, text)

    def _offset_all_start_gain(self, idx: int):
        """开始第 idx 个量程：先发送 PGA 切换并等待固件确认。"""
        if not self._offset_all_active:
            return
        if idx >= len(self._offset_all_gains) or self._offset_all_cancel_pending:
            self._offset_all_finish()
            return

        self._offset_all_cursor = idx
        gain_idx = self._offset_all_gains[idx]
        self._offset_all_wait_pga = True
        self._offset_all_pga_retries = 0
        self._offset_all_pga_buffer = ""
        self._offset_all_update_progress(
            f"正在切换至 {PGA_OPTION_TEXTS[gain_idx]}（{idx + 1}/{len(self._offset_all_gains)}）…",
            idx,
        )
        if self._offset_all_progress is not None:
            self._offset_all_progress.set_gain_state(idx, "切换中")
        if self.serial_command:
            self.serial_command.send_data(f"PGA{gain_idx}~", source="offset_all_pga")
            self._offset_all_pga_timer.start()
        else:
            self._offset_all_finish()

    def _feed_offset_all_pga_rx(self, data: bytes):
        """解析全量程流程中 PGA<n>~ 的回信（PGA n OK）。"""
        try:
            text = data.decode("utf-8", errors="replace")
        except Exception:
            return
        self._offset_all_pga_buffer += text
        while "\n" in self._offset_all_pga_buffer:
            line, self._offset_all_pga_buffer = self._offset_all_pga_buffer.split("\n", 1)
            line = line.strip("\r").strip()
            if not line:
                continue
            ok_match = re.match(r"^PGA\s+(\d+)\s+OK\s*$", line, re.IGNORECASE)
            if ok_match:
                if not self._offset_all_wait_pga:
                    continue
                target = self._offset_all_gains[self._offset_all_cursor]
                if int(ok_match.group(1)) == target:
                    self._on_offset_all_pga_confirmed()
                continue
            if re.match(r"^PGA\s+(BUSY|RANGE|ERR)\b", line, re.IGNORECASE):
                if self._offset_all_wait_pga:
                    self._offset_all_pga_fail("固件拒绝(BUSY/RANGE/ERR)")
                continue

    def _on_offset_all_pga_confirmed(self):
        """PGA 切换已确认，进入该量程的偏置校准。"""
        self._offset_all_wait_pga = False
        self._offset_all_pga_timer.stop()
        self._offset_all_pga_buffer = ""
        gain_idx = self._offset_all_gains[self._offset_all_cursor]
        logger.info("全量程偏置校准：%s 切换成功", PGA_OPTION_TEXTS[gain_idx])
        self._offset_all_start_offset()

    def _on_offset_all_pga_timeout(self):
        """PGA 切换回信超时：重试一次，仍失败则跳过该档。"""
        if not (self._offset_all_active and self._offset_all_wait_pga):
            return
        if self._offset_all_pga_retries < 1:
            self._offset_all_pga_retries += 1
            gain_idx = self._offset_all_gains[self._offset_all_cursor]
            logger.warning("全量程偏置校准：%s 切换超时，第 1 次重试",
                           PGA_OPTION_TEXTS[gain_idx])
            self._offset_all_pga_buffer = ""
            self.serial_command.send_data(f"PGA{gain_idx}~", source="offset_all_pga_retry")
            self._offset_all_pga_timer.start()
            return
        self._offset_all_pga_fail("PGA 切换超时")

    def _offset_all_pga_fail(self, reason: str):
        """PGA 切换失败：记录后跳过该档，继续下一档。"""
        if not self._offset_all_active:
            return
        self._offset_all_wait_pga = False
        self._offset_all_pga_timer.stop()
        self._offset_all_pga_buffer = ""
        gain_idx = self._offset_all_gains[self._offset_all_cursor]
        logger.warning("全量程偏置校准：%s 失败：%s", PGA_OPTION_TEXTS[gain_idx], reason)
        self._offset_all_results.append((gain_idx, False, None))
        if self._offset_all_progress is not None:
            self._offset_all_progress.show_gain_result(gain_idx, False)
            self._offset_all_progress.set_progress(
                self._offset_all_cursor + 1,
                f"{PGA_OPTION_TEXTS[gain_idx]} 切换失败：{reason}，跳过",
            )
        self._offset_all_next()

    def _offset_all_start_offset(self):
        """对当前量程执行一次偏置校准（结果写入指定量程槽位）。"""
        gain_idx = self._offset_all_gains[self._offset_all_cursor]
        self._offset_all_wait_offset = True
        self._offset_all_update_progress(
            f"正在校准 {PGA_OPTION_TEXTS[gain_idx]} 偏置"
            f"（{self._offset_all_cursor + 1}/{len(self._offset_all_gains)}）…",
            self._offset_all_cursor,
        )
        if self._offset_all_progress is not None:
            self._offset_all_progress.set_gain_state(self._offset_all_cursor, "校准中")
        if self.data_process is not None:
            self.data_process.set_offset_save_pga(gain_idx)
        if self.serial_command:
            self.serial_command.disable_position_query_timer()
            self.serial_command.offset_calibration()

    def _on_offset_all_offset_finished(self, success: bool):
        """某一档偏置校准流程结束（含固件内部重试后的最终结果）。"""
        if not (self._offset_all_active and self._offset_all_wait_offset):
            return
        # 固件内部自动重试尚未结束，继续等待
        if getattr(self.serial_command, '_offset_retrying', False):
            return
        # 用户已取消：结束流程，不再进入下一量程
        if self._offset_all_cancel_pending:
            self._offset_all_wait_offset = False
            self._offset_all_finish()
            return

        self._offset_all_wait_offset = False
        gain_idx = self._offset_all_gains[self._offset_all_cursor]
        offset_value = None
        if success:
            config = get_config_manager()
            offset_value = config.get_offset_for_pga(gain_idx)
        self._offset_all_results.append((gain_idx, bool(success), offset_value))
        offset_mt = None
        if success and offset_value is not None:
            offset_mt = offset_value / get_pga_mag_conversion_factor(gain_idx)
        logger.info(
            "全量程偏置校准：%s %s（offset=%s）",
            PGA_OPTION_TEXTS[gain_idx],
            "成功" if success else "失败",
            f"{offset_value:.1f}" if offset_value is not None else "-",
        )
        if self.serial_command:
            self.serial_command.enable_position_query_timer()
        if self._offset_all_progress is not None:
            self._offset_all_progress.show_gain_result(
                gain_idx, bool(success), offset_value, offset_mt
            )
            self._offset_all_progress.set_progress(
                self._offset_all_cursor + 1,
                f"已完成 {self._offset_all_cursor + 1}/{len(self._offset_all_gains)} 个量程",
            )
        self._offset_all_next()

    def _offset_all_next(self):
        """进入下一个量程。"""
        self._offset_all_start_gain(self._offset_all_cursor + 1)

    def _offset_all_finish(self):
        """全部结束：恢复原量程并汇总结果。"""
        if not self._offset_all_active:
            return
        self._offset_all_active = False
        self._offset_all_cancel_pending = False
        self._offset_all_wait_pga = False
        self._offset_all_wait_offset = False
        self._offset_all_pga_timer.stop()
        self._offset_all_pga_buffer = ""
        if self.data_process is not None:
            self.data_process.clear_offset_save_pga()
        if self.serial_command:
            self.serial_command.enable_position_query_timer()

        # 恢复进入前的 PGA 量程
        config = get_config_manager()
        if self._offset_all_original_pga is not None:
            config.pga_gain = self._offset_all_original_pga

        self._offset_all_set_buttons_enabled(True)

        ok = [r for r in self._offset_all_results if r[1]]
        failed = [r for r in self._offset_all_results if not r[1]]
        logger.info("全量程偏置校准结束：成功 %d 个，失败 %d 个", len(ok), len(failed))
        if self._offset_all_progress is not None:
            self._offset_all_progress.finish(len(ok), len(failed))

    def _offset_all_force_stop(self):
        """串口断开等异常情况下直接中止自动校准（不恢复硬件量程）。"""
        if not self._offset_all_active:
            return
        self._offset_all_active = False
        self._offset_all_cancel_pending = False
        self._offset_all_wait_pga = False
        self._offset_all_wait_offset = False
        self._offset_all_pga_timer.stop()
        self._offset_all_pga_buffer = ""
        if self.data_process is not None:
            self.data_process.clear_offset_save_pga()
            self.data_process.request_offset_abort()
        self._offset_all_set_buttons_enabled(True)
        if self._offset_all_progress is not None:
            self._offset_all_progress.close()
            self._offset_all_progress = None
        logger.warning("串口断开，全量程偏置校准已中止")

    def _on_test_pos(self):
        """移动到测试位置"""
        if self.serial_command:
            self.serial_command.test_position()
            logger.info("移动到测试位置")
        else:
            logger.warning("串口命令未初始化")

    def _on_suspend(self):
        """移动到挂起位置"""
        if self.serial_command:
            self.serial_command.suspend_position()
            logger.info("移动到挂起位置")
        else:
            logger.warning("串口命令未初始化")

    def _on_test_pos_save(self):
        """保存当前测试位置（水平=X, 竖直=Y）"""
        try:
            x_display = self.findChild(QLineEdit, "position_x")
            y_display = self.findChild(QLineEdit, "position_y")
            if x_display and y_display:
                x = int(x_display.text())
                y = int(y_display.text())
                config = get_config_manager()
                config.test_x = x
                config.test_z = y   # 竖直位置存入 test_z 键
                logger.info(f"保存测试位置: 水平={x}, 竖直={y}")

                test_x_display = self.findChild(QLineEdit, "test_x_value")
                test_y_display = self.findChild(QLineEdit, "test_y_value")
                if test_x_display:
                    test_x_display.setText(str(x))
                if test_y_display:
                    test_y_display.setText(str(y))
        except ValueError:
            logger.warning("无效的位置数据，无法保存")

    def _on_suspend_save(self):
        """保存当前挂起位置（水平=X, 竖直=Y）"""
        try:
            x_display = self.findChild(QLineEdit, "position_x")
            y_display = self.findChild(QLineEdit, "position_y")
            if x_display and y_display:
                x = int(x_display.text())
                y = int(y_display.text())
                config = get_config_manager()
                config.suspend_x = x
                config.suspend_z = y   # 竖直位置存入 suspend_z 键
                logger.info(f"保存挂起位置: 水平={x}, 竖直={y}")

                suspend_x_display = self.findChild(QLineEdit, "suspend_x_value")
                suspend_y_display = self.findChild(QLineEdit, "suspend_y_value")
                if suspend_x_display:
                    suspend_x_display.setText(str(x))
                if suspend_y_display:
                    suspend_y_display.setText(str(y))
        except ValueError:
            logger.warning("无效的位置数据，无法保存")
