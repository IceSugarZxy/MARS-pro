# -*- coding: utf-8 -*-
"""
配置面板 - 从 config_panel.ui 加载
"""

import os
import re
import serial.tools.list_ports
from PyQt5.QtCore import Qt, QTimer, QObject, QEvent
from PyQt5.QtGui import QTextCursor
from PyQt5.QtWidgets import (
    QWidget,
    QPushButton,
    QLineEdit,
    QLabel,
    QComboBox,
    QToolButton,
    QDoubleSpinBox,
    QSpinBox,
    QPlainTextEdit,
    QMessageBox,
    QCheckBox,
    QSizePolicy,
)
from PyQt5 import uic
from core.logger import get_logger
from core import get_config_manager
from core.config_manager import (
    PGA_OPTION_TEXTS,
    RANGE_SELECT_MARGIN_MT,
    IDAC_MIN_INDEX,
    IDAC_MAX_INDEX,
    IDAC_OPTION_TEXTS,
    action_to_text,
    format_range_selection,
    get_mag_adc_per_mt,
)
from windows.full_offset_calibration_dialog import FullOffsetCalibrationDialog
from windows.scheme_edit_dialog import SchemeEditDialog
from core import judge_thresholds

logger = get_logger('ConfigPanel')

STAGE_LONG_PRESS_MS = 500
LIGHT_CAL_RESPONSE_TIMEOUT_MS = 4000
ACTION_STATUS_RECOVER_MS = 4000
# 合格判定：左/右两列（与测量界面数据分析结果对应）、两列间隔列、限值输入框宽度
JUDGE_LEFT_COLUMN = 0
JUDGE_RIGHT_COLUMN = 4
JUDGE_COLUMN_GAP = 3
JUDGE_LIMIT_EDIT_WIDTH = 54
SERIAL_COMMAND_BUTTONS = (
    "btn_zeroing",
    "btn_offset_all",
    "btn_test_pos",
    "btn_suspend",
    "btn_center_position",
    "btn_set_light_base",
    "btn_set_light_threshold",
    "stage_btn_up",
    "stage_btn_down",
    "stage_btn_left",
    "stage_btn_right",
    "stage_btn_forward",
    "stage_btn_back",
)


