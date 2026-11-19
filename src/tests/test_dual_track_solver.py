# -*- coding: utf-8 -*-
import os
import tempfile
import unittest
from pathlib import Path

import numpy as np

from core.dual_track_solver import (
    DualTrackError,
    calibrate_track,
    describe_rating,
    quantize_phase,
    read_scan,
    solve_pair,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
GOOD_DIR = REPO_ROOT / '分析报告' / '11.18_良品_10组'
COMPENSATED_DIR = REPO_ROOT / '分析报告' / '不良品3组_补偿'
DLL_PATH = Path(__file__).resolve().parents[2] / 'vendor' / 'iC-MU150' / 'MU_3SL_INTERFACE_64.DLL'


class QuantizePhaseTests(unittest.TestCase):
    def test_matches_sdk_phase_to_code(self):
        from core.mu150_spo import phase_to_code

        angles = [-720.0, -360.0, -0.5, 0.0, 0.010986328125, 90.0, 359.99, 720.0]
        self.assertEqual(tuple(int(v) for v in quantize_phase(angles)),
                         phase_to_code(angles))

    def test_codes_stay_in_14_bit_range(self):
        codes = quantize_phase(np.linspace(-1000, 1000, 500))
        self.assertTrue(np.all(codes < 16384))


class CalibrateTrackTests(unittest.TestCase):
    def test_ideal_waveform_yields_linear_electrical_phase(self):
        points = 32768
        angle = np.arange(points) * 360.0 / points
        pole_pairs = 31
        codes, diagnostics = calibrate_track(angle, np.sin(np.deg2rad(pole_pairs * angle)),
                                             pole_pairs)

        expected = quantize_phase(pole_pairs * angle)
        wrapped = (codes.astype(np.int64) - expected.astype(np.int64)) % 16384
        offset = int(np.median(wrapped))
        residual = (wrapped - offset + 8192) % 16384 - 8192
        self.assertLess(int(np.max(np.abs(residual))), 40)
        self.assertFalse(diagnostics.saturated)
        self.assertGreater(diagnostics.normalization_amplitude, 0.5)


class ReadScanTests(unittest.TestCase):
    @unittest.skipUnless(GOOD_DIR.is_dir(), '缺少良品回归数据')
    def test_reads_32768_point_single_turn(self):
        angle, mag, meta = read_scan(GOOD_DIR / '2-外.csv', 32)
        self.assertEqual(angle.size, 32768)
        self.assertEqual(mag.size, 32768)
        self.assertEqual(meta.get('极数'), '32')

    @unittest.skipUnless(GOOD_DIR.is_dir(), '缺少良品回归数据')
    def test_rejects_wrong_pole_pairs(self):
        with self.assertRaises(DualTrackError):
            read_scan(GOOD_DIR / '2-外.csv', 31)

    @unittest.skipUnless(COMPENSATED_DIR.is_dir(), '缺少补偿后 CSV')
    def test_reads_file_with_compensation_marker(self):
        """补偿文件多一行元信息，表头要动态定位而不是固定跳过。"""
        angle, mag, meta = read_scan(COMPENSATED_DIR / '1-外.csv', 32)
        self.assertEqual(angle.size, 32768)
        self.assertEqual(meta.get('单周期包络补偿'), '已应用')


class ReadScanResampleTests(unittest.TestCase):
    """实测一圈点数不固定（32756 / 27720 / 65536），要重采样到统一网格才能配对。"""

    def _write_scan(self, points, pole_pairs=32, extra_meta=()):
        angles = np.arange(points) * (360.0 / points)
        mag = 20.0 * np.sin(np.deg2rad(pole_pairs * angles)) + 1.5
        handle = tempfile.NamedTemporaryFile('w', suffix='.csv', delete=False,
                                            encoding='utf-8-sig', newline='')
        with handle as stream:
            stream.write('样品名称,测试样品\n')
            stream.write('极数,%d\n' % pole_pairs)
            for line in extra_meta:
                stream.write(line + '\n')
            stream.write('角度(度),磁场强度\n')
            for angle, value in zip(angles, mag):
                stream.write(f'{angle:.6f},{value:.6f}\n')
        self.addCleanup(Path(handle.name).unlink)
        return Path(handle.name), angles, mag

    def test_resamples_short_grid_to_standard_length(self):
        path, angles, mag = self._write_scan(32756)
        angle, field, meta = read_scan(path, 32)
        self.assertEqual(angle.size, 32768)
        self.assertEqual(meta.get('_原始点数'), '32756')
        self.assertAlmostEqual(float(angle[1] - angle[0]), 360.0 / 32768, places=9)
        # 重采样后幅值仍应是同一圈正弦（峰值 ~20 mT）
        self.assertLess(abs(float(np.max(field)) - float(np.max(mag))), 0.1)

    def test_resamples_high_resolution_grid(self):
        path, _angles, mag = self._write_scan(65536)
        angle, field, _meta = read_scan(path, 32)
        self.assertEqual(angle.size, 32768)
        self.assertLess(abs(float(np.max(field)) - float(np.max(mag))), 0.1)

    def test_rejects_too_few_points(self):
        path, _angles, _mag = self._write_scan(512)
        with self.assertRaises(DualTrackError) as context:
            read_scan(path, 32)
        self.assertIn('一圈至少需要', str(context.exception))

    def test_rejects_non_uniform_grid(self):
        path, _angles, _mag = self._write_scan(4096)
        lines = path.read_text(encoding='utf-8-sig').splitlines()
        header = lines.index('角度(度),磁场强度')
        first = lines[header + 1].split(',')
        lines[header + 1] = f'{float(first[0]) + 1.0},{first[1]}'
        path.write_text('\n'.join(lines) + '\n', encoding='utf-8-sig')
        with self.assertRaises(DualTrackError) as context:
            read_scan(path, 32)
        self.assertIn('均匀单圈网格', str(context.exception))


@unittest.skipUnless(DLL_PATH.exists(), '缺少原厂 MU_3SL_INTERFACE_64.DLL')
@unittest.skipUnless(GOOD_DIR.is_dir(), '缺少良品回归数据')
class SolvePairRegressionTests(unittest.TestCase):
    """交接说明第 13.2 节的实测回归值。"""

    def _solve(self, mode):
        return solve_pair(GOOD_DIR / '2-外.csv', GOOD_DIR / '2-内.csv', DLL_PATH, mode)

    def test_full_band_matches_documented_regression(self):
        result = self._solve('全带空间移位差分')
        self.assertEqual((int(result.rating.minimum), int(result.rating.maximum)),
                         (-607, 456))
        self.assertEqual(result.rating.margin_codes, 256 - result.rating.peak)
        self.assertFalse(result.rating.within_rating)
        self.assertTrue(describe_rating(result.rating).startswith('超解码边界'))

    def test_sideband_modes_match_documented_regression(self):
        for mode, expected in (
                ('基波旁带±2', (-192, 167)),
                ('基波旁带±4', (-188, 185))):
            with self.subTest(mode=mode):
                result = self._solve(mode)
                self.assertEqual(
                    (int(result.rating.minimum), int(result.rating.maximum)), expected)
                self.assertTrue(result.rating.within_rating)

    @unittest.skipUnless(COMPENSATED_DIR.is_dir(), '缺少补偿后 CSV')
    def test_defective_sample_full_band_matches_documented_regression(self):
        result = solve_pair(COMPENSATED_DIR / '1-外.csv', COMPENSATED_DIR / '1-内.csv',
                            DLL_PATH, '全带空间移位差分')
        self.assertEqual((int(result.rating.minimum), int(result.rating.maximum)),
                         (-497, 495))


if __name__ == '__main__':
    unittest.main()
