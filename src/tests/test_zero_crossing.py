# -*- coding: utf-8 -*-
"""同向过零实际间距（core.zero_crossing）的回归测试。"""

import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core.zero_crossing import (  # noqa: E402
    TrackIntervals,
    ZeroCrossingError,
    ZeroPosition,
    dual_track_difference,
    same_direction_intervals,
    zero_position_deviation,
)

POINTS = 32768


def _grid():
    return np.arange(POINTS) * 360.0 / POINTS


def _sine(pole_pairs, phase_deg=0.0, amplitude=100.0):
    angle = _grid()
    return np.deg2rad(pole_pairs * angle + phase_deg)


class SameDirectionIntervalTest(unittest.TestCase):

    def test_ideal_sine_master_track(self):
        angle = _grid()
        result = same_direction_intervals(angle, 100.0 * np.sin(_sine(32, 0.7)), 32)
        self.assertIsInstance(result, TrackIntervals)
        self.assertEqual(result.cross_deg.size, 64)
        self.assertEqual(int(result.rising.sum()), 32)
        self.assertAlmostEqual(result.nominal_deg, 11.25)
        self.assertAlmostEqual(float(result.same_deg.mean()), 11.25, places=10)
        self.assertLess(float(np.ptp(result.same_deg)), 1e-9)
        self.assertAlmostEqual(float(result.adjacent_deg.sum()), 360.0, places=9)
        self.assertAlmostEqual(float(result.same_deg.sum()), 720.0, places=9)

    def test_ideal_sine_nonius_track(self):
        angle = _grid()
        result = same_direction_intervals(angle, 50.0 * np.sin(_sine(31, 0.7)), 31)
        self.assertEqual(result.cross_deg.size, 62)
        self.assertEqual(int(result.rising.sum()), 31)
        self.assertAlmostEqual(float(result.same_deg.mean()), 360.0 / 31, places=10)

    def test_rotated_sine_keeps_spacing(self):
        angle = _grid()
        for phase in (0.3, 13.9, 45.0, 111.7):
            result = same_direction_intervals(angle, np.sin(_sine(32, phase)), 32)
            self.assertEqual(result.cross_deg.size, 64)
            self.assertLess(float(np.ptp(result.same_deg)), 1e-9)
            self.assertTrue(np.all(np.diff(result.cross_deg) > 0))

    def test_waveform_with_modulated_period(self):
        angle = _grid()
        theta = np.deg2rad(angle)
        # 周期做 ±0.2° 的一圈一次调制：过零数不变，同向间距应跟着变
        field = np.sin(32 * (theta + np.deg2rad(0.2) * np.sin(theta)))
        result = same_direction_intervals(angle, field, 32)
        self.assertEqual(result.cross_deg.size, 64)
        self.assertGreater(float(np.ptp(result.same_deg)), 0.05)
        self.assertAlmostEqual(float(result.same_deg.mean()), 11.25, places=6)

    def test_dc_offset_is_removed(self):
        angle = _grid()
        result = same_direction_intervals(angle, 100.0 + np.sin(_sine(32, 0.7)), 32)
        self.assertEqual(result.cross_deg.size, 64)
        self.assertLess(float(np.ptp(result.same_deg)), 1e-9)

    def test_rejects_unsupported_pole_pairs(self):
        angle = _grid()
        with self.assertRaises(ZeroCrossingError):
            same_direction_intervals(angle, np.sin(_sine(30, 0.7)), 30)

    def test_rejects_non_uniform_grid(self):
        angle = _grid().copy()
        angle[100] += 0.5
        with self.assertRaises(ZeroCrossingError):
            same_direction_intervals(angle, np.sin(_sine(32, 0.7)), 32)

    def test_rejects_flat_waveform(self):
        angle = _grid()
        with self.assertRaises(ZeroCrossingError):
            same_direction_intervals(angle, np.zeros(POINTS), 32)

    def test_rejects_wrong_pole_pairs(self):
        # 把 16 极对的波形当 32 极对喂进去：过零数只有一半，必须报异常
        angle = _grid()
        with self.assertRaises(ZeroCrossingError):
            same_direction_intervals(angle, np.sin(_sine(16, 0.7)), 32)

    def test_rejects_shape_mismatch(self):
        angle = _grid()
        with self.assertRaises(ZeroCrossingError):
            same_direction_intervals(angle, np.sin(_sine(32, 0.7))[:-1], 32)


