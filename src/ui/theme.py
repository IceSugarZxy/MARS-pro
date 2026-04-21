# -*- coding: utf-8 -*-
"""
MARS 浅色工业风主题样式系统
提供统一的浅灰+蓝色调视觉风格
"""

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QPalette

# ============================================================================
# 颜色系统 - 浅色主题
# ============================================================================

# 主色系
COLOR_BG_DARKEST = "#f5f5f5"     # 最深背景（页面背景）
COLOR_BG_DARK = "#ffffff"         # 白色背景（卡片/面板）
COLOR_BG_PANEL = "#fafafa"        # 面板背景
COLOR_BG_PANEL_LIGHT = "#ffffff"   # 浅面板背景
COLOR_BORDER = "#e0e0e0"          # 边框色
COLOR_BORDER_LIGHT = "#ebebeb"    # 浅边框

# 强调色
COLOR_PRIMARY = "#3498db"         # 主蓝色
COLOR_PRIMARY_HOVER = "#2980b9"   # 主蓝色悬停
COLOR_PRIMARY_LIGHT = "#5dade2"  # 主蓝色浅色
COLOR_SUCCESS = "#27ae60"         # 成功绿
COLOR_SUCCESS_HOVER = "#1e8449"   # 成功绿悬停
COLOR_WARNING = "#f39c12"         # 警告橙
COLOR_WARNING_HOVER = "#d68910"   # 警告橙悬停
COLOR_DANGER = "#e74c3c"          # 危险红
COLOR_DANGER_HOVER = "#c0392b"    # 危险红悬停
COLOR_PURPLE = "#9b59b6"          # 紫色
COLOR_PURPLE_HOVER = "#8e44ad"    # 紫色悬停
COLOR_TEAL = "#16a085"            # 青色
COLOR_TEAL_HOVER = "#138d75"      # 青色悬停
COLOR_GRAY = "#7f8c8d"            # 中性灰
COLOR_GRAY_LIGHT = "#95a5a6"      # 浅灰
COLOR_GRAY_DARK = "#5d6d7e"       # 深灰

# 文字色
COLOR_TEXT_PRIMARY = "#2c3e50"    # 主要文字
COLOR_TEXT_SECONDARY = "#7f8c8d"  # 次要文字
COLOR_TEXT_MUTED = "#b0b0b0"      # 弱化文字
COLOR_TEXT_DARK = "#2c3e50"       # 深色文字

# ============================================================================
# 字体
# ============================================================================
FONT_FAMILY = "Microsoft YaHei, 黑体, SimHei, Arial"
FONT_SIZE_XL = "16px"
FONT_SIZE_L = "14px"
FONT_SIZE_M = "13px"
FONT_SIZE_S = "12px"
FONT_SIZE_XS = "11px"

# ============================================================================
# 间距
# ============================================================================
PADDING_XL = "16px"
PADDING_L = "12px"
PADDING_M = "8px"
PADDING_S = "4px"
BORDER_RADIUS = "6px"
BORDER_RADIUS_L = "8px"
BORDER_RADIUS_XL = "10px"

# ============================================================================
# 样式表
# ============================================================================

