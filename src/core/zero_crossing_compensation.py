# -*- coding: utf-8 -*-
"""过零点偏差补偿：设备侧固定角域误差的曲线表与角度去扭曲。

设备（转台 / 卡盘 / 装夹偏心 + 扫描链路的角域误差）会让每个磁周期的过零点
相对理想等距网格偏移，偏移量 e(θ) 在同一台设备上重复出现（10 组良品用
``core.zero_crossing`` 拟合出的曲线解释各样品偏差方差的 97% 以上）。

本模块把这条设备曲线做成配置表，并按「测量角 = 真角 + e(真角)」的模型
把波形重采样回均匀真角网格：

    corrected(θ) = field_interp(θ + e(θ))

补偿只改采样位置（角度域去扭曲），不改幅值，也不改角度列本身——
输出与输入**逐点对应**（点数、角度网格完全相同），值由相邻源点插值得到，
因此不会增加有效分辨率；输出的角度仍是 0–360° 均匀网格，可以直接进入
绘图、保存与分析流程。

曲线按**极对数**存放（32 / 31 两条设备曲线完全不同），另支持通配键 ``*``。
"""

import json

import numpy as np

# 配置文件里的键名
CONFIG_KEY = 'zero_crossing_compensation'
# 通配键：没有对应极对数的专属曲线时用它兜底
GLOBAL_KEY = '*'
# 默认角分辨率（度）：设备曲线是一圈一次的平滑形状，0.5° 足够
DEFAULT_STEP_DEG = 0.5


def polar_key(pole_pairs) -> str:
    """补偿曲线键：极对数字符串。"""
    try:
        return str(int(pole_pairs))
    except (TypeError, ValueError):
        return ''


def parse_table(raw) -> dict:
    """解析配置里的 JSON 表：``{key: {"step_deg": 0.5, "values": [...]}}``。"""
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    table = {}
    for key, item in parsed.items():
        if not isinstance(item, dict):
            continue
        if item.get('enabled') is False:
            continue
        values = item.get('values')
        if not isinstance(values, list) or not values:
            continue
        try:
            step = float(item.get('step_deg', DEFAULT_STEP_DEG))
            table[str(key)] = (step, np.asarray([float(v) for v in values], dtype=float))
        except (TypeError, ValueError):
            continue
    return table


def dump_table(table: dict) -> str:
    """把 ``{key: (step_deg, values)}`` 序列化成配置用的 JSON 字符串。"""
    payload = {}
    for key, item in table.items():
        try:
            step, values = item
        except (TypeError, ValueError):
            continue
        payload[str(key)] = {
            'step_deg': float(step),
            'values': [round(float(v), 6) for v in np.asarray(values, dtype=float)],
        }
    return json.dumps(payload, ensure_ascii=False, separators=(',', ':'))


def sample_curve(values, step_deg: float, angles) -> np.ndarray:
    """按角度周期线性插值取偏差曲线（度）。"""
    values = np.asarray(values, dtype=float)
    angles = np.asarray(angles, dtype=float)
    if values.size == 0:
        return np.zeros(angles.shape, dtype=float)
    step = float(step_deg) or DEFAULT_STEP_DEG
    grid = np.append(np.arange(values.size) * step, 360.0)
    extended = np.append(values, values[0])
    return np.interp(np.mod(angles, 360.0), grid, extended)


def lookup(table: dict, pole_pairs):
    """按极对数取曲线，缺失时回退通配键。返回 ``(key, step_deg, values)``。"""
    key = polar_key(pole_pairs)
    if key and key in table:
        step, values = table[key]
        return key, step, values
    if GLOBAL_KEY in table:
        step, values = table[GLOBAL_KEY]
        return GLOBAL_KEY, step, values
    return '', 0.0, None


def apply(angle, mag, table: dict, pole_pairs=None):
    """按设备曲线把波形重采样到均匀真角网格。

    Args:
        angle: 机械角序列（0° 起的均匀单圈网格）
        mag: 同一网格上的磁场
        table: ``parse_table()`` 的结果
        pole_pairs: 当前样品的极对数（用于选曲线）

    Returns:
        ``(corrected, info)``；没有可用曲线或输入不合法时 ``corrected`` 为 None，
        ``info['applied']`` 为 False 并带 ``reason``。
    """
    key, step, values = lookup(table or {}, pole_pairs)
    info = {'applied': False, 'key': key, 'step_deg': float(step),
            'pole_pairs': polar_key(pole_pairs), 'reason': ''}
    if values is None:
        info['reason'] = '无对应极对数的补偿曲线'
        return None, info

    angle = np.asarray(angle, dtype=float)
    mag = np.asarray(mag, dtype=float)
    if angle.ndim != 1 or angle.shape != mag.shape or angle.size < 4:
        info['reason'] = '角度与磁场长度不一致或点数太少'
        return None, info
    if not (np.isfinite(angle).all() and np.isfinite(mag).all()):
        info['reason'] = '角度或磁场含 NaN / Inf'
        return None, info
    if np.any(np.diff(angle) <= 0):
        info['reason'] = '角度序列不是单调递增'
        return None, info

    deviation = sample_curve(values, step, angle)
    info['peak_deg'] = float(np.max(np.abs(deviation)))
    if not np.any(np.abs(deviation) > 0):
        info['reason'] = '补偿曲线全零'
        return None, info

    # 测量角 = 真角 + e(真角)：把均匀真角上的取值重采样回来
    corrected = np.interp(np.mod(angle + deviation, 360.0), angle, mag, period=360.0)
    info['applied'] = True
    return corrected, info


__all__ = [
    'CONFIG_KEY',
    'DEFAULT_STEP_DEG',
    'GLOBAL_KEY',
    'apply',
    'dump_table',
    'lookup',
    'parse_table',
    'polar_key',
    'sample_curve',
]
