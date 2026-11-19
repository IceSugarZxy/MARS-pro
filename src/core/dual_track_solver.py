# -*- coding: utf-8 -*-
"""双码道解算：磁场 CSV → 32/31 相位码 → 原厂 B12 DLL 求 SPO 表 → 残差/评级。

主轨（外圈）32 极对，游标轨（内圈）31 极对。流程按《CC01 从磁场 CSV 到相位码及
B12 SPO 解算的 AI 交接说明》（2026-11-19）实现：

    两轨 CSV（0–360° 均匀单圈网格，点数不限 → 统一重采样到 32768 点）
    → 每道重建正交 Sin/Cos（全带空间移位差分，或基波旁带 ±w）
    → 基波幅值和固定相位归一化
    → 每磁周期 1、2 次相位谐波拟合并按量化参数校正
    → atan2 → 量化成 14 bit 相位码（0–16383）
    → 原厂 DLL 求建议表、应用、读回、复跑
    → 独立公式复算查档 k、补偿 C、分支与残差 R，逐点核对
"""

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from core.mu150_spo import (
    BOUNDARY,
    PHASE_PERIOD,
    SPO_PERIOD,
    analyze_with_dll,
    spo_buckets,
)

K_PER_DEGREE = PHASE_PERIOD / 360.0
POINTS_PER_REV = 32768
# 实测一圈点数随测量时长/采样档变化（32756、27720、65536 …），少于该值相位码不可信
MIN_POINTS_PER_REV = 1024
MASTER_POLE_PAIRS = 32
NONIUS_POLE_PAIRS = 31

# 重建模式：None 表示全带空间移位差分，其余为基波旁带 ±w
RECONSTRUCTION_MODES = (
    ('全带空间移位差分', None),
    ('基波旁带±2', 2),
    ('基波旁带±4', 4),
    ('基波旁带±8', 8),
    ('基波旁带±16', 16),
)
DEFAULT_MODE = RECONSTRUCTION_MODES[0][0]


class DualTrackError(Exception):
    """输入数据或解算过程不符合预期。"""


@dataclass
class TrackCalibration:
    """单轨前端重建与等效模拟校正的诊断信息。"""

    pole_pairs: int
    mode: str
    normalization_amplitude: float
    normalization_phase_deg: float
    coefficients_rad: tuple
    dc_applied: tuple
    gain_applied: int
    phase_request_deg: float
    phase_range_deg: float
    phase_applied_deg: float
    minimum_vector: float
    saturated: bool


@dataclass
class DualTrackResult:
    """一对（主轨/游标轨）的完整解算结果。"""

    angle: np.ndarray
    master: np.ndarray
    nonius: np.ndarray
    master_before: np.ndarray
    nonius_before: np.ndarray
    master_calibration: TrackCalibration
    nonius_calibration: TrackCalibration
    mode: str
    native: object
    buckets: np.ndarray
    worst_index: int
    worst_angle_deg: float
    outer_path: str = ''
    inner_path: str = ''
    outer_hash: str = ''
    inner_hash: str = ''
    outer_meta: dict = field(default_factory=dict)
    inner_meta: dict = field(default_factory=dict)
    master_field: np.ndarray = None
    nonius_field: np.ndarray = None

    @property
    def rating(self):
        return self.native.spo.rating

    @property
    def residual(self) -> np.ndarray:
        return np.asarray(self.native.spo.residual, dtype=np.int64)

    @property
    def phase_error(self) -> np.ndarray:
        return np.asarray(self.native.phase_error, dtype=np.int64)

    @property
    def compensation(self) -> np.ndarray:
        return np.asarray(self.native.spo.compensation, dtype=np.int64)

    def summary(self) -> dict:
        rating = self.rating
        return {
            'mode': self.mode,
            'points': int(self.angle.size),
            'master_table_recommendation': tuple(self.native.recommendation),
            'master_table_applied': tuple(self.native.applied_table),
            'compensation_branch': int(self.native.spo.residual_branch),
            'dll_branch': int(self.native.compensation_branch),
            'r_min': int(rating.minimum),
            'r_max': int(rating.maximum),
            'peak': int(rating.peak),
            'occupancy': float(rating.occupancy),
            'margin_codes': int(rating.margin_codes),
            'margin_ratio': float(rating.margin_ratio),
            'within_rating': bool(rating.within_rating),
            'within_boundary': bool(rating.within_decode_boundary),
            'worst_index': int(self.worst_index),
            'worst_angle_deg': float(self.worst_angle_deg),
            'minimum_samples_per_master_period':
                float(self.native.minimum_samples_per_master_period),
            'raw_data_gaps': int(self.native.raw_data_gaps),
        }


