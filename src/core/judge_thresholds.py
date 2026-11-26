# -*- coding: utf-8 -*-
"""合格判定：分析结果的阈值项定义、配置读写与判定计算。

分析结果各值在配置面板「合格判定」区块中配置阈值：
幅值/角度类填上下限（留空表示该侧不限），误差类只填上限。
"""

import json
import math
from typing import Dict, Iterable, List, Optional, Tuple

JUDGE_ENABLED_KEY = "judge_enabled"
JUDGE_THRESHOLDS_KEY = "judge_thresholds"

KIND_RANGE = "range"  # 上下限
KIND_UPPER = "upper"  # 仅上限（误差类）

# (分析结果键, 显示名, 单位, 判定方式)
JUDGE_ITEMS: Tuple[Tuple[str, str, str, str], ...] = (
    ("N_max", "N极最大值", "mT", KIND_RANGE),
    ("N_min", "N极最小值", "mT", KIND_RANGE),
    ("N_mean", "N极均值", "mT", KIND_RANGE),
    ("S_max", "S极最大值", "mT", KIND_RANGE),
    ("S_min", "S极最小值", "mT", KIND_RANGE),
    ("S_mean", "S极均值", "mT", KIND_RANGE),
    ("NS_2", "NS/2", "mT", KIND_RANGE),
    ("N_se", "N极误差", "%", KIND_UPPER),
    ("S_se", "S极误差", "%", KIND_UPPER),
    ("N_interval_max", "N间隔最大值", "°", KIND_RANGE),
    ("N_interval_min", "N间隔最小值", "°", KIND_RANGE),
    ("N_interval_mean", "N间隔均值", "°", KIND_RANGE),
    ("S_interval_max", "S间隔最大值", "°", KIND_RANGE),
    ("S_interval_min", "S间隔最小值", "°", KIND_RANGE),
    ("S_interval_mean", "S间隔均值", "°", KIND_RANGE),
    ("N_interval_std", "N间隔误差", "%", KIND_UPPER),
    ("S_interval_std", "S间隔误差", "%", KIND_UPPER),
    ("N_area", "N极面积", "mT·°", KIND_RANGE),
    ("S_area", "S极面积", "mT·°", KIND_RANGE),
    ("NS_area", "NS总面积", "mT·°", KIND_RANGE),
    ("SinglePolarMean", "单极均值", "°", KIND_RANGE),
    ("SinglePolarError", "单极误差", "%", KIND_UPPER),
    ("PolarErrorSum", "累计误差范围", "%", KIND_UPPER),
    ("THD_error", "THD失真率", "%", KIND_UPPER),
)

VERDICT_PASS = "pass"
VERDICT_FAIL = "fail"
VERDICT_SKIP = "skip"

# 判定项在配置界面的排布：(左列, 右列)，与测量界面「数据分析结果」的两列布局一一对应
JUDGE_LAYOUT_ROWS: Tuple[Tuple[str, str], ...] = (
    ("N_max", "N_interval_max"),
    ("N_min", "N_interval_min"),
    ("N_mean", "N_interval_mean"),
    ("N_se", "N_interval_std"),
    ("S_max", "S_interval_max"),
    ("S_min", "S_interval_min"),
    ("S_mean", "S_interval_mean"),
    ("S_se", "S_interval_std"),
    ("SinglePolarMean", "N_area"),
    ("SinglePolarError", "S_area"),
    ("PolarErrorSum", "NS_area"),
    ("THD_error", "NS_2"),
)


def item_label(name: str, unit: str) -> str:
    """表格中显示的“名称（单位）”。"""
    return f"{name}（{unit}）" if unit else name


def item_info(key: str) -> Tuple[str, str, str]:
    """返回 (显示名, 单位, 判定方式)。"""
    for item_key, name, unit, kind in JUDGE_ITEMS:
        if item_key == key:
            return name, unit, kind
    return key, "", KIND_RANGE


def item_kind(key: str) -> str:
    return item_info(key)[2]


def default_item_settings() -> Dict[str, Dict[str, object]]:
    return {key: {"on": False, "lo": None, "hi": None} for key, _n, _u, _k in JUDGE_ITEMS}


def default_settings() -> Dict[str, object]:
    return {"enabled": False, "items": default_item_settings()}


