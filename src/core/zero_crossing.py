# -*- coding: utf-8 -*-
"""同向过零实际间距：从整圈「角度-磁场」数据提取每个磁周期的实际机械角跨度。

按《CC01 同向过零实际间距算法说明》（2026-11-19）实现：

    磁场减整圈均值
    → 周期高斯平滑（σ = 8 点，wrap）
    → 相邻样点异号处线性插值求过零角
    → 排序并标记上升 / 下降方向
    → 相邻过零宽度 w
    → 同向间距 T[i] = w[i] + w[i+1]

SPO 与 atan2 不参与本计算：这里直接从处理后的扫描磁场取几何角间距。
"""

from dataclasses import dataclass

import numpy as np
from scipy.ndimage import gaussian_filter1d

SMOOTH_SIGMA = 8.0
SMOOTH_TRUNCATE = 4.0


class ZeroCrossingError(Exception):
    """波形不满足过零提取条件（点数、方向交替、角序、极对数等）。"""


@dataclass
class TrackIntervals:
    """单条码道的同向过零结果（角度单位均为机械度）。"""

    pole_pairs: int
    cross_deg: np.ndarray      # 每个同向间距的起始过零角
    same_deg: np.ndarray       # 实际同向间距 T
    rising: np.ndarray         # 起始过零是否为上升过零
    adjacent_deg: np.ndarray   # 相邻过零宽度 w（半个磁周期）
    nominal_deg: float         # 标称同向间距 360 / p
    field_mean: float          # 整圈均值（去均值前的基线）

    def stats(self):
        """全精度统计量，供状态栏或导出使用。"""
        same = np.asarray(self.same_deg, dtype=float)
        if not same.size:
            return {'count': 0}
        return {
            'count': int(same.size),
            'nominal_deg': float(self.nominal_deg),
            'mean_deg': float(same.mean()),
            'minimum_deg': float(same.min()),
            'maximum_deg': float(same.max()),
            'std_deg': float(same.std()),
            'peak_to_peak_deg': float(np.ptp(same)),
        }


def same_direction_intervals(angle, field, pole_pairs):
    """计算一条码道的同向过零实际间距。

    Args:
        angle: 机械角数组（从 0° 开始的均匀整圈网格）
        field: 同一网格上的磁场数组（原始值，内部自行去均值）
        pole_pairs: 该码道的极对数（主轨 32 / 游标轨 31）

    Raises:
        ZeroCrossingError: 输入不合法，或过零数量 / 方向交替 / 角序异常
    """
    angle = np.asarray(angle, dtype=float)
    field = np.asarray(field, dtype=float)
    points = int(pole_pairs) if str(pole_pairs).isdigit() else 0
    if points not in (31, 32):
        raise ZeroCrossingError(f'极对数需为 31 或 32，实际 {pole_pairs}')
    if angle.ndim != 1 or angle.shape != field.shape:
        raise ZeroCrossingError('机械角与磁场必须是等长一维数组')
    if angle.size < 4 * points:
        raise ZeroCrossingError('采样点太少，无法覆盖一个完整磁周期')
    if not (np.isfinite(angle).all() and np.isfinite(field).all()):
        raise ZeroCrossingError('机械角或磁场含 NaN / Inf')

    grid = np.arange(angle.size) * 360.0 / angle.size
    if np.max(np.abs(angle - grid)) > 1e-6:
        raise ZeroCrossingError('需要从 0° 开始的均匀整圈网格')

    field_mean = float(field.mean())
    smoothed = gaussian_filter1d(field - field_mean, SMOOTH_SIGMA,
                                 mode='wrap', truncate=SMOOTH_TRUNCATE)
    next_values = np.roll(smoothed, -1)
    indices = np.flatnonzero((smoothed < 0) != (next_values < 0))
    step = 360.0 / angle.size
    cross = (angle[indices]
             - smoothed[indices] / (next_values[indices] - smoothed[indices]) * step) % 360.0
    order = np.argsort(cross)
    cross = cross[order]
    rising = (next_values[indices] > 0)[order]

    if cross.size != 2 * points:
        raise ZeroCrossingError(
            f'{points} 极对应有 {2 * points} 个过零点，实际 {cross.size} 个')
    if int(rising.sum()) != points:
        raise ZeroCrossingError(
            f'上升过零应为 {points} 个，实际 {int(rising.sum())} 个')
    if not np.all(rising != np.roll(rising, 1)):
        raise ZeroCrossingError('过零方向未严格交替，波形可能退化')

    width = np.diff(np.r_[cross, cross[0] + 360.0])
    if np.any(width <= 0):
        raise ZeroCrossingError('过零角重复或角序异常')
    same = width + np.roll(width, -1)

    extended = np.r_[cross, cross[:2] + 360.0]
    if not np.allclose(same, extended[2:] - extended[:-2], rtol=0, atol=1e-10):
        raise ZeroCrossingError('同向间距周期窗口复核失败')
    nominal = 360.0 / points
    if not np.isclose(same.mean(), nominal, atol=1e-10):
        raise ZeroCrossingError('整圈同向间距均值不等于标称周期')

    return TrackIntervals(
        pole_pairs=points,
        cross_deg=cross,
        same_deg=same,
        rising=rising,
        adjacent_deg=width,
        nominal_deg=nominal,
        field_mean=field_mean,
    )



