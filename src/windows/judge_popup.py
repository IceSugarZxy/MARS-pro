# -*- coding: utf-8 -*-
"""合格判定提示窗：屏幕中央的小矩形，大字体显示“合格 / 不良”，任意点击关闭。"""

from PyQt5.QtCore import QEvent, Qt, QTimer
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

POPUP_WIDTH = 440
POPUP_HEIGHT = 240
POPUP_TEXT_PX = 96
# 弹窗出现后短暂延时再响应点击，避免触发弹窗的那次点击立刻把它关掉
POPUP_ARM_DELAY_MS = 300


class JudgePopup(QWidget):
    """无边框置顶提示窗；程序内任意鼠标点击即关闭。"""

    def __init__(self, text: str, color: str, parent: QWidget = None):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setObjectName("judge_popup")
        self.setFixedSize(POPUP_WIDTH, POPUP_HEIGHT)
        self.setStyleSheet(
            "QWidget#judge_popup { background-color: #ffffff; border: 6px solid %s; }" % color
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 12)
        layout.setSpacing(4)

        self.result_label = QLabel(text, self)
        self.result_label.setAlignment(Qt.AlignCenter)
        self.result_label.setStyleSheet(
            "color: %s; background: transparent; border: none;" % color
        )
        text_font = QFont(self.result_label.font())
        text_font.setPixelSize(POPUP_TEXT_PX)
        text_font.setBold(True)
        self.result_label.setFont(text_font)
        layout.addWidget(self.result_label, 1)

        self.hint_label = QLabel("点击任意位置关闭", self)
        self.hint_label.setAlignment(Qt.AlignCenter)
        self.hint_label.setStyleSheet(
            "color: #95a5a6; background: transparent; border: none;"
        )
        hint_font = QFont(self.hint_label.font())
        hint_font.setPixelSize(13)
        self.hint_label.setFont(hint_font)
        layout.addWidget(self.hint_label, 0)

        self._armed = False
        self._arm_timer = QTimer(self)
        self._arm_timer.setSingleShot(True)
        self._arm_timer.setInterval(POPUP_ARM_DELAY_MS)
        self._arm_timer.timeout.connect(self._arm)

        self._center_on_screen(parent)
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    def _center_on_screen(self, parent: QWidget = None) -> None:
        app = QApplication.instance()
        screen = None
        if app is not None and parent is not None:
            try:
                screen = app.screenAt(parent.mapToGlobal(parent.rect().center()))
            except AttributeError:
                screen = None
        if screen is None and app is not None:
            screen = app.primaryScreen()
        if screen is not None:
            geometry = screen.availableGeometry()
        elif parent is not None:
            geometry = parent.frameGeometry()
        else:
            return
        center = geometry.center()
        self.move(center.x() - self.width() // 2, center.y() - self.height() // 2)

    def start(self) -> "JudgePopup":
        self.show()
        self.raise_()
        self._arm_timer.start()
        return self

    def _arm(self) -> None:
        self._armed = True

    def eventFilter(self, obj, event):
        if self._armed and event.type() in (QEvent.MouseButtonPress, QEvent.MouseButtonDblClick):
            self.close()
        return False

    def closeEvent(self, event):
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        super().closeEvent(event)


def show_judge_popup(text: str, color: str, parent: QWidget = None,
                     previous: QWidget = None) -> JudgePopup:
    """关闭上一次的提示窗并显示新的判定结果。"""
    if previous is not None:
        try:
            previous.close()
        except RuntimeError:
            pass
    return JudgePopup(text, color, parent).start()
