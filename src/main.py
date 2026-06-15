# -*- coding: utf-8 -*-
"""
旋转体表磁测量分析系统 - 主程序入口
负责窗口协调、数据流连接和应用程序生命周期管理
"""
import sys
import os

# Resolve the runtime root for both source and PyInstaller builds.
if getattr(sys, 'frozen', False):
    application_path = os.path.dirname(sys.executable)
else:
    application_path = os.path.dirname(os.path.abspath(__file__))

# Allow absolute imports such as `from core import ...`.
sys.path.insert(0, application_path)

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QIcon

from core import init_logging, get_config_manager, ThreadManager


class MainApplication:
    """主应用程序类 - 负责窗口协调和数据流连接"""

    def __init__(self):
        if getattr(sys, 'frozen', False):
            base_dir = os.path.dirname(sys.executable)
        else:
            base_dir = application_path
        log_dir = os.path.join(base_dir, "logs")
        self.logger = init_logging(log_dir)
        self.logger.info("=" * 50)
        self.logger.info("旋转体表磁测量分析系统启动")
        self.logger.info("=" * 50)

        # 初始化配置
        self.config = get_config_manager()
        self.logger.info(f"配置文件: {self.config.config_file}")

        # 初始化组件
        self.thread_manager = None
        self.main_panel = None

    def initialize(self) -> bool:
        """初始化应用程序组件"""
        try:
            # 延迟导入，避免循环依赖
            from windows import MainPanel

            # 创建主面板（单窗口架构）
            self.main_panel = MainPanel()
            self.logger.info("主面板创建成功")

            # 创建线程管理器
            self.thread_manager = ThreadManager()
            self.logger.info("线程管理器创建成功")

            # Use queued connections for signals emitted from worker threads.
            self.thread_manager.serial_manager.signal_connection_status_changed.connect(
                self.main_panel.update_serial_status, Qt.QueuedConnection
            )
            self.thread_manager.data_process.signal_position_data_process_finished.connect(
                self.main_panel.update_position_from_tuple,
                Qt.QueuedConnection
            )
            self.thread_manager.data_process.signal_position_data_process.connect(
                self.thread_manager.data_process.process_position_data,
                Qt.QueuedConnection
            )
            self.thread_manager.data_process.signal_self_detect_process.connect(
                self.thread_manager.data_process.check_self_detect,
                Qt.QueuedConnection
            )
            # Keep SerialCommand's cached position aligned with parsed feedback.
            self.thread_manager.data_process.signal_position_data_process_finished.connect(
                self.thread_manager.serial_command._on_position_data_processed,
                Qt.QueuedConnection
            )
            self.thread_manager.data_process.signal_self_detect_finished.connect(
                self.thread_manager.serial_command._on_self_detect_finished
            )
            self.thread_manager.data_process.signal_offset_data_process.connect(
                self.thread_manager.data_process.process_offset_data,
                Qt.QueuedConnection
            )
            self.thread_manager.data_process.signal_measure_data_process.connect(
                self.thread_manager.data_process.process_measure_data,
                Qt.QueuedConnection
            )
            # Clear offset-calibration state after the data processor finishes.
            self.thread_manager.data_process.signal_offset_data_process_finished.connect(
                self.thread_manager.serial_command._on_offset_calibration_finished
            )
            self.thread_manager.signal_disconnect.connect(
                self.thread_manager.serial_manager.disconnect_serial
            )
            self.thread_manager.signal_connect.connect(
                self.thread_manager.serial_manager.connect_serial
            )
            self.logger.info("信号连接完成")

            # 将线程管理器传递给各面板
            self.main_panel.get_panel("measure").set_thread_manager(self.thread_manager)
            self.main_panel.get_panel("test_config").set_thread_manager(self.thread_manager)
            self.logger.info("面板线程管理器设置完成")

            # 启动线程
            self.thread_manager.start_threads()
            self.logger.info("线程启动完成")

            # 自动连接串口
            self.main_panel.get_panel("measure").auto_connect_from_config()
            self.logger.info("自动连接串口完成")

            return True

        except Exception as e:
            self.logger.error(f"应用程序初始化失败: {e}", exc_info=True)
            return False

    def run(self) -> int:
        """运行应用程序"""
        if not self.initialize():
            self.logger.error("初始化失败，程序退出")
            return 1

        # 设置无标题栏窗口
        self.main_panel.setWindowFlags(Qt.FramelessWindowHint)

        # 显示主面板（最大化）
        self.main_panel.showMaximized()
        self.logger.info("主面板已显示")

        # 启动事件循环
        return self._run_event_loop()

    def _run_event_loop(self) -> int:
        """运行Qt事件循环"""
        try:
            return QApplication.instance().exec_()
        except Exception as e:
            self.logger.error(f"事件循环异常: {e}", exc_info=True)
            return 1

    def cleanup(self) -> None:
        """清理应用程序资源"""
        self.logger.info("开始清理资源...")

        if self.thread_manager:
            self.thread_manager.cleanup()

        self.logger.info("资源清理完成")


def main() -> int:
    """主函数"""
    # 屏蔽 matplotlib 字体警告
    import warnings
    warnings.filterwarnings("ignore", category=UserWarning, module="matplotlib")

    # 创建应用程序实例
    app = QApplication(sys.argv)
    icon_path = os.path.join(application_path, "icon.png")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    # 设置应用程序信息
    app.setApplicationName("旋转体表磁测量分析系统")
    app.setApplicationVersion("2.0.0")

    # 设置应用程序样式
    app.setStyle('Fusion')

    # Create and run the coordinator object.
    main_app = MainApplication()
    exit_code = main_app.run()

    # 退出时清理资源
    main_app.cleanup()

    return exit_code


if __name__ == '__main__':
    sys.exit(main())
