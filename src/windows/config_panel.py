# -*- coding: utf-8 -*-
"""
配置面板 - 从 config_panel.ui 加载
"""

import os
import serial.tools.list_ports
from PyQt5.QtCore import Qt, QTimer, QObject, QEvent
from PyQt5.QtGui import QTextCursor
from PyQt5.QtWidgets import QWidget, QPushButton, QLineEdit, QLabel, QComboBox, QToolButton, QDoubleSpinBox, QPlainTextEdit
from PyQt5 import uic
from core.logger import get_logger
from core import get_config_manager
from core.config_manager import SENSOR_RANGE_OPTIONS, action_to_text
from core.offset_calibration_config import OFFSET_PROGRESS_SECONDS
from windows.offset_calibration_dialog import OffsetCalibrationDialog
from windows.scheme_edit_dialog import SchemeEditDialog

logger = get_logger('ConfigPanel')


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
        self._init_serial_controls()
        self._init_serial_rx_display()

        # 初始化快捷操作配置
        self._init_quick_action_settings()

        # 偏置校准对话框
        self._offset_dialog = None

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
            # 连接偏置校准完成信号
            tm.data_process.signal_offset_data_process_finished.connect(
                self._on_offset_calibration_finished,
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

        combo_sensor = self.findChild(QComboBox, "combo_sensor")
        if combo_sensor:
            combo_sensor.blockSignals(True)
            combo_sensor.clear()
            combo_sensor.addItems(SENSOR_RANGE_OPTIONS)
            combo_sensor.setCurrentIndex(config.sensor_range)
            combo_sensor.blockSignals(False)
            combo_sensor.currentIndexChanged.connect(self._on_sensor_range_changed)
            config.signal_sensor_range_changed.connect(self._on_config_sensor_range_changed)

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

    def _on_sensor_range_changed(self, index):
        """探头量程改变"""
        config = get_config_manager()
        config.sensor_range = index
        logger.info(f"探头量程已更改: {SENSOR_RANGE_OPTIONS[config.sensor_range]}")

    def _on_config_sensor_range_changed(self, index):
        """配置管理器探头量程改变，同步更新下拉框"""
        combo_sensor = self.findChild(QComboBox, "combo_sensor")
        if combo_sensor and combo_sensor.currentIndex() != index:
            combo_sensor.blockSignals(True)
            combo_sensor.setCurrentIndex(index)
            combo_sensor.blockSignals(False)

    def _sync_sensor_range_from_ui(self):
        combo_sensor = self.findChild(QComboBox, "combo_sensor")
        if combo_sensor:
            get_config_manager().sensor_range = combo_sensor.currentIndex()

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
        self.findChild(QPushButton, "btn_offset").clicked.connect(self._on_offset)
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
        """台控：按发送 ±25000 步，松停止。"""
        moves = {
            "stage_btn_up":    "Y-25000",
            "stage_btn_down":  "Y+25000",
            "stage_btn_left":  "X-25000",
            "stage_btn_right": "X+25000",
            "stage_btn_forward": "Z-25000",
            "stage_btn_back":    "Z+25000",
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

    def _on_offset(self):
        """偏置校准"""
        if self.serial_command:
            self._sync_sensor_range_from_ui()
            logger.info(
                "Offset flow: ConfigPanel request received, "
                f"dialog_present={self._offset_dialog is not None}"
            )
            # 停止位置查询定时器，防止干扰偏置校准
            self.serial_command.disable_position_query_timer()
            logger.info("Offset flow: ConfigPanel disabled position query timer")

            # 显示校准对话框
            self._offset_dialog = OffsetCalibrationDialog(self)
            self._offset_dialog.start_progress(duration=OFFSET_PROGRESS_SECONDS)
            self._offset_dialog.show()
            logger.info("Offset flow: ConfigPanel progress dialog shown")
            self.serial_command.offset_calibration()
            logger.info("Offset flow: ConfigPanel command dispatched")
        else:
            logger.warning("串口命令未初始化")

    def _on_offset_calibration_finished(self, success):
        """偏置校准完成"""
        logger.info(
            "Offset flow: ConfigPanel finished callback, "
            f"success={success}, dialog_present={self._offset_dialog is not None}"
        )
        # 重新启动位置查询定时器
        if self.serial_command:
            self.serial_command.enable_position_query_timer()
        logger.info("Offset flow: ConfigPanel re-enabled position query timer")
        if self._offset_dialog:
            config = get_config_manager()
            offset_value = getattr(config, 'offset', None)
            logger.info(f"Offset flow: ConfigPanel showing result, offset={offset_value}")
            self._offset_dialog.show_result(success, offset_value)
            self._offset_dialog.btn_cancel.clicked.connect(self._close_offset_dialog)

    def _close_offset_dialog(self):
        """关闭偏置校准对话框"""
        if self._offset_dialog:
            logger.info("Offset flow: ConfigPanel offset dialog closed")
            self._offset_dialog.close()
            self._offset_dialog = None

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