def get_base_stylesheet() -> str:
    """获取基础样式表（所有窗口共享）"""
    return f"""
    QWidget {{
        background-color: {COLOR_BG_DARK};
        color: {COLOR_TEXT_PRIMARY};
        font-family: {FONT_FAMILY};
        font-size: {FONT_SIZE_M};
    }}

    QMainWindow {{
        background-color: {COLOR_BG_DARKEST};
    }}

    QDialog {{
        background-color: {COLOR_BG_DARK};
    }}

    /* 标签 */
    QLabel {{
        background-color: transparent;
        color: {COLOR_TEXT_PRIMARY};
        font-size: {FONT_SIZE_M};
    }}

    QLabel#titleLabel {{
        font-size: {FONT_SIZE_XL};
        font-weight: bold;
        color: {COLOR_TEXT_PRIMARY};
    }}

    QLabel#subtitleLabel {{
        font-size: {FONT_SIZE_S};
        color: {COLOR_TEXT_SECONDARY};
    }}

    /* 输入框 */
    QLineEdit, QTextEdit, QPlainTextEdit {{
        background-color: #ffffff;
        color: #000000;
        border: 1px solid {COLOR_BORDER};
        border-radius: {BORDER_RADIUS};
        padding: {PADDING_S} {PADDING_M};
        selection-background-color: {COLOR_PRIMARY};
        font-size: {FONT_SIZE_M};
    }}

    QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
        border: 1px solid {COLOR_PRIMARY};
    }}

    QLineEdit:read-only {{
        background-color: #ffffff;
        color: #000000;
    }}

    /* 按钮 */
    QPushButton {{
        background-color: {COLOR_BG_PANEL_LIGHT};
        color: {COLOR_TEXT_PRIMARY};
        border: 1px solid {COLOR_BORDER};
        border-radius: {BORDER_RADIUS};
        padding: {PADDING_M} {PADDING_L};
        font-size: {FONT_SIZE_M};
        min-height: 28px;
    }}

    QPushButton:hover {{
        background-color: {COLOR_BORDER} !important;
    }}

    QPushButton:pressed {{
        background-color: {COLOR_BG_DARK};
    }}

    QPushButton:disabled {{
        background-color: {COLOR_BG_DARK};
        color: {COLOR_TEXT_MUTED};
        border: 1px solid {COLOR_BG_DARKEST};
    }}

    /* 主操作按钮（蓝色） */
    QPushButton#btnPrimary {{
        background-color: {COLOR_PRIMARY};
        color: #ffffff;
        border: none;
    }}

    QPushButton#btnPrimary:hover {{
        background-color: {COLOR_PRIMARY_HOVER};
    }}

    /* 成功按钮（绿色） */
    QPushButton#btnSuccess {{
        background-color: {COLOR_SUCCESS};
        color: #ffffff;
        border: none;
    }}

    QPushButton#btnSuccess:hover {{
        background-color: {COLOR_SUCCESS_HOVER};
    }}

    /* 警告按钮（橙色） */
    QPushButton#btnWarning {{
        background-color: {COLOR_WARNING};
        color: #ffffff;
        border: none;
    }}

    QPushButton#btnWarning:hover {{
        background-color: {COLOR_WARNING_HOVER};
    }}

    /* 危险按钮（红色） */
    QPushButton#btnDanger {{
        background-color: {COLOR_DANGER};
        color: #ffffff;
        border: none;
    }}

    QPushButton#btnDanger:hover {{
        background-color: {COLOR_DANGER_HOVER};
    }}

    /* 紫色按钮 */
    QPushButton#btnPurple {{
        background-color: {COLOR_PURPLE};
        color: #ffffff;
        border: none;
    }}

    QPushButton#btnPurple:hover {{
        background-color: {COLOR_PURPLE_HOVER};
    }}

    /* 青色按钮 */
    QPushButton#btnTeal {{
        background-color: {COLOR_TEAL};
        color: #ffffff;
        border: none;
    }}

    QPushButton#btnTeal:hover {{
        background-color: {COLOR_TEAL_HOVER};
    }}

    /* 导航按钮 */
    QPushButton#btnNav {{
        background-color: transparent;
        color: {COLOR_TEXT_SECONDARY};
        border: none;
        text-align: left;
        padding: {PADDING_M} {PADDING_L};
        border-radius: 0;
        min-height: 40px;
    }}

    QPushButton#btnNav:hover {{
        background-color: {COLOR_BG_PANEL};
        color: {COLOR_TEXT_PRIMARY};
    }}

    QPushButton#btnNav:selected {{
        background-color: {COLOR_BG_PANEL};
        color: {COLOR_PRIMARY};
        border-left: 3px solid {COLOR_PRIMARY};
    }}

    /* 表格 */
    QTableWidget, QTableView {{
        background-color: {COLOR_BG_DARK};
        color: {COLOR_TEXT_PRIMARY};
        border: 1px solid {COLOR_BORDER};
        gridline-color: {COLOR_BORDER};
        font-size: {FONT_SIZE_M};
    }}

    QTableWidget::item, QTableView::item {{
        padding: {PADDING_S};
    }}

    QTableWidget::item:selected, QTableView::item:selected {{
        background-color: {COLOR_PRIMARY};
        color: #ffffff;
    }}

    QHeaderView::section {{
        background-color: {COLOR_BG_PANEL};
        color: {COLOR_TEXT_PRIMARY};
        padding: {PADDING_M};
        border: none;
        border-bottom: 2px solid {COLOR_PRIMARY};
        font-weight: bold;
    }}

    /* 滚动条 */
    QScrollBar:vertical {{
        background-color: {COLOR_BG_DARK};
        width: 10px;
        border: none;
    }}

    QScrollBar::handle:vertical {{
        background-color: {COLOR_BORDER};
        border-radius: 5px;
        min-height: 20px;
    }}

    QScrollBar::handle:vertical:hover {{
        background-color: {COLOR_GRAY};
    }}

    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        border: none;
        height: 0px;
    }}

    QScrollBar:horizontal {{
        background-color: {COLOR_BG_DARK};
        height: 10px;
        border: none;
    }}

    QScrollBar::handle:horizontal {{
        background-color: {COLOR_BORDER};
        border-radius: 5px;
        min-width: 20px;
    }}

    /* 工具提示 */
    QToolTip {{
        background-color: {COLOR_BG_PANEL};
        color: {COLOR_TEXT_PRIMARY};
        border: 1px solid {COLOR_BORDER};
        padding: {PADDING_S};
        font-size: {FONT_SIZE_S};
    }}

    /* 消息框 */
    QMessageBox {{
        background-color: {COLOR_BG_DARK};
    }}

    /* 进度条 */
    QProgressBar {{
        background-color: {COLOR_BG_PANEL};
        border: none;
        border-radius: {BORDER_RADIUS};
        height: 8px;
        text-align: center;
    }}

    QProgressBar::chunk {{
        background-color: {COLOR_PRIMARY};
        border-radius: {BORDER_RADIUS};
    }}

    /* 分隔符 */
    QSeparator {{
        background-color: {COLOR_BORDER};
    }}

    /* 组框架 */
    QGroupBox {{
        background-color: {COLOR_BG_PANEL};
        border: 1px solid {COLOR_BORDER};
        border-radius: {BORDER_RADIUS_L};
        padding: {PADDING_L};
        margin-top: {PADDING_M};
        font-weight: bold;
    }}

    QGroupBox::title {{
        color: {COLOR_TEXT_PRIMARY};
        subcontrol-origin: margin;
        subcontrol-position: top left;
        left: {PADDING_M};
        padding: 0 {PADDING_S};
    }}

    /* 选项卡 */
    QTabWidget::pane {{
        background-color: {COLOR_BG_DARK};
        border: 1px solid {COLOR_BORDER};
        border-radius: {BORDER_RADIUS};
    }}

    QTabBar::tab {{
        background-color: {COLOR_BG_PANEL};
        color: {COLOR_TEXT_SECONDARY};
        padding: {PADDING_M} {PADDING_L};
        border: none;
        border-top-left-radius: {BORDER_RADIUS};
        border-top-right-radius: {BORDER_RADIUS};
    }}

    QTabBar::tab:selected {{
        background-color: {COLOR_BG_DARK};
        color: {COLOR_TEXT_PRIMARY};
        border-bottom: 2px solid {COLOR_PRIMARY};
    }}

    QTabBar::tab:hover {{
        background-color: {COLOR_BG_PANEL_LIGHT};
    }}

    /* ===== MainPanel 侧边栏导航样式（浅色主题） ===== */
    QWidget#nav_panel {{
        background-color: {COLOR_BG_DARK};
        border-right: 1px solid {COLOR_BORDER};
    }}

    QWidget#nav_header {{
        background-color: {COLOR_BG_DARK};
        border-bottom: 1px solid {COLOR_BORDER};
    }}

    QLabel#nav_title {{
        font-size: 32px;
        font-weight: bold;
        color: {COLOR_PRIMARY};
        background: transparent;
        border: none;
    }}

    QLabel#nav_subtitle {{
        font-size: 16px;
        color: {COLOR_TEXT_SECONDARY};
        background: transparent;
        border: none;
    }}

    /* 导航按钮 - native QWidget */
    QWidget#nav_button {{
        background-color: transparent;
        border: none;
        border-radius: {BORDER_RADIUS};
    }}
    QWidget#nav_button:hover {{
        background-color: {COLOR_BG_PANEL};
    }}
    QWidget#nav_button:selected {{
        background-color: {COLOR_PRIMARY_LIGHT};
    }}

    /* 导航按钮 - 具体按钮 */
    QWidget#nav_button_measure, QWidget#nav_button_serial, QWidget#nav_button_position,
    QWidget#nav_button_history, QWidget#nav_button_compare {{
        background-color: transparent;
        border: none;
    }}
    QWidget#nav_button_measure:hover, QWidget#nav_button_serial:hover,
    QWidget#nav_button_position:hover, QWidget#nav_button_history:hover,
    QWidget#nav_button_compare:hover {{
        background-color: {COLOR_BG_PANEL};
    }}
    QWidget#nav_button_measure:selected, QWidget#nav_button_serial:selected,
    QWidget#nav_button_position:selected, QWidget#nav_button_history:selected,
    QWidget#nav_button_compare:selected {{
        background-color: {COLOR_PRIMARY_LIGHT};
    }}

    /* 导航按钮文字 */
    QLabel#nav_text_measure, QLabel#nav_text_serial, QLabel#nav_text_position,
    QLabel#nav_text_history, QLabel#nav_text_compare {{
        color: {COLOR_TEXT_PRIMARY};
        background: transparent;
        border: none;
        font-size: 18px;
    }}

    /* 导航图标 */
    QLabel#nav_icon {{
        color: {COLOR_PRIMARY};
        background: transparent;
        border: none;
        font-size: 14px;
    }}
    QLabel#nav_icon_serial {{
        color: {COLOR_WARNING};
        background: transparent;
        border: none;
        font-size: 14px;
    }}
    QLabel#nav_icon_position {{
        color: {COLOR_PURPLE};
        background: transparent;
        border: none;
        font-size: 14px;
    }}
    QLabel#nav_icon_history {{
        color: {COLOR_SUCCESS};
        background: transparent;
        border: none;
        font-size: 14px;
    }}
    QLabel#nav_icon_compare {{
        color: {COLOR_DANGER};
        background: transparent;
        border: none;
        font-size: 14px;
    }}

    /* 导航标签 */
    QLabel#nav_label {{
        color: {COLOR_TEXT_PRIMARY};
        background: transparent;
        border: none;
        font-size: 13px;
    }}

    /* 导航底部 */
    QWidget#nav_footer {{
        background-color: {COLOR_BG_DARK};
        border-top: 1px solid {COLOR_BORDER};
    }}

    QLabel#serial_status_indicator {{
        background-color: {COLOR_DANGER};
        border-radius: 5px;
        border: none;
        min-width: 10px;
        max-width: 10px;
        min-height: 10px;
        max-height: 10px;
    }}

    QLabel#serial_status_label {{
        color: {COLOR_TEXT_SECONDARY};
        background: transparent;
        border: none;
        font-size: 10px;
    }}

    /* 内容区 */
    QWidget#content_panel {{
        background-color: {COLOR_BG_DARKEST};
    }}

    QLabel#panel_title {{
        font-size: 20px;
        font-weight: bold;
        color: {COLOR_TEXT_PRIMARY};
        background: transparent;
        border: none;
    }}

    /* 通用卡片/面板 */
    QFrame#card {{
        background-color: {COLOR_BG_DARK};
        border: 1px solid {COLOR_BORDER};
        border-radius: {BORDER_RADIUS_L};
    }}

    /* 数据比对结果文本 - 放大字体 */
    QTextEdit#result1_text, QTextEdit#result2_text {{
        font-size: 26px;
    }}

    /* 测试配置面板按钮 - 悬停效果（覆盖内联样式） */
    QPushButton#btn_offset:hover, QPushButton#btn_zeroing:hover, QPushButton#btn_press_z:hover,
    QPushButton#btn_left_x:hover, QPushButton#btn_right_x:hover, QPushButton#btn_test_pos:hover,
    QPushButton#btn_suspend:hover, QPushButton#btn_test_pos_save:hover, QPushButton#btn_suspend_save:hover,
    QToolButton#btn_test_edit_scheme:hover, QToolButton#btn_suspend_edit_scheme:hover {{
        background-color: rgb(224,224,224) !important;
    }}

    /* 测量面板按钮 - 悬停效果（覆盖内联样式） */
    QPushButton#btn_start_rotation:hover, QPushButton#btn_stop_rotation:hover,
    QPushButton#btn_zeroing:hover, QPushButton#btn_offset:hover,
    QPushButton#btn_test_position:hover, QPushButton#btn_suspend_position:hover,
    QPushButton#btn_up:hover, QPushButton#btn_down:hover, QPushButton#btn_left:hover,
    QPushButton#btn_right:hover, QPushButton#btn_save:hover {{
        background-color: rgb(224,224,224) !important;
    }}
    """


