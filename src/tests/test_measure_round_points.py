# -*- coding: utf-8 -*-
"""旋转测量一圈点数：默认按收到点数整圈使用（不裁切）。"""

import os
import queue
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import numpy as np
from PyQt5.QtWidgets import QApplication

from core.data_process import SAMPLES_PER_REV, DataProcess


class _StubConfig:
    """只提供 _process_measure_algorithm 用到的两个配置项，避免读写真实配置。"""

    def __init__(self, trim=False, speed=2):
        self.closure_trim = trim
        self.test_speed = speed


class RoundPointsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    @staticmethod
    def _wave(points, pole_pairs=5):
        angles = np.arange(points) * (360.0 / points)
        return (20.0 * np.sin(np.deg2rad(pole_pairs * angles))
                + 3.0 * np.cos(np.deg2rad(angles)))

    def _process(self, values, trim=False, speed=2):
        process = DataProcess(queue.Queue())
        process.config = _StubConfig(trim, speed)
        return process._process_measure_algorithm(list(values))

    def test_keeps_received_point_count_by_default(self):
        for points in (SAMPLES_PER_REV[2], 32756, 27720):
            with self.subTest(points=points):
                angles, mags = self._process(self._wave(points))
                self.assertEqual(len(mags), points)
                self.assertEqual(len(angles), points)
                # 输出角度保留 6 位小数，容差按舍入给
                self.assertAlmostEqual(angles[1] - angles[0], 360.0 / points,
                                       delta=1e-6)
                self.assertAlmostEqual(angles[-1], 360.0 * (points - 1) / points,
                                       delta=1e-6)

    def test_each_speed_gear_uses_its_own_point_count(self):
        """三档一圈点数各不相同（131072 / 65536 / 32768），都按收到点数整圈使用。"""
        self.assertEqual(SAMPLES_PER_REV, {0: 131072, 1: 65536, 2: 32768})
        for speed, points in SAMPLES_PER_REV.items():
            with self.subTest(speed=speed, points=points):
                with self.assertNoLogs('MARS.DataProcess', level='WARNING'):
                    angles, mags = self._process(self._wave(points), speed=speed)
                self.assertEqual(len(mags), points)
                self.assertAlmostEqual(angles[1] - angles[0], 360.0 / points,
                                       delta=1e-6)

    def test_point_count_mismatch_is_warned(self):
        """收到点数与该档位标称不符时要能在日志里看见（例如均衡档收到 32768）。"""
        with self.assertLogs('MARS.DataProcess', level='WARNING') as logs:
            self._process(self._wave(SAMPLES_PER_REV[2]), speed=1)
        self.assertTrue(any('标称' in line and '65536' in line for line in logs.output))

    def test_trim_switch_restores_closure_trimming(self):
        points = SAMPLES_PER_REV[2]
        wave = self._wave(points)
        angles, mags = self._process(wave, trim=True)
        self.assertLess(len(mags), points)
        self.assertAlmostEqual(angles[1] - angles[0], 360.0 / len(mags), delta=1e-6)

    def test_vertical_measurement_unaffected(self):
        points = 1024
        angles, mags = self._process(self._wave(points))
        self.assertEqual(len(mags), len(angles))
        self.assertLessEqual(max(mags), 25.0)


if __name__ == '__main__':
    unittest.main()
