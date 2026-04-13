# -*- coding: utf-8 -*-
"""
旋转体表磁测量分析系统 - 主程序入口
负责窗口协调、数据流连接和应用程序生命周期管理
"""
import sys
import os

# PyInstaller 打包后的路径处理
if getattr(sys, 'frozen', False):
    # 打包后的应用程序 - 使用可执行文件所在目录
    application_path = os.path.dirname(sys.executable)
else:
    # 开发环境
    application_path = os.path.dirname(os.path.abspath(__file__))

# 添加src目录到路径
sys.path.insert(0, application_path)

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt
# 绝对导入
from core import init_logging, get_config_manager, ThreadManager


class MainApplication:
    """主应用程序类 - 负责窗口协调和数据流连接"""

    def __init__(self):
        # 初始化日志 - 使用exe同级的logs目录
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

            # 连接信号到各面板（使用 QueuedConnection 确保跨线程安全）
            self.thread_manager.serial_manager.signal_connection_status_changed.connect(
                self.main_panel.update_serial_status, Qt.QueuedConnection
            )
            self.thread_manager.data_process.signal_position_data_process_finished.connect(
                lambda pos: self.main_panel.update_position(pos[0], pos[1])
            )
            # 连接位置数据处理信号
            self.thread_manager.data_process.signal_position_data_process.connect(
                self.thread_manager.data_process.process_position_data
            )
            # 连接位置数据处理完成信号 - 更新serial_command当前位置
            self.thread_manager.data_process.signal_position_data_process_finished.connect(
                self.thread_manager.serial_command._on_position_data_processed
            )
            # 连接偏置数据处理信号
            self.thread_manager.data_process.signal_offset_data_process.connect(
                self.thread_manager.data_process.process_offset_data
            )
            # 连接偏置校准完成信号 - 清除偏置校准标志
            self.thread_manager.data_process.signal_offset_data_process_finished.connect(
                self.thread_manager.serial_command._on_offset_calibration_finished
            )
            # 连接断开信号
            self.thread_manager.signal_disconnect.connect(
                self.thread_manager.serial_manager.disconnect_serial
            )
            # 连接串口连接信号
            self.thread_manager.signal_connect.connect(
                self.thread_manager.serial_manager.connect_serial
            )
            self.logger.info("信号连接完成")

            # 将线程管理器传递给各面板
            self.main_panel.get_panel("serial").set_thread_manager(self.thread_manager)
            self.main_panel.get_panel("measure").set_thread_manager(self.thread_manager)
            self.main_panel.get_panel("test_config").set_thread_manager(self.thread_manager)
            self.logger.info("面板线程管理器设置完成")

            # 启动线程
            self.thread_manager.start_threads()
            self.logger.info("线程启动完成")

            # 自动连接串口
            self.main_panel.get_panel("serial").auto_connect_from_config()
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

        # 显示主面板
        self.main_panel.show()
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
    # 创建应用程序实例
    app = QApplication(sys.argv)

    # 设置应用程序信息
    app.setApplicationName("旋转体表磁测量分析系统")
    app.setApplicationVersion("2.0.0")

    # 设置应用程序样式
    app.setStyle('Fusion')

    # 创建并运行主应用程序
    main_app = MainApplication()
    exit_code = main_app.run()

    # 退出时清理资源
    main_app.cleanup()

    return exit_code


if __name__ == '__main__':
    sys.exit(main())