def _wrap180(values):
    return (values + 180.0) % 360.0 - 180.0


def quantize_phase(degrees):
    """电角度（度）→ 14 bit 相位码，半码按偶数舍入后回绕。"""
    values = np.asarray(degrees, dtype=float) * K_PER_DEGREE
    return np.ascontiguousarray(np.rint(values).astype(np.int64) % PHASE_PERIOD,
                                dtype=np.uint16)


def read_scan(path, pole_pairs):
    """读取一份磁场 CSV，返回 (机械角, 磁场, 元信息)。

    表头前的行数动态统计（补偿文件会多一行“单周期包络补偿”）。实测数据的一圈点数
    不是固定的（32756 / 27720 / 65536 …，随测量时长与采样档变化），因此只要求
    0° 起的均匀单圈网格，读入后统一重采样到 `POINTS_PER_REV` 点——内外两轨各自独立
    测量，只有这样才可能逐点配对，原厂 DLL 也只要求两轨长度一致。
    """
    path = Path(path)
    header = '角度(度),磁场强度'
    meta = {}
    header_line = None
    with path.open(encoding='utf-8-sig') as stream:
        for number, row in enumerate(stream, 1):
            if row.strip() == header:
                header_line = number
                break
            if ',' in row:
                key, value = row.rstrip('\r\n').split(',', 1)
                meta[key.strip()] = value.strip()
    if header_line is None:
        raise DualTrackError(f'缺少数值表头“{header}”：{path.name}')

    values = np.loadtxt(path, delimiter=',', skiprows=header_line,
                        encoding='utf-8-sig', ndmin=2)
    if values.ndim != 2 or values.shape[1] != 2:
        raise DualTrackError(
            f'{path.name} 需要 2 列（角度, 磁场强度）数值，实际 {values.shape}')
    if not np.isfinite(values).all():
        raise DualTrackError(f'{path.name} 含空值或非数值，实际 {values.shape}')
    if values.shape[0] < MIN_POINTS_PER_REV:
        raise DualTrackError(
            f'{path.name} 只有 {values.shape[0]} 点，一圈至少需要 '
            f'{MIN_POINTS_PER_REV} 点')
    angle, mag = values.T
    step = 360.0 / angle.size
    grid = np.arange(angle.size) * step
    if np.max(np.abs(angle - grid)) > max(1e-6, step * 0.01):
        raise DualTrackError(f'{path.name} 不是从 0° 开始的均匀单圈网格')
    if angle.size != POINTS_PER_REV:
        target = np.arange(POINTS_PER_REV) * (360.0 / POINTS_PER_REV)
        mag = np.interp(target, angle, mag, period=360.0)
        angle = target
        meta['_原始点数'] = str(values.shape[0])

    stored_poles = meta.get('极数')
    unit = meta.get('极数口径')
    if unit and unit != '极对数':
        raise DualTrackError(f'{path.name} 的“极数口径”应为极对数，实际 {unit}')
    if stored_poles and stored_poles != str(pole_pairs):
        raise DualTrackError(
            f'{path.name} 记录极对数 {stored_poles}，与要求的 {pole_pairs} 不符')
    return angle, mag, meta


