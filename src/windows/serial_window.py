# -*- coding: utf-8 -*-
"""
串口设置窗口
使用serial_window.ui文件加载界面布局
"""

import os
import serial.tools.list_ports
from PyQt5.QtWidgets import QMainWindow, QComboBox, QLabel, QTextEdit, QPushButton
from PyQt5.QtCore import Qt, QTimer
from PyQt5 import uic
from ui.window_operations import WindowOperations
from core import ThreadManager
from core import get_config_manager
from core.logger import get_logger

logger = get_logger('SerialWindow')

class SerialWindow(QMainWindow):
    """串口设置窗口"""

    def __init__(self):
        super().__init__()
        
        # 保存组件引用
        self.thread_manager = None
        
        # 连接状态跟踪（已移除，使用串口管理器状态）
        
        # 从serial_window.ui文件加载界面
        ui_file_path = os.path.join(os.path.dirname(__file__), "..", "ui", "serial_window.ui")
        uic.loadUi(ui_file_path, self)
        
        # 初始化窗口操作功能
        self.window_operations = WindowOperations(self)
        
        # 连接按钮事件
        self._connect_buttons()
        
        # 初始化串口参数
        self._init_serial_parameters()
        
        # 初始化状态显示
        self._init_status_display()
        
        # 初始化定时器，每秒扫描一次可用串口
        self.scan_timer = QTimer()
        self.scan_timer.timeout.connect(self._scan_serial_ports)
        self.scan_timer.start(1000)  # 1秒间隔
    
    def _on_connection_status_changed(self, connected):
        """处理连接状态变化"""
        # 停止连接超时定时器
        if hasattr(self, '_connection_timeout_timer') and self._connection_timeout_timer:
            self._connection_timeout_timer.stop()

        if connected:
            self.status_label.setText("已连接")
            self.status_label.setStyleSheet("color: #27ae60; font-weight: bold;")
            self._update_button_state(True)
            logger.info("串口连接成功")
            # 连接成功后保存当前串口到配置文件
            self._save_current_com_to_config()
        else:
            self.status_label.setText("未连接")
            self.status_label.setStyleSheet("color: #e74c3c; font-weight: bold;")
            self._update_button_state(False)
            logger.info("串口断开连接")
    
    def _on_connection_timeout(self):
        """连接超时处理"""
        # 检查是否仍然需要连接（避免重复处理）
        if not self.thread_manager or not self.thread_manager.serial_manager or not self.thread_manager.serial_manager.get_connection_status():
            logger.info("连接超时")
            self.status_label.setText("连接超时")
            self.status_label.setStyleSheet("color: #e74c3c; font-weight: bold;")
            self._update_button_state(False)
            self._show_error("连接超时")
        
        # 停止定时器
        if hasattr(self, '_connection_timeout_timer') and self._connection_timeout_timer:
            self._connection_timeout_timer.stop()
    
    def _init_status_display(self):
        """初始化状态显示"""
        # 查找状态标签
        self.status_label = self.findChild(QLabel, "label_state")
        self.status_label.setText("未连接")
        self.status_label.setStyleSheet("color: #e74c3c; font-weight: bold;")

        # 初始化发送和接收控件
        self._init_send_receive_controls()
    
    def _init_send_receive_controls(self):
        """初始化发送和接收控件"""
        # 发送文本框
        self.send_text_edit = self.findChild(QTextEdit, "send_text_edit")
        # 接收文本框
        self.receive_text_edit = self.findChild(QTextEdit, "receive_text_edit")
        # 发送格式选择
        self.format_combo = self.findChild(QComboBox, "format_combo")
        # 初始状态为未连接
        self._update_button_state(False)
    
    def _connect_buttons(self):
        """连接按钮事件"""
        # 连接连接/断开按钮
        self.connect_disconnect_button = self.findChild(QPushButton, "pushButton_connect")
        self.connect_disconnect_button.clicked.connect(self._connect_disconnect_button_clicked)
        
        # 连接发送按钮
        self.send_button = self.findChild(QPushButton, "pushButton")
        self.send_button.clicked.connect(self._send_button_clicked)
        
        # 连接关闭按钮
        self.close_button = self.findChild(QPushButton, "pushButton_close")
        self.close_button.clicked.connect(self._close_button_clicked)
    
    def _init_serial_parameters(self):
        """初始化串口参数"""
        # 初始化串口号
        self.port_combo = self.findChild(QComboBox, "port_combo")
        if self.port_combo is not None:
            # 初始扫描一次可用串口
            self._scan_serial_ports()
        
        # 初始化波特率
        baudrate_combo = self.findChild(QComboBox, "baudrate_combo")
        baudrates = ["1200", "2400", "4800", "9600", "14400", "19200", 
                    "38400", "56000", "57600", "115200", "128000", 
                    "256000", "460800", "921600"]
        baudrate_combo.addItems(baudrates)
        baudrate_combo.setCurrentText("921600")  # 默认设置为921600
        
        # 初始化数据位
        databits_combo = self.findChild(QComboBox, "databits_combo")
        databits_combo.addItems(["5", "6", "7", "8"])
        databits_combo.setCurrentText("8")
        
        # 初始化停止位
        stopbits_combo = self.findChild(QComboBox, "stopbits_combo")
        stopbits_combo.addItems(["1", "1.5", "2"])
        stopbits_combo.setCurrentText("1")
        
        # 初始化校验位
        parity_combo = self.findChild(QComboBox, "parity_combo")
        parity_combo.addItems(["无", "奇校验", "偶校验", "标记", "空格"])
        parity_combo.setCurrentText("无")
    
    def _connect_disconnect_button_clicked(self):
        """连接/断开按钮点击事件 - 单个按键切换功能"""
        
        # 检查线程管理器是否初始化
        if not self.thread_manager:
            self._show_error("线程管理器未初始化")
            return
        
        # 根据当前连接状态执行相应操作
        if self.thread_manager.serial_manager and self.thread_manager.serial_manager.get_connection_status():
            # 当前已连接，执行断开操作
            self._disconnect_serial()
        else:
            # 当前未连接，执行连接操作
            self._connect_serial()
    
    def _connect_serial(self):
        """连接串口"""
        # 检查线程管理器是否已设置
        if not self.thread_manager:
            self._show_error("线程管理器未初始化")
            return False
            
        # 获取串口参数
        port = self.port_combo.currentText() if self.port_combo else ""
        baudrate = self.baudrate_combo.currentText() if hasattr(self, 'baudrate_combo') and self.baudrate_combo else "921600"
        bytesize = self.databits_combo.currentText() if hasattr(self, 'databits_combo') and self.databits_combo else "8"
        stopbits = self.stopbits_combo.currentText() if hasattr(self, 'stopbits_combo') and self.stopbits_combo else "1"
        parity = self.parity_combo.currentText() if hasattr(self, 'parity_combo') and self.parity_combo else "无"
        
        # 验证参数
        if not port or port == "无可用串口" or port == "扫描串口失败":
            self._show_error("请选择有效的串口号")
            return False
        
        # 设置连接中状态
        self.status_label.setText("连接中...")
        self.status_label.setStyleSheet("color: #3498db; font-weight: bold;")
        self.connect_disconnect_button.setEnabled(False)
        
        # 启动连接超时定时器（2秒超时）
        if not hasattr(self, '_connection_timeout_timer'):
            self._connection_timeout_timer = QTimer()
            self._connection_timeout_timer.setSingleShot(True)
            self._connection_timeout_timer.timeout.connect(self._on_connection_timeout)

        self._connection_timeout_timer.start(2000)
        logger.info("连接超时定时器已启动，2秒后触发")

        # 异步连接请求
        self.thread_manager.signal_connect.emit(port, baudrate, bytesize, stopbits, parity)
        logger.info(f"正在连接串口 {port}...")
        return True
    
    def _disconnect_serial(self):
        """断开串口"""
        # 检查线程管理器是否初始化
        if not self.thread_manager or not self.thread_manager.serial_manager:
            self._show_error("线程管理器或串口管理器未初始化")
            return
            
        # 设置断开中状态
        self.status_label.setText("断开中...")
        self.status_label.setStyleSheet("color: #3498db; font-weight: bold;")
        self.connect_disconnect_button.setEnabled(False)
        
        # 执行断开操作
        self.thread_manager.serial_manager.disconnect_serial()
        logger.info("断开串口连接")
        
        # 立即更新按钮状态
        self._update_button_state(False)
    
    def _send_button_clicked(self):
        """发送按钮点击事件"""
        # 检查线程管理器是否已设置
        if not self.thread_manager:
            self._show_error("线程管理器未初始化")
            return
            
        # 使用SerialManager的连接状态
        if not self.thread_manager.serial_manager or not self.thread_manager.serial_manager.get_connection_status():
            self._show_error("串口未连接，无法发送数据")
            return
        
        # 获取发送内容
        send_text = self.send_text_edit.toPlainText().strip()
        if not send_text:
            self._show_error("请输入要发送的数据")
            return
        
        # 直接发送数据
        try:
            self.thread_manager.write_queue.put(send_text)
            logger.info(f"发送数据: {send_text}")
            # 清空发送框
            self.send_text_edit.clear()
        except Exception as e:
            self._show_error(f"发送数据失败: {str(e)}")
            
    def _scan_serial_ports(self):
        """扫描可用串口并更新列表"""
        if not hasattr(self, 'port_combo') or self.port_combo is None:
            return
        
        # 获取当前选中的串口号
        current_port = self.port_combo.currentText()
        
        # 扫描可用串口
        try:
            ports = list(serial.tools.list_ports.comports())
            # 按数字大小排序串口号
            ports.sort(key=lambda x: int(x.device[3:]) if x.device[3:].isdigit() else 999)
            
            # 获取串口号列表
            port_names = [port.device for port in ports]
            
            # 更新下拉框
            self.port_combo.clear()
            if port_names:
                self.port_combo.addItems(port_names)
                # 如果之前的选中项仍然存在，保持选中
                if current_port in port_names:
                    self.port_combo.setCurrentText(current_port)
                else:
                    # 否则选择第一个可用串口
                    self.port_combo.setCurrentIndex(0)
            else:
                # 没有可用串口时添加提示
                self.port_combo.addItem("无可用串口")
                
        except Exception as e:
            self.port_combo.clear()
            self.port_combo.addItem("扫描串口失败")

    def _on_data_received(self, data_bytes):
        """接收数据处理"""
        # 只有当串口窗口可见时才在文本框中显示数据
        if self.isVisible():
            try:
                # 尝试解码为UTF-8文本
                decoded_text = data_bytes.decode('utf-8', errors='ignore')
                self.receive_text_edit.append(decoded_text)
            except Exception as e:
                # 如果是二进制数据，显示为十六进制格式
                hex_data = data_bytes.hex()
                self.receive_text_edit.append(f"[二进制数据] {hex_data}")
    
    def _update_button_state(self, connected):
        """更新按钮状态"""
        if not self.connect_disconnect_button:
            return

        # 确保按钮始终处于启用状态
        self.connect_disconnect_button.setEnabled(True)

        if connected:
            # 已连接状态
            self.connect_disconnect_button.setText("断开")
            self.connect_disconnect_button.setStyleSheet(
                "QPushButton { background-color: #e74c3c; color: white; font-weight: bold; border-radius: 5px; } "
                "QPushButton:hover { background-color: #c0392b; }"
            )

            # 已连接状态下禁用串口设置下拉框
            self._set_serial_controls_enabled(False)
        else:
            # 未连接状态
            self.connect_disconnect_button.setText("连接")
            self.connect_disconnect_button.setStyleSheet(
                "QPushButton { background-color: #4CAF50; color: white; font-weight: bold; border-radius: 5px; } "
                "QPushButton:hover { background-color: #66BB6A; }"
            )

            # 未连接状态下启用串口设置下拉框
            self._set_serial_controls_enabled(True)
    
    def _show_error(self, message):
        """显示错误信息"""
        if self.status_label:
            # 截断过长的消息
            display_message = message if len(message) <= 30 else message[:27] + "..."
            self.status_label.setText(f"错误: {display_message}")
            self.status_label.setStyleSheet("color: #e74c3c; font-weight: bold;")
        else:
            logger.info(f"错误: {message}")
    
    def auto_connect_from_config(self):
        """从配置文件读取串口号并自动连接"""
        try:
            # 使用ConfigManager读取配置
            config = get_config_manager()
            com_port = config.com_port

            if not com_port:
                logger.info("配置文件中未找到COM端口设置")
                return False

            logger.info(f"从配置文件中读取到串口号: {com_port}")
            
            # 检查该串口是否在可用列表中
            if not hasattr(self, 'port_combo') or self.port_combo is None:
                logger.info("串口选择框未初始化")
                return False
            
            # 扫描当前可用串口
            try:
                ports = list(serial.tools.list_ports.comports())
                available_ports = [port.device for port in ports]
                
                if com_port in available_ports:
                    logger.info(f"串口 {com_port} 可用，尝试自动连接...")
                    
                    # 设置串口号
                    self.port_combo.setCurrentText(com_port)
                    
                    # 获取其他串口参数
                    baudrate = self.baudrate_combo.currentText() if hasattr(self, 'baudrate_combo') and self.baudrate_combo else "921600"
                    bytesize = self.databits_combo.currentText() if hasattr(self, 'databits_combo') and self.databits_combo else "8"
                    stopbits = self.stopbits_combo.currentText() if hasattr(self, 'stopbits_combo') and self.stopbits_combo else "1"
                    parity = self.parity_combo.currentText() if hasattr(self, 'parity_combo') and self.parity_combo else "无"
                    
                    # 检查是否已经连接
                    if self.thread_manager and self.thread_manager.serial_manager and self.thread_manager.serial_manager.get_connection_status():
                        logger.info("串口已连接，跳过自动连接")
                        return True
                    
                    # 尝试连接（异步操作）
                    if self.thread_manager and self.thread_manager.serial_manager:
                        # 检查是否已经连接或正在连接
                        if self.thread_manager.serial_manager.get_connection_status():
                            logger.info("串口已连接，跳过自动连接")
                            return True
                        
                        # 延迟一段时间再尝试连接，确保系统完全初始化
                        import time
                        time.sleep(1)  # 延迟1秒
                        
                        # 再次检查是否已经连接（可能在延迟期间手动连接了）
                        if self.thread_manager.serial_manager.get_connection_status():
                            logger.info("串口已连接，跳过自动连接")
                            return True
                        
                        self.status_label.setText("自动连接中...")
                        self.status_label.setStyleSheet("color: #3498db; font-weight: bold;")

                        # 启动连接超时定时器（2秒超时）
                        if not hasattr(self, '_connection_timeout_timer'):
                            self._connection_timeout_timer = QTimer()
                            self._connection_timeout_timer.setSingleShot(True)
                            self._connection_timeout_timer.timeout.connect(self._on_connection_timeout)

                        self._connection_timeout_timer.start(2000)
                        
                        logger.info(f"正在自动连接串口 {com_port}...")
                        # 异步连接请求
                        self.thread_manager.signal_connect.emit(com_port, baudrate, bytesize, stopbits, parity)
                        return True
                    else:
                        logger.info("串口管理器未初始化")
                        return False
                else:
                    logger.info(f"串口 {com_port} 不可用，当前可用串口: {available_ports}")
                    return False
            except Exception as e:
                logger.info(f"扫描串口时出错: {e}")
                return False
        except Exception as e:
            logger.info(f"自动连接串口时出错: {e}")
            return False
    
    def _set_serial_controls_enabled(self, enabled):
        """设置串口设置控件的启用状态"""
        try:
            # 串口号下拉框
            if hasattr(self, 'port_combo') and self.port_combo:
                self.port_combo.setEnabled(enabled)
            
            # 波特率下拉框
            if hasattr(self, 'baudrate_combo') and self.baudrate_combo:
                self.baudrate_combo.setEnabled(enabled)
            
            # 数据位下拉框
            if hasattr(self, 'databits_combo') and self.databits_combo:
                self.databits_combo.setEnabled(enabled)
            
            # 停止位下拉框
            if hasattr(self, 'stopbits_combo') and self.stopbits_combo:
                self.stopbits_combo.setEnabled(enabled)
            
            # 校验位下拉框
            if hasattr(self, 'parity_combo') and self.parity_combo:
                self.parity_combo.setEnabled(enabled)

            logger.info(f"串口设置控件已{'启用' if enabled else '禁用'}")
            
        except Exception as e:
            logger.info(f"设置串口控件状态时出错: {e}")

    def _save_current_com_to_config(self):
        """保存当前连接的串口到配置文件"""
        try:
            # 获取当前连接的串口号
            if not hasattr(self, 'port_combo') or not self.port_combo:
                logger.info("串口选择框未初始化，无法保存配置")
                return False

            current_port = self.port_combo.currentText()
            if not current_port or current_port in ["无可用串口", "扫描串口失败"]:
                logger.info("当前串口号无效，无法保存配置")
                return False

            # 使用ConfigManager保存配置
            config = get_config_manager()
            config.set('COM', current_port)

            logger.info(f"已保存串口配置: {current_port}")
            return True

        except Exception as e:
            logger.info(f"保存串口配置时出错: {e}")
            return False

    def _close_button_clicked(self):
        """关闭按钮点击事件"""
        # 停止定时器
        if hasattr(self, 'scan_timer') and self.scan_timer.isActive():
            self.scan_timer.stop()
        
        # 只关闭窗口，不断开串口连接
        # 串口连接由全局线程管理器管理，与窗口显示无关
        self.window_operations.close_window()
    
    def closeEvent(self, event):
        """窗口关闭事件"""
        # 停止定时器
        if hasattr(self, 'scan_timer') and self.scan_timer.isActive():
            self.scan_timer.stop()
        
        # 只关闭窗口，不断开串口连接
        # 串口连接由全局线程管理器管理，与窗口显示无关
        event.accept()
    
    def mouseDoubleClickEvent(self, event):
        """双击窗口上方区域最大化/还原窗口"""
        if event.button() == Qt.LeftButton:
            # 检查是否在窗口上方区域（顶部100像素）
            if event.pos().y() <= 100:
                self.window_operations.maximize_window()
        
        super().mouseDoubleClickEvent(event)


def show_serial_window():
    """
    显示串口设置窗口
    
    Returns:
        SerialWindow: 串口窗口对象
    """
    serial_window = SerialWindow()
    serial_window.show()
    return serial_window