def _crossings(pole_pairs, offset_deg=1.0, wobble_deg=0.0):
    """构造 2p 个递增过零角：等距 + 固定零位 + 可选的 1 圈 1 次摆动。

    零位取小于标称间隔的值，保证结果仍落在 [0°, 360°) 且单调递增。
    """
    half = 180.0 / pole_pairs
    index = np.arange(2 * pole_pairs)
    return (offset_deg + index * half
            + wobble_deg * np.sin(np.deg2rad(index * half)))


class ZeroPositionDeviationTest(unittest.TestCase):

    def test_ideal_grid_has_zero_deviation(self):
        cross = _crossings(32)
        result = zero_position_deviation(cross, 32)
        self.assertIsInstance(result, ZeroPosition)
        self.assertEqual(result.position_deg.size, 64)
        self.assertAlmostEqual(result.fixed_offset_deg, 1.0, places=12)
        self.assertLess(float(np.max(np.abs(result.position_deg))), 1e-12)
        self.assertAlmostEqual(result.stats()['peak_to_peak_deg'], 0.0, places=12)

    def test_rotated_grid_only_moves_offset(self):
        for offset in (0.0, 0.5, 4.9):
            result = zero_position_deviation(_crossings(31, offset), 31)
            self.assertAlmostEqual(result.fixed_offset_deg, offset, places=12)
            self.assertLess(float(np.max(np.abs(result.position_deg))), 1e-12)

    def test_wrapped_grid_still_uniform(self):
        # 零位跨过 360° 后排序，仍是等距网格 → 偏差应接近 0
        cross = np.sort(_crossings(31, 17.3) % 360.0)
        result = zero_position_deviation(cross, 31)
        self.assertLess(float(np.max(np.abs(result.position_deg))), 1e-12)

    def test_mean_deviation_is_zero_and_relations_hold(self):
        cross = np.sort(_crossings(32, 2.5, 0.02))
        result = zero_position_deviation(cross, 32)
        position = result.position_deg
        half = 180.0 / 32
        self.assertAlmostEqual(float(position.mean()), 0.0, places=12)

        width = np.diff(np.r_[cross, cross[0] + 360.0])
        step = np.roll(position, -1) - position
        np.testing.assert_allclose(step, width - half, rtol=0, atol=1e-12)

        same = width + np.roll(width, -1)
        across = np.roll(position, -2) - position
        np.testing.assert_allclose(across, same - 2 * half, rtol=0, atol=1e-12)

    def test_rejects_bad_cross_arrays(self):
        cases = [
            (_crossings(32)[:-1], 32),                 # 点数不足
            (_crossings(32) + 400.0, 32),              # 超出 [0,360)
            (_crossings(31), 32),                      # 极对数与点数不符
            (np.zeros(64), 32),                        # 角序异常
        ]
        for cross, pole_pairs in cases:
            with self.assertRaises(ZeroCrossingError):
                zero_position_deviation(cross, pole_pairs)

    def test_unsupported_pole_pairs(self):
        with self.assertRaises(ZeroCrossingError):
            zero_position_deviation(_crossings(30), 30)