def get_card_stylesheet(bg_color: str = None) -> str:
    """获取卡片样式"""
    bg = bg_color or COLOR_BG_PANEL
    return f"""
    QFrame#card {{
        background-color: {bg};
        border: 1px solid {COLOR_BORDER};
        border-radius: {BORDER_RADIUS_L};
    }}
    """


def get_panel_stylesheet() -> str:
    """获取面板样式"""
    return f"""
    QFrame#panel {{
        background-color: {COLOR_BG_PANEL};
        border: 1px solid {COLOR_BORDER};
        border-radius: {BORDER_RADIUS};
    }}
    """


# ============================================================================
# 调色板（用于 setPalette）
# ============================================================================

def get_dark_palette() -> QPalette:
    """获取深色调色板"""
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(COLOR_BG_DARKEST))
    palette.setColor(QPalette.WindowText, QColor(COLOR_TEXT_PRIMARY))
    palette.setColor(QPalette.Base, QColor(COLOR_BG_PANEL))
    palette.setColor(QPalette.AlternateBase, QColor(COLOR_BG_PANEL_LIGHT))
    palette.setColor(QPalette.ToolTipBase, QColor(COLOR_BG_PANEL))
    palette.setColor(QPalette.ToolTipText, QColor(COLOR_TEXT_PRIMARY))
    palette.setColor(QPalette.Text, QColor(COLOR_TEXT_PRIMARY))
    palette.setColor(QPalette.Button, QColor(COLOR_BG_PANEL_LIGHT))
    palette.setColor(QPalette.ButtonText, QColor(COLOR_TEXT_PRIMARY))
    palette.setColor(QPalette.BrightText, QColor(255, 255, 255))
    palette.setColor(QPalette.Highlight, QColor(COLOR_PRIMARY))
    palette.setColor(QPalette.HighlightedTexts, QColor(255, 255, 255))
    palette.setColor(QPalette.Disabled, QPalette.Text, QColor(COLOR_TEXT_MUTED))
    palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(COLOR_TEXT_MUTED))
    return palette
