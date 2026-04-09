# -*- coding: utf-8 -*-
"""
测量类型选择弹窗
在开始测量前让用户选择测量类型：旋转测量或垂直测量
"""
from PyQt5.QtWidgets import QDialog, QWidget, QHBoxLayout, QLabel, QPushButton, QSpacerItem, QSizePolicy
from PyQt5.QtCore import Qt, QPoint
from PyQt5 import uic
from ui.theme import get_base_stylesheet
import os


class MeasureTypeDialog(QDialog):
    """测量类型选择弹窗"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.measure_type = None  # 用于存储用户选择的测量类型
        self.vertical_distance = None  # 用于存储垂直测量距离
        self.dragging = False  # 拖动状态
        self.drag_position = QPoint()  # 拖动位置

        # 加载UI文件
        ui_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ui", "measure_type_dialog.ui")
        uic.loadUi(ui_path, self)

        # 应用深色主题样式
        self.setStyleSheet(get_base_stylesheet())

        # 设置窗口标志，隐藏默认标题栏
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)

        # 设置为模态对话框
        self.setModal(True)

        # 设置对话框固定大小（与UI文件一致）
        self.setFixedSize(500, 350)

        # 创建标题栏（设置父对象为self）
        self.title_widget = self._create_title_bar()
        self.title_widget.setParent(self)
        self.title_widget.setGeometry(0, 0, 500, 35)

        # 调整原有部件位置（基于UI文件的geometry，y坐标下移35像素给标题栏留空间）
        # 标题标签
        self.label_title.setParent(self)
        self.label_title.setGeometry(50, 55, 400, 50)
        # 旋转测量按钮
        self.pushButton_rotation.setParent(self)
        self.pushButton_rotation.setGeometry(50, 125, 180, 180)
        # 垂直测量按钮
        self.pushButton_vertical.setParent(self)
        self.pushButton_vertical.setGeometry(270, 125, 180, 140)
        # 垂直测量距离输入框
        self.lineEdit_vertical_distance.setParent(self)
        self.lineEdit_vertical_distance.setGeometry(270, 275, 180, 30)

        # 连接按钮信号
        self.pushButton_rotation.clicked.connect(self._on_rotation_clicked)
        self.pushButton_vertical.clicked.connect(self._on_vertical_clicked)

    def mousePressEvent(self, event):
        """鼠标按下事件"""
        if event.button() == Qt.LeftButton:
            # 检查是否在标题栏区域
            if event.pos().y() <= 35:
                self.dragging = True
                self.drag_position = event.globalPos() - self.frameGeometry().topLeft()
                event.accept()

    def mouseMoveEvent(self, event):
        """鼠标移动事件"""
        if event.buttons() == Qt.LeftButton and self.dragging:
            self.move(event.globalPos() - self.drag_position)
            event.accept()

    def mouseReleaseEvent(self, event):
        """鼠标释放事件"""
        if event.button() == Qt.LeftButton:
            self.dragging = False

    def _on_rotation_clicked(self):
        """旋转测量按钮点击"""
        self.measure_type = "rotation"
        self.vertical_distance = None  # 旋转测量不需要距离
        self.accept()

    def _on_vertical_clicked(self):
        """垂直测量按钮点击"""
        # 获取输入的距离值
        distance_text = self.lineEdit_vertical_distance.text().strip()

        if not distance_text:
            # 如果没有输入,tip用户输入距离
            self.lineEdit_vertical_distance.setPlaceholderText("请输入垂直测量距离")
            return
        else:
            try:
                self.vertical_distance = int(float(distance_text) * 360 / 1.8 * 8)
            except ValueError:
                # 提示用户输入有效值
                self.lineEdit_vertical_distance.setPlaceholderText("请输入有效距离值")
                return

        self.measure_type = "vertical"
        self.accept()

    def get_measure_type(self):
        """获取用户选择的测量类型"""
        return self.measure_type

    def get_vertical_distance(self):
        """获取垂直测量距离"""
        return self.vertical_distance

    def _create_title_bar(self):
        """创建自定义标题栏"""
        title_widget = QWidget()
        title_widget.setObjectName("title_widget")
        title_widget.setStyleSheet("""
            QWidget#title_widget {
                background-color: #f0f0f0;
                border-bottom: 1px solid #cccccc;
            }
        """)
        title_layout = QHBoxLayout(title_widget)
        title_layout.setContentsMargins(10, 5, 10, 5)

        # 标题
        title_label = QLabel("选择测量类型")
        title_label.setStyleSheet("""
            QLabel {
                font-size: 16px;
                font-weight: bold;
                color: #333;
            }
        """)

        # 弹性空间
        spacer = QSpacerItem(40, 20, QSizePolicy.Expanding, QSizePolicy.Minimum)

        # 关闭按钮
        close_button = QPushButton("×")
        close_button.setFixedSize(30, 30)
        close_button.setCursor(Qt.PointingHandCursor)
        close_button.setStyleSheet("""
            QPushButton {
                background-color: #f44336;
                color: white;
                border: none;
                border-radius: 3px;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #d32f2f;
            }
        """)
        close_button.clicked.connect(self.reject)

        title_layout.addWidget(title_label)
        title_layout.addSpacerItem(spacer)
        title_layout.addWidget(close_button)

        # 启用标题栏拖动
        title_widget.mousePressEvent = self._title_mouse_press
        title_widget.mouseMoveEvent = self._title_mouse_move
        title_widget.mouseReleaseEvent = self._title_mouse_release

        return title_widget

    def _title_mouse_press(self, event):
        """标题栏鼠标按下"""
        if event.button() == Qt.LeftButton:
            self.dragging = True
            self.drag_position = event.globalPos() - self.frameGeometry().topLeft()

    def _title_mouse_move(self, event):
        """标题栏鼠标移动"""
        if event.buttons() == Qt.LeftButton and self.dragging:
            self.move(event.globalPos() - self.drag_position)

    def _title_mouse_release(self, event):
        """标题栏鼠标释放"""
        if event.button() == Qt.LeftButton:
            self.dragging = False
