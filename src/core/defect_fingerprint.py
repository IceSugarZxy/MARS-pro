# -*- coding: utf-8 -*-
"""缺陷指纹比对算法（上位机与测试脚本共用，纯 numpy，无 Qt 依赖）。

对每轮测量按软件的同一套处理链（闭合点裁切 + 同轴度修正 + 波形分析）重算，然后
在 0.5° 网格（720 格）上给出四条**相对偏差（%）**曲线：

    shape   缺陷指纹    ：整圈波形按极对周期折叠取残差，按格平均后相对于 N/S 平均幅值
    cross   过零点差异  ：相邻过零间隔相对平均间隔的偏差
    amp     幅值差异    ：0.5° 幅值包络减极对周期平均包络后相对于平均包络
    period  周期差异    ：单极周期（相邻两段过零间隔之和）相对平均周期的偏差

四张曲线都用同一条相位：由「缺陷指纹」曲线做循环互相关求出每轮相对基准轮的样品转角，
其余曲线共用这个转角折算到基准轮坐标系。
"""

import numpy as np

from core.plot_data_reader import read_plot_csv_mag, time_label

BIN_DEG = 0.5                              # 网格角度分辨率
BINS = int(round(360.0 / BIN_DEG))         # 720 格
MAX_RUNS = 5                               # 勾选 / 预览 / 分析统一上限

PALETTE = ("#e74c3c", "#2980b9", "#27ae60", "#8e44ad", "#e67e22",
           "#16a085", "#c0392b", "#2c3e50", "#d35400", "#7f8c8d")

# (键, 显示名)
CURVES = (
    ("shape", "缺陷指纹"),
    ("cross", "过零点差异"),
    ("amp", "幅值差异"),
    ("period", "周期差异"),
)


def grid_angles() -> np.ndarray:
    """0.5° 网格的角度轴（0, 0.5, …, 359.5）。"""
    return np.arange(BINS) * BIN_DEG


def _sanitize(curve, scale) -> np.ndarray:
    """去直流 → 按参考量程折算成 %；NaN/Inf 归零。"""
    c = np.asarray(curve, dtype=float)
    c = np.nan_to_num(c, nan=0.0, posinf=0.0, neginf=0.0)
    if len(c) != BINS:
        c = np.zeros(BINS)
    c = c - float(c.mean())
    try:
        scale = abs(float(scale))
    except (TypeError, ValueError):
        scale = 0.0
    if not np.isfinite(scale) or scale <= 0:
        return c
    return c / scale * 100.0


def _zeros() -> np.ndarray:
    return np.zeros(BINS)


