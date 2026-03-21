# -*- coding: utf-8 -*-
"""
旋转体表磁测量分析系统 - 主页面
使用.ui文件加载界面布局
"""

import os
import sys
import subprocess
from PyQt5.QtWidgets import QMainWindow, QWidget
from PyQt5.QtCore import Qt, QEvent
from PyQt5 import uic
from ui.window_operations import WindowOperations
from windows.serial_window import SerialWindow
from windows.position_window import PositionWindow
from windows.measure_window import MeasureWindow
from windows.history_window import HistoryWindow
from windows.compare_window import CompareWindow
from core import ThreadManager
from core.logger import get_logger
logger = get_logger('HomeWindow')

class HomeWindow(QMainWindow):
    """主页面窗口"""
    
    def __init__(self):
        super().__init__()
        self.thread_manager = None
        
        # 窗口引用
        self.serial_window = SerialWindow()
        self.position_window = PositionWindow()
        self.measure_window = MeasureWindow(self.position_window, self)  # 传递position_window和home_window实例
        self.history_window = HistoryWindow(self.measure_window)
        
        # 初始化比对窗口，传递同心度校准状态
        enable_concentricity = self.measure_window.radioButton_Concentricity.isChecked() if hasattr(self.measure_window, 'radioButton_Concentricity') and self.measure_window.radioButton_Concentricity else True
        self.compare_window = CompareWindow(enable_concentricity)
        
        # 从home_window.ui文件加载界面
        ui_file_path = os.path.join(os.path.dirname(__file__), "..", "ui", "home_window.ui")
        uic.loadUi(ui_file_path, self)
        
        # 初始化窗口操作功能
        self.window_operations = WindowOperations(self)
        
        # 连接按钮事件
        self._connect_buttons()
        
        # 安装事件过滤器，捕获关闭事件
        self.installEventFilter(self)
    
    def _connect_buttons(self):
        """连接按钮事件"""
        # 连接串口设置按钮
        serial_button = self.findChild(QWidget, "serial_button")
        if serial_button:
            serial_button.mousePressEvent = self._serial_button_clicked
        
        # 连接测试位置按钮
        position_button = self.findChild(QWidget, "position_button")
        if position_button:
            position_button.mousePressEvent = self._position_button_clicked
        
        # 连接测试界面按钮
        test_button = self.findChild(QWidget, "test_button")
        if test_button:
            test_button.mousePressEvent = self._test_button_clicked
        
        # 连接退出按钮
        exit_button = self.findChild(QWidget, "exit_button")
        if exit_button:
            exit_button.mousePressEvent = self._exit_button_clicked

        # 连接后台日志按钮
        logs_button = self.findChild(QWidget, "logs_button")
        if logs_button:
            logs_button.mousePressEvent = self._logs_button_clicked

        # 连接历史数据读取按钮
        history_button = self.findChild(QWidget, "history_button")
        if history_button:
            history_button.mousePressEvent = self._history_button_clicked
        
        # 连接数据比对按钮
        compare_button = self.findChild(QWidget, "compare_button")
        if compare_button:
            compare_button.mousePressEvent = self._compare_button_clicked
    
    def _serial_button_clicked(self, event):
        """串口设置按钮点击事件"""
        if event.button() == Qt.LeftButton:
            if self.serial_window:
                if not self.serial_window.isVisible():
                    self.serial_window.show()
                else:
                    # 如果窗口已经显示，则将其置顶
                    self.serial_window.raise_()
                    self.serial_window.activateWindow()
            else:
                logger.info("串口窗口引用未设置")
    
    def _position_button_clicked(self, event):
        """测试位置按钮点击事件"""
        if event.button() == Qt.LeftButton:
            if self.position_window:
                # 调用位置窗口的show_window方法，该方法会启动定时器
                self.position_window.show_window()
            else:
                logger.info("位置窗口引用未设置")
    
    def _test_button_clicked(self, event):
        """测试界面按钮点击事件"""
        if event.button() == Qt.LeftButton:
            if self.measure_window:
                # 调用测量窗口的show_window方法
                self.measure_window.show_window()
            else:
                logger.info("测量窗口引用未设置")
    
    def _exit_button_clicked(self, event):
        """退出按钮点击事件"""
        if event.button() == Qt.LeftButton:
            self.window_operations.close_window()

    def _logs_button_clicked(self, event):
        """后台日志按钮点击事件"""
        if event.button() == Qt.LeftButton:
            # 获取logs文件夹路径 (MARS/logs)
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            logs_dir = os.path.join(project_root, "logs")

            if os.path.exists(logs_dir):
                # 使用Windows资源管理器打开文件夹
                subprocess.run(["explorer", logs_dir])
                logger.info(f"打开日志文件夹: {logs_dir}")
            else:
                logger.info(f"日志文件夹不存在: {logs_dir}")

    def _history_button_clicked(self, event):
        """历史数据读取按钮点击事件"""
        if event.button() == Qt.LeftButton:
            if self.history_window:
                # 调用历史数据窗口的show_window方法
                self.history_window.show_window()
            else:
                logger.info("历史数据窗口引用未设置")
    
    def _compare_button_clicked(self, event):
        """数据比对按钮点击事件"""
        if event.button() == Qt.LeftButton:
            if self.compare_window:
                # 调用数据比对窗口的show_window方法
                self.compare_window.show_window()
            else:
                logger.info("数据比对窗口引用未设置")
    
    def mouseDoubleClickEvent(self, event):
        """双击窗口上方区域最大化/还原窗口"""
        if event.button() == Qt.LeftButton:
            # 检查是否在窗口上方区域（顶部100像素）
            if event.pos().y() <= 100:
                self.window_operations.maximize_window()
        
        super().mouseDoubleClickEvent(event)
    
    def eventFilter(self, obj, event):
        """事件过滤器，捕获关闭事件"""
        if obj is self and event.type() == QEvent.Close:
            # 执行清理操作
            self._cleanup_all_resources()
            return False  # 继续正常关闭流程
        return super().eventFilter(obj, event)
    
    def _cleanup_all_resources(self):
        """清理所有下属窗口和资源"""
        logger.info("开始清理所有资源...")
        
        # 清理线程管理器
        if self.thread_manager:
            logger.info("清理线程管理器...")
            self.thread_manager.cleanup()
            self.thread_manager = None
        
        # 关闭所有下属窗口
        logger.info("关闭所有下属窗口...")
        
        # 关闭串口窗口
        if self.serial_window:
            if self.serial_window.isVisible():
                self.serial_window.close()
            self.serial_window = None
        
        # 关闭位置窗口
        if self.position_window:
            if self.position_window.isVisible():
                self.position_window.close()
            self.position_window = None
        
        # 关闭测量窗口
        if self.measure_window:
            if self.measure_window.isVisible():
                self.measure_window.close()
            self.measure_window = None
        
        # 关闭历史数据窗口
        if self.history_window:
            if self.history_window.isVisible():
                self.history_window.close()
            self.history_window = None
        
        # 关闭数据比对窗口
        if self.compare_window:
            if self.compare_window.isVisible():
                self.compare_window.close()
            self.compare_window = None
        
        logger.info("资源清理完成")