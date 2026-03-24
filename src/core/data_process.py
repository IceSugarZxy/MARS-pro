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
import time
import statistics
import os
import csv
from datetime import datetime

import numpy as np
from PyQt5.QtCore import QObject, pyqtSignal

from .logger import get_logger
from .config_manager import get_config_manager

logger = get_logger('DataProcess')

# ============================================================================
# 常量定义
# ============================================================================
FULL_ROTATION_DATA_POINTS = 407040  # 一圈半（540度）的数据点数
FULL_ROTATION_ANGLE = 540 - 1.75  # 一圈半的角度（度）
ANGLE_RESOLUTION = FULL_ROTATION_ANGLE / FULL_ROTATION_DATA_POINTS  # 角度分辨率（度/数据点），约0.001326530612
START_OFFSET = int(FULL_ROTATION_DATA_POINTS * 90 / FULL_ROTATION_ANGLE)  # 90度对应的数据偏移 = 67840
POINTS_FOR_360 = int(FULL_ROTATION_DATA_POINTS * 360 / FULL_ROTATION_ANGLE)  # 360度对应的数据点数


class DataProcess(QObject):
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
        self.data_queue = data_queue
        self.config = get_config_manager()

        # 从配置文件加载偏置值，如果不存在则使用默认值
        self.mag_offset = self.config.offset or self.DEFAULT_OFFSET

        # 测量类型：'rotation' - 旋转测量，'vertical' - 垂直测量
        self.measure_type: str = "rotation"

        # 位置数据：最后处理的位置数据 (x_position, z_position)
        self.position_data: Optional[tuple] = None

        # 样品信息：用于保存测量数据时写入文件
        self._sample_info: dict = {}

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
        logger.debug(f"样品信息已设置: {self._sample_info}")

    def update_sample_info(self, key: str, value) -> None:
        """
        更新样品信息中的单个字段

        Args:
            key: 字段名
            value: 字段值
        """
        self._sample_info[key] = value
        logger.debug(f"样品信息已更新: {key}={value}")

    def get_sample_info(self) -> dict:
        """
        获取当前样品信息副本

        Returns:
            样品信息字典副本
        """
        return self._sample_info.copy()

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

        Returns:
            是否检测到自检完成消息
        """
        logger.debug("check_self_detect: 开始检查自检完成消息")
        try:
            # 从队列中读取数据
            data = self.data_queue.get(timeout=0.5)
            text = data.decode('utf-8', errors='ignore')
            logger.debug(f"check_self_detect: 自检流程回信: {text.strip()}")

            # 检测是否是位置数据（格式：X:****,Z:****），如果是则放回队列不消费
            if text.strip().startswith('X:') and 'Z:' in text:
                logger.debug("check_self_detect: 收到位置数据，放回队列供process_position_data处理")
                self.data_queue.put(data)
                return False

            # 检测Z轴自检完成
            if 'Z Axis Self Detect Finished' in text:
                logger.info("check_self_detect: 检测到 Z 轴自检完成")
                self.signal_self_detect_finished.emit('Z')
                return True
            # 检测X轴自检完成
            elif 'X Axis Self Detect Finished' in text:
                logger.info("check_self_detect: 检测到 X 轴自检完成")
                self.signal_self_detect_finished.emit('X')
                return True
            else:
                logger.debug(f"check_self_detect: 不是自检完成消息，内容: {text.strip()}")

        except queue.Empty:
            logger.debug("check_self_detect: 队列为空")
            # 队列为空，说明没有自检完成消息，忽略
            pass
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
        x_position: Optional[str] = None
        z_position: Optional[str] = None

        # 清空之前的位置缓冲区
        DataProcess._position_buffer.clear()

        # 总超时1.5秒，持续等待位置数据
        total_timeout = 1.5
        start_time = time.time()

        while time.time() - start_time < total_timeout:
            try:
                data = self.data_queue.get(timeout=0.1)
                DataProcess._position_buffer.extend(data)
                logger.debug(f"process_position_data: 收到数据，长度={len(data)}")

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
                        logger.debug(f"位置数据解析完成: X={x_position}, Z={z_position}")
                        break  # 解析成功，退出循环
                except UnicodeDecodeError:
                    pass

            except queue.Empty:
                continue

        # 保存位置数据（即使解析失败也发送信号）
        position_data = (x_position, z_position)
        self.signal_position_data_process_finished.emit(position_data)

    # ========================================================================
    # 测量数据处理
    # ========================================================================

    def process_measure_data(self) -> None:
        """
        处理测量数据

        从队列中读取串口返回的磁场测量数据，进行解析和处理。

        数据格式：
        - 原始数据为2字节无符号整数（HEX格式）
        - 每两个字节组成一个测量值

        处理流程：
        1. 清空队列（确保只处理本次数据）
        2. 循环读取数据，直到20次（每次0.1秒）无新数据
        3. 将HEX值转换为物理单位
        4. 根据测量类型进行后续处理
        5. 保存原始数据到CSV文件

        Note:
            - 旋转测量：调用算法处理，提取360度数据
            - 垂直测量：直接返回原始数据
        """
        logger.debug("========== 开始处理测量数据 ==========")
        logger.debug(f"测量类型: {self.measure_type}")
        logger.debug(f"当前偏置值: {self.mag_offset}")

        try:
            temp_buffer = bytearray()      # 临时缓冲区
            measure_list: List[float] = []  # 测量值列表
            no_data_count = 0              # 连续无数据计数

            logger.debug("进入数据接收循环...")
            MAX_EMPTY_COUNT = 4  # 最大空队列计数（2秒）
            while True:
                # ============================================================
                # 处理缓冲区中的已有数据
                # ============================================================
                if len(temp_buffer) >= 2:
                    # 计算可以处理的数据组数（每2字节为一组）
                    group_count = len(temp_buffer) // 2
                    # 每批处理最多100组，避免一次处理过多
                    batch_size = min(group_count, 100)

                    for i in range(batch_size):
                        # 读取两个字节组成一个测量值
                        byte1 = temp_buffer[i * 2]
                        byte2 = temp_buffer[i * 2 + 1]
                        # 合并为16位无符号整数
                        hex_value = (byte1 << 8) | byte2
                        # 转换为磁场强度（mT）并减去偏置
                        mag_value = round(hex_value * self.MAG_CONVERSION_FACTOR - self.mag_offset, 4)
                        measure_list.append(mag_value)

                    # 已处理的数据从缓冲区删除
                    del temp_buffer[0:batch_size * 2]
                    # 发出进度信号，用于更新UI (当前数据量, 期望总数据量)
                    self.signal_measure_data_progress.emit(len(measure_list), FULL_ROTATION_DATA_POINTS)
                    logger.debug(f"缓冲区处理完成，本批处理 {batch_size} 组，当前总数据点: {len(measure_list)}，缓冲区剩余: {len(temp_buffer)} 字节")

                # ============================================================
                # 获取新数据
                # ============================================================
                if len(temp_buffer) < 2:
                    try:
                        data = self.data_queue.get_nowait()
                        temp_buffer.extend(data)
                        no_data_count = 0  # 重置空计数
                        logger.debug(f"从队列获取新数据: {len(data)} 字节，缓冲区当前: {len(temp_buffer)} 字节")
                        continue
                    except queue.Empty:
                        # 连续无数据，增加计数
                        no_data_count += 1
                        queue_size = self.data_queue.qsize()
                        logger.debug(f"队列为空，无数据计数: {no_data_count}/{MAX_EMPTY_COUNT}，队列大小: {queue_size}")
                        time.sleep(0.5)
                        # MAX_EMPTY_COUNT次无数据则认为测量完成
                        if no_data_count >= MAX_EMPTY_COUNT:
                            logger.warning(f"超时停止，已连续 {no_data_count} 次队列为空")
                            if len(measure_list) > 0:
                                logger.info(f"测量数据接收完成，共 {len(measure_list)} 个数据点")
                                # 保存原始数据到CSV
                                self.save_raw_measure_data(measure_list)

                                # 根据测量类型处理数据
                                if self.measure_type == "vertical":
                                    # 垂直测量：直接返回原始数据，不做预处理和分析
                                    # 生成等间距的角度数据（作为横坐标）
                                    angle_data = list(range(len(measure_list)))
                                    mag_data = measure_list
                                    logger.debug("垂直测量模式，直接返回原始数据")
                                else:
                                    # 旋转测量：调用算法处理
                                    logger.debug("旋转测量模式，开始调用算法处理...")
                                    angle_data, mag_data = self._process_measure_algorithm(measure_list)

                                # 发出完成信号
                                logger.debug(f"发送测量完成信号，数据点: {len(angle_data)}")
                                self.signal_measure_data_process_finished.emit(angle_data, mag_data)
                                logger.debug("========== 测量数据处理完成 ==========")
                                break
                            else:
                                logger.warning("未读取到有效测量数据")
                                break

        except Exception as e:
            logger.error(f"处理测量数据时发生错误: {e}", exc_info=True)

    # ========================================================================
    # 偏置数据处理
    # ========================================================================

    def process_offset_data(self) -> None:
        """
        处理偏置数据

        用于校准磁场测量的偏置值。在无被测磁场时采集数据，
        计算平均值作为偏置，后续测量时需要减去此偏置值。

        处理流程：
        1. 清空队列
        2. 读取测量数据（与process_measure_data类似）
        3. 对数据进行低通滤波
        4. 取中间90%数据的平均值作为偏置
        5. 保存到配置文件

        Note:
            保存的偏置值会在每次程序启动时加载，用于校正测量数据
        """
        logger.info("=== DataProcess: 开始处理偏置数据 ===")
        logger.info(f"process_offset_data: 初始队列大小: {self.data_queue.qsize()}")

        try:
            temp_buffer = bytearray()
            offset_list: List[float] = []
            no_data_count = 0

            # 偏置校准命令 N{duration}~ 的 duration 单位是秒
            # 等待时间设为 duration + 2 秒保险
            max_wait_count = 4  # 超时计数，4次 * 0.5秒 = 2秒
            while no_data_count < max_wait_count:
                # 处理已有数据
                if len(temp_buffer) >= 2:
                    group_count = len(temp_buffer) // 2
                    batch_size = min(group_count, 100)

                    for i in range(batch_size):
                        byte1 = temp_buffer[i * 2]
                        byte2 = temp_buffer[i * 2 + 1]
                        hex_value = (byte1 << 8) | byte2
                        # 转换为磁场强度（mT），注意：偏置数据不使用偏置校正
                        mag_value = round(hex_value * self.MAG_CONVERSION_FACTOR, 4)
                        offset_list.append(mag_value)

                    del temp_buffer[0:batch_size * 2]
                    no_data_count = 0  # 重置空计数，因为刚处理了数据

                # 获取新数据
                if len(temp_buffer) < 2:
                    try:
                        data = self.data_queue.get_nowait()
                        temp_buffer.extend(data)
                        continue
                    except queue.Empty:
                        no_data_count += 1
                        time.sleep(0.5)

            # 超时或完成
            if len(offset_list) > 0:
                # 进行低通滤波
                filtered_offset_list = self._lowpass_filter(offset_list)
                total_len = len(filtered_offset_list)

                # 取中间90%的数据（去掉首尾各5%）
                start_index = int(total_len * 0.1)
                end_index = int(total_len * 0.9)

                if start_index < end_index:
                    middle_data = filtered_offset_list[start_index:end_index]
                    self.mag_offset = statistics.mean(middle_data)
                else:
                    self.mag_offset = statistics.mean(filtered_offset_list)

                # 保存偏置值到配置文件
                self.config.offset = self.mag_offset
                logger.info(f"偏置校准完成，当前偏置: {self.mag_offset}, 数据点数: {len(offset_list)}")
                self.signal_offset_data_process_finished.emit(True)
            else:
                logger.warning("未读取到有效偏置数据")
                self.signal_offset_data_process_finished.emit(False)

        except Exception as e:
            logger.error(f"处理偏置数据时发生错误: {e}", exc_info=True)

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
            # MARS根目录/MARS/data/raw_data
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            raw_data_dir = os.path.join(project_root, "data", "raw_data")

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
            # MARS根目录/MARS/data/plot_data
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            plot_data_dir = os.path.join(project_root, "data", "plot_data")

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
        logger.debug("数据处理停止")