def _to_limit(value) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def load_settings(config) -> Dict[str, object]:
    """从配置管理器读取合格判定设置，缺失或损坏的项按“未启用”处理。"""
    settings = default_settings()
    try:
        settings["enabled"] = bool(config.get_int(JUDGE_ENABLED_KEY, 0))
    except Exception:
        settings["enabled"] = False

    raw = config.get(JUDGE_THRESHOLDS_KEY, "") or ""
    if not raw:
        return settings
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return settings
    if not isinstance(data, dict):
        return settings

    for key, entry in data.items():
        if key not in settings["items"] or not isinstance(entry, dict):
            continue
        settings["items"][key] = {
            "on": bool(entry.get("on", False)),
            "lo": _to_limit(entry.get("lo")),
            "hi": _to_limit(entry.get("hi")),
        }
    return settings


def settings_to_dict(settings: Dict[str, object]) -> Dict[str, Dict[str, object]]:
    """序列化为配置文件中保存的 JSON 结构（未填写的限值写成 null）。"""
    items = {}
    for key, _name, _unit, _kind in JUDGE_ITEMS:
        entry = (settings.get("items") or {}).get(key) or {}
        items[key] = {
            "on": bool(entry.get("on")),
            "lo": _to_limit(entry.get("lo")),
            "hi": _to_limit(entry.get("hi")),
        }
    return items


def save_settings(config, settings: Dict[str, object]) -> bool:
    ok = config.set(JUDGE_ENABLED_KEY, 1 if settings.get("enabled") else 0)
    payload = json.dumps(settings_to_dict(settings), ensure_ascii=False)
    ok = config.set(JUDGE_THRESHOLDS_KEY, payload) and ok
    return ok


def effective_limits(key: str, entry: Dict[str, object]) -> Tuple[Optional[float], Optional[float]]:
    """返回实际参与比较的 (下限, 上限)；误差类忽略下限。"""
    lo = _to_limit((entry or {}).get("lo"))
    hi = _to_limit((entry or {}).get("hi"))
    if item_kind(key) == KIND_UPPER:
        lo = None
    return lo, hi


def is_item_active(key: str, entry: Dict[str, object]) -> bool:
    if not (entry or {}).get("on"):
        return False
    lo, hi = effective_limits(key, entry)
    return lo is not None or hi is not None


def active_items(settings: Dict[str, object]) -> List[str]:
    items = settings.get("items") or {}
    return [key for key, _n, _u, _k in JUDGE_ITEMS if is_item_active(key, items.get(key) or {})]


def judge_value(key: str, value, entry: Dict[str, object]) -> str:
    """单项判定：pass / fail；无法判定（无限制或数值无效）返回 skip。"""
    lo, hi = effective_limits(key, entry)
    if lo is None and hi is None:
        return VERDICT_SKIP
    try:
        number = float(value)
    except (TypeError, ValueError):
        return VERDICT_SKIP
    if not math.isfinite(number):
        return VERDICT_SKIP
    if lo is not None and number < lo:
        return VERDICT_FAIL
    if hi is not None and number > hi:
        return VERDICT_FAIL
    return VERDICT_PASS


def evaluate(results: Optional[Dict[str, object]], settings: Dict[str, object]) -> Dict[str, object]:
    """判定一次分析结果。

    返回 dict：
      active   —— 判定是否生效（总开关打开且至少一项配了限值）
      verdicts —— {结果键: pass/fail/skip}
      failed   —— 不合格的结果键列表（按 JUDGE_ITEMS 顺序）
      overall  —— pass / fail / None（未生效或全部无法判定时为 None）
    """
    report = {"active": False, "verdicts": {}, "failed": [], "overall": None}
    keys: Iterable[str] = active_items(settings) if settings.get("enabled") else []
    keys = list(keys)
    if not keys or not isinstance(results, dict):
        return report

    report["active"] = True
    items = settings.get("items") or {}
    judged = False
    for key in keys:
        entry = items.get(key) or {}
        verdict = judge_value(key, results.get(key), entry)
        report["verdicts"][key] = verdict
        if verdict == VERDICT_SKIP:
            continue
        judged = True
        if verdict == VERDICT_FAIL:
            report["failed"].append(key)

    if judged:
        report["overall"] = VERDICT_FAIL if report["failed"] else VERDICT_PASS
    return report
