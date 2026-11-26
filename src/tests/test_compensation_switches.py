# -*- coding: utf-8 -*-
"""补偿设定（爪盘 / 单周期幅值 / 单周期过零点）开关的单元测试。"""

import csv
import io
import os
import shutil
import tempfile
import unittest

import numpy as np

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from core.config_manager import ConfigManager
from core.data_process import compensation_scheme_text
from core.plot_data_reader import apply_sample_info_row
from windows.wave_analysis import WaveAnalysis


def _make_waveform(points=4096, poles=31):
    angles = np.arange(points, dtype=float) * (360.0 / points)
    theta = np.deg2rad(angles)
    carrier = np.sin(poles * theta)
    n_envelope = 20.0 * (1.0 + 0.12 * np.sin(theta))
    s_envelope = 18.0 * (1.0 + 0.16 * np.cos(theta))
    return angles, carrier * np.where(carrier >= 0, n_envelope, s_envelope)


class CompensationSwitchConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile('w', suffix='.txt', delete=False,
                                               encoding='utf-8')
        self.tmp.close()
        self.config = ConfigManager(self.tmp.name)

    def tearDown(self):
        os.remove(self.tmp.name)

    def test_switches_default_to_enabled(self):
        self.assertTrue(self.config.comp_chuck)
        self.assertTrue(self.config.comp_amplitude)
        self.assertTrue(self.config.comp_zero_crossing)

    def test_switches_roundtrip(self):
        self.config.comp_chuck = False
        self.config.comp_amplitude = False
        self.config.comp_zero_crossing = False
        reloaded = ConfigManager(self.tmp.name)
        self.assertFalse(reloaded.comp_chuck)
        self.assertFalse(reloaded.comp_amplitude)
        self.assertFalse(reloaded.comp_zero_crossing)

    def test_switch_accepts_truthy_text(self):
        for text in ('1', 'true', 'True', 'yes', 'on'):
            self.config.set('comp_amplitude', text)
            self.assertTrue(self.config.comp_amplitude, text)
        for text in ('0', 'false', 'off', ''):
            self.config.set('comp_amplitude', text)
            self.assertFalse(self.config.comp_amplitude, text)


class CompensationTextTests(unittest.TestCase):
    def test_scheme_text(self):
        self.assertEqual(compensation_scheme_text(True, True, True), '全部补偿')
        self.assertEqual(compensation_scheme_text(False, False, False), '未补偿')
        self.assertEqual(compensation_scheme_text(True, False, True), '部分补偿')
        self.assertEqual(compensation_scheme_text(False, False, True), '部分补偿')

    def test_reader_parses_compensation_rows(self):
        sample_info = {}
        apply_sample_info_row(sample_info, ['爪盘补偿', '已应用'])
        apply_sample_info_row(sample_info, ['单周期包络补偿', '未应用'])
        apply_sample_info_row(sample_info, ['过零点偏差补偿', '已应用'])
        apply_sample_info_row(sample_info, ['补偿方案', '部分补偿'])
        self.assertEqual(sample_info['chuck_compensation'], '已应用')
        self.assertEqual(sample_info['amplitude_compensation'], '未应用')
        self.assertEqual(sample_info['zero_crossing_compensation'], '已应用')
        self.assertEqual(sample_info['compensation_scheme'], '部分补偿')