class DualTrackDifferenceTest(unittest.TestCase):

    def test_identical_tracks_cancel(self):
        angle = _grid()
        position = zero_position_deviation(np.sort(_crossings(32, 3.0, 0.01)), 32)
        diff = dual_track_difference(angle, position, position)
        self.assertEqual(diff.size, angle.size)
        np.testing.assert_allclose(diff, 0.0, atol=1e-12)

    def test_common_shift_cancels_after_interpolation(self):
        angle = _grid()
        outer = zero_position_deviation(np.sort(_crossings(32, 1.0, 0.02)), 32)
        inner = zero_position_deviation(np.sort(_crossings(31, 1.0, 0.02)), 31)
        diff = dual_track_difference(angle, outer, inner)
        # 两道的局部形状相同，插值后差值应远小于各自峰峰
        self.assertLess(float(np.max(np.abs(diff))),
                        0.2 * outer.stats()['peak_to_peak_deg'])

    def test_period_wrapping_and_report_rounding(self):
        angle = _grid()
        outer = zero_position_deviation(np.sort(_crossings(32, 5.0, 0.03)), 32)
        inner = zero_position_deviation(np.sort(_crossings(31, 5.0, 0.0)), 31)
        exact = dual_track_difference(angle, outer, inner)
        rounded = dual_track_difference(angle, outer, inner, report_rounding=True)
        np.testing.assert_allclose(exact, rounded, rtol=0, atol=5e-5)
        # 接缝两侧连续（period=360）
        self.assertLess(abs(float(exact[0] - exact[-1])), 0.01)

    def test_rejects_bad_angle_grid(self):
        outer = zero_position_deviation(np.sort(_crossings(32)), 32)
        with self.assertRaises(ZeroCrossingError):
            dual_track_difference(np.array([[0.0, 1.0]]), outer, outer)


class RealDataRegressionTest(unittest.TestCase):
    """仓库里带了 20261118 的 9-外/9-内 实测数据时做一次端到端核对。"""

    DATA_DIR = os.path.join(os.path.dirname(__file__), '..', '..',
                            'data', 'plot_data', '20261118')

    def _read(self, track, pole_pairs):
        from core.dual_track_solver import read_scan
        name = f'9-{track}_20261118_151249.csv' if track == '外' else \
               f'9-{track}_20261118_151319.csv'
        path = os.path.join(self.DATA_DIR, name)
        if not os.path.exists(path):
            self.skipTest(f'缺少实测数据 {name}')
        return read_scan(path, pole_pairs)

    def test_selected_sample_crossing_counts(self):
        angle, outer, _ = self._read('外', 32)
        inner_angle, inner, _ = self._read('内', 31)
        np.testing.assert_array_equal(angle, inner_angle)
        outer_result = same_direction_intervals(angle, outer, 32)
        inner_result = same_direction_intervals(inner_angle, inner, 31)
        self.assertEqual(outer_result.cross_deg.size, 64)
        self.assertEqual(inner_result.cross_deg.size, 62)
        # 整圈均值严格等于标称（几何恒等关系）
        self.assertAlmostEqual(float(outer_result.same_deg.mean()), 11.25, places=9)
        self.assertAlmostEqual(float(inner_result.same_deg.mean()), 360.0 / 31, places=9)
        self.assertTrue(np.all(np.diff(outer_result.cross_deg) > 0))

    def test_selected_sample_position_deviation(self):
        angle, outer, _ = self._read('外', 32)
        inner_angle, inner, _ = self._read('内', 31)
        outer_cross = same_direction_intervals(angle, outer, 32).cross_deg
        inner_cross = same_direction_intervals(inner_angle, inner, 31).cross_deg
        outer_position = zero_position_deviation(outer_cross, 32)
        inner_position = zero_position_deviation(inner_cross, 31)

        self.assertEqual(outer_position.position_deg.size, 64)
        self.assertEqual(inner_position.position_deg.size, 62)
        self.assertAlmostEqual(float(outer_position.position_deg.mean()), 0.0, places=12)
        self.assertAlmostEqual(float(inner_position.position_deg.mean()), 0.0, places=12)
        for result, pole_pairs in ((outer_position, 32), (inner_position, 31)):
            half = 180.0 / pole_pairs
            width = np.diff(np.r_[result.cross_deg, result.cross_deg[0] + 360.0])
            step = np.roll(result.position_deg, -1) - result.position_deg
            np.testing.assert_allclose(step, width - half, rtol=0, atol=1e-10)

        diff = dual_track_difference(angle, outer_position, inner_position)
        self.assertEqual(diff.size, angle.size)
        self.assertTrue(np.isfinite(diff).all())
        self.assertGreater(float(np.ptp(outer_position.position_deg)), 0.0)


if __name__ == '__main__':
    unittest.main()