def _reconstruct(angle, mag, pole_pairs, width):
    """重建正交信号 z0（全带空间移位差分或基波旁带滤波）。"""
    if width is None:
        shift = 90.0 / pole_pairs
        shifted = lambda delta: np.interp((angle + delta) % 360.0, angle, mag, period=360.0)
        real = shifted(shift) - shifted(-shift)
        imag = mag - shifted(-2 * shift)
        return real + 1j * imag

    spectrum = np.fft.fft(mag - mag.mean())
    orders = np.arange(spectrum.size)
    keep = np.abs(orders - pole_pairs) <= width
    return np.fft.ifft(np.where(keep, 2 * spectrum, 0))


def calibrate_track(angle, mag, pole_pairs, width=None, mode_name=DEFAULT_MODE):
    """把单路磁场重建并校正成 14 bit 相位码，返回 (码, 诊断信息)。"""
    z0 = _reconstruct(angle, mag, pole_pairs, width)
    phi = np.deg2rad(pole_pairs * angle)
    reference = np.exp(1j * phi)
    normalization = np.mean(z0 / reference)
    scale = np.max(np.abs(z0)) if z0.size else 0.0
    if scale == 0 or abs(normalization) < scale * 1e-10:
        raise DualTrackError('正向载波缺失：检查扫描方向、极对数或重建模式')

    z = z0 / normalization
    x, y = z.real, z.imag
    pre = quantize_phase(np.angle(z, deg=True))

    design = np.column_stack([
        np.ones(angle.size), np.cos(phi), np.sin(phi),
        np.cos(2 * phi), np.sin(2 * phi),
    ])
    error = np.deg2rad(_wrap180(pre / K_PER_DEGREE - pole_pairs * angle))
    coefficients = np.linalg.lstsq(design, error, rcond=None)[0]
    _, c1, s1, c2, s2 = coefficients

    if 1 + 2 * s2 <= 0:
        raise DualTrackError('等效增益请求超出映射定义域（1+2s2≤0）')

    dc = np.rint([1000 * s1, -1000 * c1]).clip(-63, 63).astype(int)
    gain_request = 2048 * np.log(1 + 2 * s2) / np.log(20)
    gain = int(np.clip(np.rint(gain_request), -64, 63))
    phase_request = float(np.degrees(np.arcsin(np.clip(-2 * c2, -1, 1))))
    small, large = (8, 16) if pole_pairs == MASTER_POLE_PAIRS else (12, 20)
    span = float(small if abs(phase_request) <= small else large)
    phase_applied = float(np.clip(np.rint(phase_request / span * 63),
                                  -63, 63) * span / 63.0)

    corrected = (x * np.exp(np.log(20) * gain / 2048)
                 + dc[0] / 1000
                 + y * np.sin(np.deg2rad(phase_applied))
                 + 1j * (y + dc[1] / 1000))
    codes = quantize_phase(np.angle(corrected, deg=True))

    diagnostics = TrackCalibration(
        pole_pairs=pole_pairs,
        mode=mode_name,
        normalization_amplitude=float(abs(normalization)),
        normalization_phase_deg=float(np.degrees(np.angle(normalization))),
        coefficients_rad=tuple(float(v) for v in coefficients),
        dc_applied=(int(dc[0]), int(dc[1])),
        gain_applied=gain,
        phase_request_deg=phase_request,
        phase_range_deg=span,
        phase_applied_deg=phase_applied,
        minimum_vector=float(np.min(np.abs(corrected))),
        saturated=bool(
            np.max(np.abs([1000 * s1, -1000 * c1])) > 63
            or not -64 <= gain_request <= 63
            or abs(phase_request) > large
            or abs(-2 * c2) > 1
        ),
    )
    return codes, diagnostics


def mode_width(mode_name):
    """模式名 → 旁带宽度（全带返回 None）。"""
    for name, width in RECONSTRUCTION_MODES:
        if name == mode_name:
            return width
    raise DualTrackError(f'未知重建模式：{mode_name}')


