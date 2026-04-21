# -*- coding: utf-8 -*-
"""
测试配置面板 - 从 test_config_panel.ui 加载
"""

import os
from PyQt5.QtWidgets import (QWidget, QLabel, QPushButton, QLineEdit,
                              QGroupBox, QGridLayout, QComboBox)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from PyQt5 import uic
from core.logger import get_logger
from core import get_config_manager
from core.config_manager import action_to_text
from windows.offset_calibration_dialog import OffsetCalibrationDialog
from windows.scheme_edit_dialog import SchemeEditDialog

logger = get_logger('TestConfigPanel')


class TestConfigPanel(QWidget):
    """测试配置面板 - 从 test_config_panel.ui 加载"""

    def __init__(self):
        super().__init__()

        # 加载 UI
        ui_file_path = os.path.join(os.path.dirname(__file__), "..", "ui", "test_config_panel.ui")
        uic.loadUi(ui_file_path, self)

        # 线程管理器引用
        self.thread_manager = None
        self.serial_command = None

        # 连接按钮事件
        self._connect_buttons()

        # 初始化位置查询定时器
        self._position_query_timer = QTimer()
        self._position_query_timer.setInterval(500)  # 500ms查询一次
        self._position_query_timer.timeout.connect(self._on_position_query_timer)

        # 偏置校准对话框
        self._offset_dialog = None

        logger.info("TestConfigPanel 初始化完成")

    def set_thread_manager(self, tm):
        """设置线程管理器"""
        self.thread_manager = tm
        if tm:
            self.serial_command = tm.serial_command
            # 连接位置数据处理完成信号
            tm.data_process.signal_position_data_process_finished.connect(self._on_position_data_updated)
            # 连接偏置校准完成信号
            tm.data_process.signal_offset_data_process_finished.connect(self._on_offset_calibration_finished)
            # 启动位置查询定时器
            self._position_query_timer.start()
            logger.info("测试配置面板已启动位置查询定时器")

        # 加载保存的配置值
        self._load_saved_positions()
        # 初始化测试模式和移动方案
        self._init_test_mode_and_scheme()

    def _init_test_mode_and_scheme(self):
        """初始化测试模式和移动方案"""
        config = get_config_manager()

        # 测试类型 - 连接信号实现双向同步
        combo_test_type = self.findChild(QComboBox, "combo_test_type")
        if combo_test_type:
            combo_test_type.setCurrentIndex(config.test_type)
            combo_test_type.currentIndexChanged.connect(self._on_test_type_changed)
            # 连接配置管理器的信号
            config.signal_test_type_changed.connect(self._on_config_test_type_changed)

        # 更新方案显示
        self._update_scheme_display(config.test_type)

    def _update_scheme_display(self, test_type):
        """根据测试类型更新方案显示"""
        config = get_config_manager()

        # 获取当前活动的方案
        test_scheme = config.get_active_test_scheme(test_type)
        suspend_scheme = config.get_active_suspend_scheme(test_type)

        # 转换为显示文本
        test_steps_text = " → ".join([action_to_text(s) for s in test_scheme['steps']])
        suspend_steps_text = " → ".join([action_to_text(s) for s in suspend_scheme['steps']])

        test_scheme_edit = self.findChild(QLineEdit, "test_scheme_edit")
        if test_scheme_edit:
            test_scheme_edit.setText(test_steps_text)

        suspend_scheme_edit = self.findChild(QLineEdit, "suspend_scheme_edit")
        if suspend_scheme_edit:
            suspend_scheme_edit.setText(suspend_steps_text)

    def _on_edit_test_scheme(self):
        """编辑测试方案"""
        config = get_config_manager()
        test_type = config.test_type
        schemes = config.get_test_schemes(test_type)
        if schemes:
            scheme = schemes[0].copy()
            dialog = SchemeEditDialog(scheme, self)
            if dialog.exec_():
                result = dialog.get_result()
                config.update_scheme(test_type, True, 0, result)
                self._update_scheme_display(test_type)
                logger.info(f"测试方案已更新: {result}")

    def _on_test_type_changed(self, index):
        """测试类型改变"""
        config = get_config_manager()
        config.test_type = index
        logger.info(f"测试类型已更改: {index}")

        # 更新方案显示
        self._update_scheme_display(index)

    def _on_config_test_type_changed(self, index):
        """配置管理器测试类型改变，同步更新下拉框"""
        combo_test_type = self.findChild(QComboBox, "combo_test_type")
        if combo_test_type and combo_test_type.currentIndex() != index:
            combo_test_type.blockSignals(True)
            combo_test_type.setCurrentIndex(index)
            combo_test_type.blockSignals(False)
        # 更新方案显示
        self._update_scheme_display(index)

    def _load_saved_positions(self):
        """从配置文件加载保存的位置"""
        try:
            config = get_config_manager()
            # 更新测试位置显示
            test_x_display = self.findChild(QLineEdit, "test_x_value")
            test_z_display = self.findChild(QLineEdit, "test_z_value")
            if test_x_display:
                test_x_display.setText(str(config.test_x))
            if test_z_display:
                test_z_display.setText(str(config.test_z))

            # 更新挂起位置显示
            suspend_x_display = self.findChild(QLineEdit, "suspend_x_value")
            suspend_z_display = self.findChild(QLineEdit, "suspend_z_value")
            if suspend_x_display:
                suspend_x_display.setText(str(config.suspend_x))
            if suspend_z_display:
                suspend_z_display.setText(str(config.suspend_z))

            logger.info(f"已加载保存的位置: 测试位置({config.test_x}, {config.test_z}), 挂起位置({config.suspend_x}, {config.suspend_z})")
        except Exception as e:
            logger.error(f"加载保存位置失败: {e}")

    def _connect_buttons(self):
        """连接按钮事件"""
        # 快捷操作
        self.findChild(QPushButton, "btn_zeroing").clicked.connect(self._on_zeroing)
        self.findChild(QPushButton, "btn_offset").clicked.connect(self._on_offset)
        self.findChild(QPushButton, "btn_press_z").clicked.connect(self._on_press_z)
        self.findChild(QPushButton, "btn_left_x").clicked.connect(self._on_left_x)
        self.findChild(QPushButton, "btn_right_x").clicked.connect(self._on_right_x)
        self.findChild(QPushButton, "btn_test_pos").clicked.connect(self._on_test_pos)
        self.findChild(QPushButton, "btn_suspend").clicked.connect(self._on_suspend)
        self.findChild(QPushButton, "btn_test_pos_save").clicked.connect(self._on_test_pos_save)
        self.findChild(QPushButton, "btn_suspend_save").clicked.connect(self._on_suspend_save)

    def _on_position_query_timer(self):
        """定时器触发位置查询"""
        import time
        t = time.time()
        if self.serial_command and self.thread_manager:
            if self.thread_manager.serial_manager.get_connection_status():
                # 只在命令锁未锁定且不在偏置校准时发送查询
                if not self.serial_command._command_lock and not self.serial_command._offset_calibrating and not self.serial_command._is_measuring:
                    logger.debug(f"[{t:.3f}] _on_position_query_timer: 发送位置查询")
                    self.serial_command.send_data("?XZ~")
                    # 触发数据处理信号
                    self.thread_manager.data_process.signal_position_data_process.emit()
                else:
                    logger.debug(f"[{t:.3f}] _on_position_query_timer: 跳过 (_command_lock={self.serial_command._command_lock}, _offset_calibrating={self.serial_command._offset_calibrating}, _is_measuring={self.serial_command._is_measuring})")
            else:
                # 未连接时显示 --
                self.update_position("--", "--")

    def _on_position_data_updated(self, position_data):
        """位置数据更新"""
        if position_data and len(position_data) >= 2:
            x, z = position_data[0], position_data[1]
            self.update_position(x, z)

    def _on_zeroing(self):
        """零位校准"""
        if self.serial_command:
            self.serial_command.slider_reset()
            logger.info("零位校准")
        else:
            logger.warning("串口命令未初始化")

    def _on_offset(self):
        """偏置校准"""
        if self.serial_command:
            # 停止位置查询定时器，防止干扰偏置校准
            self._position_query_timer.stop()
            logger.info("偏置校准：位置查询定时器已停止")

            # 显示校准对话框
            self._offset_dialog = OffsetCalibrationDialog(self)
            self._offset_dialog.start_progress(duration=3)  # 偏置校准约3秒
            self._offset_dialog.show()
            logger.info("偏置校准开始")
            self.serial_command.offset_calibration()
        else:
            logger.warning("串口命令未初始化")

    def _on_offset_calibration_finished(self, success):
        """偏置校准完成"""
        logger.info(f"偏置校准完成: success={success}")
        # 重新启动位置查询定时器
        self._position_query_timer.start()
        logger.info("偏置校准完成：位置查询定时器已重启")
        if self._offset_dialog:
            config = get_config_manager()
            offset_value = getattr(config, 'offset', None)
            self._offset_dialog.show_result(success, offset_value)
            self._offset_dialog.btn_cancel.clicked.connect(self._close_offset_dialog)

    def _close_offset_dialog(self):
        """关闭偏置校准对话框"""
        if self._offset_dialog:
            self._offset_dialog.close()
            self._offset_dialog = None

    def _on_press_z(self):
        """Z轴下压贴靠"""
        if self.serial_command:
            self.serial_command.auto_press()
            logger.info("Z轴下压贴靠")
        else:
            logger.warning("串口命令未初始化")

    def _on_left_x(self):
        """X轴左贴靠"""
        if self.serial_command:
            self.serial_command.auto_press_left()
            logger.info("X轴左贴靠")
        else:
            logger.warning("串口命令未初始化")

    def _on_right_x(self):
        """X轴右贴靠"""
        if self.serial_command:
            self.serial_command.auto_press_right()
            logger.info("X轴右贴靠")
        else:
            logger.warning("串口命令未初始化")

    def _on_test_pos(self):
        """移动到测试位置"""
        if self.serial_command:
            self.serial_command.test_position()
            logger.info("移动到测试位置")
        else:
            logger.warning("串口命令未初始化")

    def _on_suspend(self):
        """移动到挂起位置"""
        if self.serial_command:
            self.serial_command.suspend_position()
            logger.info("移动到挂起位置")
        else:
            logger.warning("串口命令未初始化")

    def _on_reset(self):
        """滑台复位"""
        if self.serial_command:
            self.serial_command.slider_reset()
            logger.info("滑台复位")
        else:
            logger.warning("串口命令未初始化")

    def _on_test_pos_save(self):
        """保存当前测试位置"""
        try:
            x_display = self.findChild(QLineEdit, "position_x")
            z_display = self.findChild(QLineEdit, "position_z")
            if x_display and z_display:
                x = int(x_display.text())
                z = int(z_display.text())
                config = get_config_manager()
                config.test_x = x
                config.test_z = z
                logger.info(f"保存测试位置: X={x}, Z={z}")

                # 更新测试位置显示
                test_x_display = self.findChild(QLineEdit, "test_x_value")
                test_z_display = self.findChild(QLineEdit, "test_z_value")
                if test_x_display:
                    test_x_display.setText(str(x))
                if test_z_display:
                    test_z_display.setText(str(z))
        except ValueError:
            logger.warning("无效的位置数据，无法保存")

    def _on_suspend_save(self):
        """保存当前挂起位置"""
        try:
            x_display = self.findChild(QLineEdit, "position_x")
            z_display = self.findChild(QLineEdit, "position_z")
            if x_display and z_display:
                x = int(x_display.text())
                z = int(z_display.text())
                config = get_config_manager()
                config.suspend_x = x
                config.suspend_z = z
                logger.info(f"保存挂起位置: X={x}, Z={z}")

                # 更新挂起位置显示
                suspend_x_display = self.findChild(QLineEdit, "suspend_x_value")
                suspend_z_display = self.findChild(QLineEdit, "suspend_z_value")
                if suspend_x_display:
                    suspend_x_display.setText(str(x))
                if suspend_z_display:
                    suspend_z_display.setText(str(z))
        except ValueError:
            logger.warning("无效的位置数据，无法保存")

    def update_position(self, x, z):
        """更新位置显示"""
        x_display = self.findChild(QLineEdit, "position_x")
        z_display = self.findChild(QLineEdit, "position_z")
        if x_display:
            x_display.setText(str(x))
        if z_display:
            z_display.setText(str(z))