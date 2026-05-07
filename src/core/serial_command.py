# -*- coding: utf-8 -*-
"""
Serial command coordination.
"""

import time
from contextlib import contextmanager
from enum import Enum
from typing import Callable, Optional, TYPE_CHECKING

from PyQt5.QtCore import QObject, QTimer

from .config_manager import get_config_manager
from .logger import get_logger
from .offset_calibration_config import (
    OFFSET_COLLECTION_COMMAND_SECONDS,
    OFFSET_STOP_GUARD_DELAY_MS,
)

if TYPE_CHECKING:
    from .thread_manager import ThreadManager


logger = get_logger("SerialCommand")

X_AXIS_PULSES_PER_MM = 400
Z_AXIS_PULSES_PER_MM = 1000 / 0.62
POSITION_TOLERANCE_MM = 0.2
POSITION_WAIT_TIMEOUT_MS = 20000
POSITION_WAIT_POLL_INTERVAL_MS = 150
POSITION_STALL_RECHECK_DELAY_MS = 500
SELF_DETECT_TIMEOUT_MS = 10000
SELF_DETECT_POLL_INTERVAL_MS = 50


class WorkState(Enum):
    IDLE = "idle"
    SELF_DETECTING = "self_detecting"
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

        self._pending_retract_axis: Optional[str] = None
        self._self_detect_axis: Optional[str] = None
        self._self_detect_completed = False
        self._pending_move_task: Optional[tuple] = None

        self._offset_calibrating = False
        self._is_measuring = False

        self._current_x: Optional[int] = None
        self._current_z: Optional[int] = None

        self._position_query_retry_count = 0
        self._max_position_query_retries = 3
        self._position_query_in_flight = False

        self._movement_sequence: Optional[dict] = None
        self._active_position_wait: Optional[dict] = None
        self._async_command_lock_state: Optional[dict] = None
        self._tx_sequence = 0

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
        self._position_wait_poll_timer.setInterval(POSITION_WAIT_POLL_INTERVAL_MS)
        self._position_wait_poll_timer.timeout.connect(self._poll_position_wait)

        self._position_wait_stall_timer = QTimer(self)
        self._position_wait_stall_timer.setSingleShot(True)
        self._position_wait_stall_timer.timeout.connect(self._on_position_wait_stall_recheck)

        self._position_wait_timeout_timer = QTimer(self)
        self._position_wait_timeout_timer.setSingleShot(True)
        self._position_wait_timeout_timer.timeout.connect(self._on_position_wait_timeout)

        self._self_detect_poll_timer = QTimer(self)
        self._self_detect_poll_timer.setInterval(SELF_DETECT_POLL_INTERVAL_MS)
        self._self_detect_poll_timer.timeout.connect(self._poll_self_detect)

        self._self_detect_timeout_timer = QTimer(self)
        self._self_detect_timeout_timer.setSingleShot(True)
        self._self_detect_timeout_timer.timeout.connect(self._on_self_detect_timeout)

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
            or self._self_detect_axis
            or self._pending_retract_axis
            or self._command_lock
        ):
            logger.warning(
                f"{operation_name} skipped: another serial operation is running. "
                f"state={self._work_state.value}, command_lock={self._command_lock}, "
                f"movement={bool(self._movement_sequence)}, "
                f"active_position_wait={bool(self._active_position_wait)}, "
                f"self_detect_axis={self._self_detect_axis}, "
                f"pending_retract_axis={self._pending_retract_axis}, "
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
        self._position_wait_stall_timer.stop()
        self._position_wait_timeout_timer.stop()
        wait_state = self._active_position_wait
        self._active_position_wait = None
        return wait_state

    @staticmethod
    def _get_axis_pulses_per_mm(axis: str) -> float:
        if axis == "X":
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
        callback: Callable[[bool], None],
        timeout_ms: int = POSITION_WAIT_TIMEOUT_MS,
    ) -> None:
        current_position = self._current_x if axis == "X" else self._current_z
        self._active_position_wait = {
            "axis": axis,
            "target": target,
            "callback": callback,
            "last_position": current_position,
            "stall_reference_position": None,
            "stall_recheck_pending": False,
        }
        self._work_state = WorkState.WAITING_POSITION
        self._position_wait_timeout_timer.start(timeout_ms)
        self._position_wait_poll_timer.start()
        self.position_query(source="position_wait_start")

    def _poll_position_wait(self) -> None:
        if self._active_position_wait:
            self.position_query(source="position_wait_poll")

    def _on_position_wait_stall_recheck(self) -> None:
        if not self._active_position_wait or not self._active_position_wait.get("stall_recheck_pending"):
            return
        self.position_query(source="position_wait_stall_recheck")

    def _mark_position_wait_failed(self, reason: str) -> None:
        wait_state = self._clear_position_wait()
        self._work_state = WorkState.IDLE
        if wait_state:
            logger.error(reason)
            wait_state["callback"](False)

    def _handle_position_wait_update(self, position_data: tuple) -> None:
        if not self._active_position_wait:
            return
        if position_data[0] is None or position_data[1] is None:
            return

        wait_state = self._active_position_wait
        axis = wait_state["axis"]
        target = wait_state["target"]
        current = self._current_x if axis == "X" else self._current_z
        tolerance = self._get_position_tolerance_pulse(axis)
        diff = abs(current - target) if current is not None else None
        if current is None or diff > tolerance:
            last_position = wait_state.get("last_position")
            if last_position is None:
                wait_state["last_position"] = current
                return

            if current != last_position:
                wait_state["last_position"] = current
                wait_state["stall_reference_position"] = None
                wait_state["stall_recheck_pending"] = False
                self._position_wait_stall_timer.stop()
                if not self._position_wait_poll_timer.isActive():
                    self._position_wait_poll_timer.start()
                return

            if wait_state.get("stall_recheck_pending"):
                stall_reference = wait_state.get("stall_reference_position")
                if stall_reference == current:
                    self._mark_position_wait_failed(
                        f"{axis} axis movement abnormal: current={current}, target={target}, "
                        f"diff={diff}, no position change after {POSITION_STALL_RECHECK_DELAY_MS}ms recheck."
                    )
                    return

                wait_state["last_position"] = current
                wait_state["stall_reference_position"] = None
                wait_state["stall_recheck_pending"] = False
                if not self._position_wait_poll_timer.isActive():
                    self._position_wait_poll_timer.start()
                return

            wait_state["stall_reference_position"] = current
            wait_state["stall_recheck_pending"] = True
            self._position_wait_poll_timer.stop()
            self._position_wait_stall_timer.start(POSITION_STALL_RECHECK_DELAY_MS)
            return

        wait_state = self._clear_position_wait()
        self._work_state = WorkState.IDLE
        logger.info(
            f"{axis} axis reached target: current={current}, target={target}, diff={diff}, tolerance={tolerance}"
        )
        if wait_state:
            wait_state["callback"](True)

    def _on_position_wait_timeout(self) -> None:
        wait_state = self._clear_position_wait()
        self._work_state = WorkState.IDLE
        if not wait_state:
            return

        axis = wait_state["axis"]
        target = wait_state["target"]
        current = self._current_x if axis == "X" else self._current_z
        tolerance = self._get_position_tolerance_pulse(axis)
        diff = abs(current - target) if current is not None else None
        if current is not None and diff <= tolerance:
            logger.info(
                f"{axis} axis accepted at timeout: current={current}, target={target}, diff={diff}, tolerance={tolerance}"
            )
            wait_state["callback"](True)
            return

        if current is None:
            logger.warning(f"{axis} axis move to {target} timed out: no valid position feedback.")
        else:
            logger.warning(
                f"{axis} axis move to {target} timed out, current={current}, diff={diff}, tolerance={tolerance}"
            )
        wait_state["callback"](False)

    def _resolve_step_target(self, step: str, target_x: int, target_z: int) -> Optional[tuple]:
        x_offset_pulse = self.config.get_inner_x_offset_pulse()
        z_offset_pulse = self.config.get_inner_z_offset_pulse()

        if step == "X":
            return "X", target_x
        if step == "Z":
            return "Z", target_z
        if step == "X+":
            current_x = self._current_x if self._current_x is not None else target_x
            return "X", current_x + x_offset_pulse
        if step == "X-":
            current_x = self._current_x if self._current_x is not None else target_x
            return "X", current_x - x_offset_pulse
        if step == "Z+":
            current_z = self._current_z if self._current_z is not None else target_z
            return "Z", current_z + z_offset_pulse
        if step == "Z-":
            current_z = self._current_z if self._current_z is not None else target_z
            return "Z", current_z - z_offset_pulse
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
            f"{self._movement_sequence['name']} step {step_index + 1}/{len(steps)}: {step} -> {target_position}"
        )
        move_sent = self.move_x(target_position) if axis == "X" else self.move_z(target_position)
        if not move_sent:
            self._finish_movement_sequence(False)
            return

        self._start_position_wait(axis, target_position, self._on_movement_step_finished)

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

    def _stop_self_detect(self) -> None:
        self._self_detect_poll_timer.stop()
        self._self_detect_timeout_timer.stop()
        self._self_detect_axis = None
        if hasattr(self.data_process, "_self_detecting"):
            self.data_process._self_detecting = False

    def _poll_self_detect(self) -> None:
        if self._self_detect_axis:
            self.data_process.signal_self_detect_process.emit()

    def _on_self_detect_timeout(self) -> None:
        if not self._self_detect_axis:
            return

        logger.warning(
            "Adhesion flow: self detect timed out, "
            f"detect_axis={self._self_detect_axis}, "
            f"pending_retract_axis={self._pending_retract_axis}, "
            f"queue_size={self.data_process.data_queue.qsize()}, "
            f"parser_buffer_chars={len(getattr(self.data_process, '_self_detect_text_buffer', ''))}, "
            f"parser_buffer_preview={self.data_process.get_self_detect_buffer_preview() if hasattr(self.data_process, 'get_self_detect_buffer_preview') else ''}"
        )
        stop_result = self.send_data("S~", source="self_detect_timeout_stop")
        logger.warning(
            "Adhesion flow: stop command queued after self detect timeout, "
            f"result={stop_result}, write_queue_size={self.thread_manager.write_queue.qsize()}"
        )
        self._stop_self_detect()
        if hasattr(self.data_process, "clear_self_detect_buffer"):
            self.data_process.clear_self_detect_buffer()
        self._pending_retract_axis = None
        self._self_detect_completed = False
        self._position_query_retry_count = 0
        self._work_state = WorkState.IDLE
        self._end_async_command_lock()

    def _start_self_detect(self, command: str, retract_axis: str, detect_axis: str) -> bool:
        operation_name = f"self detect {detect_axis}"
        if not self._can_start_async_operation(operation_name):
            return False

        logger.info(
            "Adhesion flow: self detect start, "
            f"command={command}, detect_axis={detect_axis}, "
            f"retract_axis={retract_axis}, retract_distance={self.config.retract_distance:.3f}mm, "
            f"queue_before_clear={self.data_process.data_queue.qsize()}"
        )
        self._pending_retract_axis = retract_axis
        self._self_detect_axis = detect_axis
        self._self_detect_completed = False
        self._position_query_retry_count = 0
        self._work_state = WorkState.SELF_DETECTING
        if hasattr(self.data_process, "_self_detecting"):
            self.data_process._self_detecting = True
        self.data_process.clear_data_queue()
        if hasattr(self.data_process, "clear_self_detect_buffer"):
            self.data_process.clear_self_detect_buffer()
        logger.debug(
            "Adhesion flow: queue and parser buffer cleared before self detect, "
            f"queue_after_clear={self.data_process.data_queue.qsize()}"
        )
        self._begin_async_command_lock(allow_position_query=True)
        dropped_writes = self._drop_pending_position_query_writes(
            reason=f"before self detect {detect_axis}"
        )
        if dropped_writes:
            logger.info(
                "Adhesion flow: pending position query writes dropped before self detect, "
                f"dropped={dropped_writes}, write_queue_size={self.thread_manager.write_queue.qsize()}"
            )

        if not self.send_data(command, source=f"self_detect_{detect_axis}"):
            logger.warning(
                "Adhesion flow: self detect command not queued, "
                f"command={command}, detect_axis={detect_axis}"
            )
            self._stop_self_detect()
            self._pending_retract_axis = None
            self._work_state = WorkState.IDLE
            self._end_async_command_lock()
            return False

        logger.debug(
            "Adhesion flow: self detect command queued, "
            f"command={command}, timeout_ms={SELF_DETECT_TIMEOUT_MS}"
        )
        self._self_detect_timeout_timer.start(SELF_DETECT_TIMEOUT_MS)
        self._self_detect_poll_timer.start()
        self.data_process.signal_self_detect_process.emit()
        return True

    def send_data(self, data: str, source: str = "") -> bool:
        command = str(data)
        is_position_query = command.startswith("?XZ")
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
            enqueue_log = logger.debug if is_position_query else logger.info
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

    def enable_position_query_timer(self, interval: int = 500) -> None:
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
        if self._active_position_wait or self._self_detect_axis or self._pending_retract_axis:
            return
        self.position_query(source="position_timer")

    def claw_rotate(self) -> None:
        round_pulse = 542720
        self.send_data(f"B{int(round_pulse * 1.5)}~", source="claw_rotate")

    def claw_stop(self) -> None:
        with self.command_lock():
            self.send_data("S~", source="claw_stop")

    def vertical_move(self, distance: int) -> None:
        with self.command_lock():
            self.send_data(f"N{distance}~", source="vertical_move")

    def auto_press(self) -> bool:
        logger.info("Adhesion flow: Z press requested.")
        return self._start_self_detect("P~", "Z", "Z")

    def auto_press_left(self) -> bool:
        logger.info("Adhesion flow: X left press requested.")
        return self._start_self_detect("Y~", "X", "X")

    def auto_press_right(self) -> bool:
        logger.info("Adhesion flow: X right press requested.")
        return self._start_self_detect("Y-~", "X-", "X")

    def _on_self_detect_finished(self, axis: str) -> None:
        if not self._pending_retract_axis:
            logger.debug("No pending retract task.")
            return
        if self._self_detect_axis and axis != self._self_detect_axis:
            logger.debug(f"Ignore self detect signal: {axis}")
            return

        logger.info(
            "Adhesion flow: self detect finished, "
            f"detect_axis={axis}, pending_retract_axis={self._pending_retract_axis}, "
            f"position_query_in_flight={self._position_query_in_flight}"
        )
        self._stop_self_detect()
        self._self_detect_completed = True
        self._work_state = WorkState.WAITING_POSITION
        self._position_query_in_flight = False
        queue_before_position_query = self.data_process.data_queue.qsize()
        self.data_process.clear_data_queue()
        logger.debug(
            "Adhesion flow: queue cleared before retract position query, "
            f"queue_before_clear={queue_before_position_query}, "
            f"queue_after_clear={self.data_process.data_queue.qsize()}"
        )
        logger.debug("Adhesion flow: querying position for retract target.")
        self.position_query(source="retract_position_query")

    def _on_position_data_processed(self, position_data: tuple) -> None:
        self._position_query_in_flight = False

        if position_data[0] is not None:
            self._current_x = int(position_data[0])
        if position_data[1] is not None:
            self._current_z = int(position_data[1])

        if self._pending_retract_axis:
            if not self._self_detect_completed:
                return

            if position_data[0] is None or position_data[1] is None:
                self._position_query_retry_count += 1
                logger.warning(
                    "Adhesion flow: invalid position for retract, "
                    f"position={position_data}, retry={self._position_query_retry_count}/"
                    f"{self._max_position_query_retries}, "
                    f"pending_retract_axis={self._pending_retract_axis}"
                )
                if self._position_query_retry_count >= self._max_position_query_retries:
                    logger.error(
                        f"Invalid retract position data after {self._max_position_query_retries} retries."
                    )
                    self._pending_retract_axis = None
                    self._self_detect_completed = False
                    self._position_query_retry_count = 0
                    self._work_state = WorkState.IDLE
                    self._end_async_command_lock()
                else:
                    self.position_query(source="retract_position_retry")
                return

            self._position_query_retry_count = 0
            logger.info(
                "Adhesion flow: position ready for retract, "
                f"position={position_data}, pending_retract_axis={self._pending_retract_axis}"
            )
            self._execute_retract(position_data)
            return

        if self._active_position_wait:
            self._handle_position_wait_update(position_data)
            return

        if self._pending_move_task:
            self._execute_move_task(position_data)

    def _execute_retract(self, position_data: tuple) -> None:
        axis = self._pending_retract_axis
        if not axis:
            return

        self._pending_retract_axis = None
        self._self_detect_completed = False

        retract_mm = max(0.0, self.config.retract_distance)
        if axis in {"X", "X-"}:
            retract_pulse = int(retract_mm * X_AXIS_PULSES_PER_MM)
        elif axis == "Z":
            retract_pulse = int(retract_mm * Z_AXIS_PULSES_PER_MM)
        else:
            self._work_state = WorkState.IDLE
            self._end_async_command_lock()
            return

        if axis == "X":
            current_x = int(position_data[0])
            target = current_x - retract_pulse
            result = self.move_x(target)
            logger.info(
                "Adhesion flow: retract command queued, "
                f"axis=X, current={current_x}, target={target}, "
                f"retract_pulse={retract_pulse}, retract_mm={retract_mm:.3f}, result={result}"
            )
        elif axis == "X-":
            current_x = int(position_data[0])
            target = current_x + retract_pulse
            result = self.move_x(target)
            logger.info(
                "Adhesion flow: retract command queued, "
                f"axis=X-, current={current_x}, target={target}, "
                f"retract_pulse={retract_pulse}, retract_mm={retract_mm:.3f}, result={result}"
            )
        elif axis == "Z":
            current_z = int(position_data[1])
            target = current_z - retract_pulse
            result = self.move_z(target)
            logger.info(
                "Adhesion flow: retract command queued, "
                f"axis=Z, current={current_z}, target={target}, "
                f"retract_pulse={retract_pulse}, retract_mm={retract_mm:.3f}, result={result}"
            )

        self._work_state = WorkState.IDLE
        self._end_async_command_lock()
        logger.info(f"Adhesion flow: retract flow finished, axis={axis}")

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
            distance_pulse = int(distance_mm * 1000 / 0.62)
        elif axis == "X":
            distance_pulse = int(distance_mm * 400)
        else:
            logger.error(f"Unknown axis: {axis}")
            return

        with self.command_lock():
            if axis == "X":
                current_x = int(position_data[0])
                self.move_x(current_x + direction * distance_pulse)
            elif axis == "Z":
                current_z = int(position_data[1])
                self.move_z(current_z + direction * distance_pulse)

    def set_move_task(self, axis: str, direction: int, distance_mm: float) -> None:
        if self._movement_sequence or self._self_detect_axis or self._pending_retract_axis or self._active_position_wait:
            logger.warning("Manual move skipped: another serial operation is running.")
            return
        self._pending_move_task = (axis, direction, distance_mm)

    def position_query(self, source: str = "position_query") -> None:
        if self._offset_calibrating or self._position_query_in_flight:
            logger.debug(
                "Position query skipped: "
                f"source={source}, offset_calibrating={self._offset_calibrating}, "
                f"in_flight={self._position_query_in_flight}, state={self._work_state.value}"
            )
            return
        if self.send_data("?XZ~", source=source):
            self._position_query_in_flight = True
            self.data_process.signal_position_data_process.emit()

    def counter_measurer(self) -> None:
        logger.debug("=" * 60)
        queue_before_clear = self.data_process.data_queue.qsize()
        logger.info(
            "Offset flow: counter measurement start, "
            f"queue_before_clear={queue_before_clear}, connected={self.serial_manager.get_connection_status()}"
        )
        self.data_process.clear_data_queue()
        logger.debug(
            "Offset flow: data queue cleared before offset command, "
            f"queue_after_clear={self.data_process.data_queue.qsize()}"
        )
        command = f"K{OFFSET_COLLECTION_COMMAND_SECONDS}~"
        result = self.send_data(command, source="offset_collection")
        logger.info(
            "Offset flow: collection command queued, "
            f"command={command}, result={result}, "
            f"process_delay_ms=200, stop_guard_ms={OFFSET_STOP_GUARD_DELAY_MS}"
        )
        if not result:
            logger.warning("Offset flow: collection command was not queued successfully")
        QTimer.singleShot(200, self._emit_offset_process_signal)
        QTimer.singleShot(OFFSET_STOP_GUARD_DELAY_MS, self._stop_offset_collection_if_needed)

    def _emit_offset_process_signal(self) -> None:
        logger.debug(
            "Offset flow: trigger data processor, "
            f"queue_size={self.data_process.data_queue.qsize()}, "
            f"offset_calibrating={self._offset_calibrating}"
        )
        self.data_process.signal_offset_data_process.emit()

    def _stop_offset_collection_if_needed(self) -> None:
        if not self._offset_calibrating:
            logger.debug("Offset flow: stop guard skipped, calibration already finished")
            return

        result = self.send_data("S~", source="offset_stop_guard")
        logger.info(
            "Offset flow: stop guard sent stop command, "
            f"result={result}, queue_size={self.data_process.data_queue.qsize()}"
        )

    def slider_reset(self) -> None:
        self.send_data("I~", source="slider_reset")

    def move_x(self, position: int) -> bool:
        return self.send_data(f"X{position}~", source="move_x")

    def move_z(self, position: int) -> bool:
        return self.send_data(f"Z{position}~", source="move_z")

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
