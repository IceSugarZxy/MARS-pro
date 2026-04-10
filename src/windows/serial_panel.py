# -*- coding: utf-8 -*-
"""
串口设置面板 - 从 serial_panel.ui 加载
"""

import os
import time
import serial
from PyQt5.QtWidgets import (QWidget, QLabel, QComboBox, QPushButton, QTextEdit,
                              QGroupBox, QHBoxLayout)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from PyQt5 import uic
from core.logger import get_logger
from core import get_config_manager

logger = get_logger('SerialPanel')


class SerialPanel(QWidget):
    """串口设置面板 - 从 serial_panel.ui 加载"""

    signal_serial_connected = pyqtSignal(bool, str)
    signal_serial_status_changed = pyqtSignal(str)

    def __init__(self):
        super().__init__()

        # 加载 UI
        ui_file_path = os.path.join(os.path.dirname(__file__), "..", "ui", "serial_panel.ui")
        uic.loadUi(ui_file_path, self)

        self.thread_manager = None
        self.serial_manager = None

        # 连接按钮事件
        self._connect_buttons()

        # 刷新串口列表
        self._refresh_ports()

        # 初始化定时器
        self._connection_timeout_timer = QTimer()
        self._connection_timeout_timer.setSingleShot(True)
        self._connection_timeout_timer.timeout.connect(self._on_connection_timeout)

        logger.info("SerialPanel 初始化完成")

    def _connect_buttons(self):
        """连接按钮事件"""
        self.findChild(QPushButton, "connect_btn").clicked.connect(self._on_connect_clicked)
        self.findChild(QPushButton, "disconnect_btn").clicked.connect(self._on_disconnect_clicked)
        self.findChild(QPushButton, "refresh_btn").clicked.connect(self._refresh_ports)

    def _refresh_ports(self):
        """刷新可用串口列表"""
        port_combo = self.findChild(QComboBox, "port_combo")
        if not port_combo:
            return

        port_combo.clear()
        try:
            ports = list(serial.tools.list_ports.comports())
            for port in ports:
                port_combo.addItem(port.device)
            if port_combo.count() == 0:
                port_combo.addItem("无可用串口")
                port_combo.setEnabled(False)
            else:
                port_combo.setEnabled(True)
        except Exception as e:
            logger.error(f"刷新串口失败: {e}")
            port_combo.addItem("刷新失败")

    def _on_connect_clicked(self):
        """连接按钮点击"""
        if not self.thread_manager or not self.thread_manager.serial_manager:
            logger.error("串口管理器未初始化")
            return

        if self.thread_manager.serial_manager.get_connection_status():
            logger.info("串口已连接")
            return

        port_combo = self.findChild(QComboBox, "port_combo")
        com_port = port_combo.currentText() if port_combo else ""
        if not com_port or com_port == "无可用串口":
            logger.error("请选择有效的串口")
            return

        baud_combo = self.findChild(QComboBox, "baudrate_combo")
        data_combo = self.findChild(QComboBox, "databits_combo")
        stop_combo = self.findChild(QComboBox, "stopbits_combo")
        parity_combo = self.findChild(QComboBox, "parity_combo")

        baudrate = baud_combo.currentText() if baud_combo else "921600"
        bytesize = data_combo.currentText() if data_combo else "8"
        stopbits = stop_combo.currentText() if stop_combo else "1"
        parity_text = parity_combo.currentText() if parity_combo else "无"
        parity_map = {"无": "N", "奇": "O", "偶": "E"}
        parity = parity_map.get(parity_text, "N")

        status_label = self.findChild(QLabel, "status_label")
        if status_label:
            status_label.setText("正在连接...")
            status_label.setStyleSheet("color: #3498db; font-weight: bold;")

        self._connection_timeout_timer.start(2000)

        logger.info(f"正在连接串口 {com_port}...")
        self.thread_manager.signal_connect.emit(com_port, baudrate, bytesize, stopbits, parity)

    def _on_disconnect_clicked(self):
        """断开按钮点击"""
        if not self.thread_manager or not self.thread_manager.serial_manager:
            return

        if not self.thread_manager.serial_manager.get_connection_status():
            return

        self.thread_manager.signal_disconnect.emit()
        logger.info("串口已断开")

    def _on_connection_timeout(self):
        """连接超时"""
        status_label = self.findChild(QLabel, "status_label")
        if status_label:
            status_label.setText("连接超时")
            status_label.setStyleSheet("color: #e74c3c; font-weight: bold;")
        logger.warning("串口连接超时")

    def set_thread_manager(self, tm):
        """设置线程管理器"""
        self.thread_manager = tm
        if tm:
            self.serial_manager = tm.serial_manager
            if hasattr(self.serial_manager, 'signal_connection_status_changed'):
                self.serial_manager.signal_connection_status_changed.connect(self._on_serial_status_changed)

    def _on_serial_status_changed(self, connected):
        """串口状态变化"""
        self._connection_timeout_timer.stop()

        status_label = self.findChild(QLabel, "status_label")
        connect_btn = self.findChild(QPushButton, "connect_btn")
        disconnect_btn = self.findChild(QPushButton, "disconnect_btn")

        if connected:
            port = self.serial_manager.port if hasattr(self.serial_manager, 'port') else ""
            if status_label:
                status_label.setText(f"已连接 {port}")
                status_label.setStyleSheet("color: #27ae60; font-weight: bold;")
            if connect_btn:
                connect_btn.setEnabled(False)
            if disconnect_btn:
                disconnect_btn.setEnabled(True)
            self.signal_serial_connected.emit(True, port)
            logger.info(f"串口 {port} 连接成功")
        else:
            if status_label:
                status_label.setText("未连接")
                status_label.setStyleSheet("")
            if connect_btn:
                connect_btn.setEnabled(True)
            if disconnect_btn:
                disconnect_btn.setEnabled(False)
            self.signal_serial_connected.emit(False, "")
            logger.info("串口已断开")

    def auto_connect_from_config(self):
        """从配置文件读取串口号并自动连接"""
        try:
            config = get_config_manager()
            com_port = config.com_port

            if not com_port:
                logger.info("配置文件中未找到COM端口设置")
                return False

            logger.info(f"从配置文件中读取到串口号: {com_port}")

            try:
                ports = list(serial.tools.list_ports.comports())
                available_ports = [port.device for port in ports]

                if com_port in available_ports:
                    logger.info(f"串口 {com_port} 可用，尝试自动连接...")
                    port_combo = self.findChild(QComboBox, "port_combo")
                    if port_combo:
                        port_combo.setCurrentText(com_port)

                    baud_combo = self.findChild(QComboBox, "baudrate_combo")
                    data_combo = self.findChild(QComboBox, "databits_combo")
                    stop_combo = self.findChild(QComboBox, "stopbits_combo")
                    parity_combo = self.findChild(QComboBox, "parity_combo")

                    baudrate = baud_combo.currentText() if baud_combo else "921600"
                    bytesize = data_combo.currentText() if data_combo else "8"
                    stopbits = stop_combo.currentText() if stop_combo else "1"
                    parity_text = parity_combo.currentText() if parity_combo else "无"
                    parity_map = {"无": "N", "奇": "O", "偶": "E"}
                    parity = parity_map.get(parity_text, "N")

                    if self.thread_manager and self.thread_manager.serial_manager:
                        if self.thread_manager.serial_manager.get_connection_status():
                            logger.info("串口已连接，跳过自动连接")
                            return True

                        time.sleep(1)

                        if self.thread_manager.serial_manager.get_connection_status():
                            logger.info("串口已连接，跳过自动连接")
                            return True

                        status_label = self.findChild(QLabel, "status_label")
                        if status_label:
                            status_label.setText("自动连接中...")
                            status_label.setStyleSheet("color: #3498db; font-weight: bold;")

                        self._connection_timeout_timer.start(2000)
                        logger.info(f"正在自动连接串口 {com_port}...")
                        self.thread_manager.signal_connect.emit(com_port, baudrate, bytesize, stopbits, parity)
                        return True
                else:
                    logger.info(f"串口 {com_port} 不可用")
                    return False

            except Exception as e:
                logger.error(f"扫描串口失败: {e}")
                return False

        except Exception as e:
            logger.error(f"自动连接失败: {e}")
            return False
