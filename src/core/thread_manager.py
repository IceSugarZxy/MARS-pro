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

        # 窗口引用
        self.serial_window = None
        self.position_window = None
        self.measure_window = None

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

        logger.debug("线程初始化完成")
        return True

    def connect_thread_signal(self, serial_window, position_window, measure_window) -> bool:
        """连接所有组件间的信号流"""
        # 连接串口管理器信号
        self.signal_connect.connect(self.serial_manager.connect_serial)

        # 串口设置界面实时显示信号
        self.serial_manager.signal_data_received.connect(serial_window._on_data_received)
        self.serial_manager.signal_connection_status_changed.connect(
            serial_window._on_connection_status_changed
        )

        # 连接位置数据处理信号
        self.data_process.signal_position_data_process.connect(
            self.data_process.process_position_data
        )

        # 连接位置数据处理完成信号 - 位置窗口更新
        self.data_process.signal_position_data_process_finished.connect(
            position_window._on_data_processed
        )



        # 连接位置数据处理完成信号 - 移动任务处理
        self.data_process.signal_position_data_process_finished.connect(
            self.serial_command._on_position_data_processed
        )

        # 连接偏置数据处理信号
        self.data_process.signal_offset_data_process.connect(
            self.data_process.process_offset_data
        )

        # 连接偏置数据处理完成信号 - 提示信息更新
        self.data_process.signal_offset_data_process_finished.connect(
            position_window._on_offset_calibration_finished
        )

        # 连接偏置数据处理完成信号 - 清除偏置校准标志
        self.data_process.signal_offset_data_process_finished.connect(
            self.serial_command._on_offset_calibration_finished
        )

        # 连接测量数据处理信号
        self.data_process.signal_measure_data_process.connect(
            self.data_process.process_measure_data
        )
        self.data_process.signal_measure_data_process_finished.connect(
            measure_window._on_measure_data_processed
        )
        self.data_process.signal_measure_data_progress.connect(
            measure_window._on_measure_data_progress
        )

        # 连接自检消息处理信号
        self.data_process.signal_self_detect_process.connect(
            self.data_process.check_self_detect
        )
        self.data_process.signal_self_detect_finished.connect(
            self.serial_command._on_self_detect_finished
        )

        # 设置窗口的线程管理器引用
        serial_window.thread_manager = self
        position_window.thread_manager = self
        measure_window.thread_manager = self

        # 保存窗口引用
        self.serial_window = serial_window
        self.position_window = position_window
        self.measure_window = measure_window

        logger.info("数据流信号连接完成")
        return True

    def start_threads(self) -> None:
        """启动所有线程"""
        if self.serial_thread:
            self.serial_thread.start()
            logger.debug("串口线程已启动")

        if self.data_process_thread:
            self.data_process_thread.start()
            logger.debug("数据处理线程已启动")

    def stop_threads(self) -> None:
        """停止所有线程"""
        if self.data_process_thread and self.data_process_thread.isRunning():
            if self.data_process:
                self.data_process.stop()
            self.data_process_thread.quit()
            self.data_process_thread.wait()
            logger.debug("数据处理线程已停止")

        if self.serial_thread and self.serial_thread.isRunning():
            if self.serial_manager:
                self.serial_manager.stop()
            self.serial_thread.quit()
            self.serial_thread.wait()
            logger.debug("串口线程已停止")

    def cleanup(self) -> None:
        """清理资源"""
        self.stop_threads()
        self.serial_manager = None
        self.serial_thread = None
        self.data_process = None
        self.data_process_thread = None
        self.serial_command = None
        logger.info("线程管理器资源清理完成")
