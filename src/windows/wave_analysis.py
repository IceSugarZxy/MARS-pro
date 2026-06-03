# -*- coding: utf-8 -*-
"""
波形分析模块
实现磁场波形的各项指标分析功能
"""

import numpy as np
from scipy.signal import find_peaks
from scipy.fft import fft
from core.logger import get_logger

logger = get_logger('WaveAnalysis')


class WaveAnalysis:
    """波形分析类"""

    def __init__(self):
        pass

    @staticmethod
    def _get_zero_angle_merge_tolerance(x):
        """计算过零点去重容差，避免0度/360度同一过零点被重复计入。"""
        try:
            diffs = np.diff(x)
            positive_diffs = diffs[diffs > 0]
            if len(positive_diffs) > 0:
                return max(1e-6, float(np.median(positive_diffs) * 5))
        except Exception:
            pass
        return 1e-6

    @staticmethod
    def _get_zero_value_tolerance(y):
        """计算磁场零值容差，用于识别首尾恰好落在零点的闭环边界。"""
        try:
            y_scale = float(np.max(np.abs(y)))
            if np.isfinite(y_scale) and y_scale > 0:
                return max(1e-9, y_scale * 1e-6)
        except Exception:
            pass
        return 1e-9

    def _normalize_zero_angles(self, zero_angles, x):
        """去除过近的重复过零点，并合并首尾相接的同一物理过零点。"""
        if not zero_angles:
            return []

        merge_tolerance = self._get_zero_angle_merge_tolerance(x)
        normalized = []
        for angle in sorted(float(a) for a in zero_angles):
            if not normalized or abs(angle - normalized[-1]) > merge_tolerance:
                normalized.append(angle)

        if len(normalized) > 1:
            boundary_gap = (normalized[0] - x[0]) + (x[-1] - normalized[-1])
            if 0 <= boundary_gap <= merge_tolerance:
                removed = normalized.pop()
                logger.info(
                    "  首尾过零点合并: "
                    f"first={normalized[0]:.6f}, removed_last={removed:.6f}, "
                    f"boundary_gap={boundary_gap:.6f}, tolerance={merge_tolerance:.6f}"
                )

        return normalized

    def _build_circular_polar_intervals(self, zero_angles, x, y):
        """按闭环过零点计算N/S半波间隔和单对极周期。"""
        if len(zero_angles) < 2:
            return [], [], []

        span = float(x[-1] - x[0])
        if span <= 0:
            return [], [], []

        intervals = []
        for i, start_angle in enumerate(zero_angles):
            end_angle = zero_angles[(i + 1) % len(zero_angles)]
            if i == len(zero_angles) - 1:
                end_angle += span

            interval = float(end_angle - start_angle)
            if interval <= 0:
                continue

            midpoint = start_angle + interval / 2
            sample_angle = ((midpoint - x[0]) % span) + x[0]
            midpoint_value = float(np.interp(sample_angle, x, y))
            pole = 'N' if midpoint_value >= 0 else 'S'
            intervals.append({'length': interval, 'pole': pole})

        N_interval = [item['length'] for item in intervals if item['pole'] == 'N']
        S_interval = [item['length'] for item in intervals if item['pole'] == 'S']

        SinglePolarValue = []
        for i, item in enumerate(intervals):
            next_item = intervals[(i + 1) % len(intervals)]
            if item['pole'] == 'N' and next_item['pole'] == 'S':
                SinglePolarValue.append(item['length'] + next_item['length'])

        return N_interval, S_interval, SinglePolarValue

    def analyze_waveform(self, angle_data, mag_data, enable_concentricity_calibration=True):
        """执行波形分析
        
        Args:
            angle_data: 角度数据列表
            mag_data: 磁场数据列表
            enable_concentricity_calibration: 是否启用同心度校准（正弦拟合）
            
        Returns:
            dict: 分析结果字典
        """
        logger.info("开始波形分析...")
        
        try:
            # 检查输入数据
            if not angle_data or not mag_data or len(angle_data) != len(mag_data):
                logger.info("波形分析错误：数据为空或长度不一致")
                return {}
            
            # 转换为numpy数组
            x = np.array(angle_data)
            y = np.array(mag_data)
            
            results = self._wave_analysis(x, y, enable_concentricity_calibration)
            return results
            
        except Exception as e:
            logger.info(f"波形分析过程中发生错误: {e}")
            return {}
    
    def _wave_analysis(self, x, y, enable_concentricity_calibration=True):
        """波形分析核心算法
        
        Args:
            x: 角度数据数组
            y: 磁场数据数组
            enable_concentricity_calibration: 是否启用同心度校准（正弦拟合）
            
        Returns:
            dict: 分析结果字典
        """
        try:
            # Part 1: 峰值分析
            N_part = y[y >= 0]
            S_part = abs(y[y <= 0])

            N_peaks, _ = find_peaks(N_part, height=1.0, distance=20, prominence=0.5)
            N_peak_values = N_part[N_peaks]
            
            S_peaks, _ = find_peaks(S_part, height=1.0, distance=20, prominence=0.5)
            S_peak_values = S_part[S_peaks]

            # 排除异常峰值
            def remove_low_peaks(values):
                if len(values) <= 1:
                    return values
                mean_val = np.mean(values)
                mask = values >= mean_val
                filtered_values = values[mask]
                return filtered_values if len(filtered_values) > 0 else values

            def remove_high_peaks(values):
                if len(values) <= 1:
                    return values
                mean_val = np.mean(values)
                mask = values <= mean_val
                filtered_values = values[mask]
                return filtered_values if len(filtered_values) > 0 else values

            if len(N_peak_values) > 1:
                N_peak_values = remove_low_peaks(N_peak_values)
            if len(S_peak_values) > 1:
                S_peak_values = remove_high_peaks(S_peak_values)

            # 计算N极统计
            if len(N_peak_values) > 1:
                N_max = round(float(np.max(N_peak_values)), 2)
                N_min = round(float(np.min(N_peak_values)), 2)
                N_mean = round(np.mean(N_peak_values), 2)
                N_se = round(np.std(N_peak_values, ddof=1)/np.mean(N_peak_values)*100, 2)
            elif len(N_peak_values) == 1:
                N_max = N_min = N_mean = round(float(N_peak_values[0]), 2)
                N_se = float('nan')
                logger.info(f"  N极只有1个峰值: {N_max}")
            else:
                N_max = N_min = N_mean = N_se = float('nan')
                logger.info("  N极无有效峰值")

            # 计算S极统计
            if len(S_peak_values) > 1:
                S_max = round(float(np.max(S_peak_values)), 2)
                S_min = round(float(np.min(S_peak_values)), 2)
                S_mean = round(np.mean(S_peak_values), 2)
                S_se = round(np.std(S_peak_values, ddof=1)/np.mean(S_peak_values)*100, 2)
            elif len(S_peak_values) == 1:
                S_max = S_min = S_mean = round(float(S_peak_values[0]), 2)
                S_se = float('nan')
                logger.info(f"  S极只有1个峰值: {S_max}")
            else:
                S_max = S_min = S_mean = S_se = float('nan')
                logger.info("  S极无有效峰值")

            # 计算NS_2
            peak_combine = np.concatenate((N_peak_values, S_peak_values))
            NS_2 = round(np.mean(peak_combine), 2) if len(peak_combine) > 0 else float('nan')

            # Part 2: 过零点分析
            zero_crossings = []
            zero_angles = []
            zero_value_tolerance = self._get_zero_value_tolerance(y)

            # 角度首尾是同一个物理位置；如果边界点正好在零点，先纳入一个闭环零点，
            # 后续归一化会把0度/360度的重复点合并为同一个物理过零点。
            if abs(float(y[0])) <= zero_value_tolerance:
                zero_angles.append(float(x[0]))
            if len(y) > 1 and abs(float(y[-1])) <= zero_value_tolerance:
                zero_angles.append(float(x[-1]))

            # 检测过零点
            for i in range(len(y) - 1):
                if y[i] * y[i+1] <= 0:
                    if len(zero_crossings) == 0 or (i - zero_crossings[-1] > 10):
                        zero_crossings.append(i)

            # 线性拟合计算过零点角度
            for zero_idx, idx in enumerate(zero_crossings, start=1):
                try:
                    fit_start = max(0, idx - 10)
                    fit_end = min(len(x), idx + 11)

                    if fit_end - fit_start >= 2:
                        x_fit = x[fit_start:fit_end]
                        y_fit = y[fit_start:fit_end]
                        coefficients = np.polyfit(x_fit, y_fit, 1)

                        if coefficients[0] != 0:
                            zero_angle = -coefficients[1] / coefficients[0]
                            if x[0] <= zero_angle <= x[-1]:
                                zero_angles.append(zero_angle)
                except Exception as e:
                    logger.info(f"  过零点{zero_idx}计算失败: {e}")
                    continue

            zero_angles = self._normalize_zero_angles(zero_angles, x)

            # 计算极间隔和误差
            N_interval, S_interval, SinglePolarValue = [], [], []
            SinglePolarError, PolarErrorSumList = [], []

            if len(zero_angles) >= 2:
                N_interval, S_interval, SinglePolarValue = self._build_circular_polar_intervals(
                    zero_angles, x, y
                )

                # 验证间隔数量一致性
                if len(N_interval) > 0 and len(S_interval) > 0:
                    logger.info(f"  N极间隔数量: {len(N_interval)}, S极间隔数量: {len(S_interval)}")
                if len(N_interval) != len(S_interval):
                    logger.info(
                        f"  N/S极间隔数量不一致: N={len(N_interval)}, S={len(S_interval)}"
                    )

                # 单极误差
                if len(SinglePolarValue) > 0:
                    mean_polar = np.mean(SinglePolarValue)

                    for i in range(len(SinglePolarValue)):
                        error = (SinglePolarValue[i] - mean_polar) / mean_polar * 100
                        SinglePolarError.append(error)

                # 正弦函数拟合校准单极误差列表
                if len(SinglePolarError) >= 4 and enable_concentricity_calibration:
                    try:
                        # 创建x轴数据（从0开始的索引）
                        x_fit = np.arange(len(SinglePolarError))
                        y_original = np.array(SinglePolarError)

                        # 正弦函数拟合：y = A * sin(ω*x + φ) + C
                        # 使用最小二乘法进行正弦拟合
                        from scipy.optimize import curve_fit

                        # 定义正弦函数模型
                        def sin_func(x, A, omega, phi, C):
                            return A * np.sin(omega * x + phi) + C

                        # 初始参数估计
                        y_mean = np.mean(y_original)
                        y_amplitude = (np.max(y_original) - np.min(y_original)) / 2

                        if y_amplitude <= 1e-12:
                            logger.info("  单极误差波动过小，跳过正弦拟合")
                        else:
                            # 尝试不同的初始参数
                            initial_guess = [y_amplitude, 2*np.pi/len(x_fit), 0, y_mean]

                            # 进行正弦拟合
                            popt, _ = curve_fit(sin_func, x_fit, y_original, p0=initial_guess, maxfev=5000)

                            A_fit, omega_fit, phi_fit, C_fit = popt

                            # 计算拟合值
                            y_fit = sin_func(x_fit, A_fit, omega_fit, phi_fit, C_fit)

                            # 用原始单极误差减去拟合的正弦函数，削弱同心度导致的周期性波动
                            y_adjusted = y_original - y_fit

                            # 更新单极误差列表，后续累计误差基于校准后的单极误差重新累加
                            SinglePolarError = y_adjusted.tolist()

                    except Exception as e:
                        logger.info(f"  单极误差正弦拟合失败，使用原始单极误差: {e}")
                else:
                    logger.info("  单极误差数据点不足，跳过正弦拟合")

                # 误差和：基于当前单极误差列表逐项累加，包含起点0以保持累计范围定义完整
                errorSum = 0
                PolarErrorSumList.append(errorSum)
                for i in range(len(SinglePolarError)):
                    errorSum += SinglePolarError[i]
                    PolarErrorSumList.append(errorSum)
            else:
                logger.info("过零点数量不足，无法计算极间隔")

            # 计算N极间隔统计
            if len(N_interval) > 1:
                N_interval_max = round(float(np.max(N_interval)), 2)
                N_interval_min = round(float(np.min(N_interval)), 2)
                N_interval_mean = round(np.mean(N_interval), 2)
                N_interval_std = round(np.std(N_interval, ddof=1)/np.mean(N_interval)*100, 2)
            elif len(N_interval) == 1:
                N_interval_max = N_interval_min = N_interval_mean = round(float(N_interval[0]), 2)
                N_interval_std = float('nan')
                logger.info(f"  N极间隔只有1个: {N_interval_max}")
            else:
                N_interval_max = N_interval_min = N_interval_mean = N_interval_std = float('nan')
                logger.info("  N极间隔数据为空")

            # 计算S极间隔统计
            if len(S_interval) > 1:
                S_interval_max = round(float(np.max(S_interval)), 2)
                S_interval_min = round(float(np.min(S_interval)), 2)
                S_interval_mean = round(np.mean(S_interval), 2)
                S_interval_std = round(np.std(S_interval, ddof=1)/np.mean(S_interval)*100, 2)
            elif len(S_interval) == 1:
                S_interval_max = S_interval_min = S_interval_mean = round(float(S_interval[0]), 2)
                S_interval_std = float('nan')
                logger.info(f"  S极间隔只有1个: {S_interval_max}")
            else:
                S_interval_max = S_interval_min = S_interval_mean = S_interval_std = float('nan')
                logger.info("  S极间隔数据为空")

            # Part 3: 面积计算
            try:
                mask = x < 360
                x_filtered = x[mask]
                y_filtered = y[mask]

                N_part = np.where(y_filtered < 0, 0, y_filtered)
                N_area = round(np.trapz(N_part, x_filtered), 2)

                S_part = np.where(y_filtered > 0, 0, y_filtered)
                S_area = abs(round(np.trapz(S_part, x_filtered), 2))

                NS_area = round(N_area + S_area, 2)
            except Exception as e:
                N_area = S_area = NS_area = float('nan')
                logger.info(f"  面积计算失败: {e}")

            # 计算THD失真率
            try:
                # 使用完整磁场数据进行FFT分析
                y_fft = fft(y)
                n = len(y_fft)
                
                # 计算功率谱
                power_spectrum = np.abs(y_fft[:n//2])**2
                
                # 找到基波频率（最大功率的频率，跳过直流分量）
                if len(power_spectrum) > 1:
                    fundamental_idx = np.argmax(power_spectrum[1:]) + 1
                    fundamental_power = power_spectrum[fundamental_idx]
                else:
                    fundamental_power = 0
                    fundamental_idx = 0
                
                # 计算谐波功率（2次到10次谐波）
                harmonic_power_sum = 0
                if fundamental_idx > 0:
                    for harmonic in range(2, 11):
                        harmonic_idx = fundamental_idx * harmonic
                        if harmonic_idx < len(power_spectrum):
                            harmonic_power_sum += power_spectrum[harmonic_idx]

                # 计算THD（总谐波失真率）
                if fundamental_power > 0:
                    THD_error = round(np.sqrt(harmonic_power_sum / fundamental_power) * 100, 5)
                else:
                    THD_error = float('nan')

            except Exception as e:
                THD_error = float('nan')
                logger.info(f"  THD计算失败: {e}")

            # 计算极对数（使用FFT的基波频率索引）
            try:
                # 基波频率索引即为极对数
                if fundamental_idx > 0:
                    pole_num = int(fundamental_idx)
                else:
                    pole_num = float('nan')
                logger.info(f"  极对数: {pole_num}")
            except Exception as e:
                pole_num = float('nan')
                logger.info(f"  极对数计算失败: {e}")

            # 计算单极统计
            if len(SinglePolarValue) > 1:
                SinglePolarMean = round(np.mean(SinglePolarValue), 2)
                SinglePolarErrorMax = round(float(np.max(np.abs(SinglePolarError))), 5)
                PolarErrorSum = round(float(np.max(PolarErrorSumList)-np.min(PolarErrorSumList)), 5)
            else:
                SinglePolarMean = SinglePolarErrorMax = PolarErrorSum = float('nan')
                logger.info("  单极统计数据不足")

            results = {
                'N_max': N_max, 'N_min': N_min, 'N_mean': N_mean, 'N_se': N_se,
                'S_max': S_max, 'S_min': S_min, 'S_mean': S_mean, 'S_se': S_se,
                'NS_2': NS_2,
                'N_interval_max': N_interval_max, 'N_interval_min': N_interval_min,
                'N_interval_mean': N_interval_mean, 'N_interval_std': N_interval_std,
                'S_interval_max': S_interval_max, 'S_interval_min': S_interval_min,
                'S_interval_mean': S_interval_mean, 'S_interval_std': S_interval_std,
                'N_area': N_area, 'S_area': S_area, 'NS_area': NS_area,
                'SinglePolarMean': SinglePolarMean, 'SinglePolarError': SinglePolarErrorMax,
                'PolarErrorSum': PolarErrorSum, 'THD_error': THD_error,
                'pole_num': pole_num
            }

            # 记录最终指标，便于追踪分析结果。
            for key, value in results.items():
                logger.info(f"  {key}: {value}")

            logger.info("=== 波形分析完成 ===")

            return results

        except Exception as e:
            logger.info(f"波形分析算法执行出错: {e}")
            return {}
