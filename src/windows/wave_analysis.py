# -*- coding: utf-8 -*-
"""
波形分析模块
实现磁场波形的各项指标分析功能
"""

import os
import numpy as np
from scipy.signal import find_peaks
from scipy.fft import fft
from core.logger import get_logger

logger = get_logger('WaveAnalysis')


class WaveAnalysis:
    """波形分析类"""
    
    def __init__(self):
        pass
    
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
            
            # 调用波形分析函数
            results = self._wave_analysis(x, y, enable_concentricity_calibration)
            
            # logger.info("波形分析完成")
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
            # logger.info(f"=== 波形分析开始 ===")
            # logger.info(f"输入数据: x长度={len(x)}, y长度={len(y)}")
            # logger.info(f"x范围: {x[0]:.2f}° ~ {x[-1]:.2f}°")
            # logger.info(f"y范围: {y.min():.2f} ~ {y.max():.2f}")
            
            # Part 1: 峰值分析
            N_part = y[y >= 0]
            S_part = abs(y[y <= 0])
            
            # logger.info(f"N极数据点: {len(N_part)}个, S极数据点: {len(S_part)}个")

            N_peaks, _ = find_peaks(N_part, height=1.0, distance=20, prominence=0.5)
            N_peak_values = N_part[N_peaks]
            
            S_peaks, _ = find_peaks(S_part, height=1.0, distance=20, prominence=0.5)
            S_peak_values = S_part[S_peaks]
            
            # logger.info(f"检测到N极峰值: {len(N_peak_values)}个, S极峰值: {len(S_peak_values)}个")

            # 排除异常峰值
            def remove_low_peaks(values):
                if len(values) <= 1:
                    return values
                mean_val = np.mean(values)
                # 使用布尔索引过滤数组
                mask = values >= mean_val
                filtered_values = values[mask]
                # logger.info(f"  排除低峰值: 原始{len(values)}个, 过滤后{len(filtered_values)}个")
                return filtered_values if len(filtered_values) > 0 else values
            
            def remove_high_peaks(values):
                if len(values) <= 1:
                    return values
                mean_val = np.mean(values)
                # 使用布尔索引过滤数组
                mask = values <= mean_val
                filtered_values = values[mask]
                # logger.info(f"  排除高峰值: 原始{len(values)}个, 过滤后{len(filtered_values)}个")
                return filtered_values if len(filtered_values) > 0 else values

            # logger.info("=== 峰值排除处理 ===")
            if len(N_peak_values) > 1:
                # logger.info(f"N极峰值排除前: {N_peak_values}")
                N_peak_values = remove_low_peaks(N_peak_values)
                # logger.info(f"N极峰值排除后: {N_peak_values}")
            if len(S_peak_values) > 1:
                # logger.info(f"S极峰值排除前: {S_peak_values}")
                S_peak_values = remove_high_peaks(S_peak_values)
                # logger.info(f"S极峰值排除后: {S_peak_values}")

            # 计算N极统计
            # logger.info("=== N极统计计算 ===")
            if len(N_peak_values) > 1:
                N_max = round(float(np.max(N_peak_values)), 2)
                N_min = round(float(np.min(N_peak_values)), 2)
                N_mean = round(np.mean(N_peak_values), 2)
                N_se = round(np.std(N_peak_values, ddof=1)/np.mean(N_peak_values)*100, 2)
                # logger.info(f"  N_max={N_max}, N_min={N_min}, N_mean={N_mean}, N_se={N_se}")
            elif len(N_peak_values) == 1:
                N_max = N_min = N_mean = round(float(N_peak_values[0]), 2)
                N_se = float('nan')
                logger.info(f"  N极只有1个峰值: {N_max}")
            else:
                N_max = N_min = N_mean = N_se = float('nan')
                logger.info("  N极无有效峰值")

            # 计算S极统计
            # logger.info("=== S极统计计算 ===")
            if len(S_peak_values) > 1:
                S_max = round(float(np.max(S_peak_values)), 2)
                S_min = round(float(np.min(S_peak_values)), 2)
                S_mean = round(np.mean(S_peak_values), 2)
                S_se = round(np.std(S_peak_values, ddof=1)/np.mean(S_peak_values)*100, 2)
                # logger.info(f"  S_max={S_max}, S_min={S_min}, S_mean={S_mean}, S_se={S_se}")
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
            # logger.info(f"=== NS_2计算 ===")
            # logger.info(f"  合并峰值数量: {len(peak_combine)}, NS_2={NS_2}")

            # Part 2: 过零点分析
            # logger.info("=== 过零点分析 ===")
            zero_crossings = []
            angles_at_zero = [x[0]]
            
            # 检测过零点
            for i in range(len(y) - 1):
                if y[i] * y[i+1] <= 0:
                    if len(zero_crossings) == 0 or (i - zero_crossings[-1] > 10):
                        zero_crossings.append(i)
            
            # logger.info(f"检测到过零点索引: {zero_crossings}")
            
            # 线性拟合计算过零点角度
            # logger.info("=== 过零点角度计算 ===")
            for idx in zero_crossings:
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
                                angles_at_zero.append(zero_angle)
                                # logger.info(f"  过零点{i+1}: 索引={idx}, 角度={zero_angle:.2f}°")
                except Exception as e:
                    logger.info(f"  过零点{i+1}计算失败: {e}")
                    continue
            
            angles_at_zero.append(x[-1])
            angles_at_zero.sort()
            # print(f"最终过零点角度: {[f'{a:.2f}°' for a in angles_at_zero]}")

            # 计算极间隔和误差
            # logger.info("=== 极间隔分析 ===")
            N_interval, S_interval, SinglePolarValue = [], [], []
            SinglePolarError, PolarErrorSumList = [], []
            
            if len(angles_at_zero) > 1:
                # logger.info(f"过零点数量: {len(angles_at_zero)}")
                
                # 计算N极和S极间隔
                for i in range(len(angles_at_zero)-1):
                    interval = angles_at_zero[i+1] - angles_at_zero[i]
                    if interval > 0:
                        if i % 2 == 0:
                            N_interval.append(interval)
                            # logger.info(f"  N极间隔{i//2+1}: {interval:.2f}°")
                        else:
                            S_interval.append(interval)
                            # logger.info(f"  S极间隔{i//2+1}: {interval:.2f}°")
                
                # 单对极周期
                # logger.info("=== 单对极周期计算 ===")
                for i in range(0, len(angles_at_zero)-2, 2):
                    interval = angles_at_zero[i+2] - angles_at_zero[i]
                    if interval > 0:
                        SinglePolarValue.append(interval)
                        # logger.info(f"  单对极周期{i//2+1}: {interval:.2f}°")
                
                # 单极误差
                # logger.info("=== 单极误差计算 ===")
                if len(SinglePolarValue) > 0:
                    mean_polar = np.mean(SinglePolarValue)
                    # logger.info(f"  单对极周期平均值: {mean_polar:.2f}°")
                    
                    for i in range(len(SinglePolarValue)):
                        error = (SinglePolarValue[i] - mean_polar) / mean_polar * 100
                        SinglePolarError.append(error)
                        # logger.info(f"  单极误差{i+1}: {error:.2f}%")
                
                # 误差和
                # logger.info("=== 误差和计算 ===")
                errorSum = 0
                for i in range(len(SinglePolarError)):
                    errorSum += SinglePolarError[i]
                    PolarErrorSumList.append(errorSum)
                    # logger.info(f"  误差和{i+1}: {errorSum:.2f}%")
                
                # 正弦函数拟合削弱波动性
                if len(PolarErrorSumList) > 2 and enable_concentricity_calibration:
                    # logger.info("=== 正弦函数拟合削弱波动性（同心度校准） ===")
                    try:
                        # 创建x轴数据（从0开始的索引）
                        x_fit = np.arange(len(PolarErrorSumList))
                        y_original = np.array(PolarErrorSumList)
                        
                        # 正弦函数拟合：y = A * sin(ω*x + φ) + C
                        # 使用最小二乘法进行正弦拟合
                        from scipy.optimize import curve_fit
                        
                        # 定义正弦函数模型
                        def sin_func(x, A, omega, phi, C):
                            return A * np.sin(omega * x + phi) + C
                        
                        # 初始参数估计
                        y_mean = np.mean(y_original)
                        y_amplitude = (np.max(y_original) - np.min(y_original)) / 2
                        
                        # 尝试不同的初始参数
                        initial_guess = [y_amplitude, 2*np.pi/len(x_fit), 0, y_mean]
                        
                        # 进行正弦拟合
                        popt, pcov = curve_fit(sin_func, x_fit, y_original, p0=initial_guess, maxfev=5000)
                        
                        A_fit, omega_fit, phi_fit, C_fit = popt
                        
                        # logger.info(f"  正弦拟合参数: A={A_fit:.4f}, ω={omega_fit:.4f}, φ={phi_fit:.4f}, C={C_fit:.4f}")
                        
                        # 计算拟合值
                        y_fit = sin_func(x_fit, A_fit, omega_fit, phi_fit, C_fit)
                        
                        # 用原始数据减去拟合的正弦函数，削弱波动性
                        y_adjusted = y_original - y_fit
                        
                        # 更新误差和列表
                        PolarErrorSumList = y_adjusted.tolist()
                        
                        # logger.info("  正弦拟合削弱波动性完成")
                        # logger.info(f"  原始误差和范围: {np.min(y_original):.4f} ~ {np.max(y_original):.4f}")
                        # logger.info(f"  调整后误差和范围: {np.min(y_adjusted):.4f} ~ {np.max(y_adjusted):.4f}")
                        
                        # 可视化正弦拟合过程（可注释关闭）
                        # try:
                        #     # visualize_error_fit(y_original.tolist(), "误差和正弦拟合分析")  # 正弦拟合波形校准查看
                        # except ImportError:
                        #     logger.info("  警告: 无法导入可视化模块，跳过可视化")
                        # except Exception as e:
                        #     logger.info(f"  可视化失败: {e}")
                        
                    except Exception as e:
                        logger.info(f"  正弦拟合失败，使用原始误差和: {e}")
                else:
                    logger.info("  误差和数据点不足，跳过正弦拟合")
            else:
                logger.info("过零点数量不足，无法计算极间隔")

            # 计算N极间隔统计
            # logger.info("=== N极间隔统计 ===")
            if len(N_interval) > 1:
                N_interval_max = round(float(np.max(N_interval)), 2)
                N_interval_min = round(float(np.min(N_interval)), 2)
                N_interval_mean = round(np.mean(N_interval), 2)
                N_interval_std = round(np.std(N_interval, ddof=1)/np.mean(N_interval)*100, 2)
                # logger.info(f"  N_interval_max={N_interval_max}, N_interval_min={N_interval_min}, N_interval_mean={N_interval_mean}, N_interval_std={N_interval_std}")
            elif len(N_interval) == 1:
                N_interval_max = N_interval_min = N_interval_mean = round(float(N_interval[0]), 2)
                N_interval_std = float('nan')
                logger.info(f"  N极间隔只有1个: {N_interval_max}")
            else:
                N_interval_max = N_interval_min = N_interval_mean = N_interval_std = float('nan')
                logger.info("  N极间隔数据为空")

            # 计算S极间隔统计
            logger.info("=== S极间隔统计 ===")
            if len(S_interval) > 1:
                S_interval_max = round(float(np.max(S_interval)), 2)
                S_interval_min = round(float(np.min(S_interval)), 2)
                S_interval_mean = round(np.mean(S_interval), 2)
                S_interval_std = round(np.std(S_interval, ddof=1)/np.mean(S_interval)*100, 2)
                # logger.info(f"  S_interval_max={S_interval_max}, S_interval_min={S_interval_min}, S_interval_mean={S_interval_mean}, S_interval_std={S_interval_std}")
            elif len(S_interval) == 1:
                S_interval_max = S_interval_min = S_interval_mean = round(float(S_interval[0]), 2)
                S_interval_std = float('nan')
                logger.info(f"  S极间隔只有1个: {S_interval_max}")
            else:
                S_interval_max = S_interval_min = S_interval_mean = S_interval_std = float('nan')
                logger.info("  S极间隔数据为空")

            # Part 3: 面积计算
            # logger.info("=== 面积计算 ===")
            try:
                mask = x < 360
                x_filtered = x[mask]
                y_filtered = y[mask]
                
                # logger.info(f"  面积计算范围: {x_filtered[0]:.2f}° ~ {x_filtered[-1]:.2f}°")

                N_part = np.where(y_filtered < 0, 0, y_filtered)
                N_area = round(np.trapz(N_part, x_filtered), 2)
                # logger.info(f"  N极面积: {N_area}")

                S_part = np.where(y_filtered > 0, 0, y_filtered)
                S_area = abs(round(np.trapz(S_part, x_filtered), 2))
                # logger.info(f"  S极面积: {S_area}")

                NS_area = round(N_area + S_area, 2)
                # logger.info(f"  NS总面积: {NS_area}")
            except Exception as e:
                N_area = S_area = NS_area = float('nan')
                logger.info(f"  面积计算失败: {e}")

            # 计算THD失真率
            # logger.info("=== THD失真率计算 ===")
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
                
                # logger.info(f"  基波功率: {fundamental_power:.2f}")
                # logger.info(f"  谐波功率和: {harmonic_power_sum:.2f}")
                # logger.info(f"  THD失真率: {THD_error:.5f}%")
                
            except Exception as e:
                THD_error = float('nan')
                logger.info(f"  THD计算失败: {e}")

            # 计算极对数（使用FFT的基波频率索引）
            # logger.info("=== 极对数计算 ===")
            try:
                # 基波频率索引即为极对数
                if fundamental_idx > 0:
                    pole_num = int(fundamental_idx)
                else:
                    pole_num = int('nan')
                logger.info(f"  极对数: {pole_num}")
            except Exception as e:
                pole_num = float('nan')
                logger.info(f"  极对数计算失败: {e}")

            # 计算单极统计
            # logger.info("=== 单极统计计算 ===")
            if len(SinglePolarValue) > 1:
                SinglePolarMean = round(np.mean(SinglePolarValue), 2)
                SinglePolarErrorMax = round(float(np.max(SinglePolarError)), 5)
                PolarErrorSum = round(float(np.max(PolarErrorSumList)-np.min(PolarErrorSumList)), 5)
                # logger.info(f"  SinglePolarMean={SinglePolarMean}, SinglePolarErrorMax={SinglePolarErrorMax}, PolarErrorSum={PolarErrorSum}")
            else:
                SinglePolarMean = SinglePolarErrorMax = PolarErrorSum = float('nan')
                logger.info("  单极统计数据不足")

            # 返回结果
            # logger.info("=== 最终结果汇总 ===")
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
            
            # 打印所有结果
            for key, value in results.items():
                logger.info(f"  {key}: {value}")
            
            logger.info("=== 波形分析完成 ===")

            return results

        except Exception as e:
            logger.info(f"波形分析算法执行出错: {e}")
            return {}