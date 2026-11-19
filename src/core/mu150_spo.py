"""MU150 32/31 双轨游标分析。纯函数仅使用 Python 标准库。"""

from ctypes import POINTER, c_bool, c_double, c_int8, c_int32, c_size_t
from ctypes import c_uint8, c_uint16, c_uint32, c_void_p
from dataclasses import dataclass
from math import isfinite
from operator import index
from pathlib import Path


PHASE_PERIOD = 16384
SPO_PERIOD = PHASE_PERIOD // 32
SPO_BIN_WIDTH = PHASE_PERIOD // 128
BOUNDARY = SPO_PERIOD // 2


@dataclass(frozen=True)
class Rating:
    """整圈残差评级，比例字段 1.0 对应 100%。"""

    minimum: int
    maximum: int
    peak: int
    occupancy: float
    margin_codes: int
    margin_ratio: float
    within_rating: bool
    within_decode_boundary: bool


@dataclass(frozen=True)
class SpoResult:
    """SPO 补偿、整圈归一和评级的结果。"""

    buckets: tuple[int, ...]
    compensation: tuple[int, ...]
    residual: tuple[int, ...]
    residual_branch: int
    rating: Rating


@dataclass(frozen=True)
class NativeResult:
    """原厂 DLL 逐点返回的数据及推荐、应用表。"""

    phase_error: tuple[int, ...]
    recommendation: tuple[int, ...]
    applied_table: tuple[int, ...]
    compensation_branch: int
    minimum_samples_per_master_period: float
    raw_data_gaps: int
    spo: SpoResult


def _trunc_div(value, divisor):
    """有符号整数除法向零截断。"""
    return abs(value) // divisor * (-1 if value < 0 else 1)


def _integers(values, name):
    try:
        return tuple(index(v) for v in values)
    except TypeError as exc:
        raise ValueError(f"{name}必须是整数序列") from exc


def _phase_pair(master, nonius):
    master = _integers(master, "主轨相位码")
    nonius = _integers(nonius, "游标轨相位码")
    if not master or len(master) != len(nonius):
        raise ValueError("两轨必须等长且至少有一个点")
    if not all(0 <= p < PHASE_PERIOD for p in master + nonius):
        raise ValueError("相位码必须在 0～16383")
    return master, nonius


def phase_to_code(electrical_degrees):
    """将一组电角度量化到 14 bit，半码平局采用 Python 的偶数舍入。"""
    angles = tuple(float(a) for a in electrical_degrees)
    if not all(isfinite(a) for a in angles):
        raise ValueError("电角度必须为有限值")
    return tuple(round((a % 360) * PHASE_PERIOD / 360) % PHASE_PERIOD for a in angles)


def phase_difference(master, nonius):
    """返回两轨的回绕相位差码，用于查档。"""
    master, nonius = _phase_pair(master, nonius)
    return tuple((m - n) % PHASE_PERIOD for m, n in zip(master, nonius))