def solve_pair(outer_path, inner_path, dll_path, mode_name=DEFAULT_MODE,
               applied_table=None):
    """解算一对（外圈主轨 / 内圈游标轨）CSV。

    Args:
        outer_path: 外圈 CSV（32 极对，主轨）
        inner_path: 内圈 CSV（31 极对，游标轨）
        dll_path: 原厂 MU_3SL_INTERFACE_64.DLL
        mode_name: RECONSTRUCTION_MODES 中的模式名
        applied_table: 可选的 SPO 表（BASE + 15/16 段）；省略时用原厂建议表
    """
    width = mode_width(mode_name)
    angle, outer, outer_meta = read_scan(outer_path, MASTER_POLE_PAIRS)
    inner_angle, inner, inner_meta = read_scan(inner_path, NONIUS_POLE_PAIRS)
    if not np.array_equal(angle, inner_angle):
        raise DualTrackError('内外圈角度网格未逐点配对')

    master_before, master_cal = calibrate_track(
        angle, outer, MASTER_POLE_PAIRS, width, mode_name)
    nonius_before, nonius_cal = calibrate_track(
        angle, inner, NONIUS_POLE_PAIRS, width, mode_name)

    try:
        native = analyze_with_dll(dll_path, master_before, nonius_before,
                                  applied_table=applied_table)
    except DualTrackError:
        raise
    except Exception as exc:  # ctypes/DLL 侧错误统一转成可读信息
        raise DualTrackError(f'原厂 DLL 解算失败：{exc}') from exc

    buckets = np.asarray(spo_buckets(master_before, nonius_before), dtype=np.int64)
    if not np.array_equal(buckets, np.asarray(native.spo.buckets, dtype=np.int64)):
        raise DualTrackError('独立查档（k）与原厂结果不一致')

    residual = np.asarray(native.spo.residual, dtype=np.int64)
    worst_index = int(np.argmax(np.abs(residual)))
    if native.spo.rating.margin_codes != BOUNDARY - native.spo.rating.peak:
        raise DualTrackError('裕量核对失败')

    return DualTrackResult(
        angle=angle,
        master=master_before,
        nonius=nonius_before,
        master_before=master_before,
        nonius_before=nonius_before,
        master_calibration=master_cal,
        nonius_calibration=nonius_cal,
        mode=mode_name,
        native=native,
        buckets=buckets,
        worst_index=worst_index,
        worst_angle_deg=float(angle[worst_index]),
        outer_path=str(outer_path),
        inner_path=str(inner_path),
        outer_hash=hashlib.sha256(Path(outer_path).read_bytes()).hexdigest(),
        inner_hash=hashlib.sha256(Path(inner_path).read_bytes()).hexdigest(),
        outer_meta=outer_meta,
        inner_meta=inner_meta,
        master_field=outer,
        nonius_field=inner,
    )


def describe_rating(rating):
    """把评级翻成一句中文结论。"""
    if rating.within_rating:
        return '在 90% 评级线内'
    if rating.within_decode_boundary:
        return '超评级线，但在 256 码解码边界内'
    return '超解码边界'


def bucket_histogram(buckets, bins=128):
    """档号直方图（0–127 共 128 档）。"""
    return np.bincount(np.asarray(buckets, dtype=np.int64), minlength=bins)[:bins]


__all__ = [
    'DEFAULT_MODE',
    'MASTER_POLE_PAIRS',
    'MIN_POINTS_PER_REV',
    'NONIUS_POLE_PAIRS',
    'POINTS_PER_REV',
    'RECONSTRUCTION_MODES',
    'DualTrackError',
    'DualTrackResult',
    'TrackCalibration',
    'bucket_histogram',
    'calibrate_track',
    'describe_rating',
    'mode_width',
    'quantize_phase',
    'read_scan',
    'solve_pair',
]
