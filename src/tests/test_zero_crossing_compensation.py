# -*- coding: utf-8 -*-
"""过零点偏差补偿（core.zero_crossing_compensation + 波形分析链路）的回归测试。"""

import json
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core.zero_crossing import (same_direction_intervals,          # noqa: E402
                                zero_position_deviation)
from core.zero_crossing_compensation import (apply, dump_table,    # noqa: E402
                                             GLOBAL_KEY, lookup,
                                             parse_table, polar_key,
                                             sample_curve)
from core.plot_data_reader import apply_sample_info_row            # noqa: E402
from windows.wave_analysis import WaveAnalysis                     # noqa: E402

POINTS = 16384
POLE_PAIRS = 32


def _grid():
    return np.arange(POINTS) * 360.0 / POINTS


def _device_curve(step_deg=0.5, amplitude=1.2, phase_deg=20.0):
    """构造一条一圈一次的“设备曲线”（机械度）。"""
    count = int(round(360 / step_deg))
    theta = np.deg2rad(np.arange(count) * step_deg)
    return theta, amplitude * np.sin(theta + np.deg2rad(phase_deg))


def _waveform(angle, deviation_fn=None, pole_pairs=POLE_PAIRS):
    """理想正弦；给定 deviation_fn 时让实测位置偏差恰好等于 e(θ)。

    实测偏差 e = 网格角 − 真角，因此真角 = 网格角 − e(网格角)。
    """
    theta = np.deg2rad(angle)
    if deviation_fn is None:
        return np.cos(pole_pairs * theta) * 100.0
    measured = angle - deviation_fn(angle)
    base = np.cos(np.deg2rad(pole_pairs * (np.mod(measured, 360.0))))
    return base * 100.0


def _deviation_peak(field, pole_pairs=POLE_PAIRS):
    intervals = same_direction_intervals(_grid(), field, pole_pairs)
    return zero_position_deviation(intervals.cross_deg, pole_pairs).stats()


class ZeroCrossingTableTest(unittest.TestCase):

    def test_parse_and_dump_round_trip(self):
        theta, values = _device_curve()
        raw = dump_table({'32': (0.5, values)})
        table = parse_table(raw)
        self.assertIn('32', table)
        step, parsed = table['32']
        self.assertAlmostEqual(step, 0.5)
        np.testing.assert_allclose(parsed, values, atol=1e-6)
        np.testing.assert_allclose(parse_table(dump_table(table))['32'][1], parsed, atol=1e-6)

    def test_disabled_entry_is_skipped(self):
        payload = json.dumps({'32': {'step_deg': 0.5, 'values': [0.1, 0.2],
                                     'enabled': False}})
        self.assertEqual(parse_table(payload), {})

    def test_broken_json_is_ignored(self):
        self.assertEqual(parse_table('not json'), {})
        self.assertEqual(parse_table(''), {})
        self.assertEqual(parse_table('[1,2,3]'), {})

    def test_lookup_falls_back_to_global_key(self):
        theta, values = _device_curve()
        table = {'*': (0.5, values)}
        key, step, got = lookup(table, 32)
        self.assertEqual(key, '*')
        self.assertAlmostEqual(step, 0.5)
        np.testing.assert_allclose(got, values, atol=1e-9)

    def test_polar_key(self):
        self.assertEqual(polar_key(32), '32')
        self.assertEqual(polar_key('31'), '31')
        self.assertEqual(polar_key(None), '')


class ZeroCrossingApplyTest(unittest.TestCase):

    def setUp(self):
        self.theta, self.values = _device_curve()
        self.table = {'32': (0.5, self.values)}
        self.angle = _grid()
        self.deviation = lambda a: sample_curve(self.values, 0.5, a)

    def test_compensation_reduces_position_deviation(self):
        distorted = _waveform(self.angle, self.deviation)
        before = _deviation_peak(distorted)['peak_to_peak_deg']
        corrected, info = apply(self.angle, distorted, self.table, POLE_PAIRS)
        self.assertTrue(info['applied'])
        self.assertEqual(info['key'], '32')
        after = _deviation_peak(corrected)['peak_to_peak_deg']
        self.assertGreater(before, 1.0)
        self.assertLess(after, before * 0.1)

    def test_compensation_restores_true_waveform(self):
        distorted = _waveform(self.angle, self.deviation)
        ideal = _waveform(self.angle)
        corrected, _info = apply(self.angle, distorted, self.table, POLE_PAIRS)
        self.assertEqual(corrected.shape, distorted.shape)
        self.assertTrue(np.isfinite(corrected).all())
        # 补偿后应当接近“没有设备偏差时”的理想波形
        self.assertLess(float(np.max(np.abs(corrected - ideal))),
                        0.03 * float(np.max(np.abs(ideal))))
        self.assertLess(abs(np.max(np.abs(corrected)) - np.max(np.abs(distorted))), 5.0)

    def test_missing_curve_returns_none(self):
        distorted = _waveform(self.angle, self.deviation)
        corrected, info = apply(self.angle, distorted, {'31': (0.5, self.values)}, 32)
        self.assertIsNone(corrected)
        self.assertFalse(info['applied'])
        self.assertIn('极对数', info['reason'])

    def test_invalid_inputs_are_rejected(self):
        distorted = _waveform(self.angle, self.deviation)
        bad_angle = self.angle.copy()
        bad_angle[10] = bad_angle[11]
        cases = [
            (bad_angle, distorted),
            (self.angle[:-1], distorted),
            (self.angle, distorted[:-1]),
        ]
        for angle, field in cases:
            corrected, info = apply(angle, field, self.table, POLE_PAIRS)
            self.assertIsNone(corrected)
            self.assertFalse(info['applied'])