class ConfigPanel(QWidget):
    """配置面板 - 从 config_panel.ui 加载"""

    def __init__(self):
        super().__init__()

        # 加载 UI
        ui_file_path = os.path.join(os.path.dirname(__file__), "..", "ui", "config_panel.ui")
        uic.loadUi(ui_file_path, self)

        # 线程管理器引用
        self.thread_manager = None
        self.serial_manager = None
        self.serial_command = None
        self._pending_connection_port = None
        self._serial_rx_update_enabled = False

        self._connection_timeout_timer = QTimer(self)
        self._connection_timeout_timer.setSingleShot(True)
        self._connection_timeout_timer.timeout.connect(self._on_connection_timeout)

        self._light_cal_pending = None
        self._light_cal_rx_buffer = ""
        self._light_cal_timer = QTimer(self)
        self._light_cal_timer.setSingleShot(True)
        self._light_cal_timer.setInterval(LIGHT_CAL_RESPONSE_TIMEOUT_MS)
        self._light_cal_timer.timeout.connect(self._on_light_cal_timeout)

        self._port_refresh_timer = QTimer(self)
        self._port_refresh_timer.setInterval(2000)
        self._port_refresh_timer.timeout.connect(self._refresh_ports)

        self._action_status_timer = QTimer(self)
        self._action_status_timer.setSingleShot(True)
        self._action_status_timer.setInterval(ACTION_STATUS_RECOVER_MS)
        self._action_status_timer.timeout.connect(self._clear_action_status)

        # 连接按钮事件
        self._connect_buttons()
        self._init_light_threshold()
        self._init_stage_distance()
        self._init_serial_controls()
        self._init_serial_rx_display()

        # 初始化快捷操作配置
        self._init_quick_action_settings()

        # 初始化合格判定阈值
        self._init_judge_settings()

        # 初始化补偿设定
        self._init_compensation_settings()

        # 全量程偏置校准自动流程状态
        self._offset_all_active = False
        # 全档偏置校准目标：IDAC3~6 × PGA×1~×128 共 32 组（按 IDAC 分组，减少切档次数）
        self._offset_all_targets = [
            (pga, idac)
            for idac in range(IDAC_MIN_INDEX, IDAC_MAX_INDEX + 1)
            for pga in range(len(PGA_OPTION_TEXTS))
        ]
        self._offset_all_cursor = 0
        self._offset_all_original_pga = None
        self._offset_all_original_idac = None
        self._offset_all_wait_pga = False
        self._offset_all_wait_idac = False
        self._offset_all_wait_offset = False
        self._offset_all_pga_retries = 0
        self._offset_all_idac_retries = 0
        self._offset_all_pga_buffer = ""
        self._offset_all_idac_buffer = ""
        self._offset_all_cancel_pending = False
        self._offset_all_results = []
        self._offset_all_progress = None
        self._serial_connected = False
        self._offset_all_pga_timer = QTimer(self)
        self._offset_all_pga_timer.setSingleShot(True)
        self._offset_all_pga_timer.setInterval(2500)
        self._offset_all_pga_timer.timeout.connect(self._on_offset_all_pga_timeout)
        self._offset_all_idac_timer = QTimer(self)
        self._offset_all_idac_timer.setSingleShot(True)
        self._offset_all_idac_timer.setInterval(2500)
        self._offset_all_idac_timer.timeout.connect(self._on_offset_all_idac_timeout)

        # 加载台控示意图
        self._init_stage_picture()

        logger.info("ConfigPanel 初始化完成")

    def _init_stage_picture(self):
        """widget_picture 背景图 + 所有箭头按钮用 QPainter 三角 Icon。"""
        pic = self.findChild(QWidget, "widget_picture")
        if pic is None:
            return

        img_path = os.path.join(os.path.dirname(__file__), "..", "ui", "stage.png")
        if os.path.exists(img_path):
            from PyQt5.QtGui import QPixmap
            bg = QLabel(pic)
            bg.setScaledContents(True)
            bg.setPixmap(QPixmap(img_path))
            bg.lower()
            bg.setGeometry(0, 0, pic.width(), pic.height())
            class _PicResizer(QObject):
                def eventFilter(self, obj, event):
                    if event.type() == QEvent.Resize:
                        bg.setGeometry(0, 0, obj.width(), obj.height())
                    return False
            pic.installEventFilter(_PicResizer(pic))

        from PyQt5.QtGui import QPainter, QColor, QIcon, QPixmap, QPolygon, QTransform
        from PyQt5.QtCore import QPoint
        size = 32
        color = QColor("#2c3e50")

        # 只画朝上三角，其余方向旋转
        base = QPixmap(size, size)
        base.fill(Qt.transparent)
        p = QPainter(base)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(color)
        p.setPen(Qt.NoPen)
        p.drawPolygon(QPolygon([QPoint(16,4), QPoint(4,24), QPoint(28,24)]))
        p.end()

        def _icon(angle):
            t = QTransform().rotate(angle)
            return QIcon(base.transformed(t, Qt.SmoothTransformation))

        icons = {
            "stage_btn_up":      QIcon(base),          # 0°
            "stage_btn_down":    _icon(180),            # 180°
            "stage_btn_left":    _icon(-90),            # ←
            "stage_btn_right":   _icon(90),             # →
            "stage_btn_forward": _icon(45),             # ↗
            "stage_btn_back":    _icon(-135),            # ↙
        }

        for name, icon in icons.items():
            btn = self.findChild(QPushButton, name)
            if btn:
                btn.setIcon(icon)
                btn.setIconSize(btn.size())
                btn.setText("")

        style = (
            "QPushButton { border:1px solid #999; border-radius:4px; background:rgba(255,255,255,220); }"
            "QPushButton:hover { background-color:rgb(224,224,224); }"
        )
        for name in icons:
            btn = self.findChild(QPushButton, name)
            if btn:
                btn.setStyleSheet(style)

    def set_thread_manager(self, tm):
        """设置线程管理器"""
        self.thread_manager = tm
        if tm:
            self.serial_manager = tm.serial_manager
            self.serial_command = tm.serial_command
            self.data_process = tm.data_process
            self.serial_manager.signal_connection_status_changed.connect(
                self._on_serial_status_changed,
                Qt.QueuedConnection,
            )
            self.serial_manager.signal_data_received.connect(
                self._on_serial_data_received,
                Qt.QueuedConnection,
            )
            # 连接位置数据处理完成信号
            tm.data_process.signal_position_data_process_finished.connect(
                self._on_position_data_updated,
                Qt.QueuedConnection,
            )
            # 全量程偏置校准完成信号
            tm.data_process.signal_offset_data_process_finished.connect(
                self._on_offset_all_offset_finished,
                Qt.QueuedConnection,
            )
            logger.info("测试配置面板已绑定线程管理器，位置查询由 SerialCommand 管理")

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
            config.signal_scheme_changed.connect(self._on_config_scheme_changed)

        combo_test_speed = self.findChild(QComboBox, "combo_test_speed")
        if combo_test_speed:
            combo_test_speed.setCurrentIndex(config.test_speed)
            combo_test_speed.currentIndexChanged.connect(self._on_test_speed_changed)
            config.signal_test_speed_changed.connect(self._on_config_test_speed_changed)

        combo_sensor_range = self.findChild(QComboBox, "combo_sensor_range")
        if combo_sensor_range:
            combo_sensor_range.blockSignals(True)
            combo_sensor_range.clear()
            combo_sensor_range.addItems(PGA_OPTION_TEXTS)
            combo_sensor_range.setCurrentIndex(config.pga_gain)
            combo_sensor_range.blockSignals(False)
            combo_sensor_range.currentIndexChanged.connect(self._on_pga_gain_changed)

        # 量程改为“输入估计磁场 + 自动选档”
        estimate_edit = self.findChild(QLineEdit, "edit_range_estimate")
        if estimate_edit:
            estimate_edit.editingFinished.connect(self._on_range_estimate_changed)
        config.signal_pga_gain_changed.connect(lambda _index: self._update_range_selection_label())
        if hasattr(config, 'signal_idac_index_changed'):
            config.signal_idac_index_changed.connect(
                lambda _index: self._update_range_selection_label())
        if hasattr(config, 'signal_range_estimate_changed'):
            config.signal_range_estimate_changed.connect(
                self._on_shared_range_estimate_changed)
        self._update_range_selection_label()
        config.signal_pga_gain_changed.connect(self._on_config_pga_gain_changed)

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
                self._show_action_status("测试方案已保存")

    def _on_suspend_edit_scheme(self):
        """编辑挂起方案"""
        config = get_config_manager()
        test_type = config.test_type
        schemes = config.get_suspend_schemes(test_type)
        if schemes:
            scheme = schemes[0].copy()
            dialog = SchemeEditDialog(scheme, self)
            if dialog.exec_():
                result = dialog.get_result()
                config.update_scheme(test_type, False, 0, result)
                self._update_scheme_display(test_type)
                logger.info(f"挂起方案已更新: {result}")
                self._show_action_status("挂起方案已保存")

    def _on_test_type_changed(self, index):
        """测试类型改变"""
        config = get_config_manager()
        config.test_type = index
        logger.info(f"测试类型已更改: {index}")

        # 更新方案显示
        self._update_scheme_display(index)

    def _on_test_speed_changed(self, index):
        """测试速度改变 → 下发对应的采集参数（ACQCFG + ADCRATE）"""
        config = get_config_manager()
        config.test_speed = index
        logger.info(f"测试速度已更改: {index}")
        if self.serial_command and self.serial_manager and self.serial_manager.get_connection_status():
            self.serial_command.apply_test_speed(index)

    def _on_config_test_type_changed(self, index):
        """配置管理器测试类型改变，同步更新下拉框"""
        combo_test_type = self.findChild(QComboBox, "combo_test_type")
        if combo_test_type and combo_test_type.currentIndex() != index:
            combo_test_type.blockSignals(True)
            combo_test_type.setCurrentIndex(index)
            combo_test_type.blockSignals(False)
        # 更新方案显示
        self._update_scheme_display(index)

    def _on_config_test_speed_changed(self, index):
        """配置管理器测试速度改变，同步更新下拉框"""
        combo_test_speed = self.findChild(QComboBox, "combo_test_speed")
        if combo_test_speed and combo_test_speed.currentIndex() != index:
            combo_test_speed.blockSignals(True)
            combo_test_speed.setCurrentIndex(index)
            combo_test_speed.blockSignals(False)

    def _on_pga_gain_changed(self, index):
        """用户修改 PGA 量程：写入配置（发送与回信确认由测量面板统一处理）。"""
        config = get_config_manager()
        config.pga_gain = index
        logger.info(f"PGA 量程已更改: {PGA_OPTION_TEXTS[config.pga_gain]}")

    # ==================== 量程估计输入与自动选档 ====================

    def _range_estimate(self):
        """读取估计磁场（mT）；非法返回 None。"""
        edit = self.findChild(QLineEdit, "edit_range_estimate")
        if not edit:
            return None
        text = edit.text().strip()
        if not text:
            return None
        try:
            return abs(float(text))
        except ValueError:
            return None

    def _on_range_estimate_changed(self):
        """输入估计磁场后自动选档：写入共享估计值，测量界面同步显示。"""
        estimate = self._range_estimate()
        config = get_config_manager()
        config.range_estimate_mt = estimate          # 触发两界面同步
        if estimate is None:
            self._update_range_selection_label()
            return
        selection = config.apply_range_estimate(estimate)
        if selection is None:
            self._update_range_selection_label()
            return
        if not self._is_serial_connected():
            self._warn_serial_not_connected()
        pga, idac, span, target, overflow = selection
        logger.info(
            f"配置面板自动选档：估计 {estimate:.1f} mT + 余量 "
            f"{target - estimate:.0f} mT → IDAC{idac} / PGA{pga}（量程 {span:.1f} mT）"
            + ("（超出最大量程，取最大档）" if overflow else "")
        )
        self._update_range_selection_label(overflow=overflow)

    def _is_serial_connected(self) -> bool:
        """串口/设备是否可用。"""
        return bool(self.serial_manager and self.serial_manager.get_connection_status())

    def _warn_serial_not_connected(self):
        """档位未能下发时的提示（非模态，避免阻塞自动流程）。"""
        text = ("串口未连接，PGA/IDAC 档位无法下发。\n"
                "请先打开设备电源并点击配置区的“连接”，再输入估计磁场。")
        logger.warning("配置面板选档未下发：串口未连接")
        if os.environ.get('QT_QPA_PLATFORM', '').startswith('offscreen'):
            return
        try:
            box = getattr(self, '_serial_warn_box', None)
            if box is None:
                box = QMessageBox(QMessageBox.Warning, "串口未连接", text,
                                  QMessageBox.Ok, self)
                self._serial_warn_box = box
            box.setText(text)
            box.show()
            box.raise_()
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"显示串口未连接提示失败: {exc}")

    def _update_range_selection_label(self, overflow=False):
        """刷新选档提示：只显示两个挡位（IDAC / PGA 增益）+ 一个最大量程数字。"""
        label = self.findChild(QLabel, "label_range_selected")
        if not label:
            return
        config = get_config_manager()
        if config.range_estimate_mt is None:
            label.setText("请输入估计磁场")
            label.setStyleSheet("color: #b0b0b0;")
            return
        pga, idac = config.pga_gain, config.idac_index
        # 显示按输入估计值算出的选档结果（而不是“当前配置”，避免切换失败时显示拼接组合）
        selection = config.select_range(config.range_estimate_mt)
        if selection:
            pga, idac, span, _target, sel_overflow = selection
            overflow = overflow or sel_overflow
        else:
            span = config.max_range_mt(pga, idac)
            overflow = overflow or (config.range_estimate_mt + RANGE_SELECT_MARGIN_MT > span)
        text = format_range_selection(pga, idac, span)
        # 标签只显示两个挡位 + 量程数字；“档位未下发”等状态放到悬停提示
        tooltip = text
        if overflow:
            tooltip += "（超出可用量程，读数可能溢出）"
        if (pga, idac) != (config.pga_gain, config.idac_index):
            tooltip += "（档位未下发）"
        label.setText(text)
        label.setToolTip(tooltip)
        label.setStyleSheet("color: #c0392b;" if overflow else "color: #2c3e50;")

    def _on_shared_range_estimate_changed(self, value):
        """另一界面修改了量程估计值：同步输入框与提示标签。"""
        edit = self.findChild(QLineEdit, "edit_range_estimate")
        if edit:
            text = '' if value is None else f'{float(value):g}'
            if edit.text().strip() != text:
                edit.blockSignals(True)
                edit.setText(text)
                edit.blockSignals(False)
        self._update_range_selection_label()

    def _on_config_pga_gain_changed(self, index):
        """配置管理器 PGA 量程改变，同步更新下拉框"""
        combo_sensor_range = self.findChild(QComboBox, "combo_sensor_range")
        if combo_sensor_range and combo_sensor_range.currentIndex() != index:
            combo_sensor_range.blockSignals(True)
            combo_sensor_range.setCurrentIndex(index)
            combo_sensor_range.blockSignals(False)

    def _on_config_scheme_changed(self, test_type):
        """配置管理器移动方案改变，同步更新当前测试类型流程。"""
        config = get_config_manager()
        if test_type == config.test_type:
            self._update_scheme_display(test_type)

    def _load_saved_positions(self):
        """从配置文件加载保存的位置"""
        try:
            config = get_config_manager()
            # 更新测试位置显示
            test_x_display = self.findChild(QLineEdit, "test_x_value")
            test_y_display = self.findChild(QLineEdit, "test_y_value")
            if test_x_display:
                test_x_display.setText(str(config.test_x))
            if test_y_display:
                test_y_display.setText(str(config.test_z))

            # 更新挂起位置显示
            suspend_x_display = self.findChild(QLineEdit, "suspend_x_value")
            suspend_y_display = self.findChild(QLineEdit, "suspend_y_value")
            if suspend_x_display:
                suspend_x_display.setText(str(config.suspend_x))
            if suspend_y_display:
                suspend_y_display.setText(str(config.suspend_z))

            # 更新圆心位置显示
            center_x_display = self.findChild(QLineEdit, "center_x_value")
            center_z_display = self.findChild(QLineEdit, "center_z_value")
            center_text = (
                (str(config.center_x), str(config.center_z))
                if config.center_saved else ("--", "--")
            )
            if center_x_display:
                center_x_display.setText(center_text[0])
            if center_z_display:
                center_z_display.setText(center_text[1])

            logger.info(
                f"已加载保存的位置: 水平({config.test_x}, {config.test_z}), "
                f"挂起({config.suspend_x}, {config.suspend_z}), "
                f"圆心({center_text[0]}, {center_text[1]})"
            )
        except Exception as e:
            logger.error(f"加载保存位置失败: {e}")

    def _init_serial_controls(self):
        """初始化测试配置页顶部的串口号连接控件。"""
        self._refresh_ports()
        self._apply_serial_port_to_ui(get_config_manager().com_port)
        self._set_serial_status("未连接", "#e74c3c")
        self._set_serial_button_state(False)

        port_combo = self.findChild(QComboBox, "port_combo")
        if port_combo:
            port_combo.currentTextChanged.connect(self._on_port_combo_changed)

    def _init_serial_rx_display(self) -> None:
        serial_rx_text = self.findChild(QPlainTextEdit, "serial_rx_text")
        if serial_rx_text:
            serial_rx_text.document().setMaximumBlockCount(500)

    def _set_combo_text(self, combo_name: str, value: str) -> None:
        combo = self.findChild(QComboBox, combo_name)
        if not combo:
            return

        index = combo.findText(str(value))
        if index >= 0:
            combo.setCurrentIndex(index)

    def _get_serial_port_from_ui(self) -> str:
        port_combo = self.findChild(QComboBox, "port_combo")
        return port_combo.currentText() if port_combo else ""

    def _apply_serial_port_to_ui(self, com_port: str) -> None:
        self._set_combo_text("port_combo", com_port)

    def _set_serial_status(self, text: str, color: str) -> None:
        status_label = self.findChild(QLabel, "serial_status_label")
        if status_label:
            status_label.setText(text)
            status_label.setStyleSheet(f"color: {color}; font-weight: bold; font-size: 14px;")

    def _show_action_status(self, message: str, is_error: bool = False) -> None:
        """在快捷操作区显示短暂的操作结果，成功信息统一使用绿色。"""
        label = self.findChild(QLabel, "label_action_status")
        if label is None:
            return
        color = "#c0392b" if is_error else "#27ae60"
        label.setText(message)
        label.setToolTip(message)
        label.setStyleSheet(
            f"color: {color}; font-weight: bold; font-size: 12px;"
        )
        self._action_status_timer.start()

    def _clear_action_status(self) -> None:
        label = self.findChild(QLabel, "label_action_status")
        if label is not None:
            label.clear()
            label.setToolTip("")

    def _set_serial_button_state(self, connected: bool = False, connecting: bool = False) -> None:
        connect_btn = self.findChild(QPushButton, "btnSuccess")
        if not connect_btn:
            return

        connect_btn.setEnabled(True)
        if connecting:
            connect_btn.setText("连接中...")
            connect_btn.setStyleSheet(
                "QPushButton { background-color: #3498db; color: white; }"
            )
        elif connected:
            connect_btn.setText("断开")
            connect_btn.setStyleSheet(
                "QPushButton { background-color: #e74c3c; color: white; }"
            )
        else:
            connect_btn.setText("连接")
            connect_btn.setStyleSheet(
                "QPushButton { background-color: #27ae60; color: white; }"
            )

    def _save_serial_port(self, com_port: str) -> None:
        config = get_config_manager()
        config.com_port = com_port or config.com_port

    def _on_port_combo_changed(self, text: str) -> None:
        """下拉框选项变更时保存到配置"""
        if text and text not in ("无可用串口", "刷新失败"):
            self._save_serial_port(text)

    def _refresh_ports(self):
        port_combo = self.findChild(QComboBox, "port_combo")
        if port_combo is None:
            logger.error("port_combo not found")
            return

        current_port = port_combo.currentText() or get_config_manager().com_port
        is_connected = bool(self.serial_manager and self.serial_manager.get_connection_status())

        port_combo.blockSignals(True)
        port_combo.clear()
        try:
            ports = list(serial.tools.list_ports.comports())
            for port in ports:
                port_combo.addItem(port.device)

            if current_port:
                index = port_combo.findText(current_port)
                if index >= 0:
                    port_combo.setCurrentIndex(index)

            if port_combo.count() == 0:
                port_combo.addItem("无可用串口")
                port_combo.setEnabled(False)
            else:
                port_combo.setEnabled(not is_connected)
        except Exception as e:
            logger.error(f"Refresh serial ports failed: {e}")
            port_combo.addItem("刷新失败")
        finally:
            port_combo.blockSignals(False)

    def _start_connect(self, com_port: str, status_text: str) -> bool:
        if not self.thread_manager or not self.thread_manager.serial_manager:
            logger.error("Serial manager is not initialized.")
            return False

        if self.thread_manager.serial_manager.get_connection_status():
            logger.info("Serial port is already connected.")
            return True

        if not com_port or com_port in ("无可用串口", "刷新失败"):
            logger.error("Please select a valid serial port.")
            return False

        self._pending_connection_port = com_port
        self._apply_serial_port_to_ui(com_port)
        self._set_serial_status(status_text, "#3498db")
        self._set_serial_button_state(connecting=True)
        self._connection_timeout_timer.start(2000)

        logger.info(f"Connecting serial port {com_port}...")
        self.thread_manager.signal_connect.emit(com_port)
        return True

    def _set_port_refresh_enabled(self, enabled: bool) -> None:
        if enabled:
            if not self._port_refresh_timer.isActive():
                self._port_refresh_timer.start()
            self._refresh_ports()
            return

        if self._port_refresh_timer.isActive():
            self._port_refresh_timer.stop()

    def showEvent(self, event):
        super().showEvent(event)
        self._serial_rx_update_enabled = True
        self._set_port_refresh_enabled(True)
        self._refresh_ports()
        self._apply_serial_port_to_ui(get_config_manager().com_port)

    def hideEvent(self, event):
        self._set_port_refresh_enabled(False)
        self._serial_rx_update_enabled = False
        super().hideEvent(event)

    def _on_serial_data_received(self, data: bytes) -> None:
        if self._light_cal_pending is not None:
            self._feed_light_cal_rx(data)

        # 全档偏置校准进行中：等待 IDAC / PGA 回信时先喂给自动流程解析
        if self._offset_all_active and self._offset_all_wait_idac:
            self._feed_offset_all_idac_rx(data)
        # 全量程偏置校准进行中且等待 PGA 回信时，先喂给自动流程解析
        if self._offset_all_active and self._offset_all_wait_pga:
            self._feed_offset_all_pga_rx(data)

        if not self._serial_rx_update_enabled:
            return

        serial_rx_text = self.findChild(QPlainTextEdit, "serial_rx_text")
        if not serial_rx_text:
            return

        text = data.decode("utf-8", errors="replace")
        text = text.replace("\r", "\\r").replace("\n", "\\n\n")
        serial_rx_text.moveCursor(QTextCursor.End)
        serial_rx_text.insertPlainText(text)
        serial_rx_text.moveCursor(QTextCursor.End)

    def _set_light_cal_status(self, text: str, color: str = "#7f8c8d") -> None:
        label = self.findChild(QLabel, "label_light_cal_status")
        if label:
            label.setText(text)
            label.setStyleSheet(
                f"color: {color}; font-weight: bold; font-size: 12px;"
            )

    def _set_light_cal_buttons_enabled(self, enabled: bool) -> None:
        enabled = bool(enabled and self._serial_connected and self._light_cal_pending is None)
        for name in ("btn_set_light_base", "btn_set_light_threshold"):
            btn = self.findChild(QPushButton, name)
            if btn:
                btn.setEnabled(enabled)
        spin = self.findChild(QSpinBox, "spin_light_threshold")
        if spin:
            spin.setEnabled(self._light_cal_pending is None)

    def _init_light_threshold(self) -> None:
        spin = self.findChild(QSpinBox, "spin_light_threshold")
        if spin:
            spin.setValue(get_config_manager().light_threshold)

    def _set_serial_command_buttons_enabled(self, enabled: bool) -> None:
        """串口未连接时禁用所有会下发设备指令的按钮。"""
        self._serial_connected = bool(enabled)
        for name in SERIAL_COMMAND_BUTTONS:
            btn = self.findChild(QPushButton, name)
            if btn:
                btn.setEnabled(self._serial_connected)
        self._set_light_cal_buttons_enabled(self._serial_connected)

        if not self._serial_connected:
            btn = getattr(self, "_stage_pressed_button", None)
            if btn is not None:
                btn.releaseMouse()
            self._stage_pressed_button = None
            timer = getattr(self, "_stage_press_timer", None)
            if timer is not None:
                timer.stop()
            self._stage_long_pressed = False

    def _on_set_light_base(self) -> None:
        self._send_light_cal_command("LSBASE~", "base", "正在记录静态基准…")

    def _on_set_light_threshold(self) -> None:
        spin = self.findChild(QSpinBox, "spin_light_threshold")
        if spin is None:
            return
        threshold = int(spin.value())
        self._send_light_cal_command(
            f"LSTH{threshold}~",
            "threshold",
            f"正在设置下降量阈值 {threshold} ADC…",
        )

    def _send_light_cal_command(self, command: str, kind: str, pending_text: str) -> None:
        if self._light_cal_pending is not None:
            return
        if not self._is_serial_connected():
            self._set_light_cal_status("请先连接设备", "#c0392b")
            self._set_light_cal_buttons_enabled(False)
            logger.warning(f"光电标定：串口未连接，未发送 {command}")
            return

        self._light_cal_pending = kind
        self._light_cal_rx_buffer = ""
        self._set_light_cal_buttons_enabled(False)
        self._set_light_cal_status(pending_text, "#3498db")
        if self.serial_command is None or not self.serial_command.send_data(
            command, source=f"light_cal_{kind}"
        ):
            self._finish_light_cal(False, f"{command} 发送失败，请检查串口连接")
            return
        logger.info(f"光电标定：已发送 {command}（source=light_cal_{kind}）")
        self._light_cal_timer.start()

    def _feed_light_cal_rx(self, data: bytes) -> None:
        self._light_cal_rx_buffer += data.decode("utf-8", errors="replace")
        while "\n" in self._light_cal_rx_buffer:
            line, self._light_cal_rx_buffer = self._light_cal_rx_buffer.split("\n", 1)
            line = line.strip()
            if line.startswith("LIGHTSW"):
                self._handle_light_cal_line(line)

    def _handle_light_cal_line(self, line: str) -> None:
        if line.startswith("LIGHTSW:"):
            values = dict(re.findall(r"([A-Z_]+)=(-?\d+)", line))
            static_value = values.get("STATIC", "?")
            threshold = values.get("THRESH", "?")
            diff_value = values.get("DIFF", values.get("ABS_DIFF", "?"))
            try:
                threshold_value = int(threshold)
            except (TypeError, ValueError):
                threshold_value = None
            if threshold_value is not None:
                spin = self.findChild(QSpinBox, "spin_light_threshold")
                if spin:
                    spin.setValue(threshold_value)
                get_config_manager().light_threshold = threshold_value
            if self._light_cal_pending == "base":
                message = (
                    f"基准已设置：STATIC={static_value}，"
                    f"THRESH={threshold}，DIFF={diff_value}"
                )
            elif self._light_cal_pending == "threshold":
                message = (
                    f"阈值已设置：THRESH={threshold}，"
                    f"STATIC={static_value}，DIFF={diff_value}"
                )
            else:
                message = (
                    f"LIGHT_SW：STATIC={static_value}，"
                    f"THRESH={threshold}，DIFF={diff_value}"
                )
            self._finish_light_cal(True, message)
            return

        detail = line[len("LIGHTSW"):].strip() or line
        error_messages = {
            "ADC INVALID": "光电传感器采样无效，请检查传感器后重试",
            "BUSY": "设备忙，请停止运动或采集后重试",
            "SAVE FAIL": "设备 Flash 保存失败，原配置保持不变",
            "RANGE": "阈值格式错误，请检查 LSBASE~ 和 LSTH<n>~",
        }
        self._finish_light_cal(False, error_messages.get(detail, f"设置失败：{detail}"))

    def _finish_light_cal(self, success: bool, message: str) -> None:
        self._light_cal_timer.stop()
        pending = self._light_cal_pending
        self._light_cal_pending = None
        self._light_cal_rx_buffer = ""
        self._set_light_cal_status(message, "#27ae60" if success else "#c0392b")
        self._set_light_cal_buttons_enabled(self._is_serial_connected())
        log = logger.info if success else logger.warning
        log(f"光电标定{'成功' if success else '失败'}（{pending or 'unknown'}）：{message}")

    def _on_light_cal_timeout(self) -> None:
        if self._light_cal_pending is None:
            return
        self._finish_light_cal(
            False,
            "未收到设备回信，请确认固件为 LIGHTSW_DROP2_R20 或更高版本",
        )

    def _on_connect_clicked(self):
        if self.thread_manager and self.thread_manager.serial_manager:
            if self.thread_manager.serial_manager.get_connection_status():
                self.thread_manager.signal_disconnect.emit()
                logger.info("Serial port disconnected.")
                return

        self._start_connect(self._get_serial_port_from_ui(), "正在连接...")

    def _on_connection_timeout(self):
        self._set_serial_status("连接超时", "#e74c3c")
        self._set_serial_button_state(False)
        self._pending_connection_port = None
        logger.warning("Serial connection timed out.")

    def _on_serial_status_changed(self, connected):
        self._connection_timeout_timer.stop()

        if connected:
            port = ""
            if self.serial_manager and getattr(self.serial_manager, "serial_port", None):
                port = self.serial_manager.serial_port.portName()

            self._set_serial_button_state(True)
            self._set_serial_command_buttons_enabled(True)

            com_port = str(port or self._pending_connection_port or self._get_serial_port_from_ui()).strip().strip('"')
            self._save_serial_port(com_port)
            self._apply_serial_port_to_ui(com_port)
            self._set_serial_status("已连接", "#27ae60")

            port_combo = self.findChild(QComboBox, "port_combo")
            if port_combo:
                port_combo.setEnabled(False)

            if self.thread_manager and getattr(self.thread_manager, "serial_command", None):
                self.thread_manager.serial_command.enable_position_query_timer()

            # 串口连接后同步当前速度档位的采集参数
            if self.serial_command:
                self.serial_command.apply_test_speed(get_config_manager().test_speed)

            logger.info(f"Serial connected: {com_port}")
        else:
            self._set_serial_button_state(False)
            self._light_cal_timer.stop()
            self._light_cal_pending = None
            self._light_cal_rx_buffer = ""
            self._set_serial_command_buttons_enabled(False)
            self._set_light_cal_status("基准/阈值：请连接设备后设置")

            if self.thread_manager and getattr(self.thread_manager, "serial_command", None):
                self.thread_manager.serial_command.disable_position_query_timer()

            # 串口断开时中止进行中的全量程偏置校准
            if self._offset_all_active:
                self._offset_all_force_stop()

            port_combo = self.findChild(QComboBox, "port_combo")
            if port_combo and port_combo.count() > 0:
                port_combo.setEnabled(True)

            self._set_serial_status("未连接", "#e74c3c")
            logger.info("Serial disconnected.")

        self._pending_connection_port = None

    def _connect_buttons(self):
        """连接按钮事件"""
        connect_btn = self.findChild(QPushButton, "btnSuccess")
        if connect_btn:
            connect_btn.clicked.connect(self._on_connect_clicked)

        btn_set_light_base = self.findChild(QPushButton, "btn_set_light_base")
        if btn_set_light_base:
            btn_set_light_base.clicked.connect(self._on_set_light_base)
        btn_set_light_threshold = self.findChild(QPushButton, "btn_set_light_threshold")
        if btn_set_light_threshold:
            btn_set_light_threshold.clicked.connect(self._on_set_light_threshold)
        self._set_serial_command_buttons_enabled(False)

        # 快捷操作
        self.findChild(QPushButton, "btn_zeroing").clicked.connect(self._on_zeroing)
        btn_offset_all = self.findChild(QPushButton, "btn_offset_all")
        if btn_offset_all:
            btn_offset_all.clicked.connect(self._on_offset_all)
        self.findChild(QPushButton, "btn_test_pos").clicked.connect(self._on_test_pos)
        self.findChild(QPushButton, "btn_suspend").clicked.connect(self._on_suspend)
        self.findChild(QPushButton, "btn_test_pos_save").clicked.connect(self._on_test_pos_save)
        self.findChild(QPushButton, "btn_suspend_save").clicked.connect(self._on_suspend_save)
        self.findChild(QPushButton, "btn_center_position_save").clicked.connect(
            self._on_center_position_save
        )
        self.findChild(QPushButton, "btn_center_position").clicked.connect(
            self._on_center_position
        )
        # 方案编辑
        self.findChild(QToolButton, "btn_test_edit_scheme").clicked.connect(self._on_edit_test_scheme)
        self.findChild(QToolButton, "btn_suspend_edit_scheme").clicked.connect(self._on_suspend_edit_scheme)
        # 台控方向按钮
        self._connect_stage_buttons()

    def _connect_stage_buttons(self):
        """台控：按发送 ±500000 步，松停止。

        使用事件过滤器接管 press/release，确保鼠标移出按钮后松手也能发送 O~。
        Qt 原生 released 信号仅在鼠标位于按钮区域内松手时触发，不可靠。
        """
        stage_specs = {
            "stage_btn_up":      ("Y-500000", "Y", -1, "向上"),
            "stage_btn_down":    ("Y+500000", "Y", 1,  "向下"),
            "stage_btn_left":    ("X-500000", "X", -1, "向左"),
            "stage_btn_right":   ("X+500000", "X", 1,  "向右"),
            "stage_btn_forward": ("Z-500000", "Z", -1, "向后"),
            "stage_btn_back":    ("Z+500000", "Z", 1,  "向前"),
        }
        # 追踪当前按下的按钮，确保松手时发送正确的停止指令
        self._stage_pressed_button: Optional[QPushButton] = None
        self._stage_long_pressed = False
        self._stage_press_timer = QTimer(self)
        self._stage_press_timer.setSingleShot(True)
        self._stage_press_timer.setInterval(STAGE_LONG_PRESS_MS)
        self._stage_press_timer.timeout.connect(self._on_stage_press_timeout)

        for name, (cmd, axis, direction, label) in stage_specs.items():
            btn = self.findChild(QPushButton, name)
            if btn:
                btn._stage_cmd = cmd
                btn._stage_axis = axis
                btn._stage_direction = direction
                btn._stage_label = label
                btn.installEventFilter(self)

    def eventFilter(self, obj, event):
        """拦截台控按钮的 press/release，确保 O~ 可靠发送。"""
        from PyQt5.QtCore import QEvent
        if isinstance(obj, QPushButton) and hasattr(obj, '_stage_cmd'):
            if event.type() == QEvent.MouseButtonPress:
                self._stage_press_timer.stop()
                self._stage_pressed_button = obj
                self._stage_long_pressed = False
                self._stage_press_timer.start()
                obj.grabMouse()  # 捕获鼠标，确保 release 事件不丢失
                return True
            elif event.type() == QEvent.MouseButtonRelease:
                self._stage_press_timer.stop()
                btn = self._stage_pressed_button
                was_long = self._stage_long_pressed
                self._stage_pressed_button = None
                self._stage_long_pressed = False
                if btn is not None:
                    btn.releaseMouse()
                if self.serial_command:
                    if was_long:
                        self.serial_command.send_data("O~", source="stage_release")
                    elif btn is not None:
                        self._execute_short_press(btn)
                return True
        return super().eventFilter(obj, event)

    def _on_stage_press_timeout(self):
        """长按判定成立：开始连续移动。"""
        btn = self._stage_pressed_button
        if btn is None or not hasattr(btn, '_stage_cmd'):
            return
        self._stage_long_pressed = True
        if self.serial_command:
            self.serial_command.send_data(f"{btn._stage_cmd}~", source="stage_press")
            self._show_action_status(f"正在{btn._stage_label}移动，松开按钮停止")

    def _execute_short_press(self, btn):
        """短按：按输入距离沿对应轴方向移动一次。"""
        distance = self._get_distance_value()
        if distance is None or self.serial_command is None:
            return
        self.serial_command.set_move_task(btn._stage_axis, btn._stage_direction, distance)
        self.serial_command.position_query(source="stage_short_press")
        self._show_action_status(
            f"{btn._stage_label}移动 {distance:g} mm，指令已发送"
        )

    def _get_distance_value(self):
        """读取短按距离(mm)，非法时提示并返回 None。"""
        distance_edit = self.findChild(QLineEdit, "distance_edit")
        if not distance_edit:
            return None
        text = distance_edit.text().strip()
        if not text:
            self._set_serial_status("错误：距离值为空", "#e74c3c")
            return None
        try:
            value = float(text)
        except ValueError:
            self._set_serial_status("错误：距离值格式错误", "#e74c3c")
            return None
        if value <= 0:
            self._set_serial_status("错误：距离值必须大于 0", "#e74c3c")
            return None
        return value

    def _init_stage_distance(self):
        """从配置载入短按距离，并连接编辑结束校验保存。"""
        config = get_config_manager()
        distance_edit = self.findChild(QLineEdit, "distance_edit")
        if distance_edit:
            distance_edit.setText(f"{config.stage_step_distance:g}")
            distance_edit.editingFinished.connect(self._on_stage_distance_edited)

    def _on_stage_distance_edited(self):
        """校验输入的距离值，合法则持久化，非法则回退为配置值。"""
        config = get_config_manager()
        distance_edit = self.findChild(QLineEdit, "distance_edit")
        if not distance_edit:
            return
        value = self._get_distance_value()
        if value is None:
            distance_edit.setText(f"{config.stage_step_distance:g}")
            return
        config.stage_step_distance = value
        distance_edit.setText(f"{value:g}")

    def _init_quick_action_settings(self):
        """初始化快捷操作配置"""
        config = get_config_manager()

        # 按钮行均分「快捷操作」分组的剩余高度：分组变高时按钮跟着变高，
        # 而不是在底部两行状态文字下面留一片空白
        for row in range(5):
            self.action_layout.setRowStretch(row, 1)

        self._bind_double_spin(
            "spin_x_offset",
            config.inner_x_offset,
            self._on_x_offset_changed,
        )
        self._bind_double_spin(
            "spin_z_offset",
            config.inner_z_offset,
            self._on_z_offset_changed,
        )

    def _bind_double_spin(self, object_name, value, handler):
        """Load a double spin box from config and persist user changes."""
        spin = self.findChild(QDoubleSpinBox, object_name)
        if not spin:
            logger.warning(f"未找到数值输入控件: {object_name}")
            return

        spin.blockSignals(True)
        spin.setValue(float(value))
        spin.blockSignals(False)
        spin.valueChanged.connect(handler)

    def _on_x_offset_changed(self, value):
        """更新X轴偏移量"""
        config = get_config_manager()
        config.inner_x_offset = value
        logger.info(f"X轴偏移量已更新: {value:.2f} mm")

    def _on_z_offset_changed(self, value):
        """更新Z轴偏移量"""
        config = get_config_manager()
        config.inner_z_offset = value
        logger.info(f"Z轴偏移量已更新: {value:.2f} mm")

    # ==================== 补偿设定 ====================

    def _init_compensation_settings(self):
        """三个补偿开关：加载配置并绑定，改动即时保存。"""
        config = get_config_manager()
        self._comp_loading = True
        for check_name, attr in (
            ("comp_chuck_check", "comp_chuck"),
            ("comp_amplitude_check", "comp_amplitude"),
            ("comp_zero_crossing_check", "comp_zero_crossing"),
        ):
            checkbox = self.findChild(QCheckBox, check_name)
            if checkbox is None:
                logger.warning(f"未找到补偿开关控件: {check_name}")
                continue
            checkbox.setChecked(bool(getattr(config, attr)))
            checkbox.toggled.connect(
                lambda checked, name=check_name, key=attr:
                self._on_compensation_toggled(name, key, checked)
            )
        self._comp_loading = False

    def _on_compensation_toggled(self, check_name: str, attr: str, checked: bool) -> None:
        if getattr(self, "_comp_loading", False):
            return
        setattr(get_config_manager(), attr, bool(checked))
        logger.info(f"补偿设定已更新: {check_name}={'开' if checked else '关'}")

    # ==================== 合格判定阈值 ====================

    def _init_judge_settings(self):
        """加载合格判定阈值，按测量界面的两列布局生成判定项。"""
        self._judge_loading = True
        self._judge_settings = judge_thresholds.load_settings(get_config_manager())
        self._judge_widgets = {}
        self._build_judge_items()

        self.judge_enable_check.setChecked(bool(self._judge_settings["enabled"]))
        self.judge_enable_check.toggled.connect(self._on_judge_enabled_toggled)
        self.judge_layout.setRowStretch(1, 1)
        self._judge_loading = False

    def _build_judge_items(self):
        """左/右两列与测量界面「数据分析结果」的相对位置一一对应。"""
        layout = self.judge_items_layout
        for first_column in (JUDGE_LEFT_COLUMN, JUDGE_RIGHT_COLUMN):
            for offset, text in enumerate(("判定项目", "下限", "上限")):
                label = QLabel(text, self.judge_items_widget)
                label.setStyleSheet("color: #7f8c8d; font-weight: bold;")
                label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
                layout.addWidget(label, 0, first_column + offset)
            for offset in (1, 2):
                layout.setColumnMinimumWidth(first_column + offset, JUDGE_LIMIT_EDIT_WIDTH)
            layout.setColumnStretch(first_column, 1)
        layout.setColumnMinimumWidth(JUDGE_COLUMN_GAP, 16)

        for row, (left_key, right_key) in enumerate(judge_thresholds.JUDGE_LAYOUT_ROWS, start=1):
            self._add_judge_item(layout, row, JUDGE_LEFT_COLUMN, left_key)
            self._add_judge_item(layout, row, JUDGE_RIGHT_COLUMN, right_key)
            # 行高均分剩余空间，与测量界面左右两列的间距观感一致
            layout.setRowStretch(row, 1)

    def _add_judge_item(self, layout, row: int, column: int, key: str) -> None:
        name, unit, kind = judge_thresholds.item_info(key)
        entry = self._judge_settings["items"].get(key) or {}

        check = QCheckBox(judge_thresholds.item_label(name, unit), self.judge_items_widget)
        check.setChecked(bool(entry.get("on")))
        check.toggled.connect(
            lambda checked, item_key=key: self._on_judge_item_toggled(item_key, checked)
        )
        layout.addWidget(check, row, column)

        lo_edit = self._make_judge_limit_edit(key, kind, "lo", entry.get("lo"))
        hi_edit = self._make_judge_limit_edit(key, kind, "hi", entry.get("hi"))
        layout.addWidget(lo_edit, row, column + 1)
        layout.addWidget(hi_edit, row, column + 2)
        self._judge_widgets[key] = {"check": check, "lo": lo_edit, "hi": hi_edit}

    def _make_judge_limit_edit(self, key: str, kind: str, field: str, value):
        edit = QLineEdit(self.judge_items_widget)
        edit.setFixedWidth(JUDGE_LIMIT_EDIT_WIDTH)
        edit.setMaxLength(12)
        edit.setAlignment(Qt.AlignRight)
        edit.setText(self._judge_limit_text(kind, field, value))
        if kind == judge_thresholds.KIND_UPPER and field == "lo":
            # 误差类只判上限
            edit.setEnabled(False)
        else:
            edit.editingFinished.connect(
                lambda item_key=key, item_field=field: self._on_judge_limit_edited(item_key, item_field)
            )
        return edit

    @staticmethod
    def _format_judge_limit(value: float) -> str:
        return f"{value:g}"

    @staticmethod
    def _judge_limit_text(kind: str, field: str, value) -> str:
        """误差类的下限不参与判定，输入框显示占位符。"""
        if kind == judge_thresholds.KIND_UPPER and field == "lo":
            return "—"
        return "" if value is None else ConfigPanel._format_judge_limit(value)

    @staticmethod
    def _parse_judge_limit(text):
        """空串返回 None，非法内容返回 False。"""
        text = (text or "").strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return False

    def _on_judge_enabled_toggled(self, checked: bool) -> None:
        if self._judge_loading:
            return
        self._judge_settings["enabled"] = bool(checked)
        judge_thresholds.save_settings(get_config_manager(), self._judge_settings)
        logger.info(f"合格判定总开关: {'开启' if checked else '关闭'}")

    def _on_judge_item_toggled(self, key: str, checked: bool) -> None:
        if self._judge_loading:
            return
        entry = self._judge_settings["items"].setdefault(
            key, {"on": False, "lo": None, "hi": None}
        )
        entry["on"] = bool(checked)
        judge_thresholds.save_settings(get_config_manager(), self._judge_settings)
        logger.info(f"合格判定项勾选: {key} 启用={entry['on']}")

    def _on_judge_limit_edited(self, key: str, field: str) -> None:
        if self._judge_loading:
            return
        widgets = self._judge_widgets.get(key)
        if not widgets:
            return

        kind = judge_thresholds.item_kind(key)
        if kind == judge_thresholds.KIND_UPPER:
            lo = None
        else:
            lo = self._parse_judge_limit(widgets["lo"].text())
        hi = self._parse_judge_limit(widgets["hi"].text())
        bad_range = (
            kind != judge_thresholds.KIND_UPPER
            and isinstance(lo, float) and isinstance(hi, float) and lo > hi
        )
        if lo is False or hi is False or bad_range:
            logger.warning(
                f"合格判定限值输入无效: {key} 下限={widgets['lo'].text()!r} "
                f"上限={widgets['hi'].text()!r}"
            )
            self._refresh_judge_item(key)
            return

        entry = self._judge_settings["items"].setdefault(
            key, {"on": False, "lo": None, "hi": None}
        )
        entry["lo"] = None if kind == judge_thresholds.KIND_UPPER else lo
        entry["hi"] = hi
        judge_thresholds.save_settings(get_config_manager(), self._judge_settings)
        logger.info(f"合格判定项限值: {key} 下限={entry['lo']} 上限={entry['hi']}")

    def _refresh_judge_item(self, key: str) -> None:
        """用已保存的设置刷新该项（丢弃非法输入）。"""
        widgets = self._judge_widgets.get(key)
        if not widgets:
            return
        kind = judge_thresholds.item_kind(key)
        entry = self._judge_settings["items"].get(key) or {}
        self._judge_loading = True
        widgets["check"].setChecked(bool(entry.get("on")))
        widgets["lo"].setText(self._judge_limit_text(kind, "lo", entry.get("lo")))
        widgets["hi"].setText(self._judge_limit_text(kind, "hi", entry.get("hi")))
        self._judge_loading = False

    def _on_position_data_updated(self, position_data):
        """位置数据更新（M~ 响应解析后的 (x, y, z) 三元组）"""
        if not self.isVisible():
            return
        if position_data and len(position_data) >= 3:
            x, y, z = position_data[0], position_data[1], position_data[2]
            self.update_position(x, y, z)

    def update_position(self, x, y, z):
        """更新当前位置显示（左右=X, 上下=Y, 前后=Z）。"""
        x_display = self.findChild(QLineEdit, "position_x")
        y_display = self.findChild(QLineEdit, "position_y")
        z_display = self.findChild(QLineEdit, "position_z")
        if x_display:
            x_display.setText(str(x) if x is not None else "--")
        if y_display:
            y_display.setText(str(y) if y is not None else "--")
        if z_display:
            z_display.setText(str(z) if z is not None else "--")

    def _on_zeroing(self):
        """零位校准"""
        if self.serial_command:
            self.serial_command.slider_reset()
            logger.info("零位校准")
            self._show_action_status("滑台零位校准指令已发送")
        else:
            logger.warning("串口命令未初始化")
            self._show_action_status("零位校准未发送：串口命令未初始化", is_error=True)

    # ==================== 全量程偏置校准 ====================

    def _on_offset_all(self):
        """全档偏置校准：遍历 IDAC3~6 × PGA×1~×64 共 28 个组合逐个执行偏置校准。"""
        if self._offset_all_active:
            return
        connected = bool(
            self.serial_command
            and self.serial_manager
            and self.serial_manager.get_connection_status()
        )
        if not connected:
            self._show_action_status("全量程偏置校准未启动：请先连接设备", is_error=True)
            QMessageBox.warning(self, "全量程偏置校准", "请先连接串口")
            return
        if getattr(self.serial_command, '_offset_calibrating', False):
            self._show_action_status("全量程偏置校准未启动：已有校准正在进行", is_error=True)
            QMessageBox.warning(self, "全量程偏置校准", "当前已有偏置校准进行中，请稍后再试")
            return

        config = get_config_manager()
        self._offset_all_active = True
        self._offset_all_original_pga = config.pga_gain
        self._offset_all_original_idac = config.idac_index
        self._offset_all_cursor = 0
        self._offset_all_cancel_pending = False
        self._offset_all_results = []
        self._offset_all_wait_pga = False
        self._offset_all_wait_idac = False
        self._offset_all_wait_offset = False
        self._offset_all_pga_buffer = ""
        self._offset_all_idac_buffer = ""
        self._offset_all_pga_retries = 0
        self._offset_all_idac_retries = 0
        self._offset_all_set_buttons_enabled(False)

        progress = FullOffsetCalibrationDialog(
            self, total=len(self._offset_all_targets), targets=self._offset_all_targets
        )
        progress.cancel_requested.connect(self._offset_all_on_cancel_requested)
        progress.show()
        self._offset_all_progress = progress

        logger.info("全档偏置校准开始，共 %d 个组合", len(self._offset_all_targets))
        self._show_action_status(
            f"全量程偏置校准已启动，共 {len(self._offset_all_targets)} 个档位组合"
        )
        self._offset_all_start_target(0)

    def _offset_all_set_buttons_enabled(self, enabled: bool):
        """自动校准期间禁用/恢复偏置相关按钮，避免并发操作。"""
        for name in ("btn_offset_all",):
            btn = self.findChild(QPushButton, name)
            if btn:
                btn.setEnabled(enabled and self._serial_connected)
        combo = self.findChild(QComboBox, "combo_sensor_range")
        if combo:
            combo.setEnabled(enabled)
        estimate = self.findChild(QLineEdit, "edit_range_estimate")
        if estimate:
            estimate.setEnabled(enabled)

    def _offset_all_on_cancel_requested(self):
        """用户点击取消：立即关闭界面；若正在采集则停止并丢弃本轮数据。"""
        if not self._offset_all_active:
            return
        self._offset_all_cancel_pending = True
        # 立即关闭对话框，不等当前轮结束
        if self._offset_all_progress is not None:
            self._offset_all_progress.accept()
            self._offset_all_progress = None

        if self._offset_all_wait_pga:
            # 正在切换量程，无采集进行中，直接收尾
            self._offset_all_wait_pga = False
            self._offset_all_pga_timer.stop()
            self._offset_all_pga_buffer = ""
            self._offset_all_finish()
            return
        if self._offset_all_wait_idac:
            # 正在切换 IDAC，无采集进行中，直接收尾
            self._offset_all_wait_idac = False
            self._offset_all_idac_timer.stop()
            self._offset_all_idac_buffer = ""
            self._offset_all_finish()
            return
        if self._offset_all_wait_offset:
            # 正在偏置采集：立即停止并丢弃残缺数据，finished 到达后收尾
            if self.serial_command is not None:
                self.serial_command.cancel_offset_calibration()
            return
        # 其他间隙：直接收尾
        self._offset_all_finish()

    def _offset_all_update_progress(self, text: str, value: int):
        if self._offset_all_progress is not None:
            self._offset_all_progress.set_progress(value, text)

    def _offset_all_target_text(self, pga: int, idac: int) -> str:
        """校准过程显示文本：只显示挡位与量程，不显示电流值。"""
        return f"IDAC{idac}  {PGA_OPTION_TEXTS[pga]}"

    def _offset_all_start_target(self, idx: int):
        """开始第 idx 个组合：需要时先切 IDAC，再切 PGA，等固件确认后校准。"""
        if not self._offset_all_active:
            return
        if idx >= len(self._offset_all_targets) or self._offset_all_cancel_pending:
            self._offset_all_finish()
            return

        self._offset_all_cursor = idx
        pga, idac = self._offset_all_targets[idx]
        self._offset_all_pga_retries = 0
        self._offset_all_idac_retries = 0
        self._offset_all_pga_buffer = ""
        self._offset_all_idac_buffer = ""
        total = len(self._offset_all_targets)
        self._offset_all_update_progress(
            f"正在切换至 {self._offset_all_target_text(pga, idac)}（{idx + 1}/{total}）…",
            idx,
        )
        if self._offset_all_progress is not None:
            self._offset_all_progress.set_gain_state(idx, "切换中")
        if not self.serial_command:
            self._offset_all_finish()
            return

        config = get_config_manager()
        if idac != config.idac_index:
            self._offset_all_wait_idac = True
            self.serial_command.send_data(f"IDAC{idac}~", source="offset_all_idac")
            self._offset_all_idac_timer.start()
            return
        self._offset_all_send_pga(pga)

    def _offset_all_send_pga(self, pga: int):
        """发送 PGA 切换指令并等待确认。"""
        self._offset_all_wait_pga = True
        self._offset_all_pga_buffer = ""
        self.serial_command.send_data(f"PGA{pga}~", source="offset_all_pga")
        self._offset_all_pga_timer.start()

    def _feed_offset_all_idac_rx(self, data: bytes):
        """解析全档流程中 IDAC<n>~ 的回信（IDAC n OK / BUSY / RANGE）。"""
        try:
            text = data.decode("utf-8", errors="replace")
        except Exception:
            return
        self._offset_all_idac_buffer += text
        while "\n" in self._offset_all_idac_buffer:
            line, self._offset_all_idac_buffer = self._offset_all_idac_buffer.split("\n", 1)
            line = line.strip("\r").strip()
            if not line:
                continue
            ok_match = re.match(r"^IDAC\s+(\d+)\s+OK\s*$", line, re.IGNORECASE)
            if ok_match:
                if not self._offset_all_wait_idac:
                    continue
                pga, idac = self._offset_all_targets[self._offset_all_cursor]
                if int(ok_match.group(1)) != idac:
                    continue
                self._offset_all_wait_idac = False
                self._offset_all_idac_timer.stop()
                self._offset_all_idac_buffer = ""
                get_config_manager().idac_index = idac
                logger.info("全档偏置校准：IDAC%d 切换成功", idac)
                self._offset_all_send_pga(pga)
                continue
            if re.match(r"^IDAC\s+(BUSY|RANGE|ERR)\b", line, re.IGNORECASE):
                if self._offset_all_wait_idac:
                    self._offset_all_mark_failed("IDAC 切换被拒绝(BUSY/RANGE/ERR)")
                continue

    def _on_offset_all_idac_timeout(self):
        """IDAC 切换回信超时：重试一次，仍失败则跳过该组合。"""
        if not (self._offset_all_active and self._offset_all_wait_idac):
            return
        pga, idac = self._offset_all_targets[self._offset_all_cursor]
        if self._offset_all_idac_retries < 1:
            self._offset_all_idac_retries += 1
            logger.warning("全档偏置校准：IDAC%d 切换超时，第 1 次重试", idac)
            self._offset_all_idac_buffer = ""
            self.serial_command.send_data(f"IDAC{idac}~", source="offset_all_idac_retry")
            self._offset_all_idac_timer.start()
            return
        self._offset_all_mark_failed("IDAC 切换超时")

    def _offset_all_mark_failed(self, reason: str):
        """把当前组合记为失败并进入下一组。"""
        if not self._offset_all_active:
            return
        self._offset_all_wait_idac = False
        self._offset_all_wait_pga = False
        self._offset_all_idac_timer.stop()
        self._offset_all_pga_timer.stop()
        self._offset_all_idac_buffer = ""
        self._offset_all_pga_buffer = ""
        pga, idac = self._offset_all_targets[self._offset_all_cursor]
        logger.warning("全档偏置校准：%s 失败：%s",
                       self._offset_all_target_text(pga, idac), reason)
        self._offset_all_results.append(((pga, idac), False, None))
        if self._offset_all_progress is not None:
            self._offset_all_progress.show_gain_result(self._offset_all_cursor, False)
            self._offset_all_progress.set_progress(
                self._offset_all_cursor + 1,
                f"{self._offset_all_target_text(pga, idac)} 失败：{reason}，跳过",
            )
        self._offset_all_next()

    def _feed_offset_all_pga_rx(self, data: bytes):
        """解析全量程流程中 PGA<n>~ 的回信（PGA n OK）。"""
        try:
            text = data.decode("utf-8", errors="replace")
        except Exception:
            return
        self._offset_all_pga_buffer += text
        while "\n" in self._offset_all_pga_buffer:
            line, self._offset_all_pga_buffer = self._offset_all_pga_buffer.split("\n", 1)
            line = line.strip("\r").strip()
            if not line:
                continue
            ok_match = re.match(r"^PGA\s+(\d+)\s+OK\s*$", line, re.IGNORECASE)
            if ok_match:
                if not self._offset_all_wait_pga:
                    continue
                target_pga, _target_idac = self._offset_all_targets[self._offset_all_cursor]
                if int(ok_match.group(1)) == target_pga:
                    self._on_offset_all_pga_confirmed()
                continue
            if re.match(r"^PGA\s+(BUSY|RANGE|ERR)\b", line, re.IGNORECASE):
                if self._offset_all_wait_pga:
                    self._offset_all_pga_fail("固件拒绝(BUSY/RANGE/ERR)")
                continue

    def _on_offset_all_pga_confirmed(self):
        """PGA 切换已确认，进入该量程的偏置校准。"""
        self._offset_all_wait_pga = False
        self._offset_all_pga_timer.stop()
        self._offset_all_pga_buffer = ""
        pga, idac = self._offset_all_targets[self._offset_all_cursor]
        logger.info("全档偏置校准：%s 切换成功", self._offset_all_target_text(pga, idac))
        self._offset_all_start_offset()

    def _on_offset_all_pga_timeout(self):
        """PGA 切换回信超时：重试一次，仍失败则跳过该档。"""
        if not (self._offset_all_active and self._offset_all_wait_pga):
            return
        pga, idac = self._offset_all_targets[self._offset_all_cursor]
        if self._offset_all_pga_retries < 1:
            self._offset_all_pga_retries += 1
            logger.warning("全档偏置校准：%s 切换超时，第 1 次重试",
                           self._offset_all_target_text(pga, idac))
            self._offset_all_pga_buffer = ""
            self.serial_command.send_data(f"PGA{pga}~", source="offset_all_pga_retry")
            self._offset_all_pga_timer.start()
            return
        self._offset_all_mark_failed("PGA 切换超时")

    def _offset_all_pga_fail(self, reason: str):
        """PGA 切换失败：记录后跳过该档，继续下一档。"""
        self._offset_all_mark_failed(reason)

    def _offset_all_start_offset(self):
        """对当前量程执行一次偏置校准（结果写入指定量程槽位）。"""
        pga, idac = self._offset_all_targets[self._offset_all_cursor]
        total = len(self._offset_all_targets)
        self._offset_all_wait_offset = True
        self._offset_all_update_progress(
            f"正在校准 {self._offset_all_target_text(pga, idac)} 偏置"
            f"（{self._offset_all_cursor + 1}/{total}）…",
            self._offset_all_cursor,
        )
        if self._offset_all_progress is not None:
            self._offset_all_progress.set_gain_state(self._offset_all_cursor, "校准中")
        if self.data_process is not None:
            self.data_process.set_offset_save_target(pga, idac)
        if self.serial_command:
            self.serial_command.disable_position_query_timer()
            self.serial_command.offset_calibration()

    def _on_offset_all_offset_finished(self, success: bool):
        """某一档偏置校准流程结束（含固件内部重试后的最终结果）。"""
        if not (self._offset_all_active and self._offset_all_wait_offset):
            return
        # 固件内部自动重试尚未结束，继续等待
        if getattr(self.serial_command, '_offset_retrying', False):
            return
        # 用户已取消：结束流程，不再进入下一量程
        if self._offset_all_cancel_pending:
            self._offset_all_wait_offset = False
            self._offset_all_finish()
            return

        self._offset_all_wait_offset = False
        pga, idac = self._offset_all_targets[self._offset_all_cursor]
        offset_value = None
        if success:
            config = get_config_manager()
            offset_value = config.get_offset_for(pga, idac)
        self._offset_all_results.append(((pga, idac), bool(success), offset_value))
        offset_mt = None
        if success and offset_value is not None:
            offset_mt = offset_value / get_mag_adc_per_mt(pga, idac)
        logger.info(
            "全档偏置校准：%s %s（offset=%s）",
            self._offset_all_target_text(pga, idac),
            "成功" if success else "失败",
            f"{offset_value:.1f}" if offset_value is not None else "-",
        )
        if self.serial_command:
            self.serial_command.enable_position_query_timer()
        if self._offset_all_progress is not None:
            self._offset_all_progress.show_gain_result(
                self._offset_all_cursor, bool(success), offset_value, offset_mt
            )
            self._offset_all_progress.set_progress(
                self._offset_all_cursor + 1,
                f"已完成 {self._offset_all_cursor + 1}/{len(self._offset_all_targets)} 个组合",
            )
        self._offset_all_next()

    def _offset_all_next(self):
        """进入下一个组合。"""
        self._offset_all_start_target(self._offset_all_cursor + 1)

    def _offset_all_finish(self):
        """全部结束：恢复原量程并汇总结果。"""
        if not self._offset_all_active:
            return
        self._offset_all_active = False
        self._offset_all_cancel_pending = False
        self._offset_all_wait_pga = False
        self._offset_all_wait_idac = False
        self._offset_all_wait_offset = False
        self._offset_all_pga_timer.stop()
        self._offset_all_idac_timer.stop()
        self._offset_all_pga_buffer = ""
        self._offset_all_idac_buffer = ""
        if self.data_process is not None:
            self.data_process.clear_offset_save_pga()
        if self.serial_command:
            self.serial_command.enable_position_query_timer()

        # 恢复进入前的 PGA 量程与 IDAC 档位
        config = get_config_manager()
        if self._offset_all_original_pga is not None:
            config.pga_gain = self._offset_all_original_pga
        if self._offset_all_original_idac is not None:
            config.idac_index = self._offset_all_original_idac

        self._offset_all_set_buttons_enabled(True)

        ok = [r for r in self._offset_all_results if r[1]]
        failed = [r for r in self._offset_all_results if not r[1]]
        logger.info("全档偏置校准结束：成功 %d 个，失败 %d 个", len(ok), len(failed))
        if self._offset_all_progress is not None:
            self._offset_all_progress.finish(len(ok), len(failed))

    def _offset_all_force_stop(self):
        """串口断开等异常情况下直接中止自动校准（不恢复硬件量程）。"""
        if not self._offset_all_active:
            return
        self._offset_all_active = False
        self._offset_all_cancel_pending = False
        self._offset_all_wait_pga = False
        self._offset_all_wait_idac = False
        self._offset_all_wait_offset = False
        self._offset_all_pga_timer.stop()
        self._offset_all_idac_timer.stop()
        self._offset_all_pga_buffer = ""
        self._offset_all_idac_buffer = ""
        if self.data_process is not None:
            self.data_process.clear_offset_save_pga()
            self.data_process.request_offset_abort()
        self._offset_all_set_buttons_enabled(True)
        if self._offset_all_progress is not None:
            self._offset_all_progress.close()
            self._offset_all_progress = None
        logger.warning("串口断开，全档偏置校准已中止")

    def _on_test_pos(self):
        """移动到测试位置"""
        if self.serial_command:
            self.serial_command.test_position()
            logger.info("移动到测试位置")
            self._show_action_status("移动到测试位置指令已发送")
        else:
            logger.warning("串口命令未初始化")
            self._show_action_status("测试位置未发送：串口命令未初始化", is_error=True)

    def _on_suspend(self):
        """移动到挂起位置"""
        if self.serial_command:
            self.serial_command.suspend_position()
            logger.info("移动到挂起位置")
            self._show_action_status("移动到挂起位置指令已发送")
        else:
            logger.warning("串口命令未初始化")
            self._show_action_status("挂起位置未发送：串口命令未初始化", is_error=True)

    def _on_center_position(self):
        """查询三轴，按需回零 Y，再依次执行 X、Z。"""
        config = get_config_manager()
        if not config.center_saved:
            self._show_action_status("尚未保存圆心位置，请先定位并保存", is_error=True)
            QMessageBox.warning(self, "圆心定位", "尚未保存圆心位置，请先定位并保存。")
            return
        if not self.serial_command:
            logger.warning("串口命令未初始化")
            self._show_action_status("圆心定位未启动：串口命令未初始化", is_error=True)
            return
        if not self.serial_command.center_position():
            self._show_action_status("圆心定位未启动，请检查设备状态", is_error=True)
            QMessageBox.warning(
                self, "圆心定位",
                "圆心定位未启动，请检查当前轴位置或等待上一项运动结束。",
            )
            return
        self._show_action_status("圆心定位已启动：Y 轴回零，随后依次执行 X、Z")

    def _on_center_position_save(self):
        """保存当前左右 X、前后 Z 轴位置为圆心。"""
        try:
            x_display = self.findChild(QLineEdit, "position_x")
            z_display = self.findChild(QLineEdit, "position_z")
            if not x_display or not z_display:
                return
            x = int(x_display.text())
            z = int(z_display.text())
            config = get_config_manager()
            if not config.set_center_position(x, z):
                raise OSError("配置文件保存失败")

            center_x_display = self.findChild(QLineEdit, "center_x_value")
            center_z_display = self.findChild(QLineEdit, "center_z_value")
            if center_x_display:
                center_x_display.setText(str(x))
            if center_z_display:
                center_z_display.setText(str(z))
            logger.info(f"保存圆心位置: X={x}, Z={z}")
            self._show_action_status(f"圆心位置已保存：X={x}，Z={z}")
        except (TypeError, ValueError, OSError):
            self._show_action_status("圆心位置保存失败：当前位置无效或配置写入失败", is_error=True)
            QMessageBox.warning(self, "圆心定位", "当前位置无效或配置保存失败。")
            logger.warning("无效的位置数据，无法保存圆心位置")

    def _on_test_pos_save(self):
        """保存当前测试位置（水平=X, 竖直=Y）"""
        try:
            x_display = self.findChild(QLineEdit, "position_x")
            y_display = self.findChild(QLineEdit, "position_y")
            if x_display and y_display:
                x = int(x_display.text())
                y = int(y_display.text())
                config = get_config_manager()
                config.test_x = x
                config.test_z = y   # 竖直位置存入 test_z 键
                logger.info(f"保存测试位置: 水平={x}, 竖直={y}")

                test_x_display = self.findChild(QLineEdit, "test_x_value")
                test_y_display = self.findChild(QLineEdit, "test_y_value")
                if test_x_display:
                    test_x_display.setText(str(x))
                if test_y_display:
                    test_y_display.setText(str(y))
                self._show_action_status(f"测试位置已保存：水平={x}，竖直={y}")
        except ValueError:
            self._show_action_status("测试位置保存失败：当前位置无效", is_error=True)
            logger.warning("无效的位置数据，无法保存")

    def _on_suspend_save(self):
        """保存当前挂起位置（水平=X, 竖直=Y）"""
        try:
            x_display = self.findChild(QLineEdit, "position_x")
            y_display = self.findChild(QLineEdit, "position_y")
            if x_display and y_display:
                x = int(x_display.text())
                y = int(y_display.text())
                config = get_config_manager()
                config.suspend_x = x
                config.suspend_z = y   # 竖直位置存入 suspend_z 键
                logger.info(f"保存挂起位置: 水平={x}, 竖直={y}")

                suspend_x_display = self.findChild(QLineEdit, "suspend_x_value")
                suspend_y_display = self.findChild(QLineEdit, "suspend_y_value")
                if suspend_x_display:
                    suspend_x_display.setText(str(x))
                if suspend_y_display:
                    suspend_y_display.setText(str(y))
                self._show_action_status(f"挂起位置已保存：水平={x}，竖直={y}")
        except ValueError:
            self._show_action_status("挂起位置保存失败：当前位置无效", is_error=True)
            logger.warning("无效的位置数据，无法保存")
