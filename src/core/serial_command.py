# -*- coding: utf-8 -*-
"""
串口命令管理器 - 优化版本
定义一批串口发送功能指令，并调用serial_manager中的发送功能
"""
import time
from contextlib import contextmanager
from enum import Enum
from typing import Optional, TYPE_CHECKING

from PyQt5.QtCore import QObject, QTimer

from .logger import get_logger
from .config_manager import get_config_manager

if TYPE_CHECKING:
    from thread_manager import ThreadManager

logger = get_logger('SerialCommand')

# 常量定义
MOVE_WAIT_TIME = 2  # 移动后等待时间（秒）


class WorkState(Enum):
    """工作状态枚举"""
    IDLE = "idle"                    # 空闲状态
    SELF_DETECTING = "self_detecting"  # 自检中
    WAITING_POSITION = "waiting_position"  # 等待位置数据（自检完成后查询位置）


class SerialCommand(QObject):
    """串口命令管理器"""

    def __init__(self, thread_manager: 'ThreadManager'):
        super().__init__()
        self.thread_manager = thread_manager
        self.serial_manager = thread_manager.serial_manager
        self.data_process = thread_manager.data_process
        self.config = get_config_manager()

        # 位置查询定时器
        self.position_query_timer: Optional[QTimer] = None
        self.position_query_enabled = False

        # 命令锁 - 用于独占串口通信
        self._command_lock = False

        # 工作状态
        self._work_state = WorkState.IDLE

        # 待执行的反向移动任务（自检完成后需要反向移动）
        self._pending_retract_axis: Optional[str] = None

        # 待执行的方向键移动任务 (axis, direction, distance)
        # axis: 'X' 或 'Z', direction: +1 或 -1, distance: 脉冲值
        self._pending_move_task: Optional[tuple] = None

        # 偏置校准标志
        self._offset_calibrating = False

        # 位置查询重试计数（用于自检后反向移动）
        self._position_query_retry_count = 0
        self._max_position_query_retries = 3

        logger.debug("SerialCommand 初始化完成")

    @contextmanager
    def command_lock(self):
        """
        串口命令锁上下文管理器
        确保命令执行期间位置查询不会打断串口通信
        """
        self._command_lock = True
        # 停止位置查询定时器
        if self.position_query_enabled:
            self.disable_position_query_timer()
            logger.debug("命令锁：已停止位置查询定时器")
        try:
            yield
        finally:
            self._command_lock = False
            # 恢复位置查询（如果有窗口在显示）
            if hasattr(self.thread_manager, 'position_window'):
                pw = self.thread_manager.position_window
                if pw and pw.isVisible():
                    self.enable_position_query_timer()
                    logger.debug("命令锁：已恢复位置查询定时器")
            logger.debug("命令锁：已释放")

    def send_data(self, data: str) -> bool:
        """发送数据到串口"""
        # 检查命令锁 - 如果被锁定，跳过位置查询命令
        if self._command_lock and data.startswith("?XZ"):
            return False

        if not self.serial_manager:
            logger.error("串口管理器未设置")
            return False

        if not self.serial_manager.get_connection_status():
            logger.warning("串口未连接")
            return False

        try:
            self.thread_manager.write_queue.put(data)
            logger.debug(f"SerialCommand: 数据已放入写队列: {data}")
            return True
        except Exception as e:
            logger.error(f"发送数据失败: {e}")
            return False

    def enable_position_query_timer(self, interval: int = 500) -> None:
        """启用位置查询定时器"""
        if not self.position_query_timer:
            self.position_query_timer = QTimer()
            self.position_query_timer.timeout.connect(self._position_query_from_timer)

        self.position_query_timer.setInterval(interval)
        self.position_query_timer.start()
        self.position_query_enabled = True
        logger.debug(f"位置查询定时器已启用，间隔: {interval}ms")

    def disable_position_query_timer(self) -> None:
        """禁用位置查询定时器"""
        if self.position_query_timer and self.position_query_timer.isActive():
            self.position_query_timer.stop()
            self.position_query_enabled = False
            logger.debug("位置查询定时器已禁用")

    def _position_query_from_timer(self) -> None:
        """定时器触发的位置查询"""
        # 检查是否正在偏置校准中
        if self._offset_calibrating:
            return

        # 如果有待处理的反向移动任务，检查自检完成信号
        if self._pending_retract_axis:
            self.data_process.signal_self_detect_process.emit()
            return

        # 正常的位置查询
        self.position_query()

    # 串口命令
    def claw_rotate(self) -> None:
        """发送爪盘旋转命令"""
        round = 542720
        self.send_data(f"B{round*1.5}~")

    def claw_stop(self) -> None:
        """发送爪盘停止命令"""
        with self.command_lock():
            self.send_data("S~")

    def vertical_move(self, distance: int) -> None:
        """发送垂直移动命令（Z轴相对脉冲移动）"""
        with self.command_lock():
            command = f"N{distance}~"
            self.send_data(command)

    def auto_press(self) -> None:
        """发送自动下压命令（Z轴）"""
        self._pending_retract_axis = 'Z'
        self._position_query_retry_count = 0
        logger.info("开始Z轴自检")
        # 清空队列，避免之前的位置数据干扰自检流程
        self.data_process.clear_data_queue()
        with self.command_lock():
            self.send_data("P~")

    def auto_press_left(self) -> None:
        """发送向左贴靠命令（X轴）"""
        self._pending_retract_axis = 'X'
        self._position_query_retry_count = 0
        logger.info("开始X轴自检")
        # 清空队列，避免之前的位置数据干扰自检流程
        self.data_process.clear_data_queue()
        with self.command_lock():
            self.send_data("Y~")

    def _on_self_detect_finished(self, axis: str) -> None:
        """
        自检完成回调 - 检查是否有待处理的任务，有则触发位置查询

        Args:
            axis: 轴类型，'X' 或 'Z'
        """
        logger.info(f"_on_self_detect_finished: 收到 {axis} 轴自检完成信号, _command_lock={self._command_lock}, _pending_retract_axis={self._pending_retract_axis}")
        # 检查是否有待处理的反向移动任务
        if self._pending_retract_axis:
            logger.info(f"检测到 {axis} 轴自检完成，触发位置查询")
            # 立即触发位置查询
            self.position_query()
        else:
            logger.warning(f"没有待处理的反向移动任务，忽略")

    def _on_position_data_processed(self, position_data: tuple) -> None:
        """
        位置数据处理完成回调 - 检查并执行待处理的任务

        Args:
            position_data: 位置数据 (x, z)
        """
        logger.info(f"位置数据处理完成回调: X={position_data[0]}, Z={position_data[1]}, pending_move_task={self._pending_move_task}")
        # 1. 优先处理自检反向移动任务
        if self._pending_retract_axis:
            # 检查位置数据有效性
            if position_data[0] is None or position_data[1] is None:
                self._position_query_retry_count += 1
                if self._position_query_retry_count >= self._max_position_query_retries:
                    logger.error(f"位置数据无效，已达最大重试次数({self._max_position_query_retries})，放弃反向移动")
                    self._pending_retract_axis = None
                    self._position_query_retry_count = 0
                else:
                    logger.warning(f"位置数据无效，重新查询位置 ({self._position_query_retry_count}/{self._max_position_query_retries}): {position_data}")
                    self.position_query()
            else:
                self._position_query_retry_count = 0
                self._execute_retract(position_data)
        # 2. 处理方向键移动任务
        elif self._pending_move_task:
            self._execute_move_task(position_data)

    def _execute_retract(self, position_data: tuple) -> None:
        """执行反向移动"""
        axis = self._pending_retract_axis
        if not axis:
            return

        self._pending_retract_axis = None

        # 反向移动距离（mm）
        RETRACT_MM = 0.6
        # Z轴换算公式：1000脉冲 = 0.62mm，即 1mm = 1000/0.62 ≈ 1612.9脉冲
        # X轴换算公式：10000脉冲 = 25mm，即 1mm = 400脉冲
        if axis == 'X':
            retract_pulse = int(RETRACT_MM * 400)
        elif axis == 'Z':
            retract_pulse = int(RETRACT_MM * 1000 / 0.62)
        else:
            return

        with self.command_lock():
            if axis == 'X':
                current_x = int(position_data[0])
                target_x = current_x - retract_pulse
                logger.info(f"执行X轴反向移动: X={current_x} -> {target_x}, 脉冲={retract_pulse}")
                self.move_x(target_x)
            elif axis == 'Z':
                current_z = int(position_data[1])
                target_z = current_z - retract_pulse
                logger.info(f"执行Z轴反向移动: Z={current_z} -> {target_z}, 脉冲={retract_pulse}")
                self.move_z(target_z)

    def _execute_move_task(self, position_data: tuple) -> None:
        """执行方向键移动任务"""
        axis, direction, distance_mm = self._pending_move_task
        if not axis:
            return

        # 检查位置数据有效性
        if position_data[0] is None or position_data[1] is None:
            logger.warning(f"位置数据无效，跳过移动任务: {position_data}")
            self._pending_move_task = None
            return

        self._pending_move_task = None

        # Z轴换算公式：1000脉冲 = 0.62mm，即 1mm = 1000/0.62 ≈ 1612.9脉冲
        # X轴换算公式：10000脉冲 = 25mm，即 1mm = 400脉冲
        if axis == 'Z':
            distance_pulse = int(distance_mm * 1000 / 0.62)
        elif axis == 'X':
            distance_pulse = int(distance_mm * 400)
        else:
            logger.error(f"未知轴类型: {axis}")
            return

        with self.command_lock():
            if axis == 'X':
                current_x = int(position_data[0])
                target_x = current_x + direction * distance_pulse
                logger.debug(f"执行X轴移动: X={current_x} -> {target_x}，移动距离={distance_mm}mm={distance_pulse}脉冲")
                self.move_x(target_x)
            elif axis == 'Z':
                current_z = int(position_data[1])
                target_z = current_z + direction * distance_pulse
                logger.debug(f"执行Z轴移动: Z={current_z} -> {target_z}，移动距离={distance_mm}mm={distance_pulse}脉冲")
                self.move_z(target_z)

    def set_move_task(self, axis: str, direction: int, distance_mm: float) -> None:
        """
        设置方向键移动任务（measure_window.py调用）

        Args:
            axis: 'X' 或 'Z'
            direction: +1 或 -1（移动方向）
            distance_mm: 距离值（mm）
        """
        self._pending_move_task = (axis, direction, distance_mm)
        logger.debug(f"设置移动任务: axis={axis}, direction={direction}, distance={distance_mm}mm")

    def position_query(self) -> None:
        """发送位置查询命令"""
        logger.debug(f"position_query: 开始执行, _command_lock={self._command_lock}, _offset_calibrating={self._offset_calibrating}")
        # 偏置校准期间不发送位置查询
        if self._offset_calibrating:
            logger.debug("position_query: 偏置校准中，跳过")
            return
        result = self.send_data("?XZ~")
        logger.debug(f"position_query: send_data结果={result}")
        if result:
            self.data_process.signal_position_data_process.emit()

    def counter_measurer(self) -> None:
        """发送计数器测量命令"""
        # 清空队列，确保之前的数据不会干扰
        self.data_process.clear_data_queue()
        command = "K3~" # 3秒测量
        self.send_data(command)
        time.sleep(0.1)  # 确保命令发送后再处理数据
        self.data_process.signal_offset_data_process.emit()

    def slider_reset(self) -> None:
        """发送滑台复位命令"""
        self.send_data("I~")

    def move_x(self, position: int) -> bool:
        """发送X轴移动命令"""
        return self.send_data(f"X{position}~")

    def move_z(self, position: int) -> bool:
        """发送Z轴移动命令"""
        return self.send_data(f"Z{position}~")

    def suspend_position(self, position_window_ref=None) -> None:
        """挂起操作 - 移动到保存的挂起位置坐标"""
        logger.info("执行挂起操作")

        with self.command_lock():
            target_x = self.config.suspend_x
            target_z = self.config.suspend_z
            logger.info(f"移动到挂起位置: X={target_x}, Z={target_z}")

            self.move_z(target_z)
            time.sleep(MOVE_WAIT_TIME)
            self.move_x(target_x)

    def test_position(self) -> None:
        """测试位置 - 移动到保存的测试位置坐标"""
        logger.info("执行测试位置操作")

        with self.command_lock():
            target_x = self.config.test_x
            target_z = self.config.test_z
            logger.info(f"移动到测试位置: X={target_x}, Z={target_z}")

            self.move_x(target_x)
            time.sleep(MOVE_WAIT_TIME)
            self.move_z(target_z)

    def offset_calibration(self, position_window_ref=None) -> None:
        """偏置校准"""
        logger.info("=== 开始执行偏置校准 ===")
        # 设置偏置校准标志
        self._offset_calibrating = True
        self.counter_measurer()

    def _on_offset_calibration_finished(self, success: bool) -> None:
        """
        偏置校准完成回调 - 清除偏置校准标志

        Args:
            success: 校准是否成功
        """
        self._offset_calibrating = False