def shape_curve(mag, result) -> np.ndarray:
    """缺陷指纹：按极对周期折叠求平均后取残差（单位 %，相对 N/S 平均幅值）。"""
    y = np.asarray(mag, dtype=float)
    n = len(y)
    pole_pairs = int(result.get('pole_num') or 0)
    if pole_pairs < 1 or n < pole_pairs * 16:
        return _zeros()

    per = n // pole_pairs
    y = y[:per * pole_pairs]
    fold = y.reshape(pole_pairs, per).mean(axis=0)
    resid = (y.reshape(pole_pairs, per) - fold).ravel()

    idx = np.minimum((np.arange(len(resid)) * BINS) // len(resid), BINS - 1)
    counts = np.bincount(idx, minlength=BINS)
    sums = np.bincount(idx, weights=resid, minlength=BINS)
    img = sums / np.maximum(counts, 1)

    scale = abs(float(result.get('NS_2') or 0.0))
    if not np.isfinite(scale) or scale <= 0:
        scale = float(np.std(y)) or 1.0
    return _sanitize(img, scale)


def amp_curve(mag, result) -> np.ndarray:
    """幅值差异：0.5° 幅值包络减极对周期平均包络（单位 %）。"""
    y = np.asarray(mag, dtype=float)
    n = len(y)
    if n < BINS:
        return _zeros()

    idx = np.minimum((np.arange(n) * BINS) // n, BINS - 1)
    env = np.zeros(BINS)
    np.maximum.at(env, idx, np.abs(y))

    pole_pairs = int(result.get('pole_num') or 0)
    fold_len = BINS // pole_pairs if pole_pairs > 0 else 0
    if fold_len >= 4:
        fold = np.mean([env[(np.arange(BINS) + fold_len * k) % BINS]
                        for k in range(pole_pairs)], axis=0)
    else:
        fold = np.full(BINS, float(env.mean()))

    scale = float(fold.mean())
    return _sanitize(env - fold, scale)


def _sorted_details(result):
    """按修正后角度排序的 (cross, interval, pole)，数据不足时返回 None。"""
    details = result.get('zero_crossing_details') or []
    if len(details) < 3:
        return None
    try:
        cross = np.array([float(d['angle_corrected']) for d in details], dtype=float)
        interval = np.array([float(d['interval_to_next']) for d in details], dtype=float)
    except (KeyError, TypeError, ValueError):
        return None
    if not (np.all(np.isfinite(cross)) and np.all(np.isfinite(interval))):
        return None
    order = np.argsort(cross)
    cross = cross[order]
    interval = interval[order]
    pole = [str(details[i].get('pole', '')) for i in order]
    return cross, interval, pole


def cross_curve(result) -> np.ndarray:
    """过零点差异：相邻过零间隔相对平均间隔的偏差（单位 %）。"""
    parsed = _sorted_details(result)
    if parsed is None:
        return _zeros()
    cross, interval, _pole = parsed
    mean_interval = float(interval.mean())
    if not np.isfinite(mean_interval) or mean_interval <= 0:
        return _zeros()

    dev = (interval - mean_interval) / mean_interval * 100.0
    grid = grid_angles()
    img = np.interp(grid,
                    np.append(cross, cross[:1] + 360.0),
                    np.append(dev, dev[:1]),
                    period=360.0)
    return _sanitize(img, 1.0)


def period_curve(result) -> np.ndarray:
    """周期差异：单极周期（N 段 + 紧随的 S 段）相对平均周期的偏差（单位 %）。"""
    parsed = _sorted_details(result)
    if parsed is None:
        return _zeros()
    cross, interval, pole = parsed
    count = len(cross)
    if count < 4:
        return _zeros()

    positions = []
    periods = []
    for i in range(count):
        j = (i + 1) % count
        if pole[i] == 'N' and pole[j] == 'S':
            positions.append(cross[i])
            periods.append(interval[i] + interval[j])

    if len(periods) < 2:
        return _zeros()
    periods = np.asarray(periods, dtype=float)
    positions = np.asarray(positions, dtype=float)
    mean_period = float(periods.mean())
    if not np.isfinite(mean_period) or mean_period <= 0:
        return _zeros()

    dev = (periods - mean_period) / mean_period * 100.0
    grid = grid_angles()
    img = np.interp(grid,
                    np.append(positions, positions[:1] + 360.0),
                    np.append(dev, dev[:1]),
                    period=360.0)
    return _sanitize(img, 1.0)


def build_curves(mag, result) -> dict:
    """一次算出四条曲线。"""
    return {
        'shape': shape_curve(mag, result),
        'cross': cross_curve(result),
        'amp': amp_curve(mag, result),
        'period': period_curve(result),
    }


def analyze_run(path, proc, analyzer, label=None) -> dict:
    """分析单个数据文件；失败时返回带 'error' 的字典。"""
    result = {'path': path, 'label': label or time_label('', path)}
    try:
        mags, meta, save_stamp = read_plot_csv_mag(path)
    except Exception as exc:
        result['error'] = '读取失败: %s' % exc
        return result

    if len(mags) < 1000:
        result['error'] = '数据点不足（%d 点）' % len(mags)
        return result

    try:
        angle, processed = proc._process_measure_algorithm(list(mags))
    except Exception as exc:
        result['error'] = '数据处理失败: %s' % exc
        return result

    processed = np.asarray(processed, dtype=float)
    if len(processed) < 1000:
        result['error'] = '有效数据点不足（%d 点）' % len(processed)
        return result

    try:
        analysis = analyzer.analyze_waveform(angle, processed)
    except Exception as exc:
        result['error'] = '波形分析失败: %s' % exc
        return result
    if not analysis:
        result['error'] = '波形分析失败'
        return result

    pole_pairs = int(analysis.get('pole_num') or 0)
    if pole_pairs < 1:
        result['error'] = '未识别出极对数'
        return result
    if len(analysis.get('zero_crossing_details') or []) < 3:
        result['error'] = '过零点不足'
        return result

    result.update({
        'label': label or time_label(save_stamp, path),
        'sample': meta.get('样品名称', ''),
        'save_time': save_stamp,
        'pole_pairs': pole_pairs,
        'trimmed': len(mags) - len(processed),
        'mag': processed,
        'analysis': analysis,
        'n_mean': float(analysis.get('N_mean') or 0.0),
        'curves': build_curves(processed, analysis),
    })
    return result


def analyze_runs(paths, proc, analyzer, progress_cb=None, cancel_cb=None):
    """依次分析多个文件。

    Returns:
        (runs, failed, cancelled)
        runs: 分析成功、可直接用于比对的轮次（保持传入顺序）
        failed: [{'path','label','error'}, ...]
        cancelled: 是否被取消
    """
    runs = []
    failed = []
    total = len(paths)
    for index, path in enumerate(paths):
        if cancel_cb and cancel_cb():
            return runs, failed, True
        run = analyze_run(path, proc, analyzer)
        if run.get('error'):
            failed.append(run)
        else:
            runs.append(run)
        if progress_cb:
            progress_cb(index + 1, total, run.get('label') or '')
    return runs, failed, False


def best_shift(img_a, img_b):
    """循环互相关：返回 (bin 数, 相关系数)，满足 img_a[i] ≈ img_b[i - s]。"""
    a = np.asarray(img_a, dtype=float)
    b = np.asarray(img_b, dtype=float)
    a = a - a.mean()
    b = b - b.mean()
    denom = float(np.sqrt(float(np.dot(a, a)) * float(np.dot(b, b)))) or 1.0
    corr = np.array([float(np.dot(a, np.roll(b, s))) / denom for s in range(BINS)])
    shift = int(np.argmax(corr))
    return shift, float(corr[shift])


def signed_deg(bins) -> float:
    deg = (float(bins) * BIN_DEG) % 360.0
    return deg - 360.0 if deg > 180.0 else deg


def rotation_deg(img_a, img_b):
    """img_b 相对 img_a 的样品转角（°）与相关度。

    best_shift 给出"把 b 滚动 s 格后与 a 对齐"，即 b 的缺陷角 = a 的缺陷角 − s，
    所以样品从 a 转到 b 的转角是 −s。
    """
    shift, corr = best_shift(img_a, img_b)
    return -signed_deg(shift), corr


def _pearson(a, b) -> float:
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    a = a - a.mean()
    b = b - b.mean()
    denom = float(np.sqrt(float(np.dot(a, a)) * float(np.dot(b, b))))
    if denom <= 0:
        return 0.0
    return float(np.dot(a, b) / denom)


def compare_stats(runs) -> dict:
    """对齐 + 统计。以 runs[0] 为基准轮，四个 tab 共用缺陷指纹求出的转角。"""
    if not runs:
        return {}

    ref = runs[0]
    shape_shifts = [best_shift(ref['curves']['shape'], run['curves']['shape'])[0]
                    for run in runs]
    rotations = [-signed_deg(shift) for shift in shape_shifts]

    per_curve = {}
    for key, name in CURVES:
        raw = np.vstack([run['curves'][key] for run in runs])
        aligned = np.vstack([np.roll(run['curves'][key], shape_shifts[i])
                             for i, run in enumerate(runs)])

        spread_before = float(np.median(np.std(raw, axis=0)))
        spread_after = float(np.median(np.std(aligned, axis=0)))
        gain = (1.0 - spread_after / spread_before) * 100.0 if spread_before > 0 else 0.0

        per_curve[key] = {
            'name': name,
            'raw': raw,
            'aligned': aligned,
            'mean': aligned.mean(axis=0) if len(aligned) > 1 else aligned[0],
            'std': aligned.std(axis=0, ddof=0) if len(aligned) > 1 else np.zeros(BINS),
            'spread_before': spread_before,
            'spread_after': spread_after,
            'gain_pct': gain,
            'corr': [_pearson(ref['curves'][key], aligned[i]) for i in range(len(runs))],
        }

    # 场强与中位数相差 >25% 的轮次：只作提示，不阻止比对
    n_means = [float(run.get('n_mean') or 0.0) for run in runs]
    finite_means = [v for v in n_means if np.isfinite(v) and v > 0]
    field_outliers = []
    if len(finite_means) >= 2:
        median_mean = float(np.median(finite_means))
        if median_mean > 0:
            field_outliers = [runs[i]['label'] for i, v in enumerate(n_means)
                              if np.isfinite(v) and v > 0
                              and abs(v - median_mean) / median_mean > 0.25]

    cross_count = len((ref['analysis'].get('zero_crossing_details') or []))
    return {
        'ref_index': 0,
        'ref_label': ref['label'],
        'labels': [run['label'] for run in runs],
        'pole_pairs': ref['pole_pairs'],
        'pole_pitch_deg': 360.0 / ref['pole_pairs'] if ref['pole_pairs'] else 0.0,
        'half_pitch_deg': 360.0 / cross_count if cross_count else 0.0,
        'shifts': shape_shifts,
        'rotations': rotations,
        'align_corr': [best_shift(ref['curves']['shape'], run['curves']['shape'])[1]
                       for run in runs],
        'per_curve': per_curve,
        'n_mean': n_means,
        'field_outliers': field_outliers,
    }
