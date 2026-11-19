# -*- coding: utf-8 -*-
import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import numpy as np
from PyQt5.QtWidgets import QApplication

from windows.plot_window import (
    PlotWindow,
    Y_AXIS_MARGIN_MT,
    Y_AXIS_STEP_MT,
    resolve_y_limit_for_peak,
)


class ResolveYLimitTests(unittest.TestCase):
    def test_peak_rounds_up_to_next_step(self):
        self.assertEqual(resolve_y_limit_for_peak(0.0), 50.0)
        self.assertEqual(resolve_y_limit_for_peak(12.0), 50.0)
        self.assertEqual(resolve_y_limit_for_peak(50.0), 50.0)
        self.assertEqual(resolve_y_limit_for_peak(50.4), 100.0)
        self.assertEqual(resolve_y_limit_for_peak(73.0), 100.0)
        self.assertEqual(resolve_y_limit_for_peak(-150.0), 150.0)
        self.assertEqual(resolve_y_limit_for_peak(151.0), 200.0)

    def test_invalid_peak_falls_back_to_one_step(self):
        self.assertEqual(resolve_y_limit_for_peak(None), Y_AXIS_STEP_MT)
        self.assertEqual(resolve_y_limit_for_peak('abc'), Y_AXIS_STEP_MT)
        self.assertEqual(resolve_y_limit_for_peak(float('nan')), Y_AXIS_STEP_MT)


class PlotWindowYLimitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    @staticmethod
    def _y_range(window):
        low, high = window.plot_widget.plotItem.getViewBox().viewRange()[1]
        return round(float(low), 2), round(float(high), 2)

    def test_default_state_uses_one_step(self):
        window = PlotWindow()
        self.assertEqual(window.y_limit_mt, Y_AXIS_STEP_MT)
        self.assertEqual(self._y_range(window), (-60.0, 60.0))

    def test_plot_picks_step_covering_peak(self):
        window = PlotWindow()
        angles = np.linspace(0.0, 360.0, 2048)

        window.update_plot(angles, 18.0 * np.sin(np.deg2rad(angles) * 31), 'r')
        self.assertEqual(window.y_limit_mt, 50.0)
        self.assertEqual(self._y_range(window), (-60.0, 60.0))

        window.update_plot(angles, 73.0 * np.sin(np.deg2rad(angles) * 31), 'r')
        self.assertEqual(window.y_limit_mt, 100.0)
        self.assertEqual(self._y_range(window), (-110.0, 110.0))

        window.update_plot(angles, 130.0 * np.sin(np.deg2rad(angles) * 31), 'r')
        self.assertEqual(window.y_limit_mt, 150.0)
        self.assertEqual(self._y_range(window), (-160.0, 160.0))

    def test_reset_returns_to_base_step(self):
        window = PlotWindow()
        angles = np.linspace(0.0, 360.0, 2048)
        window.update_plot(angles, 130.0 * np.sin(np.deg2rad(angles) * 31), 'r')

        window.reset_y_limit()

        self.assertEqual(window.y_limit_mt, 50.0)
        self.assertEqual(self._y_range(window), (-60.0, 60.0))

    def test_reset_view_keeps_current_step(self):
        window = PlotWindow()
        angles = np.linspace(0.0, 360.0, 2048)
        window.update_plot(angles, 73.0 * np.sin(np.deg2rad(angles) * 31), 'r')
        window.plot_widget.setYRange(-5, 5)

        window.reset_plot_view()

        self.assertEqual(self._y_range(window), (-110.0, 110.0))

    def test_explicit_limit_overrides_step(self):
        window = PlotWindow()

        window.set_y_limit(30.0)
        self.assertEqual(self._y_range(window), (-30.0 - Y_AXIS_MARGIN_MT, 30.0 + Y_AXIS_MARGIN_MT))

        window.set_y_limit(0)
        window.set_y_limit('abc')
        self.assertEqual(window.y_limit_mt, 30.0)


if __name__ == '__main__':
    unittest.main()
