# -*- coding: utf-8 -*-
"""
Serial settings panel.
"""

import os
import time

import serial
import serial.tools.list_ports
from PyQt5 import uic
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QTextCursor
from PyQt5.QtWidgets import QComboBox, QLabel, QPushButton, QTextEdit, QWidget

from core import get_config_manager
from core.logger import get_logger

logger = get_logger("SerialPanel")

SERIAL_PANEL_RX_FLUSH_INTERVAL_MS = 150
SERIAL_PANEL_MAX_BLOCKS = 1200


class SerialPanel(QWidget):
    signal_serial_connected = pyqtSignal(bool, str)
    signal_serial_status_changed = pyqtSignal(str)

    def __init__(self):
        super().__init__()

        ui_file_path = os.path.join(os.path.dirname(__file__), "..", "ui", "serial_panel.ui")
        uic.loadUi(ui_file_path, self)

        self.thread_manager = None
        self.serial_manager = None
        self._pending_connection_settings = None
        self._receive_stream_connected = False
        self._rx_buffer = []
        self._receive_text = self.findChild(QTextEdit, "receive_text")
        if self._receive_text and hasattr(self._receive_text.document(), "setMaximumBlockCount"):
            self._receive_text.document().setMaximumBlockCount(SERIAL_PANEL_MAX_BLOCKS)

        self._connect_buttons()

        self._connection_timeout_timer = QTimer(self)
        self._connection_timeout_timer.setSingleShot(True)
        self._connection_timeout_timer.timeout.connect(self._on_connection_timeout)

        self._port_refresh_timer = QTimer(self)
        self._port_refresh_timer.setInterval(2000)
        self._port_refresh_timer.timeout.connect(self._refresh_ports)

        self._rx_flush_timer = QTimer(self)
        self._rx_flush_timer.setInterval(SERIAL_PANEL_RX_FLUSH_INTERVAL_MS)
        self._rx_flush_timer.timeout.connect(self._flush_received_data)

        self._refresh_ports()
        self._apply_serial_settings_to_ui(self._get_serial_settings_from_config())
        logger.info("SerialPanel initialized.")

    def _connect_buttons(self):
        self.findChild(QPushButton, "btnSuccess").clicked.connect(self._on_connect_clicked)
        self.findChild(QPushButton, "btnDanger").clicked.connect(self._on_disconnect_clicked)
        self.findChild(QPushButton, "send_btn").clicked.connect(self._on_send_clicked)

    def _normalize_parity_display(self, value: str) -> str:
        parity_map = {
            "N": "无",
            "O": "奇",
            "E": "偶",
            "M": "标记",
            "S": "空格",
        }
        text = str(value or "无").strip().strip('"').strip("'")
        return parity_map.get(text.upper(), text or "无")

    def _set_combo_text(self, combo_name: str, value: str) -> None:
        combo = self.findChild(QComboBox, combo_name)
        if not combo:
            return

        text = str(value)
        index = combo.findText(text)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _get_serial_settings_from_ui(self) -> dict:
        port_combo = self.findChild(QComboBox, "port_combo")
        baud_combo = self.findChild(QComboBox, "baudrate_combo")
        data_combo = self.findChild(QComboBox, "databits_combo")
        stop_combo = self.findChild(QComboBox, "stopbits_combo")
        parity_combo = self.findChild(QComboBox, "parity_combo")

        return {
            "com_port": port_combo.currentText() if port_combo else "",
            "baudrate": baud_combo.currentText() if baud_combo else "921600",
            "bytesize": data_combo.currentText() if data_combo else "8",
            "stopbits": stop_combo.currentText() if stop_combo else "1",
            "parity": parity_combo.currentText() if parity_combo else "无",
        }

    def _get_serial_settings_from_config(self) -> dict:
        config = get_config_manager()
        return {
            "com_port": config.com_port,
            "baudrate": str(config.baudrate),
            "bytesize": config.bytesize,
            "stopbits": config.stopbits,
            "parity": self._normalize_parity_display(config.parity),
        }

    def _apply_serial_settings_to_ui(self, settings: dict) -> None:
        self._set_combo_text("port_combo", settings.get("com_port", ""))
        self._set_combo_text("baudrate_combo", settings.get("baudrate", "921600"))
        self._set_combo_text("databits_combo", settings.get("bytesize", "8"))
        self._set_combo_text("stopbits_combo", settings.get("stopbits", "1"))
        self._set_combo_text("parity_combo", self._normalize_parity_display(settings.get("parity", "无")))

    def _set_status(self, text: str, color: str) -> None:
        status_label = self.findChild(QLabel, "serial_status_label")
        if status_label:
            status_label.setText(text)
            status_label.setStyleSheet(f"color: {color}; font-weight: bold; font-size: 18px;")

    def _save_serial_settings(self, settings: dict) -> None:
        config = get_config_manager()
        config.com_port = settings.get("com_port", config.com_port)
        config.baudrate = int(settings.get("baudrate", config.baudrate))
        config.bytesize = settings.get("bytesize", config.bytesize)
        config.stopbits = settings.get("stopbits", config.stopbits)
        config.parity = self._normalize_parity_display(settings.get("parity", config.parity))

    def _start_connect(self, settings: dict, status_text: str) -> bool:
        if not self.thread_manager or not self.thread_manager.serial_manager:
            logger.error("Serial manager is not initialized.")
            return False

        if self.thread_manager.serial_manager.get_connection_status():
            logger.info("Serial port is already connected.")
            return True

        com_port = settings.get("com_port", "")
        if not com_port or com_port == "无可用串口":
            logger.error("Please select a valid serial port.")
            return False

        settings = settings.copy()
        settings["parity"] = self._normalize_parity_display(settings.get("parity", "无"))
        self._pending_connection_settings = settings
        self._apply_serial_settings_to_ui(settings)
        self._set_status(status_text, "#3498db")
        self._connection_timeout_timer.start(2000)

        logger.info(f"Connecting serial port {com_port}...")
        self.thread_manager.signal_connect.emit(
            settings["com_port"],
            settings["baudrate"],
            settings["bytesize"],
            settings["stopbits"],
            settings["parity"],
        )
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
        self._set_receive_stream_enabled(True)

    def hideEvent(self, event):
        self._set_receive_stream_enabled(False)
        self._flush_received_data()
        self._set_port_refresh_enabled(False)
        super().hideEvent(event)

    def _refresh_ports(self):
        port_combo = self.findChild(QComboBox, "port_combo")
        if port_combo is None:
            logger.error("port_combo not found")
            return

        current_port = port_combo.currentText() or get_config_manager().com_port

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
                port_combo.setEnabled(True)
        except Exception as e:
            logger.error(f"Refresh serial ports failed: {e}")
            port_combo.addItem("刷新失败")
        finally:
            port_combo.blockSignals(False)

    def _on_connect_clicked(self):
        settings = self._get_serial_settings_from_ui()
        self._start_connect(settings, "正在连接...")

    def _on_disconnect_clicked(self):
        if not self.thread_manager or not self.thread_manager.serial_manager:
            return
        if not self.thread_manager.serial_manager.get_connection_status():
            return

        self.thread_manager.signal_disconnect.emit()
        logger.info("Serial port disconnected.")

    def _on_connection_timeout(self):
        self._set_status("连接超时", "#e74c3c")
        self._pending_connection_settings = None
        logger.warning("Serial connection timed out.")

    def _on_send_clicked(self):
        if not self.thread_manager or not self.thread_manager.serial_manager:
            logger.error("Serial manager is not initialized.")
            return
        if not self.thread_manager.serial_manager.get_connection_status():
            logger.error("Serial port is not connected.")
            return

        send_text = self.findChild(QTextEdit, "send_text")
        if not send_text:
            return

        data = send_text.toPlainText()
        if not data:
            logger.warning("Send data is empty.")
            return

        try:
            tx_item = {
                "id": None,
                "data": data,
                "source": "serial_panel_send",
                "enqueued_at": time.time(),
            }
            queue_before = self.thread_manager.write_queue.qsize()
            self.thread_manager.serial_manager.write_queue.put(tx_item)
            logger.info(
                "Serial TX enqueue from panel: "
                f"command={data}, queue_before={queue_before}, queue_after={self.thread_manager.write_queue.qsize()}"
            )
        except Exception as e:
            logger.error(f"Send failed: {e}")

    def set_thread_manager(self, tm):
        self.thread_manager = tm
        if not tm:
            return

        self.serial_manager = tm.serial_manager
        if hasattr(self.serial_manager, "signal_connection_status_changed"):
            self.serial_manager.signal_connection_status_changed.connect(
                self._on_serial_status_changed, Qt.QueuedConnection
            )
        self._set_receive_stream_enabled(self.isVisible())

    def _set_receive_stream_enabled(self, enabled: bool) -> None:
        if not self.serial_manager or not hasattr(self.serial_manager, "signal_data_received"):
            return

        if enabled and not self._receive_stream_connected:
            self.serial_manager.signal_data_received.connect(
                self._on_data_received, Qt.QueuedConnection
            )
            self._receive_stream_connected = True
        elif not enabled and self._receive_stream_connected:
            try:
                self.serial_manager.signal_data_received.disconnect(self._on_data_received)
            except Exception:
                pass
            self._receive_stream_connected = False

    def _on_data_received(self, data: bytes):
        try:
            if not self.isVisible():
                return
            self._rx_buffer.append(data.decode("utf-8", errors="replace"))
            if not self._rx_flush_timer.isActive():
                self._rx_flush_timer.start()
        except Exception as e:
            logger.error(f"Handle received data failed: {e}")

    def _flush_received_data(self):
        if not self._rx_buffer:
            if self._rx_flush_timer.isActive():
                self._rx_flush_timer.stop()
            return

        receive_text = self._receive_text or self.findChild(QTextEdit, "receive_text")
        if not receive_text:
            self._rx_buffer.clear()
            return

        text = "".join(self._rx_buffer)
        self._rx_buffer.clear()
        receive_text.moveCursor(QTextCursor.End)
        receive_text.insertPlainText(text)
        receive_text.moveCursor(QTextCursor.End)
        if self._rx_flush_timer.isActive():
            self._rx_flush_timer.stop()

    def _on_serial_status_changed(self, connected):
        self._connection_timeout_timer.stop()

        connect_btn = self.findChild(QPushButton, "btnSuccess")
        disconnect_btn = self.findChild(QPushButton, "btnDanger")

        if connected:
            port = ""
            baudrate = ""
            if self.serial_manager and getattr(self.serial_manager, "serial_port", None):
                port = self.serial_manager.serial_port.portName()
                baudrate = str(self.serial_manager.serial_port.baudRate())

            if connect_btn:
                connect_btn.setEnabled(False)
            if disconnect_btn:
                disconnect_btn.setEnabled(True)

            settings = dict(self._pending_connection_settings or self._get_serial_settings_from_ui())
            settings["com_port"] = str(port).strip().strip('"')
            settings["baudrate"] = baudrate or settings.get("baudrate", "921600")
            self._save_serial_settings(settings)
            self._set_status(f"已连接 {settings['com_port']}", "#27ae60")

            if self.thread_manager and getattr(self.thread_manager, "serial_command", None):
                self.thread_manager.serial_command.enable_position_query_timer()

            self.signal_serial_connected.emit(True, settings["com_port"])
            logger.info(
                f"Serial connected: {settings['com_port']} @ {settings['baudrate']} "
                f"{settings['bytesize']}/{settings['stopbits']}/{settings['parity']}"
            )
        else:
            if connect_btn:
                connect_btn.setEnabled(True)
            if disconnect_btn:
                disconnect_btn.setEnabled(False)

            if self.thread_manager and getattr(self.thread_manager, "serial_command", None):
                self.thread_manager.serial_command.disable_position_query_timer()

            self._set_status("未连接", "#e74c3c")
            self.signal_serial_connected.emit(False, "")
            logger.info("Serial disconnected.")

        self._pending_connection_settings = None

    def auto_connect_from_config(self):
        try:
            settings = self._get_serial_settings_from_config()
            com_port = settings["com_port"]
            if not com_port:
                logger.info("No COM port found in configuration.")
                return False

            ports = list(serial.tools.list_ports.comports())
            available_ports = [port.device for port in ports]
            if com_port not in available_ports:
                logger.info(f"Configured serial port {com_port} is unavailable.")
                return False

            return self._start_connect(settings, "自动连接中...")
        except Exception as e:
            logger.error(f"Auto connect failed: {e}")
            return False
