# -*- coding: utf-8 -*-
"""
位置控制窗口
使用position_window.ui文件加载界面布局
"""

import os
from PyQt5.QtWidgets import QMainWindow, QLabel, QPushButton
from PyQt5.QtCore import QTimer, Qt
from PyQt5 import uic
from ui.window_operations import WindowOperations
from core import get_config_manager
from core.logger import get_logger

logger = get_logger('PositionWindow')


class PositionWindow(QMainWindow):
    """位置控制窗口"""
    
    def __init__(self):
        super().__init__()
        
        # 保存组件引用
        self.thread_manager = None
        self.serial_manager = None
        self.data_process = None
        self.serial_command = None
        
        # 从position_window.ui文件加载界面
        ui_file_path = os.path.join(os.path.dirname(__file__), "..", "ui", "position_window.ui")
        uic.loadUi(ui_file_path, self)
        
        # 初始化窗口操作功能
        self.window_operations = WindowOperations(self)
        
        # 连接按钮事件
        self._connect_buttons()
        
        # 初始化位置显示
        self._init_position_display()
        
        # 初始化状态显示
        self._init_status_display()
    
    def _on_position_data_ready(self, position_data):
        """位置数据更新信号处理"""
        # 检查标签是否存在
        if not hasattr(self, 'current_x_label') or self.current_x_label is None:
            return
        if not hasattr(self, 'current_z_label') or self.current_z_label is None:
            return
        # 更新位置显示
        if isinstance(position_data, (tuple, list)) and len(position_data) >= 2:
            x_value = position_data[0] if position_data[0] is not None else '--'
            z_value = position_data[1] if position_data[1] is not None else '--'
            self.current_x_label.setText(str(x_value))
            self.current_z_label.setText(str(z_value))
        else:
            logger.warning(f"位置数据格式错误: {position_data}")
    
    def _connect_buttons(self):
        """连接按钮事件"""
        # 连接自动下压按钮
        auto_press_down_button = self.findChild(QPushButton, "pushButton_auto_press_down")
        if auto_press_down_button:
            auto_press_down_button.clicked.connect(self._auto_press_down_button_clicked)

        # 连接自动下压按钮2
        auto_press_left_button = self.findChild(QPushButton, "pushButton_auto_press_left")
        if auto_press_left_button:
            auto_press_left_button.clicked.connect(self._auto_press_left_button_clicked)

        # 连接保存测试位置按钮
        save_test_position_button = self.findChild(QPushButton, "pushButton_save_test_position")
        if save_test_position_button:
            save_test_position_button.clicked.connect(self._save_test_position_button_clicked)

        # 连接保存挂起位置按钮
        save_suspend_position_button = self.findChild(QPushButton, "pushButton_save_suspend_position")
        if save_suspend_position_button:
            save_suspend_position_button.clicked.connect(self._save_suspend_position_button_clicked)

        # 连接关闭窗口按钮
        close_button = self.findChild(QPushButton, "pushButton_close")
        if close_button:
            close_button.clicked.connect(self._close_button_clicked)

        # 连接零位校准按钮
        zero_calibration_button = self.findChild(QPushButton, "pushButton_zero_calibration")
        if zero_calibration_button:
            zero_calibration_button.clicked.connect(self._zero_calibration_button_clicked)

        # 连接偏置校准按钮
        offset_calibration_button = self.findChild(QPushButton, "pushButton_offset_calibration")
        if offset_calibration_button:
            offset_calibration_button.clicked.connect(self._offset_calibration_button_clicked)

        # 连接测试位置按钮
        test_position_button = self.findChild(QPushButton, "pushButton_test_position")
        if test_position_button:
            test_position_button.clicked.connect(self._test_position_button_clicked)

        # 连接挂起位置按钮
        suspend_position_button = self.findChild(QPushButton, "pushButton_suspend_position")
        if suspend_position_button:
            suspend_position_button.clicked.connect(self._suspend_position_button_clicked)
    
    def _on_data_processed(self, position_data):
        """数据处理完成信号处理"""
        self._on_position_data_ready(position_data)
    
    def _init_position_display(self):
        """初始化位置显示控件"""
        # 当前X值标签
        self.current_x_label = self.findChild(QLabel, "label_current_x_value")
        # 当前Z值标签
        self.current_z_label = self.findChild(QLabel, "label_current_z_value")
        # 测试位置X值标签
        self.test_x_label = self.findChild(QLabel, "label_stored_test_position_x_value")
        # 测试位置Z值标签
        self.test_z_label = self.findChild(QLabel, "label_stored_test_position_z_value")
        # 挂起位置X值标签
        self.suspend_x_label = self.findChild(QLabel, "label_stored_suspend_position_x_value")
        # 挂起位置Z值标签
        self.suspend_z_label = self.findChild(QLabel, "label_stored_suspend_position_z_value")

        logger.info(f"current_x_label: {self.current_x_label}, current_z_label: {self.current_z_label}")

        # 初始化默认值
        self._update_position_display(0, 0, 0, 0)
    
    def _init_status_display(self):
        """初始化状态显示控件"""
        # 初始化偏置校准状态标签为None
        self.offset_status_label = None
    
    def _show_offset_status_indicator(self, status_text, color="green"):
        """在窗口上层显示偏置校准状态提示"""
        # 清除之前的提示
        self._hide_offset_status_indicator()
        
        # 创建QLabel显示状态文字
        self.offset_status_label = QLabel(status_text, self)
        
        # 设置样式
        self.offset_status_label.setStyleSheet(f"""
            QLabel {{
                background-color: rgba(255, 255, 255, 200);
                color: {color};
                font-size: 24px;
                font-weight: bold;
                border: 2px solid {color};
                border-radius: 10px;
                padding: 20px;
            }}
        """)
        
        # 设置对齐方式
        self.offset_status_label.setAlignment(Qt.AlignCenter)
        
        # 根据窗口尺寸确定位置和大小
        window_width = self.width()
        window_height = self.height()
        
        # 设置标签大小（约为窗口的1/3）
        label_width = window_width // 3
        label_height = window_height // 6
        
        # 计算居中位置
        label_x = (window_width - label_width) // 2
        label_y = (window_height - label_height) // 2
        
        # 设置位置和大小
        self.offset_status_label.setGeometry(label_x, label_y, label_width, label_height)
        
        # 显示标签
        self.offset_status_label.show()
        self.offset_status_label.raise_()  # 置顶显示
        
        logger.info(f"显示偏置校准状态: {status_text}")
    
    def _hide_offset_status_indicator(self):
        """隐藏偏置校准状态提示"""
        if self.offset_status_label:
            self.offset_status_label.hide()
            self.offset_status_label.deleteLater()
            self.offset_status_label = None
            logger.info("隐藏偏置校准状态提示")
    
    def _update_position_display(self, current_x, current_z, test_x, test_z):
        """更新位置显示"""
        self.current_x_label.setText(f"{current_x}")
        self.current_z_label.setText(f"{current_z}")
        self.test_x_label.setText(f"{test_x}")
        self.test_z_label.setText(f"{test_z}")
    
    def _close_button_clicked(self):
        """关闭窗口按钮点击事件"""
        logger.info("关闭位置控制窗口")
        self.hide()
    
    def _zero_calibration_button_clicked(self):
        """零位校准按钮点击事件"""
        logger.info("零位校准按钮被点击")
        self.serial_command.slider_reset()
    
    def _offset_calibration_button_clicked(self):
        """偏置校准按钮点击事件"""
        logger.info("偏置校准按钮被点击")

        # 显示状态为"处理中..."
        self._show_offset_status_indicator("校准中...", "blue")

        # 执行偏置校准命令
        logger.info("调用offset_calibration方法")
        self.serial_command.offset_calibration(self)
        logger.info("offset_calibration已调用")
    
    def _on_offset_calibration_finished(self, result):
        """偏置校准完成回调函数"""
        logger.info("偏置校准处理完成")
        # 根据校准结果显示不同状态
        if result:
            self._show_offset_status_indicator("偏置校准成功", "green")
        else:
            self._show_offset_status_indicator("偏置校准失败", "red")
        
        # 2秒后隐藏状态提示
        QTimer.singleShot(2000, self._hide_offset_status_indicator)

    def _test_position_button_clicked(self):
        """测试位置按钮点击事件"""
        logger.info("测试位置按钮被点击")
        self.serial_command.test_position()
    
    def _suspend_position_button_clicked(self):
        """挂起位置按钮点击事件"""
        logger.info("挂起位置按钮被点击")
        self.serial_command.suspend_position(self)

    def _auto_press_down_button_clicked(self):
        """自动下压按钮点击事件"""
        logger.info("自动下压按钮被点击")
        self.serial_command.auto_press()

    def on_x_finished(self, axis):
        logger.info(f"X轴自检完成，执行位置查询")
        self.serial_command.position_query()
        # 执行后清空该轴所有回调
        self.serial_command.clear_self_detect_callbacks('X')

    def _auto_press_left_button_clicked(self):
        """自动左压按钮点击事件"""
        logger.info("自动左压按钮被点击")
        self.serial_command.auto_press_left()

    def _save_test_position_button_clicked(self):
        """保存测试位置按钮点击事件"""
        logger.info("保存测试位置按钮被点击")

        # 获取当前坐标值
        try:
            current_x = int(self.current_x_label.text())
            current_z = int(self.current_z_label.text())
        except ValueError:
            logger.info("获取当前位置失败")
            return

        # 保存到配置文件
        try:
            self._save_test_position_to_config(current_x, current_z)
            # 更新测试位置显示
            self.test_x_label.setText(f"{current_x}")
            self.test_z_label.setText(f"{current_z}")
            # 同步更新ConfigManager缓存
            config = get_config_manager()
            config.test_x = current_x
            config.test_z = current_z
            logger.info(f"测试位置已保存: X={current_x}, Z={current_z}")
        except Exception as e:
            logger.info(f"保存测试位置失败: {str(e)}")

    def _save_suspend_position_button_clicked(self):
        """保存挂起位置按钮点击事件"""
        logger.info("保存挂起位置按钮被点击")

        # 获取当前坐标值
        try:
            current_x = int(self.current_x_label.text())
            current_z = int(self.current_z_label.text())
        except ValueError:
            logger.info("获取当前位置失败")
            return

        # 保存到配置文件
        try:
            self._save_suspend_position_to_config(current_x, current_z)
            # 更新挂起位置显示
            self.suspend_x_label.setText(f"{current_x}")
            self.suspend_z_label.setText(f"{current_z}")
            # 同步更新ConfigManager缓存
            config = get_config_manager()
            config.suspend_x = current_x
            config.suspend_z = current_z
            logger.info(f"挂起位置已保存: X={current_x}, Z={current_z}")
        except Exception as e:
            logger.info(f"保存挂起位置失败: {str(e)}")

    def _save_test_position_to_config(self, x, z):
        """保存测试位置到配置文件（使用ConfigManager）"""
        try:
            config = get_config_manager()
            config.test_x = x
            config.test_z = z
            logger.info(f"测试位置已保存: test_x={x}, test_z={z}")
        except Exception as e:
            logger.error(f"保存测试位置失败: {str(e)}")

    def _save_suspend_position_to_config(self, x, z):
        """保存挂起位置到配置文件（使用ConfigManager）"""
        try:
            config = get_config_manager()
            config.suspend_x = x
            config.suspend_z = z
            logger.info(f"挂起位置已保存: suspend_x={x}, suspend_z={z}")
        except Exception as e:
            logger.error(f"保存挂起位置失败: {str(e)}")

    def _load_and_update_stored_position(self):
        """读取配置并更新存储位置显示（使用ConfigManager）"""
        try:
            config = get_config_manager()

            # 读取测试位置
            test_x = config.test_x
            test_z = config.test_z
            # 读取挂起位置
            suspend_x = config.suspend_x
            suspend_z = config.suspend_z

            # 更新显示
            self.test_x_label.setText(f"{test_x}")
            self.test_z_label.setText(f"{test_z}")
            self.suspend_x_label.setText(f"{suspend_x}")
            self.suspend_z_label.setText(f"{suspend_z}")

            logger.info(f"位置已更新: 测试位置({test_x}, {test_z}), 挂起位置({suspend_x}, {suspend_z})")
        except Exception as e:
            logger.error(f"读取配置失败: {e}")

    def show_window(self):
        """显示窗口"""
        logger.debug(f"show_window被调用，当前窗口可见性: {self.isVisible()}")
        
        # 检查线程管理器是否已设置
        if not self.thread_manager:
            logger.debug("错误：线程管理器未设置")
            return
            
        # 初始化组件引用
        if not self.serial_manager:
            self.serial_manager = self.thread_manager.serial_manager
        if not self.data_process:
            self.data_process = self.thread_manager.data_process
        # 使用 thread_manager 中的 serial_command，不要自己创建
        self.serial_command = self.thread_manager.serial_command
        
        if not self.isVisible():
            # 窗口显示时读取配置并更新显示
            self._load_and_update_stored_position()
            self.show()
            logger.debug("窗口已显示")
            # 窗口显示时启动定时器
            self._start_position_query()
        else:
            self.raise_()
            self.activateWindow()
            logger.debug("窗口已置顶")
    
    def closeEvent(self, event):
        """窗口关闭事件"""
        # 窗口关闭时停止定时器
        self._stop_position_query()
        event.accept()
    
    def hideEvent(self, event):
        """窗口隐藏事件"""
        # 窗口隐藏时停止定时器
        self._stop_position_query()
        event.accept()
    
    def _start_position_query(self):
        """启动位置查询定时器"""
        if self.serial_command:
            self.serial_command.enable_position_query_timer(500)
            logger.debug("位置查询定时器已启动")
        else:
            logger.debug("串口命令管理器未初始化")
    
    def _stop_position_query(self):
        """停止位置查询定时器"""
        if self.serial_command:
            self.serial_command.disable_position_query_timer()
            logger.debug("位置查询定时器已停止")
    
    def _query_position(self):
        """查询位置信息"""
        # 检查窗口是否显示
        if not self.isVisible():
            logger.debug("位置查询定时器触发，但窗口已隐藏，停止定时器")
            self._stop_position_query()
            return
        
        # 检查串口是否连接
        if not self.serial_manager or not self.serial_manager.get_connection_status():
            logger.debug("位置查询定时器触发，但串口未连接，停止定时器")
            self._stop_position_query()
            return
        
        # 直接发送位置查询命令
        if self.serial_command:
            self.serial_command.position_query()

    def _show_calibrating_indicator(self):
        """在窗口上层显示校准中提示"""
        # 清除之前的提示
        self._hide_calibrating_indicator()
        
        # 创建QLabel显示"校准中..."文字
        self.calibrating_label = QLabel("校准中...", self)
        
        # 设置样式
        self.calibrating_label.setStyleSheet("""
            QLabel {
                background-color: rgba(255, 255, 255, 200);
                color: red;
                font-size: 24px;
                font-weight: bold;
                border: 2px solid red;
                border-radius: 10px;
                padding: 20px;
            }
        """)
        
        # 设置对齐方式
        self.calibrating_label.setAlignment(Qt.AlignCenter)
        
        # 根据窗口尺寸确定位置和大小
        window_width = self.width()
        window_height = self.height()
        
        # 设置标签大小（约为窗口的1/3）
        label_width = window_width // 3
        label_height = window_height // 6
        
        # 计算居中位置
        label_x = (window_width - label_width) // 2
        label_y = (window_height - label_height) // 2
        
        # 设置位置和大小
        self.calibrating_label.setGeometry(label_x, label_y, label_width, label_height)
        
        # 显示标签
        self.calibrating_label.show()
        self.calibrating_label.raise_()  # 置顶显示
        
        logger.info("显示校准中提示")

    def _hide_calibrating_indicator(self):
        """隐藏校准中提示"""
        if self.calibrating_label:
            self.calibrating_label.hide()
            self.calibrating_label.deleteLater()
            self.calibrating_label = None
            logger.info("隐藏校准中提示")