def spo_buckets(master, nonius):
    """返回 SPO 档号 0～127。"""
    return tuple(d // SPO_BIN_WIDTH for d in phase_difference(master, nonius))


def _unwrap_phase(codes):
    previous = codes[0]
    continuous = previous
    yield continuous
    for value in codes[1:]:
        difference = (value - previous + PHASE_PERIOD // 2) % PHASE_PERIOD
        continuous += difference - PHASE_PERIOD // 2
        previous = value
        yield continuous


def estimate_phase_error(master, nonius):
    """估算游标轨尺度的误差，未选原厂 DLL 的参考周期分支。

    要求相邻采样点在各道的真实位移小于半个电周期。
    若需要核对原厂绝对峰值，应使用 analyze_with_dll 返回的 phase_error。
    """
    master, nonius = _phase_pair(master, nonius)
    return tuple(
        _trunc_div(31 * m - 32 * n, 32)
        for m, n in zip(_unwrap_phase(master), _unwrap_phase(nonius))
    )


def _spo_table(base, slopes):
    base = index(base)
    slopes = _integers(slopes, "SPO 斜率")
    if not -8 <= base <= 7 or len(slopes) not in (15, 16):
        raise ValueError("BASE 必须在 −8～+7，斜率必须提供 15 或 16 段")
    if not all(-8 <= d <= 7 for d in slopes[:15]):
        raise ValueError("前 15 段斜率必须在 −8～+7")
    last = -sum(slopes[:15])
    # B12 读回表中观察到自动末段为 −8 的情况。
    if not -8 <= last <= 7 or (len(slopes) == 16 and slopes[-1] != last):
        raise ValueError("最后一段必须闭合整圈，且在 −8～+7")
    return (base, *slopes[:15], last)


def spo_compensation(buckets, base, slopes, *, branch_offset=0):
    """根据实际应用的 SPO 码生成补偿曲线。

    branch_offset 是 DLL 补偿曲线的整圈分支修正，必须为 512 的整数倍。
    """
    buckets = _integers(buckets, "SPO 档号")
    base, *slopes = _spo_table(base, slopes)
    branch_offset = index(branch_offset)
    if branch_offset % SPO_PERIOD:
        raise ValueError("补偿分支偏移必须为 512 的整数倍")
    if not all(0 <= k < 128 for k in buckets):
        raise ValueError("SPO 档号必须在 0～127")
    starts = [base]
    for slope in slopes[:-1]:
        starts.append(starts[-1] + slope)
    table = [
        -4 * (8 * start + sub * slope) + branch_offset
        for start, slope in zip(starts, slopes)
        for sub in range(8)
    ]
    return tuple(table[k] for k in buckets)


def spo_residual(phase_error, compensation):
    """返回补偿后残差和整圈共用的归一偏移。"""
    error = _integers(phase_error, "双轨误差")
    compensation = _integers(compensation, "补偿量")
    if not error or len(error) != len(compensation):
        raise ValueError("误差和补偿必须等长且非空")
    raw = tuple(e - c for e, c in zip(error, compensation))
    mean = _trunc_div(sum(raw), len(raw))
    branch = SPO_PERIOD * _trunc_div(mean + BOUNDARY, SPO_PERIOD)
    return tuple(value - branch for value in raw), branch


def rate_residual(residual, *, rating_limit=0.90):
    """按 256 码边界统计最差占用率和最小裕量。"""
    residual = _integers(residual, "残差")
    if not residual or not 0 < rating_limit <= 1:
        raise ValueError("残差必须非空，评级比例必须在 (0, 1]")
    minimum, maximum = min(residual), max(residual)
    peak = max(abs(minimum), abs(maximum))
    occupancy = peak / BOUNDARY
    margin = BOUNDARY - peak
    return Rating(
        minimum, maximum, peak, occupancy, margin, margin / BOUNDARY,
        occupancy <= rating_limit, peak <= BOUNDARY,
    )


def evaluate_spo(
    master, nonius, phase_error, base, slopes, *, branch_offset=0, rating_limit=0.90
):
    """纯函数入口。输入已知误差与 SPO 表，返回档号、补偿、残差和评级。"""
    buckets = spo_buckets(master, nonius)
    compensation = spo_compensation(buckets, base, slopes, branch_offset=branch_offset)
    residual, branch = spo_residual(phase_error, compensation)
    return SpoResult(
        buckets, compensation, residual, branch,
        rate_residual(residual, rating_limit=rating_limit),
    )


def analyze_with_dll(dll_path, master, nonius, *, applied_table=None, rating_limit=0.90):
    """通过原厂 B12 DLL 求表、应用和重放。适用于 Windows 64 位。

    applied_table 可传入 BASE 加 15 或 16 段。省略时用原厂推荐表。
    每次新建离线句柄，完成后释放，应用表只写入该句柄。
    """
    import ctypes

    master, nonius = _phase_pair(master, nonius)
    if len(master) < 2:
        raise ValueError("原厂分析至少需要两个配对采样点")
    table = None if applied_table is None else _integers(applied_table, "SPO 表")
    if table is not None:
        if not table:
            raise ValueError("SPO 表不能为空")
        table = _spo_table(table[0], table[1:])

    dll = ctypes.WinDLL(str(Path(dll_path).resolve(strict=True)))
    handle_type = c_void_p

    def bind(name, args, result):
        function = getattr(dll, name)
        function.argtypes = args
        function.restype = result
        return function

    create = bind("MU_createCalibration", [c_uint8], handle_type)
    close = bind("MU_Calibration_delete", [handle_type], None)
    configure = bind(
        "MU_Calibration_preconfigureNumberOfMasterPeriods", [handle_type, c_uint32], c_bool
    )
    analyze = bind(
        "MU_Calibration_analyzeRawData",
        [handle_type, POINTER(c_uint16), POINTER(c_uint16), c_size_t], handle_type,
    )
    free = bind("MU_CalibrationAnalyzeResult_delete", [handle_type], None)
    get_recommendation = bind(
        "MU_Calibration_getOptimizedNoniusTrackOffsetTable",
        [handle_type, POINTER(c_int8)], None,
    )
    set_table = bind(
        "MU_Calibration_setCurrentNoniusTrackOffsetTable",
        [handle_type, POINTER(c_int8)], c_bool,
    )
    read_table = bind(
        "MU_Calibration_getNoniusTrackOffsetTable",
        [handle_type, POINTER(c_int8)], None,
    )
    getter = {
        name: bind("MU_Calibration_" + name, [handle_type], result)
        for name, result in (
            ("numberOfNoniusCurveSamples", c_size_t),
            ("noniusPhaseRangeLimit", c_int32),
            ("noniusPhaseError", POINTER(c_int32)),
            ("noniusTrackOffsetCurve", POINTER(c_int32)),
            ("noniusPhaseMargin", POINTER(c_int32)),
            ("noniusPhaseMarginMin", c_int32),
            ("noniusPhaseMarginMax", c_int32),
            ("minimalNumberOfSamplesPerMasterPeriod", c_double),
            ("numberOfRawDataGaps", c_size_t),
        )
    }
    n = len(master)
    m_buffer = (c_uint16 * n)(*master)
    n_buffer = (c_uint16 * n)(*nonius)
    handle = create(0x13)
    if not handle:
        raise RuntimeError("DLL 无法建立 MU150 离线句柄")

    def call_analysis():
        result = analyze(handle, m_buffer, n_buffer, n)
        if not result:
            raise RuntimeError("DLL 无法分析这组相位数据")
        if (
            getter["numberOfNoniusCurveSamples"](result) != n
            or getter["noniusPhaseRangeLimit"](result) != BOUNDARY
        ):
            free(result)
            raise RuntimeError("DLL 未生成完整的 32/31 游标曲线，请检查点数和旋转覆盖")
        return result

    try:
        if not configure(handle, 32):
            raise RuntimeError("DLL 无法设定主轨 32 极对")
        result = call_analysis()
        recommendation = (c_int8 * 17)()
        try:
            get_recommendation(result, recommendation)
        finally:
            free(result)
        if not set_table(handle, recommendation if table is None else (c_int8 * 17)(*table)):
            raise RuntimeError("DLL 无法应用 SPO 表")
        actual = (c_int8 * 17)()
        read_table(handle, actual)
        result = call_analysis()
        try:
            curves = []
            for name in ("noniusPhaseError", "noniusTrackOffsetCurve", "noniusPhaseMargin"):
                values = getter[name](result)
                if not values:
                    raise RuntimeError(f"DLL 未返回 {name} 曲线")
                curves.append(tuple(values[:n]))
            error, native_correction, native_residual = curves
            minimum = getter["noniusPhaseMarginMin"](result)
            maximum = getter["noniusPhaseMarginMax"](result)
            samples = getter["minimalNumberOfSamplesPerMasterPeriod"](result)
            gaps = getter["numberOfRawDataGaps"](result)
        finally:
            free(result)
    finally:
        close(handle)

    # DLL 的补偿曲线还可统一加减一个周期分支，按读回表反求并逐点核对。
    buckets = spo_buckets(master, nonius)
    register_correction = spo_compensation(buckets, actual[0], actual[1:])
    offset = native_correction[0] - register_correction[0]
    output = evaluate_spo(
        master, nonius, error, actual[0], actual[1:],
        branch_offset=offset, rating_limit=rating_limit,
    )
    if (
        output.compensation != native_correction
        or output.residual != native_residual
        or (output.rating.minimum, output.rating.maximum) != (minimum, maximum)
    ):
        raise RuntimeError("通用公式与 DLL 返回结果不同，请保留相位和读回表复查")
    return NativeResult(
        error, tuple(recommendation), tuple(actual), offset, samples, gaps, output
    )

