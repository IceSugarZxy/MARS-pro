# -*- coding: utf-8 -*-
"""
串口设置面板
"""
import time
import serial
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QGroupBox, QGridLayout, QComboBox, QPushButton, QTextEdit, QHBoxLayout
from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from core.logger import get_logger
from core import get_config_manager

logger = get_logger('SerialPanel')


class SerialPanel(QWidget):
    """串口设置面板"""

    signal_serial_connected = pyqtSignal(bool, str)
    signal_serial_status_changed = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.thread_manager = None
        self.serial_manager = None
        self._setup_ui()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(16)

        title = QLabel("串口设置")
        title.setObjectName("panel_title")
        main_layout.addWidget(title)

        # 串口参数
        param_group = QGroupBox("串口参数")
        param_layout = QGridLayout(param_group)

        param_layout.addWidget(QLabel("端口:"), 0, 0)
        self.port_combo = QComboBox()
        self._refresh_ports()
        param_layout.addWidget(self.port_combo, 0, 1)

        param_layout.addWidget(QLabel("波特率:"), 0, 2)
        self.baudrate_combo = QComboBox()
        self.baudrate_combo.addItems(["9600", "115200", "921600"])
        self.baudrate_combo.setCurrentText("921600")
        param_layout.addWidget(self.baudrate_combo, 0, 3)

        param_layout.addWidget(QLabel("数据位:"), 1, 0)
        self.databits_combo = QComboBox()
        self.databits_combo.addItems(["5", "6", "7", "8"])
        self.databits_combo.setCurrentText("8")
        param_layout.addWidget(self.databits_combo, 1, 1)

        param_layout.addWidget(QLabel("停止位:"), 1, 2)
        self.stopbits_combo = QComboBox()
        self.stopbits_combo.addItems(["1", "1.5", "2"])
        param_layout.addWidget(self.stopbits_combo, 1, 3)

        param_layout.addWidget(QLabel("校验:"), 2, 0)
        self.parity_combo = QComboBox()
        self.parity_combo.addItems(["无", "奇", "偶"])
        param_layout.addWidget(self.parity_combo, 2, 1)

        # 刷新串口按钮
        refresh_btn = QPushButton("刷新串口")
        refresh_btn.clicked.connect(self._refresh_ports)
        param_layout.addWidget(refresh_btn, 2, 2, 1, 2)

        main_layout.addWidget(param_group)

        # 连接按钮
        btn_row = QHBoxLayout()
        self.connect_btn = QPushButton("连接")
        self.connect_btn.setObjectName("btnSuccess")
        self.disconnect_btn = QPushButton("断开")
        self.disconnect_btn.setObjectName("btnDanger")
        self.disconnect_btn.setEnabled(False)
        self.connect_btn.clicked.connect(self._on_connect_clicked)
        self.disconnect_btn.clicked.connect(self._on_disconnect_clicked)
        btn_row.addWidget(self.connect_btn)
        btn_row.addWidget(self.disconnect_btn)
        btn_row.addStretch()
        main_layout.addLayout(btn_row)

        # 状态标签
        self.status_label = QLabel("未连接")
        self.status_label.setObjectName("serial_status_label")
        main_layout.addWidget(self.status_label)

        # 串口监视器
        monitor_group = QGroupBox("串口监视器")
        monitor_layout = QVBoxLayout(monitor_group)
        self.send_text = QTextEdit()
        self.send_text.setMaximumHeight(80)
        self.receive_text = QTextEdit()
        self.receive_text.setReadOnly(True)
        monitor_layout.addWidget(QLabel("发送:"))
        monitor_layout.addWidget(self.send_text)
        monitor_layout.addWidget(QLabel("接收:"))
        monitor_layout.addWidget(self.receive_text)
        main_layout.addWidget(monitor_group, 1)

        # 连接超时定时器
        self._connection_timeout_timer = QTimer()
        self._connection_timeout_timer.setSingleShot(True)
        self._connection_timeout_timer.timeout.connect(self._on_connection_timeout)

        logger.info("SerialPanel 初始化完成")

    def _refresh_ports(self):
        """刷新可用串口列表"""
        self.port_combo.clear()
        try:
            ports = list(serial.tools.list_ports.comports())
            for port in ports:
                self.port_combo.addItem(port.device)
            if self.port_combo.count() == 0:
                self.port_combo.addItem("无可用串口")
                self.port_combo.setEnabled(False)
            else:
                self.port_combo.setEnabled(True)
        except Exception as e:
            logger.error(f"刷新串口失败: {e}")
            self.port_combo.addItem("刷新失败")

    def _on_connect_clicked(self):
        """连接按钮点击"""
        if not self.thread_manager or not self.thread_manager.serial_manager:
            logger.error("串口管理器未初始化")
            return

        if self.thread_manager.serial_manager.get_connection_status():
            logger.info("串口已连接")
            return

        com_port = self.port_combo.currentText()
        if not com_port or com_port == "无可用串口":
            logger.error("请选择有效的串口")
            return

        baudrate = self.baudrate_combo.currentText()
        bytesize = self.databits_combo.currentText()
        stopbits = self.stopbits_combo.currentText()
        parity_text = self.parity_combo.currentText()
        parity_map = {"无": "N", "奇": "O", "偶": "E"}
        parity = parity_map.get(parity_text, "N")

        self.status_label.setText("正在连接...")
        self.status_label.setStyleSheet("color: #3498db; font-weight: bold;")

        # 启动连接超时定时器
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
        self.status_label.setText("连接超时")
        self.status_label.setStyleSheet("color: #e74c3c; font-weight: bold;")
        logger.warning("串口连接超时")

    def set_thread_manager(self, tm):
        """设置线程管理器"""
        self.thread_manager = tm
        if tm:
            self.serial_manager = tm.serial_manager
            # 连接信号
            if hasattr(self.serial_manager, 'signal_serial_connected'):
                self.serial_manager.signal_serial_connected.connect(self._on_serial_connected)
            if hasattr(self.serial_manager, 'signal_serial_disconnected'):
                self.serial_manager.signal_serial_disconnected.connect(self._on_serial_disconnected)
            if hasattr(self.serial_manager, 'signal_serial_error'):
                self.serial_manager.signal_serial_error.connect(self._on_serial_error)

    def _on_serial_connected(self, port):
        """串口连接成功"""
        self._connection_timeout_timer.stop()
        self.status_label.setText(f"已连接 {port}")
        self.status_label.setStyleSheet("color: #27ae60; font-weight: bold;")
        self.connect_btn.setEnabled(False)
        self.disconnect_btn.setEnabled(True)
        self.signal_serial_connected.emit(True, port)
        logger.info(f"串口 {port} 连接成功")

    def _on_serial_disconnected(self):
        """串口断开"""
        self.status_label.setText("未连接")
        self.status_label.setStyleSheet("")
        self.connect_btn.setEnabled(True)
        self.disconnect_btn.setEnabled(False)
        self.signal_serial_connected.emit(False, "")
        logger.info("串口已断开")

    def _on_serial_error(self, message):
        """串口错误"""
        self._connection_timeout_timer.stop()
        self.status_label.setText(f"错误: {message}")
        self.status_label.setStyleSheet("color: #e74c3c; font-weight: bold;")
        logger.error(f"串口错误: {message}")

    def auto_connect_from_config(self):
        """从配置文件读取串口号并自动连接"""
        try:
            config = get_config_manager()
            com_port = config.com_port

            if not com_port:
                logger.info("配置文件中未找到COM端口设置")
                return False

            logger.info(f"从配置文件中读取到串口号: {com_port}")

            if not hasattr(self, 'port_combo') or self.port_combo is None:
                logger.info("串口选择框未初始化")
                return False

            # 扫描当前可用串口
            try:
                ports = list(serial.tools.list_ports.comports())
                available_ports = [port.device for port in ports]

                if com_port in available_ports:
                    logger.info(f"串口 {com_port} 可用，尝试自动连接...")
                    self.port_combo.setCurrentText(com_port)

                    baudrate = self.baudrate_combo.currentText() if hasattr(self, 'baudrate_combo') else "921600"
                    bytesize = self.databits_combo.currentText() if hasattr(self, 'databits_combo') else "8"
                    stopbits = self.stopbits_combo.currentText() if hasattr(self, 'stopbits_combo') else "1"
                    parity_text = self.parity_combo.currentText() if hasattr(self, 'parity_combo') else "无"
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

                        self.status_label.setText("自动连接中...")
                        self.status_label.setStyleSheet("color: #3498db; font-weight: bold;")

                        self._connection_timeout_timer.start(2000)

                        logger.info(f"正在自动连接串口 {com_port}...")
                        self.thread_manager.signal_connect.emit(com_port, baudrate, bytesize, stopbits, parity)
                        return True
                    else:
                        logger.info("串口管理器未初始化")
                        return False
                else:
                    logger.info(f"串口 {com_port} 不可用")
                    return False

            except Exception as e:
                logger.error(f"扫描串口失败: {e}")
                return False

        except Exception as e:
            logger.error(f"自动连接失败: {e}")
            return False
