# -*- coding: utf-8 -*-
import csv
import importlib.util
import tempfile
import unittest
from pathlib import Path

import numpy as np

from windows.wave_analysis import WaveAnalysis

SCRIPT_PATH = (Path(__file__).resolve().parents[4]
               / "测试脚本" / "脚本" / "单周期补偿重算plotdata.py")


def _load_converter():
    spec = importlib.util.spec_from_file_location("convert_plot_data_compensation", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


converter = _load_converter()


def _write_source_csv(path, points=4096):
    angles = np.arange(points, dtype=float) * (360.0 / points)
    theta = np.deg2rad(angles)
    carrier = np.sin(31 * theta)
    n_envelope = 20.0 * (1.0 + 0.12 * np.sin(theta))
    s_envelope = 18.0 * (1.0 + 0.16 * np.cos(theta))
    mags = carrier * np.where(carrier >= 0, n_envelope, s_envelope)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["样品名称", "测试样品"])
        writer.writerow(["保存时间", "20261028_101010"])
        writer.writerow([])
        writer.writerow(["角度(度)", "磁场强度"])
        for angle, mag in zip(angles, mags):
            writer.writerow(["%.6f" % angle, "%.5f" % mag])
    return angles, mags


class ConvertPlotDataCompensationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.source_dir = self.root / "20261028"
        self.source_dir.mkdir()
        self.source = self.source_dir / "测试样品_20261028_101010.csv"
        self.angles, self.raw = _write_source_csv(self.source)
        self.analyzer = WaveAnalysis()

    def tearDown(self):
        self.tmp.cleanup()

    def test_converts_into_sibling_folder_and_keeps_source(self):
        source_bytes = self.source.read_bytes()

        result = converter.convert_file(self.source, self.analyzer)

        self.assertEqual(result["status"], "converted", result["detail"])
        target = converter.build_output_path(self.source)
        self.assertEqual(target.parent.name, "20261028_补偿")
        self.assertTrue(target.exists())
        self.assertEqual(self.source.read_bytes(), source_bytes)

        with open(target, "r", encoding="utf-8", newline="") as fh:
            rows = list(csv.reader(fh))
        self.assertIn(["单周期包络补偿", "已应用"], rows)
        header_index = rows.index(["角度(度)", "磁场强度"])
        written_angles = np.asarray([float(row[0]) for row in rows[header_index + 1:]])
        written = np.asarray([float(row[1]) for row in rows[header_index + 1:]])
        np.testing.assert_allclose(written_angles, self.angles, atol=1e-6)
        np.testing.assert_array_equal(np.signbit(written), np.signbit(self.raw))

        raw_info = self.analyzer._wave_analysis(
            self.angles, self.raw, apply_amplitude_correction=False)["concentricity"]
        written_info = self.analyzer._wave_analysis(
            self.angles, written, apply_amplitude_correction=False)["concentricity"]
        for pole in ("n", "s"):
            self.assertLess(written_info["%s_1x_pct" % pole],
                            raw_info["%s_1x_pct" % pole] * 0.25)

    def test_skips_file_already_marked_compensated(self):
        first = converter.convert_file(self.source, self.analyzer)
        self.assertEqual(first["status"], "converted", first["detail"])

        second = converter.convert_file(Path(first["target"]), self.analyzer)

        self.assertEqual(second["status"], "skipped")
        self.assertIn("已是补偿后数据", second["detail"])

    def test_skips_file_without_waveform_section(self):
        other = self.source_dir / "说明_20261028_101011.csv"
        other.write_text("样品名称,无波形\n备注,空文件\n", encoding="utf-8")

        result = converter.convert_file(other, self.analyzer)

        self.assertEqual(result["status"], "skipped")
        self.assertIn("没有波形数据段", result["detail"])
        self.assertFalse(converter.build_output_path(other).exists())


if __name__ == "__main__":
    unittest.main()
