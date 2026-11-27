# -*- coding: utf-8 -*-
"""「测量结束」弹窗显示合格/不良的单元测试。"""

import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtWidgets import QApplication

from windows.test_progress_dialog import TestProgressDialog


class TestProgressDialogVerdictTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.dialog = TestProgressDialog()

    def tearDown(self):
        self.dialog.close()
        self.dialog.deleteLater()

    def test_show_result_keeps_original_text(self):
        self.dialog.show_result(True, "采集完成，共 32768 个数据点")
        self.assertEqual(self.dialog.label_title.text(), "测量完成")
        self.assertEqual(self.dialog.label_status.text(), "采集完成，共 32768 个数据点")
        self.assertEqual(self.dialog.btn_cancel.text(), "确定")

    def test_judge_verdict_replaces_title_with_big_text(self):
        self.dialog.show_result(True, "采集完成")
        self.dialog.show_judge_verdict("合格", "#27ae60")
        self.assertEqual(self.dialog.label_title.text(), "合格")
        style = self.dialog.label_title.styleSheet()
        self.assertIn("#27ae60", style)
        self.assertIn("40px", style)
        # 采集点数等状态文字保留
        self.assertEqual(self.dialog.label_status.text(), "采集完成")

    def test_judge_verdict_fail_uses_red(self):
        self.dialog.show_judge_verdict("不良", "#e74c3c")
        self.assertEqual(self.dialog.label_title.text(), "不良")
        self.assertIn("#e74c3c", self.dialog.label_title.styleSheet())


if __name__ == '__main__':
    unittest.main()
