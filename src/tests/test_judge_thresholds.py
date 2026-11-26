# -*- coding: utf-8 -*-
"""合格判定阈值与判定计算的单元测试。"""

import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from core import judge_thresholds as jt


class _FakeConfig:
    """只实现 config_manager 里判定设置用到的接口。"""

    def __init__(self, values=None):
        self.values = dict(values or {})
        self.saved = 0

    def get(self, key, default=None):
        return self.values.get(key, default)

    def get_int(self, key, default=0):
        try:
            return int(self.values.get(key, default))
        except (TypeError, ValueError):
            return default

    def set(self, key, value):
        self.values[key] = str(value)
        self.saved += 1
        return True


def _settings(**items):
    """构造启用的设置：items 为 key=(lo, hi)。"""
    settings = jt.default_settings()
    settings["enabled"] = True
    for key, limits in items.items():
        lo, hi = limits
        settings["items"][key] = {"on": True, "lo": lo, "hi": hi}
    return settings


class LoadSaveTests(unittest.TestCase):
    def test_missing_config_gives_disabled_defaults(self):
        settings = jt.load_settings(_FakeConfig())
        self.assertFalse(settings["enabled"])
        self.assertFalse(any(entry["on"] for entry in settings["items"].values()))
        self.assertEqual(len(settings["items"]), len(jt.JUDGE_ITEMS))

    def test_roundtrip_keeps_limits(self):
        config = _FakeConfig()
        settings = _settings(N_max=(300, 420), N_se=(None, 5))
        self.assertTrue(jt.save_settings(config, settings))

        loaded = jt.load_settings(config)
        self.assertTrue(loaded["enabled"])
        self.assertEqual(loaded["items"]["N_max"], {"on": True, "lo": 300.0, "hi": 420.0})
        self.assertEqual(loaded["items"]["N_se"], {"on": True, "lo": None, "hi": 5.0})

    def test_corrupt_json_is_ignored(self):
        config = _FakeConfig({jt.JUDGE_THRESHOLDS_KEY: "{not json", jt.JUDGE_ENABLED_KEY: "1"})
        settings = jt.load_settings(config)
        self.assertTrue(settings["enabled"])
        self.assertFalse(any(entry["on"] for entry in settings["items"].values()))

    def test_unknown_keys_are_dropped(self):
        config = _FakeConfig({jt.JUDGE_THRESHOLDS_KEY: '{"Nope": {"on": true, "hi": 1}}'})
        settings = jt.load_settings(config)
        self.assertNotIn("Nope", settings["items"])


class ActiveItemTests(unittest.TestCase):
    def test_item_needs_checkbox_and_a_limit(self):
        self.assertFalse(jt.is_item_active("N_max", {"on": False, "lo": 1, "hi": 2}))
        self.assertFalse(jt.is_item_active("N_max", {"on": True, "lo": None, "hi": None}))
        self.assertTrue(jt.is_item_active("N_max", {"on": True, "lo": None, "hi": 2}))

    def test_error_item_ignores_lower_limit(self):
        self.assertEqual(jt.effective_limits("N_se", {"lo": 1, "hi": 5}), (None, 5.0))
        self.assertEqual(jt.effective_limits("N_max", {"lo": 1, "hi": 5}), (1.0, 5.0))

    def test_error_item_with_only_lower_limit_is_inactive(self):
        self.assertFalse(jt.is_item_active("THD_error", {"on": True, "lo": 1, "hi": None}))


class EvaluateTests(unittest.TestCase):
    def test_inactive_when_master_switch_off(self):
        settings = _settings(N_max=(300, 420))
        settings["enabled"] = False
        report = jt.evaluate({"N_max": 350}, settings)
        self.assertFalse(report["active"])
        self.assertIsNone(report["overall"])
        self.assertEqual(report["verdicts"], {})

    def test_inactive_when_no_item_configured(self):
        report = jt.evaluate({"N_max": 350}, jt.default_settings())
        self.assertFalse(report["active"])
        self.assertIsNone(report["overall"])

    def test_all_items_pass(self):
        settings = _settings(N_max=(300, 420), N_se=(None, 5))
        report = jt.evaluate({"N_max": 350, "N_se": 3.2}, settings)
        self.assertTrue(report["active"])
        self.assertEqual(report["overall"], jt.VERDICT_PASS)
        self.assertEqual(report["failed"], [])

    def test_out_of_range_fails(self):
        settings = _settings(N_max=(300, 420), N_se=(None, 5))
        report = jt.evaluate({"N_max": 430, "N_se": 6.0}, settings)
        self.assertEqual(report["overall"], jt.VERDICT_FAIL)
        self.assertEqual(report["failed"], ["N_max", "N_se"])
        self.assertEqual(report["verdicts"]["N_max"], jt.VERDICT_FAIL)

    def test_boundary_values_pass(self):
        settings = _settings(N_max=(300, 420))
        self.assertEqual(jt.evaluate({"N_max": 300}, settings)["overall"], jt.VERDICT_PASS)
        self.assertEqual(jt.evaluate({"N_max": 420}, settings)["overall"], jt.VERDICT_PASS)

    def test_nan_and_missing_values_are_skipped(self):
        settings = _settings(N_max=(300, 420), THD_error=(None, 5))
        report = jt.evaluate({"N_max": 350, "THD_error": float("nan"), "S_max": None}, settings)
        self.assertEqual(report["verdicts"]["THD_error"], jt.VERDICT_SKIP)
        self.assertEqual(report["verdicts"]["N_max"], jt.VERDICT_PASS)
        self.assertNotIn("S_max", report["verdicts"])
        self.assertEqual(report["overall"], jt.VERDICT_PASS)

    def test_all_skipped_has_no_overall(self):
        settings = _settings(THD_error=(None, 5))
        report = jt.evaluate({"THD_error": "n/a"}, settings)
        self.assertTrue(report["active"])
        self.assertIsNone(report["overall"])

    def test_string_values_are_judged(self):
        settings = _settings(N_max=(300, 420))
        self.assertEqual(jt.evaluate({"N_max": "305.25"}, settings)["overall"], jt.VERDICT_PASS)
        self.assertEqual(jt.evaluate({"N_max": "299.99"}, settings)["overall"], jt.VERDICT_FAIL)


if __name__ == '__main__':
    unittest.main()
