# -*- coding: utf-8 -*-
"""
线程管理器 - 优化版本
只负责纯粹的线程管理，不涉及窗口管理
"""
import queue
from typing import Optional

from PyQt5.QtCore import QObject, QThread, pyqtSignal

from .logger import get_logger
from .serial_manager import SerialManager
from .data_process import DataProcess
from .serial_command import SerialCommand

logger = get_logger('ThreadManager')


class ThreadManager(QObject):
    """线程管理器"""

    # 信号定义
    signal_connect = pyqtSignal(str, str, str, str, str)
    signal_disconnect = pyqtSignal()
    signal_connection_status_changed = pyqtSignal(bool)
    signal_data_received = pyqtSignal(bytes)

    def __init__(self):
        super().__init__()
        self.serial_manager: Optional[SerialManager] = None
        self.serial_thread: Optional[QThread] = None
        self.data_process: Optional[DataProcess] = None
        self.data_process_thread: Optional[QThread] = None
        self.serial_command: Optional[SerialCommand] = None

        self.read_queue: queue.Queue = queue.Queue()
        self.write_queue: queue.Queue = queue.Queue()

        self.initialize_threads()
        logger.info("ThreadManager 初始化完成")

    def initialize_threads(self) -> bool:
        """初始化所有线程"""
        # 初始化串口管理器
        self.serial_manager = SerialManager(self.read_queue, self.write_queue, self)

        # 初始化数据处理管理器
        self.data_process = DataProcess(self.read_queue)

        # 初始化串口命令管理器
        self.serial_command = SerialCommand(self)

        # 创建串口线程
        self.serial_thread = QThread()
        self.serial_manager.moveToThread(self.serial_thread)

        # 创建数据处理线程
        self.data_process_thread = QThread()
        self.data_process.moveToThread(self.data_process_thread)

        return True

    def start_threads(self) -> None:
        """启动所有线程"""
        if self.serial_thread:
            self.serial_thread.start()

        if self.data_process_thread:
            self.data_process_thread.start()

    def stop_threads(self) -> None:
        """停止所有线程"""
        if self.data_process_thread and self.data_process_thread.isRunning():
            if self.data_process:
                self.data_process.stop()
            self.data_process_thread.quit()
            self.data_process_thread.wait()

        if self.serial_thread and self.serial_thread.isRunning():
            if self.serial_manager:
                self.serial_manager.stop()
            self.serial_thread.quit()
            self.serial_thread.wait()

    def cleanup(self) -> None:
        """清理资源"""
        self.stop_threads()
        self.serial_manager = None
        self.serial_thread = None
        self.data_process = None
        self.data_process_thread = None
        self.serial_command = None
        logger.info("线程管理器资源清理完成")
