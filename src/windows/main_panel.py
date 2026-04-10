# -*- coding: utf-8 -*-
"""
MARS 主面板 - 单窗口 + 侧边栏导航架构
"""

import os
from PyQt5.QtWidgets import QMainWindow, QWidget, QStackedWidget, QHBoxLayout, QVBoxLayout, QLabel, QFrame
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5 import uic
from core.logger import get_logger
from ui.theme import get_base_stylesheet, COLOR_BORDER

logger = get_logger('MainPanel')


class MainPanel(QMainWindow):
    """主面板 - 单窗口架构"""

    # 信号：切换到指定面板
    signal_switch_to = pyqtSignal(str)

    def __init__(self):
        super().__init__()

        # 加载UI
        ui_file_path = os.path.join(os.path.dirname(__file__), "..", "ui", "main_window.ui")
        uic.loadUi(ui_file_path, self)

        # 应用浅色主题样式
        self.setStyleSheet(get_base_stylesheet())

        # 创建子面板（延迟导入避免循环引用）
        self._panels = {}
        self._active_panel = None

        # 构建布局
        self._setup_ui()

        # 默认显示测量面板
        self._switch_panel("measure")

    def _setup_ui(self):
        """构建界面"""
        central_widget = self.findChild(QWidget, "centralwidget")
        main_layout = central_widget.layout()

        # 侧边栏
        self.sidebar = self._create_sidebar()
        sidebar_container = QWidget()
        sidebar_container.setObjectName("nav_panel")
        sidebar_container.setFixedWidth(200)
        sidebar_container.setLayout(self.sidebar)

        # 内容区
        self.stacked_widget = QStackedWidget()
        self.stacked_widget.setObjectName("content_panel")

        # 添加入主布局
        main_layout.addWidget(sidebar_container)
        main_layout.addWidget(self.stacked_widget, 1)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 状态栏
        self._setup_statusbar()

        # 加载所有面板
        self._load_panels()

    def _create_sidebar(self):
        """创建侧边栏"""
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        # 标题区
        title_widget = QWidget()
        title_widget.setObjectName("nav_header")
        title_layout = QVBoxLayout(title_widget)
        title_layout.setContentsMargins(16, 20, 16, 16)
        title_layout.setSpacing(4)

        title_label = QLabel("MARS")
        title_label.setObjectName("nav_title")
        title_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        subtitle_label = QLabel("旋转体表磁测量分析系统")
        subtitle_label.setObjectName("nav_subtitle")
        subtitle_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        title_layout.addWidget(title_label)
        title_layout.addWidget(subtitle_label)
        title_layout.addStretch()

        # 分隔线
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFrameShadow(QFrame.Plain)
        sep.setStyleSheet(f"background-color: {COLOR_BORDER}; border: none; height: 1px;")

        layout.addWidget(title_widget)
        layout.addWidget(sep)

        # 导航按钮
        self.nav_buttons = {}
        nav_items = [
            ("measure", "测量界面", "▶", "nav_icon"),
            ("serial", "串口设置", "⚙", "nav_icon_serial"),
            ("position", "位置控制", "◎", "nav_icon_position"),
            ("history", "历史数据", "☰", "nav_icon_history"),
            ("compare", "数据比对", "⚡", "nav_icon_compare"),
        ]
        for item_id, item_text, item_icon, icon_obj_name in nav_items:
            btn = self._create_nav_button(item_id, item_text, item_icon, icon_obj_name)
            self.nav_buttons[item_id] = btn
            layout.addWidget(btn)

        layout.addStretch()

        # 底部状态区
        footer_widget = self._create_footer()
        layout.addWidget(footer_widget)

        return layout

    def _create_nav_button(self, panel_id, text, icon, icon_obj_name):
        """创建导航按钮"""
        btn = QWidget()
        btn.setObjectName("nav_button")
        btn.setCursor(Qt.PointingHandCursor)

        layout = QHBoxLayout(btn)
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(12)

        icon_label = QLabel(icon)
        icon_label.setObjectName(icon_obj_name)
        icon_label.setFixedWidth(20)

        text_label = QLabel(text)
        text_label.setObjectName("nav_label")

        layout.addWidget(icon_label)
        layout.addWidget(text_label, 1)

        btn.mousePressEvent = lambda e, pid=panel_id: self._on_nav_clicked(pid)

        return btn

    def _create_footer(self):
        """创建底部状态区"""
        footer = QWidget()
        footer.setObjectName("nav_footer")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(16, 10, 16, 10)
        footer_layout.setSpacing(8)

        # 串口状态指示灯
        serial_indicator = QLabel("●")
        serial_indicator.setObjectName("serial_status_indicator")
        serial_indicator.setStyleSheet("color: #e74c3c;")

        serial_label = QLabel("未连接")
        serial_label.setObjectName("serial_status_label")

        footer_layout.addWidget(serial_indicator)
        footer_layout.addWidget(serial_label, 1)

        self._footer_serial_indicator = serial_indicator
        self._footer_serial_label = serial_label

        return footer

    def _on_nav_clicked(self, panel_id):
        """导航按钮点击"""
        self._switch_panel(panel_id)

    def _switch_panel(self, panel_id):
        """切换到指定面板"""
        if panel_id not in self._panels:
            return

        # 更新按钮状态
        for pid, btn in self.nav_buttons.items():
            if pid == panel_id:
                btn.setProperty("selected", True)
            else:
                btn.setProperty("selected", False)
            btn.style().unpolish(btn)
            btn.style().polish(btn)

        # 切换面板
        panel = self._panels[panel_id]
        self.stacked_widget.setCurrentWidget(panel)
        self._active_panel = panel_id

        logger.debug(f"切换到面板: {panel_id}")

    def _load_panels(self):
        """加载所有面板"""
        from windows.measure_panel import MeasurePanel
        from windows.serial_panel import SerialPanel
        from windows.position_panel import PositionPanel
        from windows.history_panel import HistoryPanel
        from windows.compare_panel import ComparePanel

        # 创建面板实例
        panels = [
            ("measure", MeasurePanel()),
            ("serial", SerialPanel()),
            ("position", PositionPanel()),
            ("history", HistoryPanel()),
            ("compare", ComparePanel()),
        ]

        for panel_id, panel in panels:
            self._panels[panel_id] = panel
            self.stacked_widget.addWidget(panel)

        logger.info(f"已加载 {len(panels)} 个面板")

    def _setup_statusbar(self):
        """设置状态栏"""
        statusbar = self.statusBar()

        # 当前位置
        pos_label = QLabel("位置: X=-- Z=--")
        pos_label.setObjectName("status_position_label")

        statusbar.addPermanentWidget(pos_label)

        self._status_position_label = pos_label

    def update_serial_status(self, connected, port=""):
        """更新串口状态"""
        if connected:
            self._footer_serial_indicator.setStyleSheet("color: #27ae60;")
            self._footer_serial_label.setText(f"已连接 {port}")
        else:
            self._footer_serial_indicator.setStyleSheet("color: #e74c3c;")
            self._footer_serial_label.setText("未连接")

    def update_position(self, x, z):
        """更新位置显示"""
        self._status_position_label.setText(f"位置: X={x} Z={z}")

    def get_panel(self, panel_id):
        """获取指定面板"""
        return self._panels.get(panel_id)

    def get_active_panel(self):
        """获取当前活动面板ID"""
        return self._active_panel
