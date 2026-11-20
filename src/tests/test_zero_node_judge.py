# -*- coding: utf-8 -*-
"""三点判定（core.zero_node_judge）的回归测试。"""

import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core.zero_node_judge import (LOWER_BOUND_DEG, ZeroNodeError,   # noqa: E402
                                 judge_three_nodes)


def _uniform(count, interval, start=0.0):
    """等角度分布的 K 个起点与统一的同向间距。"""
    angles = (start + np.arange(count) * (360.0 / count)) % 360.0
    angles.sort()
    return angles, np.full(count, float(interval))


class IdealNodeTests(unittest.TestCase):
    def test_nominal_32_31_nodes_pass(self):
        outer_angles, outer_intervals = _uniform(64, 360.0 / 32)
        inner_angles, inner_intervals = _uniform(62, 360.0 / 31)
        report = judge_three_nodes(outer_angles, outer_intervals,
                                   inner_angles, inner_intervals)
        self.assertEqual(report['judgement'], 'pass')
        self.assertEqual(report['judgement_text'], '合格')
        self.assertEqual(report['failed_count'], 0)
        self.assertEqual(report['margins_deg'].size, 62)
        expected = (360.0 / 31) - (360.0 / 32) - LOWER_BOUND_DEG
        self.assertAlmostEqual(report['minimum_margin_deg'], expected, places=9)
        self.assertTrue(report['passed'].all())
        # 三项差值都来自 T外 的最近节点及前后节点
        self.assertEqual(report['differences_deg'].shape, (62, 3))
        np.testing.assert_allclose(
            report['differences_deg'][:, 1],
            inner_intervals - outer_intervals[report['nearest_outer_index']],
            atol=1e-12)


class ThresholdTests(unittest.TestCase):
    def _report(self, inner_value):
        outer_angles, outer_intervals = _uniform(64, 11.0)
        inner_angles, inner_intervals = _uniform(62, inner_value)
        return judge_three_nodes(outer_angles, outer_intervals,
                                 inner_angles, inner_intervals)

    def test_below_lower_bound_fails(self):
        report = self._report(11.0 + LOWER_BOUND_DEG * 0.5)
        self.assertEqual(report['judgement'], 'fail')
        self.assertEqual(report['failed_count'], 62)
        self.assertAlmostEqual(report['failed_percent'], 100.0, places=9)

    def test_equal_lower_bound_is_boundary(self):
        # 用二进制可精确表示的数值构造“恰好等于下限”，验证边界分支
        outer_angles, outer_intervals = _uniform(64, 11.0)
        inner_angles, inner_intervals = _uniform(62, 11.5)
        report = judge_three_nodes(outer_angles, outer_intervals,
                                   inner_angles, inner_intervals, lower_deg=0.5)
        self.assertEqual(report['judgement'], 'boundary')
        self.assertEqual(report['judgement_text'], '边界待复核')
        self.assertEqual(report['failed_count'], 0)
        np.testing.assert_allclose(report['margins_deg'], 0.0, atol=1e-12)
        self.assertTrue(report['boundary'].all())

    def test_above_lower_bound_passes(self):
        report = self._report(11.0 + LOWER_BOUND_DEG * 2)
        self.assertEqual(report['judgement'], 'pass')
        self.assertAlmostEqual(report['minimum_margin_deg'], LOWER_BOUND_DEG, places=9)


class MatchingTests(unittest.TestCase):
    def test_nearest_node_and_neighbours_wrap_at_360(self):
        outer_angles = np.array([1.0, 100.0, 200.0, 300.0])
        outer_intervals = np.array([11.0, 11.0, 11.0, 11.5])
        inner_angles = np.array([0.2, 359.9])
        inner_intervals = np.array([11.2, 11.2])
        report = judge_three_nodes(outer_angles, outer_intervals,
                                   inner_angles, inner_intervals)
        # 0.2° 与 359.9° 最近的外道节点都是 1.0°（下标 0）
        np.testing.assert_array_equal(report['nearest_outer_index'], [0, 0])
        # 前节点按圆周取最后一个，后节点为下一个
        np.testing.assert_array_equal(report['outer_indices'], [[3, 0, 1], [3, 0, 1]])
        np.testing.assert_allclose(report['reference_intervals_deg'][0],
                                   [11.5, 11.0, 11.0])
        # 前节点 T外=11.5 → 差值 11.2−11.5 为负，节点不通过
        self.assertEqual(report['judgement'], 'fail')

    def test_worst_node_is_reported(self):
        outer_angles = np.array([0.0, 120.0, 240.0])
        outer_intervals = np.array([11.0, 11.0, 12.0])
        inner_angles = np.array([10.0, 130.0, 250.0])
        inner_intervals = np.array([11.5, 11.5, 10.0])
        report = judge_three_nodes(outer_angles, outer_intervals,
                                   inner_angles, inner_intervals)
        # 250° 最近外道 240°（下标 2），前节点 120°(11.0)、后节点 0°(11.0)
        # 差值 = 10.0−11.0 / 10.0−12.0 / 10.0−11.0 → 最小 −2.0
        self.assertEqual(report['worst_inner_index'], 2)
        self.assertAlmostEqual(report['worst_inner_angle_deg'], 250.0)
        self.assertAlmostEqual(report['minimum_margin_deg'],
                               -2.0 - LOWER_BOUND_DEG, places=9)
        # 12.0 的节点会波及前后各一个内道节点，加上 250° 本身，三个都不通过
        self.assertEqual(report['failed_count'], 3)
        self.assertAlmostEqual(report['failed_percent'], 100.0, places=9)


class ValidationTests(unittest.TestCase):
    def test_rejects_bad_inputs(self):
        angles = np.array([0.0, 120.0, 240.0])
        intervals = np.array([11.0, 11.0, 11.0])
        cases = (
            (angles, intervals, np.array([]), np.array([])),            # 内道为空
            (angles[:2], intervals[:2], angles, intervals),             # 外道不足 3 个
            (angles, intervals[:2], angles, intervals),                 # 长度不匹配
            (np.array([0.0, 120.0, 120.0]), intervals, angles, intervals),  # 非严格升序
            (np.array([0.0, 120.0, 360.0]), intervals, angles, intervals),  # 越界
            (angles, np.array([11.0, -1.0, 11.0]), angles, intervals),  # 间距非正
            (angles, intervals, angles, np.array([np.nan, 11.0, 11.0])),
        )
        for case in cases:
            with self.subTest(case=str(case)[:40]):
                with self.assertRaises(ZeroNodeError):
                    judge_three_nodes(*case)


if __name__ == '__main__':
    unittest.main()
