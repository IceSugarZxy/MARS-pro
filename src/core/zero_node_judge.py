# -*- coding: utf-8 -*-
"""CC01 实际过零节点三点判定。

按《CC01 实际过零节点三点判断_算法说明》（2026-11-20）实现：对每个内道实际过零
起点，取它的同向实际间距 T内[i]，分别减去外道「最近节点及其前、后节点」的同向
间距，三项差值的最小值再减下限 L，得到判定余量：

    d前 / d中 / d后 = T内[i] − T外[j−1] / T外[j] / T外[j+1]
    H[i] = min(d前, d中, d后) − L          （L = 0.36° × 10% = 0.036°）

    H > 0 通过 / H < 0 不通过 / H = 0 边界待核查

整盘判定取 H 的最小值：H盘 > 0 合格、< 0 不合格、= 0 边界待复核。
外道节点按圆周机械角距离最近匹配（`abs((z外 − z内 + 180) mod 360 − 180)`），
平局取下标较小者，首尾按圆周连接。
"""

import numpy as np

# 固定下限：32/31 码道理论间距差约 0.362903°，按 0.36° 基准的 10% 取 0.036°
LOWER_BOUND_DEG = 0.036
# 参考节点相对最近外道节点的偏移（前 / 中 / 后）
NODE_OFFSETS = (-1, 0, 1)

VERDICT_TEXT = {
    'pass': '合格',
    'fail': '不合格',
    'boundary': '边界待复核',
}


class ZeroNodeError(ValueError):
    """三点判定输入不合法。"""


def _as_array(values, name):
    array = np.asarray(values, dtype=float)
    if array.ndim != 1 or not np.isfinite(array).all():
        raise ZeroNodeError(f'{name} 必须是有限数值的一维数组')
    return array


def judge_three_nodes(outer_angles, outer_intervals, inner_angles, inner_intervals,
                      lower_deg=LOWER_BOUND_DEG):
    """按三点规则判定每个内道过零节点，返回逐点明细与整盘结论。

    Args:
        outer_angles: 外道实际过零起点角（[0°, 360°) 升序，机械度）
        outer_intervals: 外道同向实际间距 T外，与 ``outer_angles`` 逐项对应
        inner_angles: 内道实际过零起点角
        inner_intervals: 内道同向实际间距 T内
        lower_deg: 差值下限（默认 0.036°）

    Returns:
        dict：``outer_indices``(n,3)、``reference_angles_deg``、``reference_intervals_deg``、
        ``differences_deg``(n,3，列序为前/中/后)、``margins_deg``、``passed``/``failed``/
        ``boundary``、``failed_count``/``failed_percent``、``minimum_margin_deg``、
        ``worst_inner_index``/``worst_inner_angle_deg``、``judgement``（pass/fail/boundary）、
        ``judgement_text``。
    """
    outer_angles = _as_array(outer_angles, '外道过零角')
    outer_intervals = _as_array(outer_intervals, '外道同向间距')
    inner_angles = _as_array(inner_angles, '内道过零角')
    inner_intervals = _as_array(inner_intervals, '内道同向间距')

    if (outer_angles.size < 3 or inner_angles.size == 0
            or outer_angles.size != outer_intervals.size
            or inner_angles.size != inner_intervals.size):
        raise ZeroNodeError('实际节点角度与间距数量不符（外道至少 3 个节点且两两对应）')
    for angles, name in ((outer_angles, '外道'), (inner_angles, '内道')):
        if np.any(angles < 0) or np.any(angles >= 360) or np.any(np.diff(angles) <= 0):
            raise ZeroNodeError(f'{name}过零角需在 [0°, 360°) 内严格升序')
    if np.any(outer_intervals <= 0) or np.any(inner_intervals <= 0):
        raise ZeroNodeError('同向实际间距必须为正数')

    lower = float(lower_deg)
    distance = np.abs((outer_angles[None, :] - inner_angles[:, None] + 180.0) % 360.0
                      - 180.0)
    nearest = np.argmin(distance, axis=1)
    outer_indices = (nearest[:, None] + np.array(NODE_OFFSETS)) % outer_angles.size

    reference_angles = outer_angles[outer_indices]
    reference_intervals = outer_intervals[outer_indices]
    differences = inner_intervals[:, None] - reference_intervals
    margins = differences.min(axis=1) - lower

    failed = margins < 0
    boundary = margins == 0
    passed = margins > 0

    if np.any(failed):
        judgement = 'fail'
    elif np.any(boundary):
        judgement = 'boundary'
    else:
        judgement = 'pass'

    worst = int(np.argmin(margins))
    return {
        'lower_bound_deg': lower,
        'outer_indices': outer_indices,
        'nearest_outer_index': nearest,
        'reference_angles_deg': reference_angles,
        'reference_intervals_deg': reference_intervals,
        'differences_deg': differences,
        'margins_deg': margins,
        'passed': passed,
        'failed': failed,
        'boundary': boundary,
        'failed_count': int(failed.sum()),
        'failed_percent': float(failed.mean() * 100.0),
        'minimum_margin_deg': float(margins[worst]),
        'worst_inner_index': worst,
        'worst_inner_angle_deg': float(inner_angles[worst]),
        'judgement': judgement,
        'judgement_text': VERDICT_TEXT[judgement],
    }


__all__ = [
    'LOWER_BOUND_DEG',
    'NODE_OFFSETS',
    'VERDICT_TEXT',
    'ZeroNodeError',
    'judge_three_nodes',
]
