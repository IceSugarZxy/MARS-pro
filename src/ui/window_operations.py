# -*- coding: utf-8 -*-
"""
窗口操作功能模块
提供窗口拖动、最小化、最大化等操作功能
"""

from PyQt5.QtCore import Qt, QPoint, QObject
from PyQt5.QtWidgets import QWidget


class WindowOperations(QObject):
    """窗口操作功能类"""
    
    def __init__(self, window):
        """
        初始化窗口操作功能
        
        Args:
            window: 需要添加操作功能的窗口对象
        """
        super().__init__()
        self.window = window
        self.dragging = False
        self.drag_position = QPoint()
        
        # 设置窗口属性
        self.window.setWindowFlags(Qt.FramelessWindowHint)
        
        # 安装事件过滤器，实现窗口上方拖动
        self.window.installEventFilter(self)
    
    def show_window(self):
        """显示窗口"""
        self.window.show()
    
    def eventFilter(self, obj, event):
        """事件过滤器，处理窗口上方拖动"""
        if event.type() == event.MouseButtonPress:
            return self._handle_mouse_press(event)
        elif event.type() == event.MouseMove:
            return self._handle_mouse_move(event)
        elif event.type() == event.MouseButtonRelease:
            return self._handle_mouse_release(event)
        
        return False
    
    def _handle_mouse_press(self, event):
        """处理鼠标按下事件"""
        if event.button() == Qt.LeftButton:
            # 检查是否在窗口上方区域（顶部100像素）
            if event.pos().y() <= 100:
                self.dragging = True
                self.drag_position = event.globalPos() - self.window.frameGeometry().topLeft()
                return True
        return False
    
    def _handle_mouse_move(self, event):
        """处理鼠标移动事件"""
        if event.buttons() == Qt.LeftButton and self.dragging:
            self.window.move(event.globalPos() - self.drag_position)
            return True
        return False
    
    def _handle_mouse_release(self, event):
        """处理鼠标释放事件"""
        if event.button() == Qt.LeftButton and self.dragging:
            self.dragging = False
            return True
        return False
    
    def minimize_window(self):
        """最小化窗口"""
        self.window.showMinimized()
    
    def maximize_window(self):
        """最大化/还原窗口"""
        if self.window.isMaximized():
            self.window.showNormal()
        else:
            self.window.showMaximized()
    
    def close_window(self):
        """关闭窗口"""
        self.window.close()


def create_window_operations(window):
    """
    创建窗口操作功能的便捷函数
    
    Args:
        window: 窗口对象
    
    Returns:
        WindowOperations: 窗口操作对象
    """
    return WindowOperations(window)