@dataclass
class ZeroPosition:
    """单条码道的过零点位置偏差（相对本道理想等距过零网格）。"""

    pole_pairs: int
    cross_deg: np.ndarray      # 实际过零角
    fixed_offset_deg: float    # 本道拟合出的固定零位 a
    ideal_deg: np.ndarray      # 理想网格 a + i·h
    position_deg: np.ndarray   # 位置偏差 e = z - (a + i·h)

    @property
    def half_period_deg(self):
        """理想相邻过零间隔 h = 180 / p。"""
        return 180.0 / self.pole_pairs

    def stats(self):
        e = np.asarray(self.position_deg, dtype=float)
        return {
            'count': int(e.size),
            'fixed_offset_deg': float(self.fixed_offset_deg),
            'minimum_deg': float(e.min()),
            'maximum_deg': float(e.max()),
            'peak_to_peak_deg': float(np.ptp(e)),
        }


def zero_position_deviation(cross_deg, pole_pairs):
    """按《CC01 过零点位置偏差算法说明》求单道位置偏差。

    固定标称间隔 h = 180/p，只拟合本道零位 a（u = z - i·h 的均值），
    偏差 e[i] = z[i] - (a + i·h)，整圈 mean(e) = 0。

    Args:
        cross_deg: 该道排序后的过零角（2p 个，递增，[0°, 360°)）
        pole_pairs: 极对数（主轨 32 / 游标轨 31）
    """
    cross = np.asarray(cross_deg, dtype=float)
    points = int(pole_pairs) if str(pole_pairs).isdigit() else 0
    if points not in (31, 32):
        raise ZeroCrossingError(f'极对数需为 31 或 32，实际 {pole_pairs}')
    if (cross.ndim != 1 or cross.size != 2 * points
            or not np.isfinite(cross).all()
            or np.any(cross < 0) or np.any(cross >= 360)
            or np.any(np.diff(cross) <= 0)):
        raise ZeroCrossingError('需要完整、递增、位于 [0°,360°) 的过零角')

    half_period = 180.0 / points
    # 与报告实现保持同一浮点运算顺序
    base = cross - np.arange(cross.size) * 180 / points
    offset = float(base.mean())
    position = base - offset
    ideal = offset + np.arange(cross.size) * half_period

    width = np.diff(np.r_[cross, cross[0] + 360.0])
    step = np.roll(position, -1) - position
    if not np.allclose(step, width - half_period, rtol=0, atol=1e-10):
        raise ZeroCrossingError('位置偏差与相邻间距的关系复核失败')

    return ZeroPosition(pole_pairs=points, cross_deg=cross,
                        fixed_offset_deg=offset, ideal_deg=ideal,
                        position_deg=position)


def dual_track_difference(angle_deg, outer, inner, report_rounding=False):
    """外道减内道的位置偏差（在共同机械角网格上按 360° 周期插值）。

    Args:
        angle_deg: 共同机械角网格（与解算所用网格一致，点数跟随输入数据）
        outer: 外道 ZeroPosition
        inner: 内道 ZeroPosition
        report_rounding: True 时按报告口径先舍入到 6 / 5 位小数再插值
    """
    angle = np.asarray(angle_deg, dtype=float)
    if angle.ndim != 1 or not np.isfinite(angle).all():
        raise ZeroCrossingError('共同机械角网格必须是有限一维序列')
    if outer is None or inner is None:
        raise ZeroCrossingError('缺少某一道的位置偏差结果')

    outer_cross = np.asarray(outer.cross_deg, dtype=float)
    inner_cross = np.asarray(inner.cross_deg, dtype=float)
    outer_position = np.asarray(outer.position_deg, dtype=float)
    inner_position = np.asarray(inner.position_deg, dtype=float)
    if report_rounding:
        # 复现报告里“过零角 6 位、位置偏差 5 位”的序列化顺序
        outer_cross = np.round(outer_cross, 6)
        inner_cross = np.round(inner_cross, 6)
        outer_position = np.round(outer_position, 5)
        inner_position = np.round(inner_position, 5)

    difference = (np.interp(angle, outer_cross, outer_position, period=360.0)
                  - np.interp(angle, inner_cross, inner_position, period=360.0))
    return np.round(difference, 5) if report_rounding else difference


__all__ = [
    'SMOOTH_SIGMA',
    'SMOOTH_TRUNCATE',
    'TrackIntervals',
    'ZeroCrossingError',
    'ZeroPosition',
    'dual_track_difference',
    'same_direction_intervals',
    'zero_position_deviation',
]
