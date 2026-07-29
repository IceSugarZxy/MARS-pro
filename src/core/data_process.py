# -*- coding: utf-8 -*-
"""
数据处理模块

负责处理串口接收的各种数据，包括：
- 位置数据：解析 M~ 响应的 X/Y/Z 轴位置信息
- 测量数据：解析磁场强度数据并进行算法处理
- 偏置数据：计算磁场偏置值
- 运动完成：检测 X/Y/Z DONE 消息

数据流程：
1. SerialManager 从串口接收数据，放入共享队列
2. 外部触发信号（如 signal_measure_data_process）
3. DataProcess 从队列中读取数据并处理
4. 处理完成后发出 finished 信号通知上层
"""

from typing import Tuple, List, Optional
import queue
import re
import time
import statistics
import os
import csv
from datetime import datetime

import numpy as np
from PyQt5.QtCore import QObject, pyqtSignal

from .logger import get_logger
from .config_manager import get_config_manager
from .path_utils import get_data_dir
from .offset_calibration_config import (
    OFFSET_COLLECTION_SECONDS,
    OFFSET_MAX_PROCESS_SECONDS,
    OFFSET_STABLE_WINDOW_SECONDS,
)

logger = get_logger('DataProcess')

# ============================================================================
# 常量定义
# ============================================================================
# v1.x 固件：B~ 采集 = 精确 1 圈 (360°)，数据量取决于 MODE
FULL_ROTATION_ANGLE = 360.0
MODE_EXPECTED_POINTS = {0: 131072, 1: 65536, 2: 32768}
# 闭合校准：v1.x 数据已是精确一圈，首尾即为闭合边界
CLOSURE_ROUGH_START_FRACTION = 0.0
CLOSURE_ROUGH_END_FRACTION = 1.0
CLOSURE_SEARCH_PERIOD_FRACTION = 0.25  # 在粗截取尾点前后各1/4磁周期内寻找闭合点
CLOSURE_MIN_PERIOD_POINTS = 4.0
CLOSURE_DIRECTION_PERIOD_FRACTION = 1.0 / 32.0
CLOSURE_MIN_DIRECTION_SPAN_POINTS = 20
CLOSURE_MAX_DIRECTION_SPAN_POINTS = 1000
CLOSURE_EXTREMUM_VALUE_TOLERANCE_RATIO = 0.002  # 峰/谷端点判定容差，占整体幅值比例
CLOSURE_COARSE_CANDIDATE_COUNT = 5000
CLOSURE_FINE_RADIUS_POINTS = 120
OFFSET_INITIAL_DATA_TIMEOUT_SECONDS = 5.0   # 首数据超时 5s
OFFSET_NO_DATA_TIMEOUT_SECONDS = 2.0        # 数据中断 2s 判定结束
OFFSET_QUEUE_POLL_SECONDS = 0.02
OFFSET_COLLECT_LOG_INTERVAL_SECONDS = 1.0
# M~ 响应轴位置解析正则（兼容 pos= 和 pos = 两种格式）
M_POS_PATTERN = re.compile(r"([XYZ]):\s*\w+\s+pos\s*=\s*(-?\d+)")
# 运动完成检测正则
MOTION_DONE_PATTERN = re.compile(r"([XYZ])\s+DONE")
# 运动启动确认正则（固件收到指令后立即回）
MOTION_START_PATTERN = re.compile(r"([XYZ])\s+START")