class WaveAnalysisSwitchTests(unittest.TestCase):
    """幅值 / 过零点两个开关相互独立。"""

    def setUp(self):
        self.angles, self.waveform = _make_waveform()

    def test_both_enabled_changes_waveform(self):
        analyzer = WaveAnalysis(zero_crossing_table={})
        results, corrected = analyzer.analyze_waveform_with_correction(
            self.angles, self.waveform)
        self.assertTrue(results['concentricity']['waveform_corrected'])
        self.assertTrue(results['concentricity']['amplitude_compensation_applied'])
        self.assertFalse(np.allclose(corrected, self.waveform))

    def test_amplitude_disabled_keeps_waveform(self):
        analyzer = WaveAnalysis(zero_crossing_table={})
        results, corrected = analyzer.analyze_waveform_with_correction(
            self.angles, self.waveform, apply_amplitude_correction=False)
        np.testing.assert_array_equal(corrected, self.waveform)
        self.assertFalse(results['concentricity']['waveform_corrected'])
        self.assertFalse(results['concentricity']['amplitude_compensation_applied'])
        self.assertFalse(results['concentricity']['zero_crossing_applied'])

    def test_both_disabled_keeps_waveform(self):
        analyzer = WaveAnalysis(zero_crossing_table={})
        results, corrected = analyzer.analyze_waveform_with_correction(
            self.angles, self.waveform,
            apply_amplitude_correction=False,
            apply_zero_crossing_correction=False)
        np.testing.assert_array_equal(corrected, self.waveform)
        self.assertFalse(results['concentricity']['waveform_corrected'])

    def test_zero_crossing_disabled_but_amplitude_enabled(self):
        analyzer = WaveAnalysis(zero_crossing_table={})
        results, corrected = analyzer.analyze_waveform_with_correction(
            self.angles, self.waveform,
            apply_zero_crossing_correction=False)
        self.assertTrue(results['concentricity']['amplitude_compensation_applied'])
        self.assertTrue(results['concentricity']['waveform_corrected'])
        self.assertFalse(results['concentricity']['zero_crossing_applied'])
        self.assertFalse(np.allclose(corrected, self.waveform))


class ChuckAndSaveTests(unittest.TestCase):
    """爪盘补偿开关 + CSV 里记录补偿情况。"""

    class _StubConfig:
        pga_gain = 0
        idac_index = 4
        test_speed = 1

        def __init__(self, chuck_enabled=True, curve=None):
            self.comp_chuck = chuck_enabled
            self.comp_amplitude = True
            self.comp_zero_crossing = True
            self._curve = curve

        def get_chuck_compensation(self):
            return self._curve

    def _proc(self, **kwargs):
        from core.data_process import DataProcess
        import queue
        proc = DataProcess(queue.Queue())
        proc.config = self._StubConfig(**kwargs)
        return proc

    def test_chuck_switch_off_keeps_raw_data(self):
        proc = self._proc(chuck_enabled=False, curve=(1.0, [0.5] * 360))
        data = [1.0] * 360
        self.assertEqual(proc._apply_chuck_compensation(data), data)
        self.assertFalse(proc._chuck_compensation_applied)

    def test_chuck_switch_on_subtracts_curve(self):
        proc = self._proc(chuck_enabled=True, curve=(1.0, [0.5] * 360))
        corrected = proc._apply_chuck_compensation([1.0] * 360)
        self.assertAlmostEqual(corrected[0], 0.5, places=6)
        self.assertTrue(proc._chuck_compensation_applied)

    def test_attach_compensation_status_records_switches(self):
        proc = self._proc(chuck_enabled=False, curve=(1.0, [0.5] * 360))
        results = {'concentricity': {'zero_crossing_applied': True}}
        out = proc._attach_compensation_status(results)
        info = out['concentricity']
        self.assertFalse(info['chuck_compensation_applied'])
        self.assertEqual(info['compensation_switches'],
                         {'chuck': False, 'amplitude': True, 'zero_crossing': True})

    def test_saved_csv_records_compensation_scheme(self):
        import core.data_process as dp
        proc = self._proc(chuck_enabled=True, curve=(1.0, [0.5] * 360))
        proc._chuck_compensation_applied = True
        results = {'concentricity': {
            'chuck_compensation_applied': True,
            'amplitude_compensation_applied': False,
            'zero_crossing_applied': True,
        }}
        tmp_dir = tempfile.mkdtemp()
        original = dp.get_data_dir
        dp.get_data_dir = lambda name="": tmp_dir
        try:
            path = proc.save_plot_measure_data([0.0, 90.0, 180.0], [1.0, 2.0, 3.0], results)
            self.assertTrue(path)
            with io.open(path, encoding='utf-8') as fh:
                text = fh.read()
        finally:
            dp.get_data_dir = original
            shutil.rmtree(tmp_dir, ignore_errors=True)

        self.assertIn('爪盘补偿,已应用', text)
        self.assertIn('单周期包络补偿,未应用', text)
        self.assertIn('过零点偏差补偿,已应用', text)
        self.assertIn('补偿方案,部分补偿', text)


if __name__ == '__main__':
    unittest.main()
