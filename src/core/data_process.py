# -*- coding: utf-8 -*-
"""
数据处理模块

负责处理串口接收的各种数据，包括：
- 位置数据：解析X/Z轴位置信息
- 测量数据：解析磁场强度数据并进行算法处理
- 偏置数据：计算磁场偏置值
- 自检消息：检测设备自检完成状态

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
)

logger = get_logger('DataProcess')

# ============================================================================
# 常量定义
# ============================================================================
FULL_ROTATION_DATA_POINTS = 407040  # 一圈半（540度）的数据点数
FULL_ROTATION_ANGLE = 540 - 1.75  # 一圈半的角度（度）
ANGLE_RESOLUTION = FULL_ROTATION_ANGLE / FULL_ROTATION_DATA_POINTS  # 角度分辨率（度/数据点），约0.001326530612
START_OFFSET = int(FULL_ROTATION_DATA_POINTS * 90 / FULL_ROTATION_ANGLE)  # 90度对应的数据偏移 = 67840
POINTS_FOR_360 = int(FULL_ROTATION_DATA_POINTS * 360 / FULL_ROTATION_ANGLE)  # 360度对应的数据点数
PROGRESS_EMIT_INTERVAL_SECONDS = 1.0 / 16.0
OFFSET_INITIAL_DATA_TIMEOUT_SECONDS = 1.5
OFFSET_NO_DATA_TIMEOUT_SECONDS = 0.5
OFFSET_QUEUE_POLL_SECONDS = 0.02
OFFSET_COLLECT_LOG_INTERVAL_SECONDS = 1.0
SELF_DETECT_BUFFER_LIMIT = 4096
SELF_DETECT_LOG_PREVIEW_LIMIT = 220
SELF_DETECT_FINISH_PATTERNS = {
    "Z": re.compile(r"Z\s*(?:Axis\s*)?Self\s*Detect\s*Finished", re.IGNORECASE),
    "X": re.compile(r"X\s*(?:Axis\s*)?Self\s*Detect\s*Finished", re.IGNORECASE),
}


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
    signal_position_data_process_finished = pyqtSignal(tuple)           # 位置数据处理完成信号
    signal_offset_data_process = pyqtSignal()                           # 偏置数据处理信号
    signal_offset_data_process_finished = pyqtSignal(bool)              # 偏置数据处理完成信号
    signal_measure_data_process = pyqtSignal()                          # 测量数据处理信号
    signal_measure_data_process_finished = pyqtSignal(object, object)   # 测量数据处理完成信号
    signal_measure_data_progress = pyqtSignal(int, int)                 # 测量数据处理进度信号 (当前数据量, 总数据量)
    signal_self_detect_process = pyqtSignal()                           # 自检消息处理信号
    signal_self_detect_finished = pyqtSignal(str)                       # 自检完成信号，参数为轴 ('X'/'Z')
    # ========================================================================
    # 类属性（转换系数）
    # ========================================================================
    # 磁场转换系数：将原始HEX值转换为物理单位（mT）
    # 计算公式：5.12V * 1000mV / (2^16 - 1) / 1.25V * 0.1mT/V
    MAG_CONVERSION_FACTOR = 5.12 * 1000 / (65536 - 1) / 1.25 * 0.1
    DEFAULT_OFFSET = 2500 / 1.25 * 0.1  # 默认偏置值
    SAMPLING_FREQ = 27000  # 采样频率 (Hz)
    CUTOFF_RATIO = 70  # 截止频率与采样频率的比值

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
        self.mag_offset = self.config.offset or self.DEFAULT_OFFSET

        # 测量类型：'rotation' - 旋转测量，'vertical' - 垂直测量
        self.measure_type: str = "rotation"
        self.enable_concentricity_calibration: bool = True

        # 位置数据：最后处理的位置数据 (x_position, z_position)
        self.position_data: Optional[tuple] = None

        # 偏置校准标志：用于阻止位置数据处理干扰偏置校准
        self._offset_calibrating: bool = False
        self._offset_calibrating: bool = False
        self._self_detecting: bool = False
        self._self_detect_text_buffer: str = ""

        # 测量停止标志：用于中途停止测量时立即处理已采集的数据
        self._stop_measure_processing: bool = False

        # 样品信息：用于保存测量数据时写入文件
        self._sample_info: dict = {}
        self._wave_analyzer = WaveAnalysis()

        logger.info(f"初始化数据处理模块完成：√")

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
        """Persist measurement data and emit processed results."""
        if not measure_list:
            return

        logger.info(f"娴嬮噺鏁版嵁鎺ユ敹瀹屾垚锛屽叡 {len(measure_list)} 涓暟鎹偣")
        self.signal_measure_data_progress.emit(len(measure_list), len(measure_list))
        self.save_raw_measure_data(measure_list)

        if self.measure_type == "vertical":
            angle_data = list(range(len(measure_list)))
            mag_data = measure_list
            analysis_results = None
        else:
            angle_data, mag_data = self._process_measure_algorithm(measure_list)
            analysis_results = self._wave_analyzer.analyze_waveform(
                angle_data,
                mag_data,
                self.enable_concentricity_calibration,
            )

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

    def clear_self_detect_buffer(self) -> None:
        """Clear buffered self-detect text fragments."""
        self._self_detect_text_buffer = ""

    def _append_self_detect_text(self, text: str) -> str:
        self._self_detect_text_buffer = (
            self._self_detect_text_buffer + text
        )[-SELF_DETECT_BUFFER_LIMIT:]
        return self._self_detect_text_buffer

    @staticmethod
    def _text_preview(text: str, limit: int = SELF_DETECT_LOG_PREVIEW_LIMIT) -> str:
        preview = text.replace("\r", "\\r").replace("\n", "\\n")
        if len(preview) > limit:
            return preview[:limit] + "..."
        return preview

    def get_self_detect_buffer_preview(self) -> str:
        return self._text_preview(self._self_detect_text_buffer)

    # ========================================================================
    # 自检消息检测
    # ========================================================================

    # 类变量，用于累积位置数据（避免数据被意外覆盖）
    _position_buffer = bytearray()

    def check_self_detect(self) -> bool:
        """
        检测自检完成消息

        从队列中读取串口数据，检测是否包含自检完成消息。
        自检完成消息格式：
        - "X Axis Self Detect Finished" - X轴自检完成
        - "Z Axis Self Detect Finished" - Z轴自检完成

        使用非阻塞方式持续读取队列，直到找到自检完成消息或队列为空。

        Returns:
            是否检测到自检完成消息
        """
        start_time = time.time()
        item_count = 0
        ignored_position_packets = 0
        try:
            while True:
                # 非阻塞读取队列数据
                try:
                    data = self.data_queue.get_nowait()
                    item_count += 1
                except queue.Empty:
                    break

                text = data.decode('utf-8', errors='ignore')
                buffered_text = self._append_self_detect_text(text)
                if logger.isEnabledFor(10):
                    logger.debug(
                        "Adhesion flow: self detect RX chunk, "
                        f"item={item_count}, bytes={len(data)}, queue_remaining={self.data_queue.qsize()}, "
                        f"preview={self._text_preview(text)}"
                    )

                # 检测是否是位置数据（格式：X:****,Z:****），如果是则放回队列不消费
                # Consume stale position packets during self-detect.
                if re.search(r'X:-?\d+,Z:-?\d+', text):
                    ignored_position_packets += 1

                # 检测Z轴自检完成
                if SELF_DETECT_FINISH_PATTERNS["Z"].search(buffered_text):
                    logger.debug("Z axis self detect finished.")
                    logger.info(
                        "Adhesion flow: Z self detect finish detected, "
                        f"items={item_count}, ignored_position_packets={ignored_position_packets}, "
                        f"queue_remaining={self.data_queue.qsize()}, "
                        f"elapsed={time.time() - start_time:.2f}s"
                    )
                    self.clear_self_detect_buffer()
                    self.signal_self_detect_finished.emit('Z')
                    return True
                # 检测X轴自检完成
                elif SELF_DETECT_FINISH_PATTERNS["X"].search(buffered_text):
                    logger.debug("X axis self detect finished.")
                    logger.info(
                        "Adhesion flow: X self detect finish detected, "
                        f"items={item_count}, ignored_position_packets={ignored_position_packets}, "
                        f"queue_remaining={self.data_queue.qsize()}, "
                        f"elapsed={time.time() - start_time:.2f}s"
                    )
                    self.clear_self_detect_buffer()
                    self.signal_self_detect_finished.emit('X')
                    return True

            if item_count and ignored_position_packets and logger.isEnabledFor(10):
                logger.debug(
                    "Adhesion flow: ignored stale position packets during self detect, "
                    f"items={item_count}, ignored_position_packets={ignored_position_packets}, "
                    f"queue_remaining={self.data_queue.qsize()}"
                )
            if item_count and logger.isEnabledFor(10):
                logger.debug(
                    "Adhesion flow: self detect scan ended without finish, "
                    f"items={item_count}, buffer_chars={len(self._self_detect_text_buffer)}, "
                    f"buffer_preview={self.get_self_detect_buffer_preview()}"
                )

        except Exception as e:
            logger.error(f"检测自检完成消息失败: {e}")

        return False

    # ========================================================================
    # 位置数据处理
    # ========================================================================

    def process_position_data(self) -> None:
        """
        处理位置数据

        从队列中读取串口返回的位置数据，解析X轴和Z轴的当前位置。
        数据格式示例："X:****,Z:****"

        解析流程：
        1. 持续等待数据（最常1.5秒），直到解析到位置数据
        2. 尝试解码为UTF-8文本
        3. 解析X和Z的位置值
        4. 发出完成信号
        """
        # 如果正在偏置校准，跳过位置数据处理，避免干扰
        if self._offset_calibrating:
            self.signal_position_data_process_finished.emit((None, None))
            return
        if self._self_detecting:
            logger.debug("Adhesion flow: position processing skipped during self detect.")
            self.signal_position_data_process_finished.emit((None, None))
            return

        x_position: Optional[str] = None
        z_position: Optional[str] = None

        # 清空之前的位置缓冲区
        DataProcess._position_buffer.clear()

        # 总超时1.5秒，持续等待位置数据
        import time as time_module
        start_time = time_module.time()

        while time_module.time() - start_time < 1.5:
            if self._self_detecting:
                logger.debug("Adhesion flow: in-flight position processing stopped for self detect.")
                self.signal_position_data_process_finished.emit((None, None))
                return
            # 使用非阻塞get_nowait() +短暂sleep，让Qt事件循环处理其他信号
            try:
                data = self.data_queue.get_nowait()
                DataProcess._position_buffer.extend(data)

                # 尝试解码
                try:
                    text = DataProcess._position_buffer.decode('utf-8')
                    # 查找最后一个完整的 X:数字,Z:数字 模式（支持负数）
                    import re
                    pattern = r'X:(-?\d+),Z:(-?\d+)'
                    matches = re.findall(pattern, text)
                    if matches:
                        last_match = matches[-1]
                        x_position = last_match[0]
                        z_position = last_match[1]
                        break  # 解析成功，退出循环
                except UnicodeDecodeError:
                    pass

            except queue.Empty:
                # 队列为空，短暂等待后重试（让出CPU给Qt事件循环处理其他信号）
                time_module.sleep(0.05)

        # 保存位置数据（即使解析失败也发送信号）
        self.signal_position_data_process_finished.emit((x_position, z_position))

    # ========================================================================
    # 测量数据处理
    # ========================================================================

    def process_measure_data(self) -> None:
        """Collect raw measurement bytes and emit processed results."""
        logger.info("========== Start processing measurement data ==========")
        logger.info(f"Measurement type: {self.measure_type}")
        logger.info(f"Current offset: {self.mag_offset}")

        self._stop_measure_processing = False

        try:
            temp_buffer = bytearray()
            measure_list: List[float] = []
            no_data_count = 0
            last_progress_emit_time = 0.0

            max_empty_count = 4
            while True:
                if self._stop_measure_processing:
                    logger.info("Measurement processing stopped by request")
                    if measure_list:
                        logger.info(f"Measurement data collection completed: {len(measure_list)} points")
                        self._emit_measurement_results(measure_list)
                    break

                if len(temp_buffer) >= 2:
                    group_count = len(temp_buffer) // 2
                    batch_size = min(group_count, 100)

                    for i in range(batch_size):
                        byte1 = temp_buffer[i * 2]
                        byte2 = temp_buffer[i * 2 + 1]
                        hex_value = (byte1 << 8) | byte2
                        mag_value = round(hex_value * self.MAG_CONVERSION_FACTOR - self.mag_offset, 4)
                        measure_list.append(mag_value)

                    del temp_buffer[0:batch_size * 2]

                    current_time = time.time()
                    if current_time - last_progress_emit_time >= PROGRESS_EMIT_INTERVAL_SECONDS:
                        self.signal_measure_data_progress.emit(
                            len(measure_list),
                            FULL_ROTATION_DATA_POINTS,
                        )
                        last_progress_emit_time = current_time

                if len(temp_buffer) < 2:
                    try:
                        data = self.data_queue.get_nowait()
                        temp_buffer.extend(data)
                        no_data_count = 0
                        continue
                    except queue.Empty:
                        no_data_count += 1
                        time.sleep(0.5)

                        if self._stop_measure_processing:
                            logger.info("Measurement processing stopped by request while waiting for data")
                            if measure_list:
                                logger.info(f"Measurement data collection completed: {len(measure_list)} points")
                                self._emit_measurement_results(measure_list)
                            break

                        if no_data_count >= max_empty_count:
                            logger.warning(
                                f"Measurement receive timeout after {no_data_count} empty polls"
                            )
                            if measure_list:
                                logger.info(f"Measurement data collection completed: {len(measure_list)} points")
                                self._emit_measurement_results(measure_list)
                            else:
                                logger.warning("No valid measurement data received")
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
        6. 取中间90%数据的平均值作为偏置
        7. 保存到配置文件

        Note:
            保存的偏置值会在每次程序启动时加载，用于校正测量数据
        """
        try:
            start_time = time.time()
            last_data_time = start_time
            temp_buffer = bytearray()
            offset_list: List[float] = []
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

                # 2. 处理缓冲区中的所有数据
                while len(temp_buffer) >= 2:
                    byte1 = temp_buffer[0]
                    byte2 = temp_buffer[1]
                    hex_value = (byte1 << 8) | byte2
                    # 转换为磁场强度（mT），注意：偏置数据不使用偏置校正
                    mag_value = round(hex_value * self.MAG_CONVERSION_FACTOR, 4)
                    offset_list.append(mag_value)
                    del temp_buffer[0:2]

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
                        f"queue_size={self.data_queue.qsize()}, elapsed={elapsed:.2f}s"
                    )
                    break

                time.sleep(OFFSET_QUEUE_POLL_SECONDS)

            # 处理完成，计算偏置值
            if len(offset_list) > 0:
                # 进行低通滤波
                filtered_offset_list = self._lowpass_filter(offset_list)
                total_len = len(filtered_offset_list)

                # 取中间90%的数据（去掉首尾各5%）
                start_index = int(total_len * 0.05)
                end_index = int(total_len * 0.95)

                if start_index < end_index:
                    middle_data = filtered_offset_list[start_index:end_index]
                else:
                    middle_data = filtered_offset_list

                logger.info(
                    "Offset flow: calculating offset, "
                    f"raw_points={len(offset_list)}, filtered_points={total_len}, "
                    f"middle_range={start_index}:{end_index}, middle_points={len(middle_data)}"
                )
                self.mag_offset = statistics.mean(middle_data)

                # 保存偏置值到配置文件
                self.config.offset = self.mag_offset
                logger.info(
                    "Offset flow: calibration succeeded, "
                    f"offset={self.mag_offset:.4f} mT, "
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

    def _process_measure_algorithm(self, measure_list: List[float]) -> Tuple[List[float], List[float]]:
        """
        测量数据处理算法

        对原始测量数据进行算法处理，提取360度完整旋转的数据。

        算法流程：
        1. 低通滤波去除高频噪声
        2. 使用预计算常量提取中间一段360°的数据
        3. 用角度分辨率生成x轴数组，保留6位精度

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

        # Step 2: 使用预计算常量提取360度数据
        # 常量: POINTS_FOR_360=271360, START_OFFSET=67840
        total_length = len(measure_list)

        # 数据充足时：从偏移位置开始取360度数据
        if total_length >= START_OFFSET + POINTS_FOR_360:
            start_index = START_OFFSET
            end_index = start_index + POINTS_FOR_360
        # 数据不足时：从0开始取360度数据
        elif total_length >= POINTS_FOR_360:
            start_index = 0
            end_index = POINTS_FOR_360
            logger.warning(f"数据不足，从索引0开始取360度数据")
        # 数据仍不足：取全部数据
        else:
            start_index = 0
            end_index = total_length
            logger.warning(f"数据严重不足，取全部数据: {total_length} 个点")

        # 提取数据
        extracted_values = measure_list[start_index:end_index]
        data_length = len(extracted_values)

        logger.info(f"提取数据: 索引 {start_index} - {end_index}，共 {data_length} 个数据点")

        # Step 3: 用角度分辨率生成x轴数组（从0度开始）
        extracted_angles = [i * ANGLE_RESOLUTION for i in range(data_length)]

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
            plot_data_dir = get_data_dir("plot_data")

            # 创建目录（如果不存在）
            if not os.path.exists(plot_data_dir):
                os.makedirs(plot_data_dir)

            # 生成文件名：样品名称_YYYYMMDD_HHMMSS.csv
            current_time = datetime.now().strftime("%Y%m%d_%H%M%S")
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