class WaveAnalysisIntegrationTest(unittest.TestCase):

    def setUp(self):
        self.angle = _grid()
        theta, values = _device_curve()
        self.deviation = lambda a: sample_curve(values, 0.5, a)
        self.distorted = _waveform(self.angle, self.deviation)
        self.table = {'32': (0.5, values)}

    def test_analyzer_applies_compensation(self):
        analyzer = WaveAnalysis(zero_crossing_table=self.table)
        analysis, processed = analyzer.analyze_waveform_with_correction(
            self.angle, self.distorted)
        info = analysis['concentricity']
        self.assertTrue(info['zero_crossing_applied'])
        self.assertEqual(info['zero_crossing_key'], '32')
        after = _deviation_peak(np.asarray(processed))['peak_to_peak_deg']
        self.assertLess(after, 0.3)

    def test_analyzer_can_skip_compensation(self):
        analyzer = WaveAnalysis(zero_crossing_table=self.table)
        analysis, processed = analyzer.analyze_waveform_with_correction(
            self.angle, self.distorted, apply_amplitude_correction=False,
            apply_zero_crossing_correction=False)
        info = analysis['concentricity']
        self.assertFalse(info['zero_crossing_applied'])
        np.testing.assert_allclose(np.asarray(processed), self.distorted, atol=1e-9)

    def test_empty_table_is_noop(self):
        analyzer = WaveAnalysis(zero_crossing_table={})
        analysis, processed = analyzer.analyze_waveform_with_correction(
            self.angle, self.distorted, apply_amplitude_correction=False)
        info = analysis['concentricity']
        self.assertFalse(info['zero_crossing_applied'])
        np.testing.assert_allclose(np.asarray(processed), self.distorted, atol=1e-9)

    def test_csv_marker_is_parsed(self):
        info = {}
        apply_sample_info_row(info, ['过零点偏差补偿', '已应用'])
        self.assertEqual(info['zero_crossing_compensation'], '已应用')


class GlobalCurveTest(unittest.TestCase):
    """设备曲线与极对数无关：配置里只有通配键 ``*`` 时，任何极对数都要生效。"""

    def setUp(self):
        self.angle = _grid()
        theta, values = _device_curve()
        self.table = {GLOBAL_KEY: (0.5, values)}
        self.deviation = lambda a: sample_curve(values, 0.5, a)

    def test_global_curve_applies_to_any_pole_pairs(self):
        true_wave = _waveform(self.angle)
        for pole_pairs in (4, 5, 8, 31, 32):
            with self.subTest(pole_pairs=pole_pairs):
                distorted = _waveform(self.angle, self.deviation,
                                      pole_pairs=pole_pairs)
                analyzer = WaveAnalysis(zero_crossing_table=self.table)
                analysis, processed = analyzer.analyze_waveform_with_correction(
                    self.angle, distorted)
                info = analysis['concentricity']
                self.assertTrue(info['zero_crossing_applied'])
                self.assertEqual(info['zero_crossing_key'], GLOBAL_KEY)
                processed = np.asarray(processed)
                reference = _waveform(self.angle, pole_pairs=pole_pairs)
                before = float(np.sqrt(np.mean((distorted - reference) ** 2)))
                after = float(np.sqrt(np.mean((processed - reference) ** 2)))
                self.assertLess(after, before / 3.0)

    def test_shipped_configuration_has_single_global_curve(self):
        """随包配置只有一条通用曲线（*），不按极对数分键。"""
        from core.config_manager import ConfigManager

        config = ConfigManager(os.path.join(os.path.dirname(__file__), '..',
                                            'configuration.txt'))
        table = config.zero_crossing_compensation_table
        self.assertIn(GLOBAL_KEY, table)
        self.assertEqual(sorted(table), [GLOBAL_KEY])
        step, values = table[GLOBAL_KEY]
        self.assertAlmostEqual(float(step), 0.5)
        self.assertGreater(len(values), 360)
        self.assertGreater(float(np.ptp(values)), 2.0)


if __name__ == '__main__':
    unittest.main()
