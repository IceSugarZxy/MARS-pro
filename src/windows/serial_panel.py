# -*- coding: utf-8 -*-
"""
串口设置面板 - 从 serial_panel.ui 加载
"""

import os
import time
import serial
import serial.tools.list_ports
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

        # 定时刷新串口列表（每2秒）
        self._port_refresh_timer = QTimer()
        self._port_refresh_timer.setInterval(2000)
        self._port_refresh_timer.timeout.connect(self._refresh_ports)
        self._port_refresh_timer.start()

        logger.info("SerialPanel 初始化完成")

    def _connect_buttons(self):
        """连接按钮事件"""
        self.findChild(QPushButton, "btnSuccess").clicked.connect(self._on_connect_clicked)
        self.findChild(QPushButton, "btnDanger").clicked.connect(self._on_disconnect_clicked)
        self.findChild(QPushButton, "send_btn").clicked.connect(self._on_send_clicked)

    def _refresh_ports(self):
        """刷新可用串口列表"""
        port_combo = self.findChild(QComboBox, "port_combo")
        if port_combo is None:
            logger.error("port_combo not found")
            return

        # 保存当前选择的端口
        current_port = port_combo.currentText()

        # 清空并重新添加
        port_combo.blockSignals(True)  # 阻止选择变化信号
        port_combo.clear()
        try:
            ports = list(serial.tools.list_ports.comports())
            for port in ports:
                port_combo.addItem(port.device)

            # 恢复之前的端口选择（如果新列表中有该端口）
            if current_port:
                idx = port_combo.findText(current_port)
                if idx >= 0:
                    port_combo.setCurrentIndex(idx)

            if port_combo.count() == 0:
                port_combo.addItem("无可用串口")
                port_combo.setEnabled(False)
            else:
                port_combo.setEnabled(True)
        except Exception as e:
            logger.error(f"刷新串口失败: {e}")
            port_combo.addItem("刷新失败")
        finally:
            port_combo.blockSignals(False)  # 恢复信号

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

        baudrate = baud_combo.currentText() if baud_combo else "115200"
        bytesize = data_combo.currentText() if data_combo else "8"
        stopbits = stop_combo.currentText() if stop_combo else "1"
        parity_text = parity_combo.currentText() if parity_combo else "无"
        parity = parity_text  # 直接传递 UI 显示的文本

        status_label = self.findChild(QLabel, "serial_status_label")
        if status_label:
            status_label.setText("正在连接...")
            status_label.setStyleSheet("color: #3498db; font-weight: bold; font-size: 18px;")

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
        status_label = self.findChild(QLabel, "serial_status_label")
        if status_label:
            status_label.setText("连接超时")
            status_label.setStyleSheet("color: #e74c3c; font-weight: bold; font-size: 18px;")
        logger.warning("串口连接超时")

    def _on_send_clicked(self):
        """发送按钮点击"""
        if not self.thread_manager or not self.thread_manager.serial_manager:
            logger.error("串口管理器未初始化")
            return

        if not self.thread_manager.serial_manager.get_connection_status():
            logger.error("串口未连接")
            return

        send_text = self.findChild(QTextEdit, "send_text")
        if not send_text:
            return

        data = send_text.toPlainText()
        if not data:
            logger.warning("发送数据为空")
            return

        # 将数据放入写队列
        try:
            self.thread_manager.serial_manager.write_queue.put(data)
            logger.info(f"发送数据: {data}")
        except Exception as e:
            logger.error(f"发送失败: {e}")

    def set_thread_manager(self, tm):
        """设置线程管理器"""
        self.thread_manager = tm
        if tm:
            self.serial_manager = tm.serial_manager
            if hasattr(self.serial_manager, 'signal_connection_status_changed'):
                self.serial_manager.signal_connection_status_changed.connect(
                    self._on_serial_status_changed, Qt.QueuedConnection)
            if hasattr(self.serial_manager, 'signal_data_received'):
                self.serial_manager.signal_data_received.connect(
                    self._on_data_received, Qt.QueuedConnection)

    def _on_data_received(self, data: bytes):
        """串口数据接收"""
        try:
            receive_text = self.findChild(QTextEdit, "receive_text")
            if receive_text:
                text = data.decode('utf-8', errors='replace')
                receive_text.append(text)
        except Exception as e:
            logger.error(f"接收数据处理失败: {e}")

    def _on_serial_status_changed(self, connected):
        """串口状态变化"""
        self._connection_timeout_timer.stop()

        status_label = self.findChild(QLabel, "serial_status_label")
        connect_btn = self.findChild(QPushButton, "btnSuccess")
        disconnect_btn = self.findChild(QPushButton, "btnDanger")

        if connected:
            port = ""
            baudrate = ""
            if self.serial_manager and hasattr(self.serial_manager, 'serial_port') and self.serial_manager.serial_port:
                port = self.serial_manager.serial_port.portName()
                baudrate = self.serial_manager.serial_port.baudRate()
            if status_label:
                status_label.setText(f"已连接 {port}")
                status_label.setStyleSheet("color: #27ae60; font-weight: bold; font-size: 18px;")
            if connect_btn:
                connect_btn.setEnabled(False)
            if disconnect_btn:
                disconnect_btn.setEnabled(True)

            # 保存连接的串口配置
            config = get_config_manager()
            config.com_port = port
            config.baudrate = baudrate
            logger.info(f"已保存串口配置: {port} @ {baudrate}")

            self.signal_serial_connected.emit(True, port)
            logger.info(f"串口 {port} 连接成功")
        else:
            if status_label:
                status_label.setText("未连接")
                status_label.setStyleSheet("color: #e74c3c; font-weight: bold; font-size: 18px;")
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

                        status_label = self.findChild(QLabel, "serial_status_label")
                        if status_label:
                            status_label.setText("自动连接中...")
                            status_label.setStyleSheet("color: #3498db; font-weight: bold; font-size: 18px;")

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
