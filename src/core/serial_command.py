# -*- coding: utf-8 -*-
"""
Serial command coordination.
"""

import time
from contextlib import contextmanager
from enum import Enum
from typing import Callable, Optional, TYPE_CHECKING

from PyQt5.QtCore import QObject, QTimer

from .config_manager import (
    X_AXIS_PULSES_PER_MM,
    Z_AXIS_PULSES_PER_MM,
    get_config_manager,
)
from .logger import get_logger

if TYPE_CHECKING:
    from .thread_manager import ThreadManager


logger = get_logger("SerialCommand")

MOTION_DONE_TIMEOUT_MS = 5000
MOTION_DONE_POLL_INTERVAL_MS = 80
POSITION_WAIT_TIMEOUT_MS = 60000  # 单步最长等待 60s
MAX_RELATIVE_STEPS = 500000  # 固件单次最大相对步数
MAX_TIMEOUT_RESTARTS = 3      # 超时后若电机已启动(收到START)，最多重新计时次数


class WorkState(Enum):
    IDLE = "idle"
    WAITING_POSITION = "waiting_position"


class SerialCommand(QObject):
    def __init__(self, thread_manager: "ThreadManager"):
        super().__init__()
        self.thread_manager = thread_manager
        self.serial_manager = thread_manager.serial_manager
        self.data_process = thread_manager.data_process
        self.config = get_config_manager()

        self.position_query_timer: Optional[QTimer] = None
        self.position_query_enabled = False

        self._command_lock = False
        self._allow_position_query = False
        self._work_state = WorkState.IDLE

        self._pending_move_task: Optional[tuple] = None

        self._offset_calibrating = False
        self._is_measuring = False

        self._current_x: Optional[int] = None
        self._current_y: Optional[int] = None
        self._current_z: Optional[int] = None

        self._position_query_retry_count = 0
        self._max_position_query_retries = 3
        self._position_query_in_flight = False

        self._movement_sequence: Optional[dict] = None
        self._active_position_wait: Optional[dict] = None
        self._async_command_lock_state: Optional[dict] = None
        self._tx_sequence = 0

        self._pending_deltas: dict = {}  # 记录各轴本次移动的 delta，DONE 时用于更新位置缓存

        self._setup_async_timers()
        logger.info("SerialCommand initialized.")

    @contextmanager
    def command_lock(self, allow_position_query: bool = False):
        previous_lock = self._command_lock
        previous_allow = self._allow_position_query
        timer_was_active = bool(self.position_query_timer and self.position_query_timer.isActive())
        timer_interval = self.position_query_timer.interval() if timer_was_active else 500

        self._command_lock = True
        self._allow_position_query = previous_allow or allow_position_query
        if timer_was_active:
            self.disable_position_query_timer()

        try:
            yield
        finally:
            self._command_lock = previous_lock
            self._allow_position_query = previous_allow
            if timer_was_active and not previous_lock and not self._offset_calibrating and not self._is_measuring:
                self.enable_position_query_timer(timer_interval)

    def _setup_async_timers(self) -> None:
        self._position_wait_poll_timer = QTimer(self)
        self._position_wait_poll_timer.setInterval(MOTION_DONE_POLL_INTERVAL_MS)
        self._position_wait_poll_timer.timeout.connect(self._poll_motion_done)

        self._position_wait_timeout_timer = QTimer(self)
        self._position_wait_timeout_timer.setSingleShot(True)
        self._position_wait_timeout_timer.timeout.connect(self._on_position_wait_timeout)

    def _begin_async_command_lock(self, allow_position_query: bool = False) -> None:
        if self._async_command_lock_state is not None:
            self._command_lock = True
            self._allow_position_query = self._allow_position_query or allow_position_query
            return

        timer_was_active = bool(self.position_query_timer and self.position_query_timer.isActive())
        timer_interval = self.position_query_timer.interval() if timer_was_active else 500
        self._async_command_lock_state = {
            "command_lock": self._command_lock,
            "allow_position_query": self._allow_position_query,
            "timer_was_active": timer_was_active,
            "timer_interval": timer_interval,
        }

        if timer_was_active:
            self.disable_position_query_timer()

        self._command_lock = True
        self._allow_position_query = allow_position_query

    def _end_async_command_lock(self) -> None:
        if self._async_command_lock_state is None:
            return

        previous_state = self._async_command_lock_state
        self._async_command_lock_state = None
        self._command_lock = previous_state["command_lock"]
        self._allow_position_query = previous_state["allow_position_query"]

        if (
            previous_state["timer_was_active"]
            and not self._offset_calibrating
            and not self._is_measuring
        ):
            self.enable_position_query_timer(previous_state["timer_interval"])

    def _can_start_async_operation(self, operation_name: str) -> bool:
        if (
            self._movement_sequence
            or self._active_position_wait
            or self._command_lock
        ):
            logger.warning(
                f"{operation_name} skipped: another serial operation is running. "
                f"state={self._work_state.value}, command_lock={self._command_lock}, "
                f"movement={bool(self._movement_sequence)}, "
                f"active_position_wait={bool(self._active_position_wait)}, "
                f"write_queue_size={self.thread_manager.write_queue.qsize()}"
            )
            return False
        return True

    def _drop_pending_position_query_writes(self, reason: str) -> int:
        if not self.serial_manager or not hasattr(self.serial_manager, "drop_pending_writes"):
            return 0
        return self.serial_manager.drop_pending_writes("?XZ", reason=reason)

    def _clear_position_wait(self) -> Optional[dict]:
        self._position_wait_poll_timer.stop()
        self._position_wait_timeout_timer.stop()
        wait_state = self._active_position_wait
        self._active_position_wait = None
        return wait_state

    @staticmethod
    def _get_axis_pulses_per_mm(axis: str) -> float:
        if axis in ("X", "Y"):
            return X_AXIS_PULSES_PER_MM
        if axis == "Z":
            return Z_AXIS_PULSES_PER_MM
        return X_AXIS_PULSES_PER_MM

    def _get_position_tolerance_pulse(self, axis: str) -> int:
        pulses_per_mm = self._get_axis_pulses_per_mm(axis)
        return max(5, int(round(POSITION_TOLERANCE_MM * pulses_per_mm)))

    def _start_position_wait(
        self,
        axis: str,
        target: int,
        delta: int,
        callback: Callable[[bool], None],
        timeout_ms: int = POSITION_WAIT_TIMEOUT_MS,
    ) -> None:
        self._active_position_wait = {
            "axis": axis,
            "target": target,
            "delta": delta,
            "callback": callback,
            "timeout_ms": timeout_ms,
            "done_received": False,
            "start_received": False,
            "restart_count": 0,
        }
        self._work_state = WorkState.WAITING_POSITION
        logger.info(
            f"Start DONE-based wait for {axis} axis: delta={delta:+d}, target={target}, timeout_ms={timeout_ms}"
        )
        self._position_wait_timeout_timer.start(timeout_ms)
        self._position_wait_poll_timer.start()

    def _poll_motion_done(self) -> None:
        """Poll for X/Y/Z DONE/START feedback from serial data queue."""
        if not self._active_position_wait:
            return
        result = self.data_process.check_motion_feedback()
        if not result:
            return
        axis, event = result
        if event == "DONE":
            self._on_motion_done_detected(axis)
        elif event == "START":
            if axis == self._active_position_wait["axis"] and not self._active_position_wait["start_received"]:
                self._active_position_wait["start_received"] = True
                logger.info(
                    f"{axis} START received, motor confirmed running — timeout will auto-extend if needed"
                )

    def _on_motion_done_detected(self, axis: str) -> None:
        if not self._active_position_wait:
            return
        if self._active_position_wait["axis"] != axis:
            logger.debug(f"Ignore DONE for {axis}, waiting for {self._active_position_wait['axis']}")
            return

        wait_state = self._clear_position_wait()
        self._work_state = WorkState.IDLE
        delta = wait_state["delta"]
        self._apply_delta(axis, delta)
        logger.info(f"{axis} DONE received, delta={delta:+d}, new position={self._get_current(axis)}")
        wait_state["callback"](True)

    def _on_position_wait_timeout(self) -> None:
        wait_state = self._active_position_wait
        if not wait_state:
            return

        # 超时前最后检查一次 DONE
        result = self.data_process.check_motion_feedback()
        if result:
            axis, event = result
            if axis == wait_state["axis"]:
                if event == "DONE":
                    self._on_motion_done_detected(axis)
                    return
                elif event == "START" and not wait_state["start_received"]:
                    wait_state["start_received"] = True
                    logger.info(f"{axis} START received at timeout check, motor is running")

        axis = wait_state["axis"]
        start_received = wait_state["start_received"]
        restart_count = wait_state.get("restart_count", 0)

        # 如果电机已确认启动(收到START)，说明正在运动中，重新计时而非判定失败
        if start_received and restart_count < MAX_TIMEOUT_RESTARTS:
            wait_state["restart_count"] = restart_count + 1
            total_wait = (restart_count + 1) * POSITION_WAIT_TIMEOUT_MS / 1000.0
            logger.info(
                f"{axis} 运动超时但电机已启动(START已收到)，第{restart_count + 1}次重新计时 "
                f"(已等待约{total_wait:.0f}s, 剩余重试{MAX_TIMEOUT_RESTARTS - restart_count - 1}次)"
            )
            self._position_wait_timeout_timer.start(POSITION_WAIT_TIMEOUT_MS)
            return

        # 电机从未启动 或 重试次数耗尽 → 判定失败
        delta = wait_state.get("delta")
        target = wait_state.get("target")
        wait_state = self._clear_position_wait()
        self._work_state = WorkState.IDLE
        if start_received:
            logger.warning(
                f"{axis} DONE wait exhausted after {MAX_TIMEOUT_RESTARTS + 1} cycles "
                f"({(MAX_TIMEOUT_RESTARTS + 1) * POSITION_WAIT_TIMEOUT_MS / 1000:.0f}s total). "
                f"Motor started but DONE never received. "
                f"delta={delta}, target={target}, "
                f"cached_pos=({self._current_x},{self._current_y},{self._current_z})"
            )
        else:
            logger.warning(
                f"{axis} DONE wait timeout ({POSITION_WAIT_TIMEOUT_MS}ms), motor never acknowledged (no START). "
                f"delta={delta}, target={target}, "
                f"cached_pos=({self._current_x},{self._current_y},{self._current_z}), "
                f"queue_size={self.data_process.data_queue.qsize()}"
            )
        wait_state["callback"](False)

    def _get_current(self, axis: str) -> Optional[int]:
        if axis == "X":
            return self._current_x
        if axis == "Y":
            return self._current_y
        if axis == "Z":
            return self._current_z
        return None

    def _apply_delta(self, axis: str, delta: int) -> None:
        """Apply a movement delta to the cached position."""
        if axis == "X" and self._current_x is not None:
            self._current_x += delta
        elif axis == "Y" and self._current_y is not None:
            self._current_y += delta
        elif axis == "Z" and self._current_z is not None:
            self._current_z += delta

    def _resolve_step_target(self, step: str, target_x: int, target_z: int) -> Optional[tuple]:
        x_offset_pulse = self.config.get_inner_x_offset_pulse()
        z_offset_pulse = self.config.get_inner_z_offset_pulse()

        if step == "X":
            return "X", target_x
        if step == "Z":
            return "Y", target_z           # 竖直方向 → Y 轴
        if step == "X+":
            current_x = self._current_x if self._current_x is not None else target_x
            return "X", current_x + x_offset_pulse
        if step == "X-":
            current_x = self._current_x if self._current_x is not None else target_x
            return "X", current_x - x_offset_pulse
        if step == "Z+":
            current_y = self._current_y if self._current_y is not None else target_z
            return "Y", current_y + z_offset_pulse  # 竖直偏移 → Y 轴
        if step == "Z-":
            current_y = self._current_y if self._current_y is not None else target_z
            return "Y", current_y - z_offset_pulse  # 竖直偏移 → Y 轴
        return None

    def _finish_movement_sequence(self, success: bool) -> None:
        sequence = self._movement_sequence
        self._movement_sequence = None
        self._clear_position_wait()
        self._end_async_command_lock()
        self._work_state = WorkState.IDLE

        if sequence and success:
            logger.info(f"{sequence['name']} completed.")
        elif sequence:
            logger.warning(f"{sequence['name']} stopped before completion.")

    def _on_movement_step_finished(self, success: bool) -> None:
        if not self._movement_sequence:
            self._end_async_command_lock()
            return

        if not success:
            self._finish_movement_sequence(False)
            return

        self._movement_sequence["step_index"] += 1
        QTimer.singleShot(0, self._run_next_movement_step)

    def _run_next_movement_step(self) -> None:
        if not self._movement_sequence:
            self._end_async_command_lock()
            return

        steps = self._movement_sequence["steps"]
        step_index = self._movement_sequence["step_index"]
        if step_index >= len(steps):
            self._finish_movement_sequence(True)
            return

        step = steps[step_index]
        target = self._resolve_step_target(
            step,
            self._movement_sequence["target_x"],
            self._movement_sequence["target_z"],
        )
        if target is None:
            logger.warning(f"Unsupported movement step: {step}")
            self._finish_movement_sequence(False)
            return

        axis, target_position = target
        logger.info(
            f"{self._movement_sequence['name']} step {step_index + 1}/{len(steps)}: "
            f"step={step} axis={axis} target={target_position}, "
            f"cached_pos=({self._current_x},{self._current_y},{self._current_z})"
        )

        if axis == "X":
            delta = self.move_x(target_position)
        elif axis == "Y":
            delta = self.move_y(target_position)
        elif axis == "Z":
            delta = self.move_z(target_position)
        else:
            logger.warning(f"Unknown axis: {axis}")
            self._finish_movement_sequence(False)
            return

        if delta is None:
            logger.error(
                f"{self._movement_sequence['name']}: move_{axis.lower()}({target_position}) returned None, "
                f"sequence aborted"
            )
            self._finish_movement_sequence(False)
            return

        self._start_position_wait(axis, target_position, delta, self._on_movement_step_finished)

    def _start_movement_sequence(self, name: str, steps: list, target_x: int, target_z: int) -> bool:
        if not self._can_start_async_operation(name):
            return False

        self._movement_sequence = {
            "name": name,
            "steps": list(steps),
            "step_index": 0,
            "target_x": target_x,
            "target_z": target_z,
        }
        self._begin_async_command_lock(allow_position_query=True)
        self._run_next_movement_step()
        return True

    # ========================================================================
    # 命令发送
    # ========================================================================

    def send_data(self, data: str, source: str = "") -> bool:
        command = str(data)
        is_position_query = command.startswith("M~")
        if self._command_lock and is_position_query and not self._allow_position_query:
            logger.debug(
                "Serial TX blocked: "
                f"source={source or 'unknown'}, command={command}, "
                f"reason=command_lock, state={self._work_state.value}"
            )
            return False

        if not self.serial_manager:
            logger.error("SerialManager is not available.")
            return False

        if not self.serial_manager.get_connection_status():
            logger.warning(
                "Serial TX blocked: "
                f"source={source or 'unknown'}, command={command}, reason=serial_not_connected"
            )
            return False

        try:
            self._tx_sequence += 1
            tx_item = {
                "id": self._tx_sequence,
                "data": command,
                "source": source or self._work_state.value,
                "enqueued_at": time.time(),
            }
            queue_before = self.thread_manager.write_queue.qsize()
            self.thread_manager.write_queue.put(tx_item)
            enqueue_log = logger.debug
            enqueue_log(
                "Serial TX enqueue: "
                f"id={self._tx_sequence}, source={tx_item['source']}, command={command}, "
                f"is_position_query={is_position_query}, queue_before={queue_before}, "
                f"queue_after={self.thread_manager.write_queue.qsize()}, "
                f"command_lock={self._command_lock}, allow_position_query={self._allow_position_query}"
            )
            return True
        except Exception as e:
            logger.error(f"Failed to enqueue serial command: {e}", exc_info=True)
            return False

    def enable_position_query_timer(self, interval: int = 1500) -> None:
        if not self.position_query_timer:
            self.position_query_timer = QTimer(self)
            self.position_query_timer.timeout.connect(self._position_query_from_timer)

        self.position_query_timer.setInterval(interval)
        self.position_query_timer.start()
        self.position_query_enabled = True

    def disable_position_query_timer(self) -> None:
        if self.position_query_timer and self.position_query_timer.isActive():
            self.position_query_timer.stop()
        self.position_query_enabled = False

    def _position_query_from_timer(self) -> None:
        if self._offset_calibrating or self._is_measuring:
            return
        if self._active_position_wait:
            return
        self.position_query(source="position_timer")

    # ========================================================================
    # 旋转采集 / 停止
    # ========================================================================

    def claw_rotate(self) -> None:
        """开始一圈旋转采集 (B~ 无参数)。"""
        self.send_data("B~", source="claw_rotate")

    def claw_stop(self) -> None:
        with self.command_lock():
            self.send_data("S~", source="claw_stop")

    # ========================================================================
    # 手动移动
    # ========================================================================

    def set_move_task(self, axis: str, direction: int, distance_mm: float) -> None:
        if self._movement_sequence or self._active_position_wait:
            logger.warning("Manual move skipped: another serial operation is running.")
            return
        self._pending_move_task = (axis, direction, distance_mm)

    def _execute_move_task(self, position_data: tuple) -> None:
        if not self._pending_move_task:
            return

        axis, direction, distance_mm = self._pending_move_task
        if position_data[0] is None or position_data[1] is None:
            logger.warning(f"Invalid position data, skip move task: {position_data}")
            self._pending_move_task = None
            return

        self._pending_move_task = None

        if axis == "Z":
            distance_pulse = int(round(distance_mm * Z_AXIS_PULSES_PER_MM))
        elif axis in ("X", "Y"):
            distance_pulse = int(round(distance_mm * X_AXIS_PULSES_PER_MM))
        else:
            logger.error(f"Unknown axis: {axis}")
            return

        with self.command_lock():
            if axis == "X":
                current_x = int(position_data[0])
                self.move_x(current_x + direction * distance_pulse)
            elif axis == "Y":
                current_y = int(position_data[1])
                self.move_y(current_y + direction * distance_pulse)
            elif axis == "Z":
                current_z = int(position_data[2])
                self.move_z(current_z + direction * distance_pulse)

    # ========================================================================
    # 位置查询
    # ========================================================================

    def position_query(self, source: str = "position_query") -> None:
        if self._offset_calibrating or self._position_query_in_flight:
            logger.debug(
                "Position query skipped: "
                f"source={source}, offset_calibrating={self._offset_calibrating}, "
                f"in_flight={self._position_query_in_flight}, state={self._work_state.value}"
            )
            return
        if self.send_data("M~", source=source):
            self._position_query_in_flight = True
            self.data_process.signal_position_data_process.emit()

    def _on_position_data_processed(self, position_data: tuple) -> None:
        self._position_query_in_flight = False

        if position_data[0] is not None:
            self._current_x = int(position_data[0])
        if len(position_data) > 1 and position_data[1] is not None:
            self._current_y = int(position_data[1])
        if len(position_data) > 2 and position_data[2] is not None:
            self._current_z = int(position_data[2])

        if self._active_position_wait:
            return  # DONE-based wait, position updates are handled separately

        if self._pending_move_task:
            self._execute_move_task(position_data)

    # ========================================================================
    # 偏置校准
    # ========================================================================

    def counter_measurer(self) -> None:
        logger.debug("=" * 60)
        queue_before_clear = self.data_process.data_queue.qsize()
        logger.info(
            "Offset flow: counter measurement start via B~, "
            f"queue_before_clear={queue_before_clear}, connected={self.serial_manager.get_connection_status()}"
        )
        self.data_process.clear_data_queue()
        logger.debug(
            "Offset flow: data queue cleared before B~ command, "
            f"queue_after_clear={self.data_process.data_queue.qsize()}"
        )
        result = self.send_data("B~", source="offset_collection")
        logger.info(
            "Offset flow: B~ collection command queued, result={result}, "
            f"process_delay_ms=200"
        )
        if not result:
            logger.warning("Offset flow: B~ command was not queued successfully")
        QTimer.singleShot(200, self._emit_offset_process_signal)

    def _emit_offset_process_signal(self) -> None:
        logger.debug(
            "Offset flow: trigger data processor, "
            f"queue_size={self.data_process.data_queue.qsize()}, "
            f"offset_calibrating={self._offset_calibrating}"
        )
        self.data_process.signal_offset_data_process.emit()

    def slider_reset(self) -> None:
        self.send_data("I~", source="slider_reset")
        # 归零后各轴回到限位原点，缓存置零
        self._current_x = 0
        self._current_y = 0
        self._current_z = 0
        logger.info("Slider reset: position cache cleared to (0, 0, 0)")

    # ========================================================================
    # 轴运动（绝对目标 → 内部自动换算相对步数）
    # ========================================================================

    def _capped_delta(self, current: Optional[int], target: int, axis: str) -> Optional[tuple]:
        """计算裁剪后的 delta 和原始符号（超过 MAX_RELATIVE_STEPS 则裁剪）。"""
        if current is None:
            logger.warning(f"move_{axis.lower()}: current {axis} position unknown, target={target}")
            return None
        delta = target - current
        raw = abs(delta)
        capped_flag = False
        if raw > MAX_RELATIVE_STEPS:
            logger.warning(f"move_{axis.lower()}: delta {raw} > {MAX_RELATIVE_STEPS}, capped; current={current}, target={target}")
            raw = MAX_RELATIVE_STEPS
            capped_flag = True
        sign = "+" if delta >= 0 else "-"
        capped = raw if delta >= 0 else -raw
        logger.info(f"move_{axis.lower()}: current={current} target={target} delta={capped:+d} (raw={abs(delta)}{', CAPPED' if capped_flag else ''}) cmd={axis}{sign}{raw}~")
        return sign, raw, capped

    def move_x(self, position: int) -> Optional[int]:
        r = self._capped_delta(self._current_x, position, "X")
        if r is None: return None
        sign, raw, capped = r
        if not self.send_data(f"X{sign}{raw}~", source="move_x"): return None
        return capped

    def move_y(self, position: int) -> Optional[int]:
        r = self._capped_delta(self._current_y, position, "Y")
        if r is None: return None
        sign, raw, capped = r
        if not self.send_data(f"Y{sign}{raw}~", source="move_y"): return None
        return capped

    def move_z(self, position: int) -> Optional[int]:
        r = self._capped_delta(self._current_z, position, "Z")
        if r is None: return None
        sign, raw, capped = r
        if not self.send_data(f"Z{sign}{raw}~", source="move_z"): return None
        return capped

    # ========================================================================
    # 测试位置 / 挂起位置 移动方案
    # ========================================================================

    def execute_movement_scheme(self, steps: list, target_x: int, target_z: int) -> bool:
        return self._start_movement_sequence("movement scheme", steps, target_x, target_z)

    def suspend_position(self) -> None:
        logger.info("Execute suspend position movement.")
        test_type = self.config.test_type
        scheme = self.config.get_active_suspend_scheme(test_type)
        target_x = self.config.suspend_x
        target_z = self.config.suspend_z
        self._start_movement_sequence("suspend position", scheme["steps"], target_x, target_z)

    def test_position(self) -> None:
        logger.info("Execute test position movement.")
        test_type = self.config.test_type
        scheme = self.config.get_active_test_scheme(test_type)
        target_x = self.config.test_x
        target_z = self.config.test_z
        self._start_movement_sequence("test position", scheme["steps"], target_x, target_z)

    # ========================================================================
    # 偏置校准流程控制
    # ========================================================================

    def offset_calibration(self) -> None:
        logger.info(
            "Offset flow: calibration requested, "
            f"was_calibrating={self._offset_calibrating}, "
            f"position_timer_enabled={self.position_query_enabled}, "
            f"queue_size={self.data_process.data_queue.qsize()}"
        )
        self._offset_calibrating = True
        self.data_process._offset_calibrating = True
        logger.debug("Offset flow: calibration flags enabled")
        self.counter_measurer()

    def _on_offset_calibration_finished(self, success: bool) -> None:
        if self._offset_calibrating:
            self._offset_calibrating = False
            self.data_process._offset_calibrating = False
            logger.info(f"Offset flow: calibration finished, success={success}")
            stop_result = self.send_data("S~", source="offset_finish_stop")
            logger.info(
                "Offset flow: finish handler sent stop command, "
                f"result={stop_result}, success={success}"
            )
        self._offset_calibrating = False
        self.data_process._offset_calibrating = False
        queue_before_clear = self.data_process.data_queue.qsize()
        self.data_process.clear_data_queue()
        logger.info(
            "Offset flow: calibration flags cleared, "
            f"success={success}, queue_before_clear={queue_before_clear}, "
            f"queue_after_clear={self.data_process.data_queue.qsize()}"
        )
