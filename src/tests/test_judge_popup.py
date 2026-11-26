# -*- coding: utf-8 -*-
"""合格判定提示窗的单元测试。"""

import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5 import sip
from PyQt5.QtCore import QEvent, QPoint, Qt
from PyQt5.QtGui import QMouseEvent
from PyQt5.QtWidgets import QApplication, QWidget

from windows.judge_popup import JudgePopup, show_judge_popup, POPUP_TEXT_PX


class JudgePopupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.target = QWidget()
        self.target.resize(400, 300)
        self.target.show()
        self.popups = []

    def tearDown(self):
        for popup in self.popups:
            try:
                popup.close()
            except RuntimeError:
                pass
        self.target.close()
        self.target.deleteLater()

    def _popup(self, text="合格", color="#27ae60"):
        popup = JudgePopup(text, color, parent=self.target)
        self.popups.append(popup)
        return popup

    def _press(self, widget):
        pos = QPoint(10, 10)
        event = QMouseEvent(QEvent.MouseButtonPress, pos, pos, Qt.LeftButton,
                            Qt.LeftButton, Qt.NoModifier)
        self.app.sendEvent(widget, event)
        self.app.processEvents()

    def _is_open(self, popup):
        return (not sip.isdeleted(popup)) and popup.isVisible()

    def test_shows_big_verdict_text_in_color(self):
        popup = self._popup("不合格", "#e74c3c").start()
        self.assertTrue(popup.isVisible())
        self.assertEqual(popup.result_label.text(), "不合格")
        self.assertIn("#e74c3c", popup.result_label.styleSheet())
        self.assertGreaterEqual(popup.result_label.font().pixelSize(), POPUP_TEXT_PX)

    def test_click_anywhere_closes_after_arming(self):
        popup = self._popup().start()
        popup._arm()
        self._press(self.target)
        self.assertFalse(self._is_open(popup))

    def test_click_before_arming_keeps_popup(self):
        popup = self._popup().start()
        self._press(self.target)
        self.assertTrue(popup.isVisible())
        popup._arm()

    def test_new_popup_closes_previous(self):
        first = self._popup("合格").start()
        first._arm()
        second = show_judge_popup("不良", "#e74c3c", parent=self.target, previous=first)
        self.popups.append(second)
        self.assertFalse(first.isVisible())
        self.assertTrue(second.isVisible())

    def test_show_judge_popup_tolerates_deleted_previous(self):
        popup = show_judge_popup("合格", "#27ae60", parent=self.target)
        self.popups.append(popup)
        popup.close()
        another = show_judge_popup("合格", "#27ae60", parent=self.target, previous=popup)
        self.popups.append(another)
        self.assertTrue(another.isVisible())


if __name__ == '__main__':
    unittest.main()
