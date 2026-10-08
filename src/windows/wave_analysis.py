# -*- coding: utf-8 -*-
"""
波形分析模块
实现磁场波形的各项指标分析功能
"""

import warnings

import numpy as np
from scipy.optimize import OptimizeWarning
from scipy.signal import find_peaks
from scipy.fft import fft
from core.logger import get_logger

# 兼容 numpy 2.0+：np.trapz 已被移除，改用 np.trapezoid（旧版回退到 np.trapz）
_TRAPZ = getattr(np, "trapezoid", None) or np.trapz

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
                logger.debug(
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

    def analyze_waveform(self, angle_data, mag_data):
        """执行波形分析
        
        Args:
            angle_data: 角度数据列表
            mag_data: 磁场数据列表
            
        Returns:
            dict: 分析结果字典
        """
        logger.info("开始波形分析...")
        
        try:
            # 检查输入数据
            if angle_data is None or mag_data is None:
                logger.info("波形分析错误：数据为空")
                return {}
            if len(angle_data) == 0 or len(mag_data) == 0 or len(angle_data) != len(mag_data):
                logger.info("波形分析错误：数据为空或长度不一致")
                return {}
            
            # 转换为numpy数组
            x = np.array(angle_data)
            y = np.array(mag_data)
            
            results = self._wave_analysis(x, y)
            return results
            
        except Exception as e:
            logger.info(f"波形分析过程中发生错误: {e}")
            return {}
    
    def _detect_zero_angles(self, x, y):
        """检测过零点并线性拟合出各自的角度。"""
        zero_crossings = []
        zero_angles = []
        zero_value_tolerance = self._get_zero_value_tolerance(y)

        # 角度首尾是同一个物理位置；如果边界点正好在零点，先纳入一个闭环零点，
        # 后续归一化会把0度/360度的重复点合并为同一个物理过零点。
        if abs(float(y[0])) <= zero_value_tolerance:
            zero_angles.append(float(x[0]))
        if len(y) > 1 and abs(float(y[-1])) <= zero_value_tolerance:
            zero_angles.append(float(x[-1]))

        for i in range(len(y) - 1):
            if y[i] * y[i + 1] <= 0:
                if len(zero_crossings) == 0 or (i - zero_crossings[-1] > 10):
                    zero_crossings.append(i)

        for zero_idx, idx in enumerate(zero_crossings, start=1):
            try:
                fit_start = max(0, idx - 10)
                fit_end = min(len(x), idx + 11)
                if fit_end - fit_start >= 2:
                    coefficients = np.polyfit(x[fit_start:fit_end], y[fit_start:fit_end], 1)
                    if coefficients[0] != 0:
                        zero_angle = -coefficients[1] / coefficients[0]
                        if x[0] <= zero_angle <= x[-1]:
                            zero_angles.append(zero_angle)
            except Exception as e:  # noqa: BLE001
                logger.debug(f"  过零点{zero_idx}计算失败: {e}")
                continue

        return self._normalize_zero_angles(zero_angles, x)

    def _interval_peaks(self, x, y, zero_angles):
        """按过零点划分区间，取每个区间的极值，按极性分开返回。

        Returns:
            (N角度, N幅值, S角度, S幅值)
        """
        N_angles, N_values, S_angles, S_values = [], [], [], []
        if len(zero_angles) < 2:
            return np.array([]), np.array([]), np.array([]), np.array([])
        span = float(x[-1] - x[0]) + float(x[1] - x[0])
        for i in range(len(zero_angles)):
            start_angle = zero_angles[i]
            end_angle = zero_angles[(i + 1) % len(zero_angles)]
            if i == len(zero_angles) - 1:
                end_angle += span
            if i == len(zero_angles) - 1 and end_angle > x[-1]:
                mask = (x > start_angle) | (x < (end_angle - span))
            else:
                mask = (x > start_angle) & (x < end_angle)
            y_interval = y[mask]
            if len(y_interval) < 2:
                continue
            indices = np.where(mask)[0]
            midpoint = start_angle + (end_angle - start_angle) / 2
            sample_angle = ((midpoint - x[0]) % span) + x[0]
            if float(np.interp(sample_angle, x, y)) >= 0:
                local = int(np.argmax(y_interval))
                N_angles.append(float(x[indices[local]]))
                N_values.append(float(y[indices[local]]))
            else:
                local = int(np.argmin(y_interval))
                S_angles.append(float(x[indices[local]]))
                S_values.append(abs(float(y[indices[local]])))
        return (np.array(N_angles), np.array(N_values),
                np.array(S_angles), np.array(S_values))

    @staticmethod
    def _wrap_half_period(values, period):
        """把角度偏差折算到 ±period/2 区间内。"""
        return (values + period / 2.0) % period - period / 2.0

    @staticmethod
    def _fit_first_harmonic(theta, values):
        """按 y = a·sin θ + b·cos θ + c 做最小二乘。

        Returns:
            (系数向量, 一圈一次幅值, a·sinθ+b·cosθ 的相位°/设计矩阵)。
        """
        design = np.column_stack([np.sin(theta), np.cos(theta), np.ones(len(theta))])
        coef, *_ = np.linalg.lstsq(design, values, rcond=None)
        amplitude = float(np.hypot(coef[0], coef[1]))
        phase = float(np.rad2deg(np.arctan2(coef[1], coef[0])))
        return coef, amplitude, phase, design

    def _concentricity_angle_correction(self, x, zero_angles):
        """同轴度修正（角度域）：剥离过零点偏差里的"一圈一次"偏心分量。

        偏心使编码器角度 θ 与样品真实角度相差 δ(θ)，δ 是一圈一次的正弦量，
        所以实测过零点相对等分栅格会出现一圈一次的偏移。扣掉它以后，
        极间隔误差统计的就是样品本身（而不是夹具偏心）的不均匀度。

        Returns:
            (修正后的过零点角度数组, 诊断字典)。
        """
        cross = np.asarray(zero_angles, dtype=float)
        info = {"angle_applied": False, "zero_crossings": int(len(cross))}
        if len(cross) < 4:
            return cross, info

        step = float(x[1] - x[0]) if len(x) > 1 else 1.0
        span = float(x[-1] - x[0]) + step          # 一整圈 = 360°
        spacing = span / len(cross)
        nominal = cross[0] + np.arange(len(cross)) * spacing
        deviation = self._wrap_half_period(cross - nominal, span)
        theta = 2.0 * np.pi * (cross - x[0]) / span

        coef, amp, phase, design = self._fit_first_harmonic(theta, deviation)
        # 修正前也扣掉均值，保证和修正后同一口径（都是相对最佳拟合栅格）
        residual_before = float(np.std(deviation - float(np.mean(deviation))))
        residual_after = float(np.std(deviation - design @ coef))
        if amp > 5.0:       # 超过 5° 视为偏心量异常，宁可不修角度
            logger.warning(f"同轴度修正：估计角度偏心 {amp:.2f}° 过大，跳过角度修正")
            return cross, info

        # 只扣一圈一次项，保留常数项，整圈总弧长不变
        corrected = cross - (coef[0] * np.sin(theta) + coef[1] * np.cos(theta))
        info.update({
            "angle_applied": True,
            "angle_amp_deg": round(amp, 4),
            "angle_phase_deg": round(phase, 1),
            "crossing_dev_std_deg_before": round(residual_before, 4),
            "crossing_dev_std_deg_after": round(residual_after, 4),
        })
        return corrected, info

    def _concentricity_amplitude_correction(self, x, n_angles, n_values, s_angles, s_values):
        """同轴度修正（幅值域）：把 N、S 极值序列各自的"一圈一次"分量扣掉。

        偏心对极值幅值的作用是一圈一次的：加性偏移 Δ(θ) 与灵敏度调制 m(θ)，
        N 极表现为 +Δ + A·m，S 极表现为 −Δ + B·m，两者都是 θ 的一圈一次正弦。

        注意：从**极值序列**里无法把 Δ 和 m 分开——两个效应对同一序列贡献的
        都是 sinθ / cosθ 这一组基，是同一个方向（早先"联合拟合 Δ 与 m 再相除"
        的写法就卡在这里：signed·sinθ 只在极对数谐波上有分量，一圈一次分量几乎为 0，
        结果一圈一次几乎没被扣掉，反而被一个虚高的 Δ 和虚假的 m 扭曲了序列）。
        既然目标就是让 N、S 两个序列尽可能平，直接在两个序列上各自拟合并扣掉
        一圈一次项即可，既准确又严格保证方差只减不增。

        Returns:
            (修正后的 N 幅值数组, 修正后的 S 幅值数组, 诊断字典)。
        """
        n_values = np.asarray(n_values, dtype=float)
        s_values = np.asarray(s_values, dtype=float)
        info = {"amp_applied": False, "peak_count": int(len(n_values) + len(s_values))}
        if len(n_values) < 4 or len(s_values) < 4:
            return n_values, s_values, info

        step = float(x[1] - x[0]) if len(x) > 1 else 1.0
        span = float(x[-1] - x[0]) + step

        def remove_first_harmonic(angles, values):
            theta = 2.0 * np.pi * (np.asarray(angles, dtype=float) - x[0]) / span
            # 极值点的角度本身就不均匀（极点位置有误差），所以必须带上常数项，
            # 否则 sin/cos 与常数不正交，一圈一次幅值会被系统性低估/污染。
            design = np.column_stack([np.sin(theta), np.cos(theta), np.ones(len(theta))])
            coef, *_ = np.linalg.lstsq(design, values, rcond=None)
            amplitude = float(np.hypot(coef[0], coef[1]))
            phase = float(np.rad2deg(np.arctan2(coef[1], coef[0])))
            one_x = coef[0] * np.sin(theta) + coef[1] * np.cos(theta)
            return values - one_x, amplitude, phase

        n_fixed, n_amp, n_phase = remove_first_harmonic(n_angles, n_values)
        s_fixed, s_amp, s_phase = remove_first_harmonic(s_angles, s_values)
        n_scale = abs(float(np.mean(n_values))) or 1.0
        s_scale = abs(float(np.mean(s_values))) or 1.0
        info.update({
            "n_1x_mT": round(n_amp, 3),
            "n_1x_pct": round(n_amp / n_scale * 100.0, 3),
            "n_1x_phase_deg": round(n_phase, 1),
            "s_1x_mT": round(s_amp, 3),
            "s_1x_pct": round(s_amp / s_scale * 100.0, 3),
            "s_1x_phase_deg": round(s_phase, 1),
        })
        if n_amp > 0.3 * n_scale or s_amp > 0.3 * s_scale:
            logger.warning(
                "同轴度修正：极值一圈一次幅值过大（N %.2f%% / S %.2f%%），跳过幅值修正"
                % (n_amp / n_scale * 100.0, s_amp / s_scale * 100.0)
            )
            return n_values, s_values, info

        info["amp_applied"] = True
        return n_fixed, s_fixed, info

    def _wave_analysis(self, x, y):
        """波形分析核心算法
        
        Args:
            x: 角度数据数组
            y: 磁场数据数组
            
        Returns:
            dict: 分析结果字典
        """
        try:
            # =====================================================================
            # Part 0: 同轴度（偏心）修正——固定启用，不再由界面开关控制
            #   角度域：扣掉过零点偏差里的一圈一次分量
            #   幅值域：扣掉极值幅值里的一圈一次偏移与灵敏度调制
            #   两个域都只剥离一圈一次项，波形本身不做重采样，避免插值带来
            #   额外谐波失真（THD / 面积仍按原始波形计算）。
            # =====================================================================
            zero_angles_raw = self._detect_zero_angles(x, y)
            zero_angles, concentricity_info = self._concentricity_angle_correction(
                x, zero_angles_raw)

            # =====================================================================
            # Part 1: 过零点分析（上面的 zero_angles 即修正后的结果，用来定义极性区间）
            # =====================================================================
            # =====================================================================
            # Part 2: 极值分析（后执行 - 在过零点定义的区间内查找极值）
            # =====================================================================
            N_peak_values = np.array([])
            S_peak_values = np.array([])
            N_peak_source_indices = np.array([], dtype=int)
            S_peak_source_indices = np.array([], dtype=int)

            if len(zero_angles) >= 2:
                # 在相邻两个过零点之间查找极值
                # 每两个相邻过零点之间应该恰好有一个极值
                span = float(x[-1] - x[0])
                
                for i in range(len(zero_angles)):
                    start_angle = zero_angles[i]
                    end_angle = zero_angles[(i + 1) % len(zero_angles)]
                    
                    # 处理闭合问题：如果是跨越 360° 的最后一个区间
                    if i == len(zero_angles) - 1:
                        end_angle += span
                    
                    # 提取该区间内的数据（不包含边界点）
                    if i == len(zero_angles) - 1 and end_angle > x[-1]:
                        # 跨越 360° 的区间，分成两段
                        mask1 = (x > start_angle)
                        mask2 = (x < (end_angle - span))
                        mask = mask1 | mask2
                    else:
                        # 普通区间
                        mask = (x > start_angle) & (x < end_angle)
                    
                    y_interval = y[mask]
                    original_indices = np.where(mask)[0]
                    
                    if len(y_interval) < 2:
                        logger.debug(f"  区间 {i+1} ({start_angle:.2f}°-{end_angle:.2f}°): 数据点不足")
                        continue
                    
                    # 判断极性：取区间中点的磁场值
                    midpoint = start_angle + (end_angle - start_angle) / 2
                    sample_angle = ((midpoint - x[0]) % span) + x[0]
                    midpoint_value = float(np.interp(sample_angle, x, y))
                    is_positive = midpoint_value >= 0
                    
                    if is_positive:
                        # N 极区间：在此区间内应该有 1 个最大值
                        max_idx_local = np.argmax(y_interval)
                        max_idx_global = original_indices[max_idx_local]
                        max_value = float(y[max_idx_global])
                        max_angle = float(x[max_idx_global])
                        
                        logger.debug(
                            f"  N极：过零点 {start_angle:.2f}° → {end_angle:.2f}° 中的极值 = "
                            f"{max_angle:.2f}°, 幅值 {max_value:.2f} mT"
                        )
                        
                        # 保留所有 N 极极值（每个区间一定有一个）
                        N_peak_source_indices = np.concatenate((N_peak_source_indices, [max_idx_global]))
                        N_peak_values = np.concatenate((N_peak_values, [max_value]))
                    else:
                        # S 极区间：在此区间内应该有 1 个最小值
                        min_idx_local = np.argmin(y_interval)
                        min_idx_global = original_indices[min_idx_local]
                        min_value = float(y[min_idx_global])
                        min_angle = float(x[min_idx_global])
                        
                        logger.debug(
                            f"  S极：过零点 {start_angle:.2f}° → {end_angle:.2f}° 中的极值 = "
                            f"{min_angle:.2f}°, 幅值 {-min_value:.2f} mT"
                        )
                        
                        # 保留所有 S 极极值（每个区间一定有一个）
                        S_peak_source_indices = np.concatenate((S_peak_source_indices, [min_idx_global]))
                        S_peak_values = np.concatenate((S_peak_values, [-min_value]))
                
                logger.debug(
                    f"  极值检测完成：共检测到 {len(zero_angles)} 个区间，"
                    f"N极极值 {len(N_peak_values)} 个，S极极值 {len(S_peak_values)} 个"
                )
            else:
                # 当过零点数量不足时，降级为全局检测
                logger.debug("  过零点数量不足，降级为全局极值检测")
                N_part = y[y >= 0]
                S_part = abs(y[y <= 0])

                N_indices = np.where(y >= 0)[0]
                S_indices = np.where(y <= 0)[0]

                N_peaks, _ = find_peaks(N_part, height=1.0, distance=20, prominence=0.5)
                N_peak_values = N_part[N_peaks]
                N_peak_source_indices = N_indices[N_peaks] if len(N_peaks) > 0 else np.array([], dtype=int)
                
                S_peaks, _ = find_peaks(S_part, height=1.0, distance=20, prominence=0.5)
                S_peak_values = S_part[S_peaks]
                S_peak_source_indices = S_indices[S_peaks] if len(S_peaks) > 0 else np.array([], dtype=int)

            # 同轴度修正（幅值域）：N/S 极值幅值扣掉一圈一次偏移与灵敏度调制。
            # peak_details 里 'value' 仍保留原始值（与波形曲线对得上），
            # 'abs_value' / 'error_percent' 用修正后的幅值，和统计口径一致。
            if len(N_peak_values) and len(S_peak_values):
                N_peak_values, S_peak_values, amp_info = self._concentricity_amplitude_correction(
                    x,
                    x[np.asarray(N_peak_source_indices, dtype=int)],
                    N_peak_values,
                    x[np.asarray(S_peak_source_indices, dtype=int)],
                    S_peak_values,
                )
                concentricity_info.update(amp_info)
            else:
                concentricity_info.update({"amp_applied": False, "peak_count": 0})

            peak_details = []
            for source_index, value in zip(N_peak_source_indices, N_peak_values):
                peak_details.append({
                    'pole': 'N',
                    'angle': round(float(x[source_index]), 6),
                    'value': round(float(y[source_index]), 6),
                    'abs_value': round(float(value), 6),
                })
            for source_index, value in zip(S_peak_source_indices, S_peak_values):
                peak_details.append({
                    'pole': 'S',
                    'angle': round(float(x[source_index]), 6),
                    'value': round(float(y[source_index]), 6),
                    'abs_value': round(float(value), 6),
                })
            peak_details.sort(key=lambda item: item['angle'])

            # 计算N极统计
            if len(N_peak_values) > 1:
                N_max = round(float(np.max(N_peak_values)), 2)
                N_min = round(float(np.min(N_peak_values)), 2)
                N_mean = round(np.mean(N_peak_values), 2)
                N_se = round(np.std(N_peak_values, ddof=1)/np.mean(N_peak_values)*100, 2)
            elif len(N_peak_values) == 1:
                N_max = N_min = N_mean = round(float(N_peak_values[0]), 2)
                N_se = float('nan')
                logger.debug(f"  N极只有1个峰值: {N_max}")
            else:
                N_max = N_min = N_mean = N_se = float('nan')
                logger.debug("  N极无有效峰值")

            # 计算S极统计
            if len(S_peak_values) > 1:
                S_max = round(float(np.max(S_peak_values)), 2)
                S_min = round(float(np.min(S_peak_values)), 2)
                S_mean = round(np.mean(S_peak_values), 2)
                S_se = round(np.std(S_peak_values, ddof=1)/np.mean(S_peak_values)*100, 2)
            elif len(S_peak_values) == 1:
                S_max = S_min = S_mean = round(float(S_peak_values[0]), 2)
                S_se = float('nan')
                logger.debug(f"  S极只有1个峰值: {S_max}")
            else:
                S_max = S_min = S_mean = S_se = float('nan')
                logger.debug("  S极无有效峰值")

            for item in peak_details:
                if item['pole'] == 'N' and np.isfinite(N_mean) and N_mean != 0:
                    item['error_percent'] = round((item['abs_value'] - float(N_mean)) / float(N_mean) * 100, 5)
                elif item['pole'] == 'S' and np.isfinite(S_mean) and S_mean != 0:
                    item['error_percent'] = round((item['abs_value'] - float(S_mean)) / float(S_mean) * 100, 5)
                else:
                    item['error_percent'] = float('nan')

            # 计算NS_2
            peak_combine = np.concatenate((N_peak_values, S_peak_values))
            NS_2 = round(np.mean(peak_combine), 2) if len(peak_combine) > 0 else float('nan')

            # =====================================================================
            # Part 3: 极间隔分析（基于已有的过零点）
            # =====================================================================
            N_interval, S_interval, SinglePolarValue = [], [], []
            SinglePolarError, PolarErrorSumList = [], []

            if len(zero_angles) >= 2:
                N_interval, S_interval, SinglePolarValue = self._build_circular_polar_intervals(
                    zero_angles, x, y
                )

                # 验证间隔数量一致性
                if len(N_interval) > 0 and len(S_interval) > 0:
                    logger.debug(f"  N极间隔数量: {len(N_interval)}, S极间隔数量: {len(S_interval)}")
                if len(N_interval) != len(S_interval):
                    logger.debug(
                        f"  N/S极间隔数量不一致: N={len(N_interval)}, S={len(S_interval)}"
                    )

                # 单极误差
                if len(SinglePolarValue) > 0:
                    mean_polar = np.mean(SinglePolarValue)

                    for i in range(len(SinglePolarValue)):
                        error = (SinglePolarValue[i] - mean_polar) / mean_polar * 100
                        SinglePolarError.append(error)

                # 偏心的一圈一次分量已在分析入口（Part 0）统一剥离：过零点走角度域、
                # 极值幅值走幅值域。这里直接用修正后的过零点算间隔误差即可，
                # 无需再对误差列表做正弦拟合。

                # 误差和：基于当前单极误差列表逐项累加，包含起点0以保持累计范围定义完整
                errorSum = 0
                PolarErrorSumList.append(errorSum)
                for i in range(len(SinglePolarError)):
                    errorSum += SinglePolarError[i]
                    PolarErrorSumList.append(errorSum)
            else:
                logger.debug("过零点数量不足，无法计算极间隔")

            zero_crossing_details = []
            if len(zero_angles) >= 2:
                span = float(x[-1] - x[0])
                # 修正前后的过零点数量一一对应；数量不一致时退回用修正值
                raw_angles = (list(zero_angles_raw) if len(zero_angles_raw) == len(zero_angles)
                              else list(zero_angles))
                for i, start_angle in enumerate(zero_angles):
                    end_angle = zero_angles[(i + 1) % len(zero_angles)]
                    if i == len(zero_angles) - 1:
                        end_angle += span
                    interval = float(end_angle - start_angle)
                    midpoint = start_angle + interval / 2
                    sample_angle = ((midpoint - x[0]) % span) + x[0] if span > 0 else midpoint
                    midpoint_value = float(np.interp(sample_angle, x, y))
                    zero_crossing_details.append({
                        # angle 保留实测角度（与原始波形曲线对得上），
                        # angle_corrected 是剥离一圈一次偏心后的角度，
                        # interval_to_next 也按修正后角度计算。
                        'angle': round(float(raw_angles[i]), 6),
                        'angle_corrected': round(float(start_angle), 6),
                        'interval_to_next': round(interval, 6),
                        'pole': 'N' if midpoint_value >= 0 else 'S',
                    })

            period_error_details = []
            for index, period_angle in enumerate(SinglePolarValue):
                error_percent = SinglePolarError[index] if index < len(SinglePolarError) else float('nan')
                cumulative_error = PolarErrorSumList[index + 1] if index + 1 < len(PolarErrorSumList) else float('nan')
                period_error_details.append({
                    'index': index + 1,
                    'period_angle': round(float(period_angle), 6),
                    'error_percent': round(float(error_percent), 6) if np.isfinite(error_percent) else float('nan'),
                    'cumulative_error': round(float(cumulative_error), 6) if np.isfinite(cumulative_error) else float('nan'),
                })

            # =====================================================================
            # Part 4: 其他分析指标（面积、THD、极对数等）
            # =====================================================================

            # 计算N极间隔统计
            if len(N_interval) > 1:
                N_interval_max = round(float(np.max(N_interval)), 2)
                N_interval_min = round(float(np.min(N_interval)), 2)
                N_interval_mean = round(np.mean(N_interval), 2)
                N_interval_std = round(np.std(N_interval, ddof=1)/np.mean(N_interval)*100, 2)
            elif len(N_interval) == 1:
                N_interval_max = N_interval_min = N_interval_mean = round(float(N_interval[0]), 2)
                N_interval_std = float('nan')
                logger.debug(f"  N极间隔只有1个: {N_interval_max}")
            else:
                N_interval_max = N_interval_min = N_interval_mean = N_interval_std = float('nan')
                logger.debug("  N极间隔数据为空")

            # 计算S极间隔统计
            if len(S_interval) > 1:
                S_interval_max = round(float(np.max(S_interval)), 2)
                S_interval_min = round(float(np.min(S_interval)), 2)
                S_interval_mean = round(np.mean(S_interval), 2)
                S_interval_std = round(np.std(S_interval, ddof=1)/np.mean(S_interval)*100, 2)
            elif len(S_interval) == 1:
                S_interval_max = S_interval_min = S_interval_mean = round(float(S_interval[0]), 2)
                S_interval_std = float('nan')
                logger.debug(f"  S极间隔只有1个: {S_interval_max}")
            else:
                S_interval_max = S_interval_min = S_interval_mean = S_interval_std = float('nan')
                logger.debug("  S极间隔数据为空")

            # Part 3: 面积计算
            try:
                mask = x < 360
                x_filtered = x[mask]
                y_filtered = y[mask]

                N_part = np.where(y_filtered < 0, 0, y_filtered)
                N_area = round(_TRAPZ(N_part, x_filtered), 2)

                S_part = np.where(y_filtered > 0, 0, y_filtered)
                S_area = abs(round(_TRAPZ(S_part, x_filtered), 2))

                NS_area = round(N_area + S_area, 2)
            except Exception as e:
                N_area = S_area = NS_area = float('nan')
                logger.debug(f"  面积计算失败: {e}")

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
                logger.debug(f"  THD计算失败: {e}")

            # 计算极对数（使用FFT的基波频率索引）
            try:
                # 基波频率索引即为极对数
                if fundamental_idx > 0:
                    pole_num = int(fundamental_idx)
                else:
                    pole_num = float('nan')
                logger.debug(f"  极对数: {pole_num}")
            except Exception as e:
                pole_num = float('nan')
                logger.debug(f"  极对数计算失败: {e}")

            # 计算单极统计
            if len(SinglePolarValue) > 1:
                SinglePolarMean = round(np.mean(SinglePolarValue), 2)
                SinglePolarErrorMax = round(float(np.max(np.abs(SinglePolarError))), 5)
                PolarErrorSum = round(float(np.max(PolarErrorSumList)-np.min(PolarErrorSumList)), 5)
            else:
                SinglePolarMean = SinglePolarErrorMax = PolarErrorSum = float('nan')
                logger.debug("  单极统计数据不足")

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
                'pole_num': pole_num,
                'zero_crossing_details': zero_crossing_details,
                'peak_details': peak_details,
                'period_error_details': period_error_details,
                # 同轴度（偏心）修正诊断：角度偏心、幅值偏移/调制及其相位
                'concentricity': concentricity_info,
            }

            if concentricity_info.get("angle_applied") or concentricity_info.get("amp_applied"):
                logger.info(
                    "同轴度修正（固定启用）: 角度偏心 %.3f°(相位 %s)→ 过零点偏差 std %.3f°→%.3f°; "
                    "极值一圈一次幅值 N %.3f mT(%.2f%%, 相位 %s°), S %.3f mT(%.2f%%, 相位 %s°)"
                    % (concentricity_info.get("angle_amp_deg", 0.0),
                       concentricity_info.get("angle_phase_deg"),
                       concentricity_info.get("crossing_dev_std_deg_before", float("nan")),
                       concentricity_info.get("crossing_dev_std_deg_after", float("nan")),
                       concentricity_info.get("n_1x_mT", 0.0),
                       concentricity_info.get("n_1x_pct", 0.0),
                       concentricity_info.get("n_1x_phase_deg"),
                       concentricity_info.get("s_1x_mT", 0.0),
                       concentricity_info.get("s_1x_pct", 0.0),
                       concentricity_info.get("s_1x_phase_deg"))
                )
            else:
                logger.info("同轴度修正：本次数据不满足修正条件，未做一圈一次剥离")

            # 记录最终指标，便于追踪分析结果。
            for key, value in results.items():
                logger.debug(f"  {key}: {value}")

            logger.info("=== 波形分析完成 ===")

            return results

        except Exception as e:
            logger.debug(f"波形分析算法执行出错: {e}")
            return {}
