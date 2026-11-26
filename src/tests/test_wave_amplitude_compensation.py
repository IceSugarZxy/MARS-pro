import unittest

import numpy as np

from windows.wave_analysis import WaveAnalysis
from core.plot_data_reader import apply_sample_info_row


class WaveAmplitudeCompensationTests(unittest.TestCase):
    def setUp(self):
        self.angles = np.arange(16384, dtype=float) * (360.0 / 16384)
        theta = np.deg2rad(self.angles)
        carrier = np.sin(31 * theta)
        n_envelope = 20.0 * (1.0 + 0.12 * np.sin(theta))
        s_envelope = 18.0 * (1.0 + 0.16 * np.cos(theta))
        self.waveform = carrier * np.where(carrier >= 0, n_envelope, s_envelope)
        # 本文件只验证单周期包络（幅值）补偿，注入空表关掉过零点偏差补偿
        self.analyzer = WaveAnalysis(zero_crossing_table={})

    @staticmethod
    def _relative_one_cycle_amplitude(result, pole):
        peaks = [item for item in result["peak_details"] if item["pole"] == pole]
        angles = np.deg2rad([item["angle"] for item in peaks])
        values = np.asarray([abs(item["value"]) for item in peaks], dtype=float)
        design = np.column_stack([np.sin(angles), np.cos(angles), np.ones(len(values))])
        coefficients, *_ = np.linalg.lstsq(design, values, rcond=None)
        return np.hypot(coefficients[0], coefficients[1]) / abs(coefficients[2])

    def test_corrected_waveform_reduces_both_polarity_envelopes_and_preserves_zeros(self):
        raw_result = self.analyzer._wave_analysis(
            self.angles, self.waveform, apply_amplitude_correction=False)
        corrected_result, corrected = self.analyzer.analyze_waveform_with_correction(
            self.angles, self.waveform)
        corrected = np.asarray(corrected)

        self.assertTrue(corrected_result["concentricity"]["waveform_corrected"])
        np.testing.assert_array_equal(np.signbit(corrected), np.signbit(self.waveform))
        self.assertTrue(np.all(np.isfinite(corrected)))
        raw_crossings = [
            item["angle"] for item in raw_result["zero_crossing_details"]
        ]
        corrected_crossings = [
            item["angle"] for item in corrected_result["zero_crossing_details"]
        ]
        self.assertEqual(corrected_crossings, raw_crossings)

        for pole in ("N", "S"):
            before = self._relative_one_cycle_amplitude(raw_result, pole)
            after = self._relative_one_cycle_amplitude(corrected_result, pole)
            self.assertLess(after, before * 0.25)

        n_peaks = [p for p in corrected_result["peak_details"] if p["pole"] == "N"]
        s_peaks = [p for p in corrected_result["peak_details"] if p["pole"] == "S"]
        self.assertAlmostEqual(corrected_result["N_min"], min(abs(p["value"]) for p in n_peaks), places=2)
        self.assertAlmostEqual(corrected_result["S_min"], min(abs(p["value"]) for p in s_peaks), places=2)

    def test_precompensated_waveform_is_not_changed_again(self):
        _, corrected = self.analyzer.analyze_waveform_with_correction(
            self.angles, self.waveform)
        result, reused = self.analyzer.analyze_waveform_with_correction(
            self.angles, corrected, apply_amplitude_correction=False)

        # 幅值补偿关闭 = 不改波形（已补偿数据不会被二次放大）
        np.testing.assert_array_equal(reused, corrected)
        self.assertFalse(result["concentricity"]["waveform_corrected"])
        self.assertFalse(result["concentricity"]["amplitude_compensation_applied"])

    def test_csv_compensation_metadata_is_recognized(self):
        sample_info = {}
        apply_sample_info_row(sample_info, ["单周期包络补偿", "已应用"])
        self.assertEqual(sample_info["amplitude_compensation"], "已应用")


if __name__ == "__main__":
    unittest.main()
