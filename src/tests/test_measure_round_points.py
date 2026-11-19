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
