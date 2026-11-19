# -*- coding: utf-8 -*-
"""波形图「双击恢复初始缩放」的单元测试。"""

import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pyqtgraph as pg
from PyQt5.QtCore import QEvent, Qt
from PyQt5.QtGui import QMouseEvent
from PyQt5.QtWidgets import QApplication

from windows.plot_utils import DoubleClickReset


class _StubClick:
    """只提供 handler 需要的最小接口（double/accept）。"""

    def __init__(self, double):
        self._double = double
        self.accepted = False

    def double(self):
        return self._double

    def accept(self):
        self.accepted = True


class DoubleClickResetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.plot = pg.PlotWidget()
        self.plot.resize(600, 400)
        self.plot.setXRange(0, 360, padding=0)
        self.plot.setYRange(-300, 300, padding=0)
        self.reset = DoubleClickReset(self.plot)

    def tearDown(self):
        self.plot.close()
        self.plot.deleteLater()

    def _view(self):
        x_range, y_range = self.plot.plotItem.getViewBox().viewRange()
        return ((round(float(x_range[0]), 3), round(float(x_range[1]), 3)),
                (round(float(y_range[0]), 3), round(float(y_range[1]), 3)))

    def _zoom(self):
        self.plot.setXRange(120, 180, padding=0)
        self.plot.setYRange(-20, 20, padding=0)

    def test_double_click_restores_recorded_range(self):
        self._zoom()
        self.plot.scene().sigMouseClicked.emit(_StubClick(True))
        self.assertEqual(self._view(), ((0.0, 360.0), (-300.0, 300.0)))

    def test_single_click_keeps_zoomed_range(self):
        self._zoom()
        event = _StubClick(False)
        self.plot.scene().sigMouseClicked.emit(event)
        self.assertEqual(self._view(), ((120.0, 180.0), (-20.0, 20.0)))
        self.assertFalse(event.accepted)

    def test_remember_tracks_latest_range(self):
        self._zoom()
        self.reset.remember()
        self.plot.setXRange(200, 220, padding=0)
        self.plot.setYRange(-5, 5, padding=0)
        self.plot.scene().sigMouseClicked.emit(_StubClick(True))
        self.assertEqual(self._view(), ((120.0, 180.0), (-20.0, 20.0)))

    def test_auto_range_state_is_restored(self):
        plot = pg.PlotWidget()
        try:
            plot.plot([0, 1, 2], [0, 5, -5])
            plot.plotItem.enableAutoRange(True, True)
            reset = DoubleClickReset(plot)
            self.assertTrue(any(plot.plotItem.getViewBox().autoRangeEnabled()))
            plot.plotItem.getViewBox().enableAutoRange(None, False)
            plot.setXRange(0, 1, padding=0)
            plot.setYRange(-1, 1, padding=0)
            plot.scene().sigMouseClicked.emit(_StubClick(True))
            self.assertEqual(tuple(plot.plotItem.getViewBox().autoRangeEnabled()),
                             (True, True))
        finally:
            plot.close()
            plot.deleteLater()

    def test_fixed_axis_restores_range_while_auto_axis_stays_auto(self):
        """X 自动量程 + Y 固定量程：双击后 X 回到自动、Y 回到记录的固定范围。"""
        plot = pg.PlotWidget()
        try:
            plot.plot([0, 1, 2, 3], [5, 5, 5, 5])
            plot.setYRange(4.9, 5.1, padding=0)
            reset = DoubleClickReset(plot)
            plot.plotItem.getViewBox().enableAutoRange('x', False)
            plot.setXRange(1, 2, padding=0)
            plot.setYRange(0, 1, padding=0)
            plot.scene().sigMouseClicked.emit(_StubClick(True))
            x_range, y_range = plot.plotItem.getViewBox().viewRange()
            self.assertEqual(tuple(plot.plotItem.getViewBox().autoRangeEnabled()),
                             (True, False))
            self.assertEqual((round(float(y_range[0]), 3),
                              round(float(y_range[1]), 3)), (4.9, 5.1))
            self.assertNotEqual((round(float(x_range[0]), 3),
                                 round(float(x_range[1]), 3)), (1.0, 2.0))
            self.assertTrue(reset is not None)
        finally:
            plot.close()
            plot.deleteLater()

    def test_real_double_click_event_restores_view(self):
        """走真实 Qt 事件链（viewport → scene → sigMouseClicked）验证双击生效。"""
        viewport = self.plot.viewport()
        center = viewport.rect().center()

        def send(kind, buttons):
            event = QMouseEvent(kind, center, center, Qt.LeftButton, buttons,
                                Qt.NoModifier)
            self.app.sendEvent(viewport, event)
            self.app.processEvents()

        self._zoom()
        send(QEvent.MouseButtonPress, Qt.LeftButton)
        send(QEvent.MouseButtonRelease, Qt.NoButton)
        send(QEvent.MouseButtonDblClick, Qt.LeftButton)
        send(QEvent.MouseButtonRelease, Qt.NoButton)
        self.assertEqual(self._view(), ((0.0, 360.0), (-300.0, 300.0)))


if __name__ == '__main__':
    unittest.main()
