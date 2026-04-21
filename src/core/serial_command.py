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
MOVE_WAIT_TIME = 5  # 移动后等待时间（秒）
POSITION_TOLERANCE = 5  # 到位判定容差（脉冲数）
WAIT_POLL_INTERVAL = 0.1  # 到位检测轮询间隔（秒）


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

        # 自检完成标志（只有收到finish消息后才为True）
        self._self_detect_completed: bool = False

        # 待执行的方向键移动任务 (axis, direction, distance)
        # axis: 'X' 或 'Z', direction: +1 或 -1, distance: 脉冲值
        self._pending_move_task: Optional[tuple] = None

        # 偏置校准标志
        self._offset_calibrating = False

        # 测量状态标志
        self._is_measuring = False

        # 当前实时位置（用于到位检测）
        self._current_x: Optional[int] = None
        self._current_z: Optional[int] = None

        # 临时允许位置查询（等待到位期间）
        self._allow_position_query = False

        # 位置查询重试计数（用于自检后反向移动）
        self._position_query_retry_count = 0
        self._max_position_query_retries = 3

        logger.info("SerialCommand 初始化完成")

    @contextmanager
    def command_lock(self, allow_position_query: bool = False):
        """
        串口命令锁上下文管理器
        确保命令执行期间位置查询不会打断串口通信

        Args:
            allow_position_query: 等待到位期间是否允许位置查询（临时解锁）
        """
        self._command_lock = True
        self._allow_position_query = allow_position_query
        # 停止位置查询定时器
        if self.position_query_enabled:
            self.disable_position_query_timer()
        try:
            yield
        finally:
            self._command_lock = False
            self._allow_position_query = False
            # 恢复位置查询（如果有窗口在显示）
            if hasattr(self.thread_manager, 'position_window'):
                pw = self.thread_manager.position_window
                if pw and pw.isVisible():
                    self.enable_position_query_timer()

    def send_data(self, data: str) -> bool:
        """发送数据到串口"""
        # 检查命令锁 - 如果被锁定且未临时允许，跳过位置查询命令
        if self._command_lock and data.startswith("?XZ") and not self._allow_position_query:
            return False

        if not self.serial_manager:
            logger.error("串口管理器未设置")
            return False

        if not self.serial_manager.get_connection_status():
            logger.warning("串口未连接")
            return False

        try:
            self.thread_manager.write_queue.put(data)
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

    def disable_position_query_timer(self) -> None:
        """禁用位置查询定时器"""
        if self.position_query_timer and self.position_query_timer.isActive():
            self.position_query_timer.stop()
            self.position_query_enabled = False

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

    def _wait_position_reached(self, axis: str, target: int, timeout: float = 10.0) -> bool:
        """
        等待指定轴到达目标位置

        Args:
            axis: 'X' 或 'Z'
            target: 目标脉冲值
            timeout: 超时时间（秒）

        Returns:
            是否成功到达目标位置
        """
        from PyQt5.QtCore import QCoreApplication
        logger.info(f"等待{axis}轴到位: 目标={target}, 超时={timeout}s")

        # 设置临时标志，表示正在等待位置到达
        previous_lock_state = self._command_lock
        previous_allow_query = self._allow_position_query
        self._command_lock = True
        self._allow_position_query = True

        try:
            start_time = time.time()

            while time.time() - start_time < timeout:
                # 直接写入队列，不走 send_data（避免命令锁检查）
                try:
                    self.thread_manager.write_queue.put("?XZ~")
                except Exception as e:
                    logger.warning(f"发送位置查询失败: {e}")

                # 触发数据处理
                self.data_process.signal_position_data_process.emit()

                # 等待数据处理完成
                time.sleep(0.15)

                # 处理 Qt 事件
                for _ in range(5):
                    QCoreApplication.processEvents()
                    time.sleep(0.01)

                # 检查位置
                current = self._current_x if axis == 'X' else self._current_z
                if current is not None:
                    diff = abs(current - target)
                    if diff <= POSITION_TOLERANCE:
                        logger.info(f"{axis}轴到位: 当前值={current}, 目标={target}, 差值={diff}")
                        return True

                # 轮询间隔
                time.sleep(0.05)

        finally:
            # 恢复之前的锁状态
            self._command_lock = previous_lock_state
            self._allow_position_query = previous_allow_query

        logger.warning(f"{axis}轴移动到{target}超时! 最后位置={self._current_x if axis == 'X' else self._current_z}")
        return False
    def claw_rotate(self) -> None:
        """发送爪盘旋转命令"""
        round = 542720
        self.send_data(f"B{int(round * 1.5)}~")

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
        self._self_detect_completed = False
        self._position_query_retry_count = 0
        logger.info("开始Z轴自检")
        # 清空队列，避免之前的位置数据干扰自检流程
        self.data_process.clear_data_queue()
        # 使用command_lock阻止位置查询干扰，allow_position_query允许信号触发check_self_detect
        with self.command_lock(allow_position_query=True):
            self.send_data("P~")
            # 轮询等待自检完成（期间位置查询被阻止）
            self._wait_self_detect_finished('Z')

    def auto_press_left(self) -> None:
        """发送向左贴靠命令（X轴）"""
        self._pending_retract_axis = 'X'
        self._self_detect_completed = False
        self._position_query_retry_count = 0
        logger.info("开始X轴自检")
        # 清空队列，避免之前的位置数据干扰自检流程
        self.data_process.clear_data_queue()
        with self.command_lock(allow_position_query=True):
            self.send_data("Y~")
            self._wait_self_detect_finished('X')

    def auto_press_right(self) -> None:
        """发送向右贴靠命令（X轴）"""
        self._pending_retract_axis = 'X-'
        self._self_detect_completed = False
        self._position_query_retry_count = 0
        logger.info("开始X轴反向自检")
        # 清空队列，避免之前的位置数据干扰自检流程
        self.data_process.clear_data_queue()
        with self.command_lock(allow_position_query=True):
            self.send_data("Y-~")
            self._wait_self_detect_finished('X')

    def _wait_self_detect_finished(self, axis: str, timeout: float = 10.0) -> bool:
        """轮询等待自检完成"""
        from PyQt5.QtCore import QCoreApplication
        import time
        poll_count = 0
        logger.info(f"开始轮询等待 {axis} 轴自检完成, 超时={timeout}s")
        start_time = time.time()
        while time.time() - start_time < timeout:
            poll_count += 1
            # 处理Qt事件，让readyRead信号可以触发
            QCoreApplication.processEvents()
            time.sleep(0.05)
            QCoreApplication.processEvents()
            if self.data_process.check_self_detect():
                elapsed = time.time() - start_time
                logger.info(f"{axis} 轴自检完成, 耗时={elapsed:.3f}s")
                self._self_detect_completed = True
                return True
        elapsed = time.time() - start_time
        logger.warning(f"{axis} 轴自检完成超时! 耗时={elapsed:.3f}s")
        # 超时后清除待执行任务标志，避免残留触发反向运动
        self._pending_retract_axis = None
        return False

    def _on_self_detect_finished(self, _axis: str) -> None:
        """
        自检完成回调 - 检查是否有待处理的任务，有则触发位置查询

        Args:
            _axis: 轴类型，'X' 或 'Z' (未使用)
        """
        # 检查是否有待处理的反向移动任务
        if self._pending_retract_axis:
            self.position_query()
        else:
            logger.debug(f"没有待处理的反向移动任务")

    def _on_position_data_processed(self, position_data: tuple) -> None:
        """
        位置数据处理完成回调 - 检查并执行待处理的任务

        Args:
            position_data: 位置数据 (x, z)
        """
        # 更新当前实时位置（用于到位检测）
        if position_data[0] is not None:
            self._current_x = int(position_data[0])
        if position_data[1] is not None:
            self._current_z = int(position_data[1])
        # 1. 优先处理自检反向移动任务
        if self._pending_retract_axis:
            # 必须等自检完成消息才能执行反向运动
            if not self._self_detect_completed:
                return
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
        RETRACT_MM = 0.3
        # Z轴换算公式：1000脉冲 = 0.62mm，即 1mm = 1000/0.62 ≈ 1612.9脉冲
        # X轴换算公式：10000脉冲 = 25mm，即 1mm = 400脉冲
        if axis == 'X':
            retract_pulse = int(RETRACT_MM * 400)
        elif axis == 'X-':
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
            elif axis == 'X-':
                current_x = int(position_data[0])
                target_x = current_x + retract_pulse
                logger.info(f"执行X轴正向移动: X={current_x} -> {target_x}, 脉冲={retract_pulse}")
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
                logger.info(f"X轴移动: {current_x} -> {target_x}")
                self.move_x(target_x)
            elif axis == 'Z':
                current_z = int(position_data[1])
                target_z = current_z + direction * distance_pulse
                logger.info(f"Z轴移动: {current_z} -> {target_z}")
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

    def position_query(self) -> None:
        """发送位置查询命令"""
        if self._offset_calibrating:
            return
        if self.send_data("?XZ~"):
            self.data_process.signal_position_data_process.emit()

    def counter_measurer(self) -> None:
        """发送计数器测量命令"""
        logger.info("=" * 60)
        logger.info(f"counter_measurer: [{time.time():.3f}] 开始执行")
        # 清空队列，确保之前的数据不会干扰
        self.data_process.clear_data_queue()
        logger.info(f"counter_measurer: [{time.time():.3f}] 队列已清空")
        command = "K3~" # 3秒测量
        result = self.send_data(command)
        logger.info(f"counter_measurer: [{time.time():.3f}] 发送命令 {command}, 结果={result}")
        # 等待0.2秒让任何正在等待的process_position_data完成超时退出
        # 使用QTimer.singleShot避免阻塞Qt事件循环
        logger.info(f"counter_measurer: [{time.time():.3f}] 延迟0.2秒后触发数据处理信号")
        QTimer.singleShot(200, self._emit_offset_process_signal)

    def _emit_offset_process_signal(self) -> None:
        """延迟发射偏置处理信号"""
        logger.info(f"counter_measurer: [{time.time():.3f}] 触发数据处理信号，当前队列大小={self.data_process.data_queue.qsize()}")
        self.data_process.signal_offset_data_process.emit()
        logger.info(f"counter_measurer: [{time.time():.3f}] 完成，等待处理完成信号...")

    def slider_reset(self) -> None:
        """发送滑台复位命令"""
        self.send_data("I~")

    def move_x(self, position: int) -> bool:
        """发送X轴移动命令"""
        return self.send_data(f"X{position}~")

    def move_z(self, position: int) -> bool:
        """发送Z轴移动命令"""
        return self.send_data(f"Z{position}~")

    def execute_movement_scheme(self, steps: list, target_x: int, target_z: int) -> bool:
        """
        执行自定义移动方案

        Args:
            steps: 动作步骤列表，如 ["X", "Z"] 或 ["X", "X+", "Z", "X"]
            target_x: X轴目标位置
            target_z: Z轴目标位置

        Returns:
            bool: 是否全部执行成功
        """
        x_offset_pulse = self.config.get_inner_x_offset_pulse()
        z_offset_pulse = self.config.get_inner_z_offset_pulse()

        for step in steps:
            if step == 'X':
                self.move_x(target_x)
                if not self._wait_position_reached('X', target_x):
                    logger.warning(f"X轴移动到{target_x}超时")
                    return False
            elif step == 'Z':
                self.move_z(target_z)
                if not self._wait_position_reached('Z', target_z):
                    logger.warning(f"Z轴移动到{target_z}超时")
                    return False
            elif step == 'X+':
                # X正偏移 = 当前X + 偏移量
                current_x = self._current_x if self._current_x is not None else target_x
                target = current_x + x_offset_pulse
                self.move_x(target)
                if not self._wait_position_reached('X', target):
                    logger.warning(f"X轴正偏移({self.config.inner_x_offset}mm)移动到{target}超时")
                    return False
            elif step == 'X-':
                # X负偏移 = 当前X - 偏移量
                current_x = self._current_x if self._current_x is not None else target_x
                target = current_x - x_offset_pulse
                self.move_x(target)
                if not self._wait_position_reached('X', target):
                    logger.warning(f"X轴负偏移({self.config.inner_x_offset}mm)移动到{target}超时")
                    return False
            elif step == 'Z+':
                # Z正偏移
                current_z = self._current_z if self._current_z is not None else target_z
                target = current_z + z_offset_pulse
                self.move_z(target)
                if not self._wait_position_reached('Z', target):
                    logger.warning(f"Z轴正偏移({self.config.inner_z_offset}mm)移动到{target}超时")
                    return False
            elif step == 'Z-':
                # Z负偏移
                current_z = self._current_z if self._current_z is not None else target_z
                target = current_z - z_offset_pulse
                self.move_z(target)
                if not self._wait_position_reached('Z', target):
                    logger.warning(f"Z轴负偏移({self.config.inner_z_offset}mm)移动到{target}超时")
                    return False
        return True

    def suspend_position(self) -> None:
        """挂起操作 - 移动到保存的挂起位置坐标"""
        logger.info("执行挂起操作")

        with self.command_lock():
            test_type = self.config.test_type
            scheme = self.config.get_active_suspend_scheme(test_type)
            target_x = self.config.suspend_x
            target_z = self.config.suspend_z
            logger.info(f"移动到挂起位置: X={target_x}, Z={target_z}, 步骤={scheme['steps']}")

            success = self.execute_movement_scheme(scheme['steps'], target_x, target_z)
            if not success:
                logger.warning("挂起位置移动未全部完成")

    def test_position(self) -> None:
        """测试位置 - 移动到保存的测试位置坐标"""
        logger.info("执行测试位置操作")

        with self.command_lock():
            test_type = self.config.test_type
            scheme = self.config.get_active_test_scheme(test_type)
            target_x = self.config.test_x
            target_z = self.config.test_z
            logger.info(f"移动到测试位置: X={target_x}, Z={target_z}, 步骤={scheme['steps']}")

            success = self.execute_movement_scheme(scheme['steps'], target_x, target_z)
            if not success:
                logger.warning("测试位置移动未全部完成")

    def offset_calibration(self) -> None:
        """偏置校准"""
        logger.info("=== 开始执行偏置校准 ===")
        # 设置偏置校准标志（both serial_command and data_process）
        self._offset_calibrating = True
        self.data_process._offset_calibrating = True
        self.counter_measurer()

    def _on_offset_calibration_finished(self, success: bool) -> None:
        """
        偏置校准完成回调 - 清除偏置校准标志

        Args:
            success: 校准是否成功
        """
        self._offset_calibrating = False
        self.data_process._offset_calibrating = False
