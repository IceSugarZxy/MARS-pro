# -*- coding: utf-8 -*-
"""爪盘（空测）单周期补偿曲线：生成、解析与按角度扣除。

空测（样品不在爪盘上）时，爪盘自身的剩磁随转角变化，会在波形上叠加一个
"一圈一次"的波动。本模块负责：

1. 把一批空测波形按角度分箱平均成等间隔的单周期曲线（``build_curve``）；
2. 把多条曲线求平均（``mean_curves``）；
3. 按任意角度周期插值取补偿值（``sample_curve``）。

曲线按 ``PGA:IDAC:速度`` 作为键存放：同一个爪盘波动在粗量程下会被 ADC 量化
"压平"（例如 ×1/IDAC3 时 1 个计数就是 0.354 mT），与细量程下测得的形状并不相同，
所以只在与采集档位完全一致时才应用，避免把细量程拟合出来的曲线套到别的量程上。

本模块只依赖 numpy，供配置解析与数据处理共用。
"""

import json

import numpy as np

# 配置文件里的键名
CONFIG_KEY = 'chuck_compensation'
# 通配键：爪盘波动是物理磁场（mT），与量程无关，允许用一条曲线覆盖所有采集档位
GLOBAL_KEY = '*'
# 默认角分辨率（度）；空测波动是平滑的一圈一次形状，1° 足够
DEFAULT_STEP_DEG = 1.0


def comp_key(pga_index: int, idac_index: int, speed_index: int) -> str:
    """补偿曲线的键：``PGA:IDAC:速度``。"""
    return '%d:%d:%d' % (int(pga_index), int(idac_index), int(speed_index))


def _bin_count(step_deg: float) -> int:
    step = float(step_deg) or DEFAULT_STEP_DEG
    return max(1, int(round(360.0 / step)))


def build_curve(angle, mag, step_deg: float = DEFAULT_STEP_DEG) -> np.ndarray:
    """把一整圈（或多圈）空测波形按角度分箱平均成等间隔单周期曲线。

    角度先对 360° 取模；同一角度箱内的采样点取平均（顺带起到低通滤波作用），
    空箱用相邻非空箱线性插值补齐。
    """
    angle = np.asarray(angle, dtype=float)
    mag = np.asarray(mag, dtype=float)
    n_bins = _bin_count(step_deg)
    step = 360.0 / n_bins
    if angle.size == 0 or mag.size == 0:
        return np.zeros(n_bins, dtype=float)

    count = min(angle.size, mag.size)
    angle = np.mod(angle[:count], 360.0)
    mag = mag[:count]

    index = np.clip((angle / step).astype(int), 0, n_bins - 1)
    sums = np.bincount(index, weights=mag, minlength=n_bins)
    counts = np.bincount(index, minlength=n_bins).astype(float)
    curve = np.full(n_bins, np.nan, dtype=float)
    np.divide(sums, counts, out=curve, where=counts > 0)

    # 空箱（采样点没落到该角度区间）用环形插值补齐
    if not np.all(np.isfinite(curve)):
        grid = np.arange(n_bins) * step
        valid = np.isfinite(curve)
        if np.any(valid):
            curve = np.interp(grid, np.append(grid[valid], grid[valid] + 360.0),
                              np.append(curve[valid], curve[valid]))
        else:
            curve = np.zeros(n_bins, dtype=float)
    return curve


def mean_curves(curves) -> np.ndarray:
    """把多条等长曲线逐点求平均（多轮空测降噪）。"""
    arr = [np.asarray(c, dtype=float) for c in curves if c is not None and len(c)]
    if not arr:
        return np.zeros(0, dtype=float)
    return np.mean(np.vstack(arr), axis=0)


def sample_curve(values, step_deg: float, angles) -> np.ndarray:
    """按角度周期线性插值取补偿值（度）。"""
    values = np.asarray(values, dtype=float)
    if values.size == 0:
        return np.zeros(np.asarray(angles).shape, dtype=float)
    n_bins = values.size
    step = 360.0 / n_bins
    grid = np.append(np.arange(n_bins) * step, 360.0)
    value_ext = np.append(values, values[0])
    angle = np.mod(np.asarray(angles, dtype=float), 360.0)
    return np.interp(angle, grid, value_ext)


def parse_table(raw) -> dict:
    """解析配置里的 JSON 表：``{key: {"step_deg": 1.0, "values": [...]}}``。"""
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