class DataProcess(QObject):
    signal_measure_analysis_finished = pyqtSignal(object, object, object)
    """
    数据处理管理器

    Attributes:
        data_queue: 共享队列，用于接收串口数据
        mag_offset: 磁场偏置值，用于校正测量数据
        position_data: 最后处理的位置数据 (x_position, z_position)
        measure_type: 测量类型，'rotation' 或 'vertical'
    """

    # ========================================================================
    # 信号定义
    # ========================================================================
    signal_position_data_process = pyqtSignal()                         # 位置数据处理信号
    signal_position_data_process_finished = pyqtSignal(tuple)           # 位置数据处理完成信号 (x, y, z)
    signal_offset_data_process = pyqtSignal()                           # 偏置数据处理信号
    signal_offset_data_process_finished = pyqtSignal(bool)              # 偏置数据处理完成信号
    signal_measure_data_process = pyqtSignal()                          # 测量数据处理信号
    signal_measure_data_process_finished = pyqtSignal(object, object)   # 测量数据处理完成信号
    signal_measure_data_progress = pyqtSignal(int, int)                 # 测量数据处理进度信号 (当前数据量, 总数据量)
    signal_motion_done = pyqtSignal(str)                                # 运动完成信号，参数为轴 ('X'/'Y'/'Z')
    signal_offset_data_progress = pyqtSignal(int, int)                  # 偏置数据处理进度 (当前, 总量)
    # ========================================================================
    # 类属性
    # ========================================================================
    SAMPLING_FREQ = 27000  # 采样频率 (Hz)
    CUTOFF_RATIO = 70  # 截止频率与采样频率的比值
    ADC_PER_MT = 73.35   # 标定灵敏度：73.35 ADC/mT
    ZERO_FIELD_ADC = 488.69  # 标定零场偏置（绝对值）

    def __init__(self, data_queue: queue.Queue):
        """
        初始化数据处理模块

        Args:
            data_queue: 共享队列，用于与SerialManager交换数据
        """
        super().__init__()
        from windows.wave_analysis import WaveAnalysis

        self.data_queue = data_queue
        self.config = get_config_manager()

        # 从配置文件加载偏置值，如果不存在则使用默认值
        self.mag_offset = self.config.offset or self._get_default_offset()

        # 测量类型：'rotation' - 旋转测量，'vertical' - 垂直测量
        self.measure_type: str = "rotation"
        self.enable_concentricity_calibration: bool = True
        self.save_raw_data_enabled: bool = False

        # 位置数据：最后处理的位置数据 (x_position, z_position)
        self.position_data: Optional[tuple] = None

        # 偏置校准期间暂停位置数据处理，避免串口回信互相干扰。
        self._offset_calibrating: bool = False

        # 测量停止标志：用于中途停止测量时立即处理已采集的数据
        self._stop_measure_processing: bool = False

        # 测量进行中标志：阻止文本解析器误消费二进制测量数据
        self._measurement_active: bool = False

        # 样品信息：用于保存测量数据时写入文件
        self._sample_info: dict = {}
        self._wave_analyzer = WaveAnalysis()

        logger.info(f"初始化数据处理模块完成：√")

    @staticmethod
    def _decode_s16(high: int, low: int) -> int:
        """大端序有符号 16-bit 解码：两个字节 → int16 ADC 原始值。"""
        raw = (high << 8) | low
        return raw - 0x10000 if raw >= 0x8000 else raw

    def set_sample_info(self, sample_info: dict) -> None:
        """
        设置样品信息，用于保存测量数据时写入文件头

        Args:
            sample_info: 包含样品信息的字典，键包括：
                - sample_code: 样品编号
                - sample_name: 样品名称
                - material: 材料
                - coil_code: 线圈编号
                - remark: 备注
                - polar_num: 极对数（选填，测量后会自动填入）
                - tester: 测试员
                - mag_condition: 磁化条件
                - probe: 探头
                - magnetometer: 磁强计
                - magnetizer: 磁化器
        """
        self._sample_info = sample_info.copy()

    def stop_measure_processing(self) -> None:
        """停止测量数据处理，中途停止时调用"""
        self._stop_measure_processing = True

    def update_sample_info(self, key: str, value) -> None:
        """
        更新样品信息中的单个字段

        Args:
            key: 字段名
            value: 字段值
        """
        self._sample_info[key] = value

    def get_sample_info(self) -> dict:
        """
        获取当前样品信息副本

        Returns:
            样品信息字典副本
        """
        return self._sample_info.copy()

    def _emit_measurement_results(self, measure_list: List[float]) -> None:
        """Persist measurement data and emit processed results (即使为空也 emit，用于触发重试)。"""
        if measure_list:
            logger.info(f"测量数据接收完成，共 {len(measure_list)} 个数据点")
        else:
            logger.warning("测量数据为空，emit 空结果触发重试判断")
        self.signal_measure_data_progress.emit(len(measure_list), len(measure_list))
        if self.save_raw_data_enabled:
            self.save_raw_measure_data(measure_list)
        else:
            logger.info("原始测量数据自动保存已关闭，跳过 raw_data 写入")

        if self.measure_type == "vertical":
            angle_data = list(range(len(measure_list)))
            mag_data = measure_list
            analysis_results = None
            logger.info(f"垂直测量：原始 {len(measure_list)} 点 → 角度/磁场各 {len(angle_data)} 点")
        else:
            # 旋转测量：全部原始数据映射到 0-360°，波形分析单独运行
            n = len(measure_list)
            if n > 0:
                angle_data = [i * 360.0 / n for i in range(n)]
                mag_data = measure_list
                logger.info(f"旋转测量：原始 {n} 点 → 0-360° 全部绘制")
                try:
                    alg_angle, alg_mag = self._process_measure_algorithm(measure_list)
                    logger.info(
                        f"旋转测量算法处理：{n} 原始点 → "
                        f"角度 {len(alg_angle)} 点, 磁场 {len(alg_mag)} 点"
                    )
                    analysis_results = self._wave_analyzer.analyze_waveform(
                        alg_angle, alg_mag, self.enable_concentricity_calibration)
                except Exception as e:
                    logger.warning(f"波形分析失败: {e}")
                    analysis_results = None
            else:
                angle_data, mag_data, analysis_results = [], [], None

        self.signal_measure_analysis_finished.emit(angle_data, mag_data, analysis_results)

    # ========================================================================
    # 滤波与数据预处理
    # ========================================================================

    def _lowpass_filter(self, data_list: List[float]) -> List[float]:
        """
        低通滤波函数

        使用scipy的butterworth滤波器对数据进行低通滤波，
        去除高频噪声，保留低频信号。

        Args:
            data_list: 输入的原始数据列表

        Returns:
            滤波后的数据列表，如果数据点不足20个则返回原数据
        """
        # scipy filtfilt 需要至少 3*max(len(b), len(a)) 个数据点
        # 对于4阶滤波器，padlen约15，所以至少需要20个数据点
        min_data_points = 20

        if len(data_list) < min_data_points:
            logger.warning(f"数据量太少({len(data_list)})，无法进行滤波，需要至少{min_data_points}个点")
            return data_list

        try:
            from scipy import signal

            # 计算截止频率：采样频率 / 截止比值 = 27000 / 70 ≈ 385.7 Hz
            cutoff_freq = self.SAMPLING_FREQ / self.CUTOFF_RATIO
            # 奈奎斯特频率：采样频率的一半
            nyquist_freq = self.SAMPLING_FREQ / 2
            # 归一化截止频率
            normalized_cutoff = cutoff_freq / nyquist_freq

            # 创建4阶低通滤波器
            b, a = signal.butter(4, normalized_cutoff, btype='low', analog=False)
            # 应用零相位滤波（前向后向滤波，消除相位偏移）
            filtered_data = signal.filtfilt(b, a, data_list)

            return filtered_data.tolist()

        except Exception as e:
            logger.error(f"低通滤波失败: {e}")
            return data_list

    # ========================================================================
    # 队列操作
    # ========================================================================

    def clear_data_queue(self) -> None:
        """
        清空数据队列

        将队列中的所有数据丢弃，通常在开始新数据处理前调用，
        以确保只处理本次需要的数据。
        """
        while not self.data_queue.empty():
            try:
                self.data_queue.get_nowait()
            except queue.Empty:
                break

    # ========================================================================
    # 运动完成检测
    # ========================================================================

    def check_motion_done(self) -> Optional[str]:
        """
        检测运动完成消息

        从队列中读取串口数据，检测是否包含 "X DONE" / "Y DONE" / "Z DONE"。
        使用非阻塞方式持续读取队列，直到找到完成消息或队列为空。

        Returns:
            完成运动的轴名 ('X'/'Y'/'Z')，未检测到返回 None
        """
        if self._measurement_active:
            return None
        try:
            while True:
                try:
                    data = self.data_queue.get_nowait()
                except queue.Empty:
                    break

                text = data.decode('utf-8', errors='ignore')
                # 优先检测 DONE（可能在 START 之后但先被读到）
                match = MOTION_DONE_PATTERN.search(text)
                if match:
                    axis = match.group(1)
                    logger.info(f"Motion done detected: {axis} DONE")
                    return axis
                # 检测可能出现的错误/状态回信
                text_stripped = text.strip()
                if text_stripped and logger.isEnabledFor(10):
                    logger.debug(f"Serial RX (motion poll): {text_stripped}")

        except Exception as e:
            logger.error(f"检测运动完成消息失败: {e}")

        return None

    def check_motion_feedback(self) -> Optional[tuple]:
        """
        检测运动反馈消息（START 确认 + DONE 完成 + 位置数据）

        固件收到运动指令后立即返回 "X START 1000" 表示已启动，
        运动结束后返回 "X DONE"。
        M~ 查询返回 "X: IDLE pos=466101 ..." 格式的位置行。

        Returns:
            ("DONE", axis) 或 ("START", axis) 或 ("POSITION", axis, position_int)；
            未检测到返回 None
        """
        if self._measurement_active:
            return None
        try:
            while True:
                try:
                    data = self.data_queue.get_nowait()
                except queue.Empty:
                    break

                text = data.decode('utf-8', errors='ignore')
                # 1) 优先检测 DONE
                match = MOTION_DONE_PATTERN.search(text)
                if match:
                    axis = match.group(1)
                    logger.info(f"Motion feedback: {axis} DONE")
                    return ("DONE", axis)
                # 2) 检测 START 确认
                match = MOTION_START_PATTERN.search(text)
                if match:
                    axis = match.group(1)
                    logger.info(f"Motion feedback: {axis} START (motor running)")
                    return ("START", axis)
                # 3) 检测 M~ 位置数据行
                match = M_POS_PATTERN.search(text)
                if match:
                    axis = match.group(1)
                    pos = int(match.group(2))
                    logger.debug(f"Motion feedback: {axis} position={pos}")
                    return ("POSITION", axis, pos)
                # 其他回信记录 DEBUG
                text_stripped = text.strip()
                if text_stripped and logger.isEnabledFor(10):
                    logger.debug(f"Serial RX (motion poll): {text_stripped}")

        except Exception as e:
            logger.error(f"检测运动反馈失败: {e}")

        return None

    # ========================================================================
    # 位置数据处理
    # ========================================================================

    # 类变量，用于累积位置数据
    _position_buffer = bytearray()

    def process_position_data(self) -> None:
        """
        处理位置数据

        从队列中读取 M~ 响应的多行文本，解析 X/Y/Z 轴位置。
        M~ 轴状态行格式: "X: IDLE pos=466101 cnt=0/0 dir=+ stop=1"
        M~ 响应约 30+ 行，可能跨多个 USB 包到达，需分批读取。
        """
        if self._offset_calibrating:
            self.signal_position_data_process_finished.emit((None, None, None))
            return

        # 测量期间禁止位置查询，避免抽干二进制测量数据
        if self._measurement_active:
            return

        x_position: Optional[str] = None
        y_position: Optional[str] = None
        z_position: Optional[str] = None

        DataProcess._position_buffer.clear()

        import time as time_module
        deadline = time_module.time() + 1.0
        batch_wait = 0.08

        while time_module.time() < deadline:
            # 尽量一次性读完队列中的所有数据
            got_data = False
            while True:
                try:
                    data = self.data_queue.get_nowait()
                    DataProcess._position_buffer.extend(data)
                    got_data = True
                except queue.Empty:
                    break

            if got_data:
                # 检测是否为二进制数据（非 ASCII 字节占比 > 30% → 丢弃缓冲区）
                buf = DataProcess._position_buffer
                non_ascii = sum(1 for b in buf if b > 127)
                if len(buf) > 100 and non_ascii > len(buf) * 0.3:
                    logger.warning(
                        f"M~ buffer discarded ({len(buf)} bytes, {non_ascii} non-ASCII) — binary data detected"
                    )
                    DataProcess._position_buffer.clear()
                    self.signal_position_data_process_finished.emit((None, None, None))
                    return

                try:
                    text = DataProcess._position_buffer.decode('utf-8', errors='ignore')
                    matches = M_POS_PATTERN.findall(text)
                    for axis, pos in matches:
                        if axis == 'X':
                            x_position = pos
                        elif axis == 'Y':
                            y_position = pos
                        elif axis == 'Z':
                            z_position = pos

                    if x_position is not None and y_position is not None and z_position is not None:
                        logger.info(
                            f"M~ position OK: X={x_position}, Y={y_position}, Z={z_position}, "
                            f"elapsed={time_module.time() - (deadline - 1.0):.3f}s"
                        )
                        break
                except UnicodeDecodeError:
                    pass

            time_module.sleep(batch_wait)

        # 打印原始回信尾部，方便排查解析问题
        raw_tail = DataProcess._position_buffer.decode('utf-8', errors='replace')[-300:]
        if x_position is None or y_position is None or z_position is None:
            logger.warning(
                f"M~ position INCOMPLETE: X={x_position}, Y={y_position}, Z={z_position}, "
                f"buffer_bytes={len(DataProcess._position_buffer)}, "
                f"raw_tail={raw_tail}"
            )
        else:
            logger.debug(
                f"M~ raw tail: bytes={len(DataProcess._position_buffer)}, "
                f"text={raw_tail}"
            )

        self.signal_position_data_process_finished.emit((x_position, y_position, z_position))

    # ========================================================================
    # 测量数据处理
    # ========================================================================

    def process_measure_data(self) -> None:
        """Collect raw measurement bytes and emit processed results."""
        logger.info("========== Start processing measurement data ==========")
        logger.info(f"Measurement type: {self.measure_type}")

        # 加载偏置值（ADC 单位）用于零场校正
        self.mag_offset = self.config.offset or 0
        logger.info(f"Offset: {self.mag_offset:.1f} ADC")

        self._stop_measure_processing = False

        try:
            temp_buffer = bytearray()
            measure_list: List[float] = []
            no_data_count = 0
            total_bytes_read = 0
            data_started = False

            # 两段超时：启动 3s (6×0.5s)，中断 2s (4×0.5s)
            max_empty_start = 6
            max_empty_done = 4
            max_empty_count = max_empty_start
            logger.info(
                f"Measurement loop started, start_timeout={max_empty_start * 0.5}s, "
                f"done_timeout={max_empty_done * 0.5}s, queue_size={self.data_queue.qsize()}"
            )
            while True:
                if self._stop_measure_processing:
                    logger.info("Measurement processing stopped by request")
                    self._emit_measurement_results(measure_list)
                    break

                if len(temp_buffer) >= 2:
                    group_count = len(temp_buffer) // 2
                    batch_size = min(group_count, 100)

                    for i in range(batch_size):
                        byte1 = temp_buffer[i * 2]
                        byte2 = temp_buffer[i * 2 + 1]
                        adc = self._decode_s16(byte1, byte2) - self.mag_offset
                        measure_list.append(round(adc / self.ADC_PER_MT, 4))

                    del temp_buffer[0:batch_size * 2]

                    # 进度更新（已知各 MODE 数据量）
                    expected = MODE_EXPECTED_POINTS.get(self.config.test_speed, len(measure_list))
                    self.signal_measure_data_progress.emit(len(measure_list), expected)

                if len(temp_buffer) < 2:
                    try:
                        data = self.data_queue.get_nowait()
                        temp_buffer.extend(data)
                        total_bytes_read += len(data)
                        if not data_started:
                            data_started = True
                            max_empty_count = max_empty_done
                            logger.info(
                                f"First data received ({len(data)} bytes), "
                                f"switching timeout to {max_empty_done * 0.5}s"
                            )
                        logger.debug(
                            f"Measure RX: +{len(data)} bytes (total {total_bytes_read}), "
                            f"buffer={len(temp_buffer)}, points={len(measure_list)}, "
                            f"queue_remain={self.data_queue.qsize()}"
                        )
                        no_data_count = 0
                        continue
                    except queue.Empty:
                        no_data_count += 1
                        logger.debug(
                            f"Measure empty poll #{no_data_count}/{max_empty_count}, "
                            f"points={len(measure_list)}, buffer={len(temp_buffer)}, "
                            f"total_bytes={total_bytes_read}, data_started={data_started}"
                        )
                        time.sleep(0.5)

                        if self._stop_measure_processing:
                            logger.info("Measurement processing stopped by request while waiting for data")
                            self._emit_measurement_results(measure_list)
                            break

                        if no_data_count >= max_empty_count:
                            # 超时前最后捞一次队列，避免数据恰好在这 0.5s 内到达
                            try:
                                while True:
                                    tail = self.data_queue.get_nowait()
                                    temp_buffer.extend(tail)
                                    total_bytes_read += len(tail)
                                    logger.info(f"Measure final drain: +{len(tail)} bytes from queue")
                            except queue.Empty:
                                pass

                            if len(temp_buffer) >= 2:
                                # 捞到数据了，处理掉并继续等待
                                logger.info(f"Measure recovered {len(temp_buffer)} bytes at timeout boundary, continuing")
                                no_data_count = 0
                                continue

                            logger.warning(
                                f"Measurement receive timeout: {no_data_count} empty polls, "
                                f"points={len(measure_list)}, buffer_remain={len(temp_buffer)}, "
                                f"total_bytes={total_bytes_read}, queue_size={self.data_queue.qsize()}"
                            )
                            self._emit_measurement_results(measure_list)
                            break

        except Exception as e:
            logger.error(f"Error while processing measurement data: {e}", exc_info=True)

    def process_offset_data(self) -> None:
        """
        处理偏置数据

        用于校准磁场测量的偏置值。在无被测磁场时采集数据，
        计算平均值作为偏置，后续测量时需要减去此偏置值。

        处理流程：
        1. 持续从队列获取数据直到队列为空
        2. 处理缓冲区中的所有数据
        3. 等待一小段时间看是否有新数据
        4. 重复直到真的没有新数据
        5. 对数据进行低通滤波
        6. 按配置取中间稳定窗口数据的平均值作为偏置
        7. 保存到配置文件

        Note:
            保存的偏置值会在每次程序启动时加载，用于校正测量数据
        """
        try:
            start_time = time.time()
            last_data_time = start_time
            temp_buffer = bytearray()
            offset_list: List[int] = []
            got_data = False
            raw_bytes_received = 0
            queue_items_received = 0
            last_collect_log_time = start_time

            logger.info(
                "Offset flow: processor started, "
                f"initial_queue_size={self.data_queue.qsize()}, "
                f"max_process={OFFSET_MAX_PROCESS_SECONDS:.1f}s, "
                f"no_data_timeout={OFFSET_NO_DATA_TIMEOUT_SECONDS:.1f}s"
            )

            while True:
                # 1. 把队列中的数据都取出来放到缓冲区
                try:
                    while True:
                        data = self.data_queue.get_nowait()
                        if not got_data:
                            logger.info(
                                "Offset flow: first data chunk received, "
                                f"bytes={len(data)}, elapsed={time.time() - start_time:.2f}s"
                            )
                        temp_buffer.extend(data)
                        raw_bytes_received += len(data)
                        queue_items_received += 1
                        got_data = True
                        last_data_time = time.time()
                except queue.Empty:
                    pass

                # 2. 处理缓冲区：有符号 16-bit 大端序解码
                while len(temp_buffer) >= 2:
                    byte1 = temp_buffer[0]
                    byte2 = temp_buffer[1]
                    offset_list.append(self._decode_s16(byte1, byte2))
                    del temp_buffer[0:2]

                # 进度更新
                expected = MODE_EXPECTED_POINTS.get(self.config.test_speed, len(offset_list))
                self.signal_offset_data_progress.emit(len(offset_list), expected)

                current_time = time.time()
                if current_time - last_collect_log_time >= OFFSET_COLLECT_LOG_INTERVAL_SECONDS:
                    last_collect_log_time = current_time
                    logger.debug(
                        "Offset flow: collecting, "
                        f"points={len(offset_list)}, "
                        f"raw_bytes={raw_bytes_received}, "
                        f"queue_items={queue_items_received}, "
                        f"buffer_bytes={len(temp_buffer)}, "
                        f"queue_size={self.data_queue.qsize()}, "
                        f"elapsed={current_time - start_time:.2f}s"
                    )

                elapsed = current_time - start_time
                no_data_elapsed = current_time - last_data_time

                if elapsed >= OFFSET_MAX_PROCESS_SECONDS:
                    logger.warning(
                        "Offset flow: max process time reached, "
                        f"points={len(offset_list)}, raw_bytes={raw_bytes_received}, "
                        f"queue_items={queue_items_received}, elapsed={elapsed:.2f}s"
                    )
                    break

                if got_data and no_data_elapsed >= OFFSET_NO_DATA_TIMEOUT_SECONDS:
                    logger.info(
                        "Offset flow: receiver idle, "
                        f"points={len(offset_list)}, raw_bytes={raw_bytes_received}, "
                        f"queue_items={queue_items_received}, idle={no_data_elapsed:.2f}s, "
                        f"elapsed={elapsed:.2f}s"
                    )
                    break

                if not got_data and elapsed >= OFFSET_INITIAL_DATA_TIMEOUT_SECONDS:
                    logger.warning(
                        "Offset flow: initial data timeout, "
                        f"queue_size={self.data_queue.qsize()}, "
                        f"elapsed={elapsed:.2f}s, "
                        f"raw_bytes={raw_bytes_received}, "
                        f"measurement_active={self._measurement_active}, "
                        f"offset_calibrating={self._offset_calibrating}"
                    )
                    break

                time.sleep(OFFSET_QUEUE_POLL_SECONDS)

            # 处理完成，计算偏置值
            if len(offset_list) > 0:
                # 进行低通滤波
                filtered_offset_list = self._lowpass_filter(offset_list)
                total_len = len(filtered_offset_list)

                # Use the stable middle window: for 5s collection, keep the middle 3s.
                trim_ratio = 0.0
                if OFFSET_COLLECTION_SECONDS > 0 and OFFSET_STABLE_WINDOW_SECONDS > 0:
                    trim_ratio = max(
                        0.0,
                        (OFFSET_COLLECTION_SECONDS - OFFSET_STABLE_WINDOW_SECONDS)
                        / (2 * OFFSET_COLLECTION_SECONDS),
                    )

                start_index = int(total_len * trim_ratio)
                end_index = int(total_len * (1.0 - trim_ratio))

                if start_index < end_index:
                    middle_data = filtered_offset_list[start_index:end_index]
                else:
                    middle_data = filtered_offset_list

                logger.info(
                    "Offset flow: calculating offset, "
                    f"raw_points={len(offset_list)}, filtered_points={total_len}, "
                    f"middle_range={start_index}:{end_index}, middle_points={len(middle_data)}, "
                    f"trim_ratio={trim_ratio:.3f}"
                )
                self.mag_offset = statistics.mean(middle_data)

                # 保存偏置值到配置文件
                self.config.offset = self.mag_offset
                logger.info(
                    "Offset flow: calibration succeeded, "
                    f"offset={self.mag_offset:.1f} ADC ({self.mag_offset/self.ADC_PER_MT:.3f} mT), "
                    f"config_file={getattr(self.config, 'config_file', '')}"
                )
                logger.info("Offset flow: emitting finished signal, success=True")
                self.signal_offset_data_process_finished.emit(True)
            else:
                logger.warning("Offset flow: no valid offset data received")
                logger.info("Offset flow: emitting finished signal, success=False")
                self.signal_offset_data_process_finished.emit(False)

        except Exception as e:
            logger.error(f"处理偏置数据时发生错误: {e}", exc_info=True)
            logger.info("Offset flow: emitting finished signal after exception, success=False")
            self.signal_offset_data_process_finished.emit(False)

    # ========================================================================
    # 测量数据算法处理
    # ========================================================================

    @staticmethod
    def _candidate_range(lower: int, upper: int, max_count: int) -> np.ndarray:
        if upper < lower:
            return np.array([], dtype=int)

        count = upper - lower + 1
        if count <= max_count:
            return np.arange(lower, upper + 1, dtype=int)
        return np.unique(np.linspace(lower, upper, max_count, dtype=int))

    @staticmethod
    def _slope_sign(value: float, threshold: float) -> int:
        if value > threshold:
            return 1
        if value < -threshold:
            return -1
        return 0

    def _classify_local_shape(
        self,
        data: np.ndarray,
        index: int,
        span: int,
        value_scale: float,
    ) -> Tuple[str, float, Optional[float]]:
        """Classify local waveform shape around an index."""
        if span <= 0 or index + span >= len(data):
            return "unknown", 0.0, None

        slope_threshold = max(value_scale * 1e-4, 1e-9)
        extremum_tolerance = max(value_scale * CLOSURE_EXTREMUM_VALUE_TOLERANCE_RATIO, slope_threshold)
        center_value = float(data[index])
        forward_slope = float(data[index + span] - data[index])
        approach_slope = None
        if index - span >= 0:
            approach_slope = float(data[index] - data[index - span])

        forward_sign = self._slope_sign(forward_slope, slope_threshold)
        approach_sign = self._slope_sign(approach_slope, slope_threshold) if approach_slope is not None else 0

        if approach_sign > 0 and forward_sign < 0:
            return "peak", forward_slope, approach_slope
        if approach_sign < 0 and forward_sign > 0:
            return "valley", forward_slope, approach_slope
        if approach_sign >= 0 and forward_sign >= 0 and (approach_sign > 0 or forward_sign > 0):
            return "rising", forward_slope, approach_slope
        if approach_sign <= 0 and forward_sign <= 0 and (approach_sign < 0 or forward_sign < 0):
            return "falling", forward_slope, approach_slope

        window_start = max(0, index - span)
        window_end = min(len(data), index + span + 1)
        local_window = data[window_start:window_end]
        if len(local_window) > 0:
            local_max = float(np.max(local_window))
            local_min = float(np.min(local_window))
            if center_value >= local_max - extremum_tolerance:
                return "peak", forward_slope, approach_slope
            if center_value <= local_min + extremum_tolerance:
                return "valley", forward_slope, approach_slope

        if index - span >= 0:
            wide_slope = float(data[index + span] - data[index - span])
            wide_sign = self._slope_sign(wide_slope, slope_threshold)
            if wide_sign > 0:
                return "rising", forward_slope, approach_slope
            if wide_sign < 0:
                return "falling", forward_slope, approach_slope

        return "unknown", forward_slope, approach_slope

    def _score_closure_candidate(
        self,
        data: np.ndarray,
        candidate_index: int,
        slope_span: int,
        head_first_value: float,
        head_shape: str,
        value_scale: float,
    ) -> float:
        candidate_shape, _, _ = self._classify_local_shape(
            data,
            candidate_index,
            slope_span,
            value_scale,
        )
        if candidate_shape != head_shape:
            return float("inf")
        value_score = abs(float(data[candidate_index]) - head_first_value) / value_scale
        return value_score

    @staticmethod
    def _estimate_cycle_count(segment: np.ndarray) -> int:
        """估算一圈数据中的磁周期数，用于自适应限制闭合点搜索范围。"""
        if len(segment) < 4:
            return 1

        centered = segment - float(np.mean(segment))
        signs = np.sign(centered)
        nonzero_mask = signs != 0
        if np.any(nonzero_mask):
            signs = signs[nonzero_mask]
        zero_crossings = int(np.sum(signs[:-1] * signs[1:] < 0)) if len(signs) > 1 else 0
        zero_crossing_cycles = int(round(zero_crossings / 2)) if zero_crossings >= 2 else 0

        fft_cycles = 0
        try:
            max_fft_points = 32768
            if len(centered) > max_fft_points:
                sample_indices = np.linspace(0, len(centered) - 1, max_fft_points, dtype=int)
                fft_segment = centered[sample_indices]
            else:
                fft_segment = centered

            fft_segment = fft_segment - float(np.mean(fft_segment))
            spectrum = np.abs(np.fft.rfft(fft_segment))
            if len(spectrum) > 1:
                spectrum[0] = 0
                fft_cycles = int(np.argmax(spectrum))
        except Exception:
            fft_cycles = 0

        if zero_crossing_cycles > 0:
            return zero_crossing_cycles
        if fft_cycles > 0:
            return fft_cycles
        return 1

    def _estimate_period_points(self, segment: np.ndarray, fallback_points: int) -> float:
        """Estimate one magnetic period from the roughly sliced one-rotation data."""
        segment = np.asarray(segment, dtype=float)
        if len(segment) < 4:
            return float(fallback_points)

        centered = segment - float(np.mean(segment))
        crossing_points = []
        min_crossing_gap = max(5.0, len(centered) / 10000.0)

        for index in range(1, len(centered)):
            previous_value = float(centered[index - 1])
            current_value = float(centered[index])
            if previous_value == current_value:
                continue
            if (previous_value <= 0 <= current_value) or (previous_value >= 0 >= current_value):
                crossing_index = (index - 1) + (0.0 - previous_value) / (current_value - previous_value)
                direction = 1 if current_value >= previous_value else -1
                if crossing_points and crossing_index - crossing_points[-1][0] < min_crossing_gap:
                    continue
                crossing_points.append((crossing_index, direction))

        same_direction_diffs = []
        last_crossing_by_direction = {}
        for crossing_index, direction in crossing_points:
            if direction in last_crossing_by_direction:
                same_direction_diffs.append(crossing_index - last_crossing_by_direction[direction])
            last_crossing_by_direction[direction] = crossing_index

        if same_direction_diffs:
            estimated_period = float(statistics.median(same_direction_diffs))
            if estimated_period >= CLOSURE_MIN_PERIOD_POINTS:
                return estimated_period

        cycle_count = self._estimate_cycle_count(segment)
        if cycle_count > 0:
            estimated_period = float(len(segment)) / float(cycle_count)
            if estimated_period >= CLOSURE_MIN_PERIOD_POINTS:
                return estimated_period

        return float(fallback_points)

    def _find_best_rotation_closure(
        self,
        data: List[float],
        start_index: int,
        rough_end_index: int,
        estimated_period_points: float,
    ) -> Tuple[int, bool, float]:
        """在粗尾点附近寻找与起点局部形态一致、数值最接近的闭合点。"""
        total_length = len(data)
        if total_length <= 1:
            return 0, False, float("nan")

        data_array = np.asarray(data, dtype=float)
        start_index = max(0, min(total_length - 1, start_index))
        rough_end_index = max(start_index + 1, min(total_length - 1, rough_end_index))
        rough_points = rough_end_index - start_index
        search_radius = max(
            CLOSURE_MIN_DIRECTION_SPAN_POINTS,
            int(round(estimated_period_points * CLOSURE_SEARCH_PERIOD_FRACTION)),
        )
        slope_span = max(
            CLOSURE_MIN_DIRECTION_SPAN_POINTS,
            int(round(estimated_period_points * CLOSURE_DIRECTION_PERIOD_FRACTION)),
        )
        slope_span = min(CLOSURE_MAX_DIRECTION_SPAN_POINTS, slope_span)
        slope_span = min(
            slope_span,
            max(1, start_index),
            max(1, total_length - rough_end_index - 1),
        )
        logger.info(
            "闭合点局部搜索: "
            f"粗截取范围={start_index}-{rough_end_index}, "
            f"粗截取点数={rough_points}, "
            f"估算周期点数={estimated_period_points:.1f}, "
            f"1/4周期搜索半径={search_radius}, "
            f"趋势判断跨度={slope_span}, "
            f"粗尾点索引={rough_end_index}"
        )
        lower = max(start_index + 1, rough_end_index - search_radius)
        upper = min(total_length - 1, rough_end_index + search_radius)

        # 趋势判断需要候选闭合点之后仍有一小段数据。
        min_points_after_candidate = slope_span + 1
        if total_length - upper < min_points_after_candidate:
            upper = total_length - min_points_after_candidate
        if upper < lower:
            return rough_end_index, False, float("nan")

        head_first_value = float(data_array[start_index])
        value_scale = max(
            float(np.ptp(data_array[start_index:rough_end_index + 1])),
            1e-6,
        )
        head_shape, head_forward_slope, head_approach_slope = self._classify_local_shape(
            data_array,
            start_index,
            slope_span,
            value_scale,
        )
        if head_shape == "unknown":
            logger.warning("闭合点局部搜索失败：起始点局部形态无法判断，将回退为粗截取。")
            return rough_end_index, False, float("nan")

        coarse_candidates = self._candidate_range(lower, upper, CLOSURE_COARSE_CANDIDATE_COUNT)
        if len(coarse_candidates) == 0:
            return rough_end_index, False, float("nan")

        best_index = int(coarse_candidates[0])
        best_score = float("inf")
        for candidate_index in coarse_candidates:
            score = self._score_closure_candidate(
                data_array,
                int(candidate_index),
                slope_span,
                head_first_value,
                head_shape,
                value_scale,
            )
            if score < best_score:
                best_index = int(candidate_index)
                best_score = score

        if not np.isfinite(best_score):
            logger.warning(
                "闭合点局部搜索失败：粗尾点前后各1/4磁周期范围内没有找到与起点趋势一致的候选点，"
                "将回退为粗截取。"
            )
            return rough_end_index, False, float("nan")

        fine_lower = max(lower, best_index - CLOSURE_FINE_RADIUS_POINTS)
        fine_upper = min(upper, best_index + CLOSURE_FINE_RADIUS_POINTS)
        for candidate_index in range(fine_lower, fine_upper + 1):
            score = self._score_closure_candidate(
                data_array,
                candidate_index,
                slope_span,
                head_first_value,
                head_shape,
                value_scale,
            )
            if score < best_score:
                best_index = candidate_index
                best_score = score

        logger.info(
            "闭合点选择完成: "
            f"起点形态={head_shape}, "
            f"起点前向斜率={head_forward_slope:.6f}, "
            f"起点接近斜率={head_approach_slope if head_approach_slope is not None else float('nan'):.6f}, "
            f"闭合点索引={best_index}, 闭合点偏移={best_index - rough_end_index}, "
            f"首尾磁值差={float(data_array[best_index] - data_array[start_index]):.6f}, "
            f"score={best_score:.6f}"
        )
        return best_index, True, best_score

    def _process_measure_algorithm(self, measure_list: List[float]) -> Tuple[List[float], List[float]]:
        """
        测量数据处理算法

        对原始测量数据进行算法处理，提取360度完整旋转的数据。

        算法流程：
        1. 低通滤波去除高频噪声
        2. 使用预计算常量确定中间一段360°数据的大致范围
        3. 在理论一圈点数附近搜索最佳首尾闭合点
        4. 根据实际闭合点数重新计算角度分辨率

        Args:
            measure_list: 原始测量数据列表

        Returns:
            Tuple[angle_data, mag_data]: 角度列表和磁场强度列表
        """
        if not measure_list:
            logger.warning("测量数据为空，无法处理")
            return [], []

        # Step 1: 低通滤波
        measure_list = self._lowpass_filter(measure_list)

        # Step 2: 按 rawdata 的 1/6 到 5/6 粗截取一圈，并在 5/6 附近寻找闭合点。
        total_length = len(measure_list)
        closure_found = False
        closure_score = float("nan")

        # 数据充足时：rawdata 为一圈半数据，1/6 到 5/6 为中间完整一圈的粗范围。
        if total_length >= 6:
            start_index = int(round(total_length * CLOSURE_ROUGH_START_FRACTION))
            rough_end_index = int(round(total_length * CLOSURE_ROUGH_END_FRACTION))
            start_index = max(0, min(total_length - 2, start_index))
            rough_end_index = max(start_index + 1, min(total_length - 1, rough_end_index))
            fallback_period_points = max(
                CLOSURE_MIN_PERIOD_POINTS,
                float(max(1, rough_end_index - start_index)),
            )
            estimated_period_points = self._estimate_period_points(
                np.asarray(measure_list, dtype=float),
                fallback_period_points,
            )
            end_index, closure_found, closure_score = self._find_best_rotation_closure(
                measure_list,
                start_index,
                rough_end_index,
                estimated_period_points,
            )
        # 数据严重不足：取全部数据
        else:
            start_index = 0
            end_index = total_length - 1
            logger.warning(f"数据严重不足，取全部数据: {total_length} 个点")

        # 提取数据。闭合失败时 end_index 已经回退为 5/6 粗尾点。
        extracted_values = measure_list[start_index:end_index + 1]
        data_length = len(extracted_values)

        logger.info(f"提取数据: 索引 {start_index} - {end_index}，共 {data_length} 个数据点")

        # Step 3: 用实际闭合点数计算角度分辨率（0-360°）
        if data_length > 1:
            actual_angle_resolution = 360.0 / data_length
            extracted_angles = [i * actual_angle_resolution for i in range(data_length)]
            logger.info(
                "截取角度自校准完成: "
                f"一圈点数={data_length}, "
                f"分辨率={actual_angle_resolution:.9f}°/点, "
                f"closure_found={closure_found}, score={closure_score:.6f}"
            )
        else:
            extracted_angles = [i * (360.0 / max(data_length, 1)) for i in range(data_length)]
            logger.warning(f"闭合点自校准未启用，数据长度={data_length}")

        # 保留6位小数精度
        angle_data_for_plot = [round(v, 6) for v in extracted_angles]
        value_data_for_plot = [round(v, 6) for v in extracted_values]

        logger.info("数据处理完成")

        return angle_data_for_plot, value_data_for_plot

    # ========================================================================
    # 数据保存
    # ========================================================================

    def save_raw_measure_data(self, measure_list: List[float]) -> Optional[str]:
        """
        保存原始测量数据到CSV文件

        将测量原始数据保存到文件，用于数据追溯和离线分析。

        Args:
            measure_list: 测量数据列表

        Returns:
            文件路径，保存失败返回None
        """
        try:
            raw_data_dir = get_data_dir("raw_data")

            # 创建目录（如果不存在）
            if not os.path.exists(raw_data_dir):
                os.makedirs(raw_data_dir)

            # 生成文件名：raw_measure_data_YYYYMMDD_HHMMSS.csv
            current_time = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"raw_measure_data_{current_time}.csv"
            filepath = os.path.join(raw_data_dir, filename)

            # 写入CSV文件
            with open(filepath, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)

                # 写入样品信息
                if self._sample_info:
                    writer.writerow(['样品编号', self._sample_info.get('sample_code', '')])
                    writer.writerow(['样品名称', self._sample_info.get('sample_name', '')])
                    writer.writerow(['材料', self._sample_info.get('material', '')])
                    writer.writerow(['线圈编号', self._sample_info.get('coil_code', '')])
                    writer.writerow(['备注', self._sample_info.get('remark', '')])
                    writer.writerow(['保存时间', current_time])
                    writer.writerow([])  # 空行分隔

                writer.writerow(['原始测量值'])  # 表头
                for value in measure_list:
                    writer.writerow([value])

            logger.info(f"原始测量数据已保存到: {filepath}，共 {len(measure_list)} 个数据点")
            return filepath

        except Exception as e:
            logger.error(f"保存原始测量数据失败: {e}")
            return None

    def save_plot_measure_data(self, angle_data: List[float], mag_data: List[float],
                               analysis_results: dict = None) -> Optional[str]:
        """
        保存处理后的测量数据到CSV文件

        将角度和磁场强度数据保存到文件，用于数据追溯和离线分析。

        Args:
            angle_data: 角度数据列表
            mag_data: 磁场强度数据列表
            analysis_results: 波形分析结果字典（选填）

        Returns:
            文件路径，保存失败返回None
        """
        try:
            # 生成文件名：样品名称_YYYYMMDD_HHMMSS.csv
            now = datetime.now()
            date_folder = now.strftime("%Y%m%d")
            current_time = now.strftime("%Y%m%d_%H%M%S")
            plot_data_dir = os.path.join(get_data_dir("plot_data"), date_folder)

            # 创建当天目录（如果不存在）
            os.makedirs(plot_data_dir, exist_ok=True)

            sample_name = self._sample_info.get('sample_name', '未命名') if self._sample_info else '未命名'
            filename = f"{sample_name}_{current_time}.csv"
            filepath = os.path.join(plot_data_dir, filename)

            # 写入CSV文件（格式参考现有plot_data）
            with open(filepath, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)

                # 写入样品信息头
                if self._sample_info:
                    writer.writerow(['样品名称', self._sample_info.get('sample_name', '')])
                    writer.writerow(['测试员', self._sample_info.get('tester', '')])
                    writer.writerow(['磁化条件', self._sample_info.get('mag_condition', '')])
                    writer.writerow(['探头', self._sample_info.get('probe', '')])
                    writer.writerow(['样品编号', self._sample_info.get('sample_code', '')])
                    writer.writerow(['材料', self._sample_info.get('material', '')])
                    writer.writerow(['极数', self._sample_info.get('polar_num', '')])
                    writer.writerow(['气隙', self._sample_info.get('airgap', '')])
                    writer.writerow(['备注', self._sample_info.get('remark', '')])
                    writer.writerow(['线圈编号', self._sample_info.get('coil_code', '')])
                    writer.writerow(['保存时间', current_time])
                else:
                    writer.writerow(['样品名称', sample_name])
                    writer.writerow(['保存时间', current_time])

                # 写入分析结果
                if analysis_results:
                    writer.writerow([])  # 空行分隔
                    writer.writerow(['=== 分析结果 ==='])
                    writer.writerow(['N极最大值', analysis_results.get('N_max', '')])
                    writer.writerow(['N极最小值', analysis_results.get('N_min', '')])
                    writer.writerow(['N极平均值', analysis_results.get('N_mean', '')])
                    writer.writerow(['N极误差', analysis_results.get('N_se', '')])
                    writer.writerow(['S极最大值', analysis_results.get('S_max', '')])
                    writer.writerow(['S极最小值', analysis_results.get('S_min', '')])
                    writer.writerow(['S极平均值', analysis_results.get('S_mean', '')])
                    writer.writerow(['S极误差', analysis_results.get('S_se', '')])
                    writer.writerow(['NS_2', analysis_results.get('NS_2', '')])
                    writer.writerow(['单极平均值', analysis_results.get('SinglePolarMean', '')])
                    writer.writerow(['单极误差', analysis_results.get('SinglePolarError', '')])
                    writer.writerow(['极误差和', analysis_results.get('PolarErrorSum', '')])
                    writer.writerow(['N极间隔最大值', analysis_results.get('N_interval_max', '')])
                    writer.writerow(['N极间隔最小值', analysis_results.get('N_interval_min', '')])
                    writer.writerow(['N极间隔平均值', analysis_results.get('N_interval_mean', '')])
                    writer.writerow(['N极间隔误差', analysis_results.get('N_interval_std', '')])
                    writer.writerow(['S极间隔最大值', analysis_results.get('S_interval_max', '')])
                    writer.writerow(['S极间隔最小值', analysis_results.get('S_interval_min', '')])
                    writer.writerow(['S极间隔平均值', analysis_results.get('S_interval_mean', '')])
                    writer.writerow(['S极间隔误差', analysis_results.get('S_interval_std', '')])
                    writer.writerow(['N极面积', analysis_results.get('N_area', '')])
                    writer.writerow(['S极面积', analysis_results.get('S_area', '')])
                    writer.writerow(['NS面积', analysis_results.get('NS_area', '')])
                    writer.writerow(['THD失真率', analysis_results.get('THD_error', '')])
                    zero_details = analysis_results.get('zero_crossing_details')
                    zero_count = len(zero_details) if isinstance(zero_details, list) else ''
                    writer.writerow(['过零点个数', zero_count])

                writer.writerow([])  # 空行分隔

                # 写入数据表头
                writer.writerow(['角度(度)', '磁场强度'])

                # 写入数据
                for angle, mag in zip(angle_data, mag_data):
                    writer.writerow([f"{angle:.6f}", f"{mag:.5f}"])

            logger.info(f"处理后测量数据已保存到: {filepath}，共 {len(angle_data)} 个数据点")
            return filepath

        except Exception as e:
            logger.error(f"保存处理后测量数据失败: {e}")
            return None

    # ========================================================================
    # 其他
    # ========================================================================

    def stop(self) -> None:
        """
        停止数据处理

        用于清理资源和停止后台处理任务。
        """
        logger.info("数据处理停止")
