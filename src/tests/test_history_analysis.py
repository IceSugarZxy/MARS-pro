# -*- coding: utf-8 -*-
"""历史数据 / 比对 / 缺陷指纹：读已保存 CSV 时直读直算，不重复滤波、不再补偿。"""

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import numpy as np
from PyQt5.QtWidgets import QApplication

from core.defect_fingerprint import analyze_run
from core.zero_crossing_compensation import GLOBAL_KEY
from tests.test_zero_crossing_compensation import (_device_curve, _grid,
                                                   _waveform)
from windows.wave_analysis import WaveAnalysis

POINTS = 4096
POLE_PAIRS = 5


def _write_plot_csv(directory, magnitudes, angles, extra_rows=()):
    """写一份与上位机保存格式一致的 plot_data CSV（元信息 + 角度/磁场 两列）。"""
    path = Path(directory) / '测试样品_20261119_120000.csv'
    lines = ['样品名称,测试样品', '测试员,测试', '极数口径,极对数',
             '极数,%d' % POLE_PAIRS, '保存时间,20261119_120000']
    lines.extend(extra_rows)
    lines.append('角度(度),磁场强度')
    lines.extend('%.6f,%.6f' % (a, m) for a, m in zip(angles, magnitudes))
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8-sig')
    return path


class DirectReadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.angles = np.arange(POINTS) * (360.0 / POINTS)
        self.magnitudes = (20.0 * np.sin(np.deg2rad(POLE_PAIRS * self.angles))
                           + 3.0 * np.cos(np.deg2rad(self.angles)))

    def test_analyze_run_reads_saved_waveform_as_is(self):
        path = _write_plot_csv(
            self._tmp.name, self.magnitudes, self.angles,
            extra_rows=('单周期包络补偿,已应用', '过零点偏差补偿,已应用'))
        run = analyze_run(path, WaveAnalysis())
        self.assertNotIn('error', run)
        self.assertEqual(run['trimmed'], 0)
        # CSV 写入保留 6 位小数，容差按舍入给；重点是没被再滤波（滤波会把差推到 1e-2 量级）
        np.testing.assert_allclose(np.asarray(run['mag']), self.magnitudes,
                                   atol=1e-5)
        self.assertGreater(run['pole_pairs'], 0)
        self.assertTrue(run['curves'])

    def test_unmarked_legacy_file_is_not_compensated(self):
        """没有补偿标记的老文件也按 CSV 原样分析，不再现算补偿。"""
        path = _write_plot_csv(self._tmp.name, self.magnitudes, self.angles)
        run = analyze_run(path, WaveAnalysis())
        self.assertNotIn('error', run)
        np.testing.assert_allclose(np.asarray(run['mag']), self.magnitudes,
                                   atol=1e-5)
        concentricity = (run.get('analysis') or {}).get('concentricity') or {}
        self.assertFalse(concentricity.get('zero_crossing_applied'))
        self.assertFalse(concentricity.get('waveform_corrected'))

    def test_analyze_only_keeps_waveform_and_reports_analysis(self):
        angle = _grid()
        _theta, values = _device_curve()
        analyzer = WaveAnalysis(zero_crossing_table={GLOBAL_KEY: (0.5, values)})
        distorted = _waveform(angle, lambda a: 0.0, pole_pairs=POLE_PAIRS)
        analysis, processed = analyzer.analyze_only(angle, distorted)
        self.assertTrue(analysis)
        np.testing.assert_allclose(np.asarray(processed), distorted, atol=1e-9)
        concentricity = analysis.get('concentricity') or {}
        self.assertFalse(concentricity.get('zero_crossing_applied'))


if __name__ == '__main__':
    unittest.main()
