# -*- coding: utf-8 -*-
"""
绘图窗口模块
实现绘图窗口的初始化和相关功能设置
"""

import os
import numpy as np
import pyqtgraph as pg
from pyqtgraph import mkPen
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QSizePolicy
from PyQt5.QtCore import pyqtSignal, Qt
from PyQt5.QtGui import QPen, QFont
from core.logger import get_logger

logger = get_logger('PlotWindow')


class PlotWindow(QWidget):
    """绘图窗口类"""
    
    # 信号定义
    plot_double_clicked = pyqtSignal()  # 绘图区域双击信号
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.plot_widget = None
        self.curve = None
        self.mag_data = []  # 磁场数据
        self.angle_data = []  # 角度数据
        
        self._init_plot_widget()
        self._setup_plot_layout()
    
    def _init_plot_widget(self):
        """初始化绘图控件"""
        # 创建绘图控件
        self.plot_widget = pg.PlotWidget()
        
        # 设置背景色为白色
        self.plot_widget.setBackground('w')
        
        # 显示网格
        self.plot_widget.showGrid(x=True, y=True, alpha=0.5)
        
        # 禁用自动范围调整
        self.plot_widget.enableAutoRange(False, False)
        
        # 启用鼠标交互
        self.plot_widget.plotItem.getViewBox().setMouseEnabled(x=True, y=True)
        
        # 隐藏缩放按钮
        self.plot_widget.plotItem.hideButtons()
        
        # 创建曲线
        self.curve = self.plot_widget.plot(pen=mkPen('r', width=1))
        
        # 设置初始显示范围
        self.plot_widget.setXRange(0, 360)
        self.plot_widget.setYRange(-70, 70)
        
        # 连接双击事件
        self.plot_widget.scene().sigMouseClicked.connect(self._on_plot_double_click)
        
        # 连接视图范围变化信号，实现自适应刻度
        self.plot_widget.plotItem.getViewBox().sigRangeChanged.connect(self._on_view_range_changed)
        
        # 初始化自适应刻度
        self._update_adaptive_ticks()
    
    def _setup_x_axis(self):
        """设置X轴固定刻度"""
        # 关键位置：从-3600到+3600，间隔90度
        key_positions = list(range(-3600, 3601, 90))
        
        # 生成刻度位置和标签
        tick_positions = []
        tick_labels = []
        
        # 添加关键位置
        for pos in key_positions:
            tick_positions.append(pos)
            tick_labels.append(f"{pos}°")
        
        # 设置X轴刻度
        ticks_x = [[pos, label] for pos, label in zip(tick_positions, tick_labels)]
        pw_x = self.plot_widget.plotItem.getAxis('bottom')
        pw_x.setTicks([ticks_x])
        pw_x.setPen(QPen(Qt.transparent))  # 隐藏x轴轴线，保留刻度
        pw_x.setStyle(tickFont=QFont('Alibaba PuHuiTi', 10), tickTextOffset=10, tickLength=5)
    
    def _setup_y_axis(self):
        """设置Y轴刻度"""
        y_num = list(range(-700, 700, 7))
        y_str = [f'{abs(y)}' if y != 0 else '0' for y in y_num]
        
        ticks_y = [[i, j] for i, j in zip(y_num, y_str)]
        pw_y = self.plot_widget.plotItem.getAxis('left')
        pw_y.setTicks([ticks_y])
        pw_y.setPen(QPen(Qt.transparent))  # 隐藏y轴轴线，保留刻度
        pw_y.setStyle(tickFont=QFont('Alibaba PuHuiTi', 10), tickTextOffset=10, tickLength=5)
    
    def _setup_plot_layout(self):
        """设置绘图布局"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # 设置绘图控件的大小策略，使其可以随窗口大小变化
        self.plot_widget.setSizePolicy(
            QSizePolicy.Expanding, 
            QSizePolicy.Expanding
        )
        layout.addWidget(self.plot_widget)
    
    def _on_plot_double_click(self, event):
        """处理绘图区域双击事件"""
        if event.double():
            self.reset_plot_view()
            self.plot_double_clicked.emit()
    
    def _on_view_range_changed(self, view_box, view_range):
        """视图范围变化回调函数"""
        # 延迟更新刻度，避免频繁更新
        from PyQt5.QtCore import QTimer
        QTimer.singleShot(100, self._update_adaptive_ticks)
    
    def _update_adaptive_ticks(self):
        """更新自适应刻度 - 仅Y轴自适应，X轴固定刻度"""
        # 获取当前视图范围
        view_range = self.plot_widget.plotItem.getViewBox().viewRange()
        x_range = view_range[0]  # [x_min, x_max]
        y_range = view_range[1]  # [y_min, y_max]
        
        # 计算Y轴的范围
        y_span = y_range[1] - y_range[0]
        
        # 根据范围大小动态调整Y轴刻度间隔
        y_tick_interval = self._calculate_tick_interval(y_span)
        
        # 设置X轴固定刻度
        self._setup_x_axis()
        
        # 更新Y轴自适应刻度
        self._update_y_axis_ticks(y_range, y_tick_interval)
    
    def _calculate_tick_interval(self, span):
        """根据范围大小计算合适的刻度间隔 - 支持0.01最小分辨率"""
        # 基础间隔，根据范围大小动态调整
        if span <= 0.1:
            return 0.01
        elif span <= 0.5:
            return 0.05
        elif span <= 1:
            return 0.1
        elif span <= 5:
            return 0.5
        elif span <= 10:
            return 1
        elif span <= 20:
            return 2
        elif span <= 50:
            return 5
        elif span <= 100:
            return 10
        elif span <= 200:
            return 20
        elif span <= 500:
            return 50
        elif span <= 1000:
            return 100
        elif span <= 2000:
            return 200
        else:
            return 500
    

    
    def _update_y_axis_ticks(self, y_range, tick_interval):
        """更新Y轴刻度 - 支持小数刻度"""
        y_min, y_max = y_range
        
        # 计算起始刻度位置（支持小数）
        start_tick = (int(y_min // tick_interval)) * tick_interval
        end_tick = (int(y_max // tick_interval) + 1) * tick_interval
        
        # 生成刻度位置和标签
        tick_positions = []
        tick_labels = []
        
        # 使用浮点数步进，支持小数刻度
        current_tick = start_tick
        while current_tick <= end_tick:
            # 格式化标签，根据刻度间隔决定小数位数
            if tick_interval < 0.1:
                label = f"{current_tick:.2f}"  # 两位小数
            elif tick_interval < 1:
                label = f"{current_tick:.1f}"  # 一位小数
            else:
                label = f"{int(current_tick)}"  # 整数
            
            tick_positions.append(current_tick)
            tick_labels.append(label)
            current_tick += tick_interval
        
        # 设置Y轴刻度
        ticks_y = [[pos, label] for pos, label in zip(tick_positions, tick_labels)]
        pw_y = self.plot_widget.plotItem.getAxis('left')
        pw_y.setTicks([ticks_y])
        pw_y.setPen(QPen(Qt.transparent))  # 隐藏y轴轴线，保留刻度
        pw_y.setStyle(tickFont=QFont('Alibaba PuHuiTi', 10), tickTextOffset=10, tickLength=5)
    
    def reset_plot_view(self):
        """重置绘图视图到初始状态"""
        self.plot_widget.setXRange(0, 360)
        self.plot_widget.setYRange(-70, 70)
        # 更新刻度显示
        self._update_adaptive_ticks()
    
    def update_plot(self, angle_data=None, mag_data=None, color='r', auto_y_range=True):
        """更新绘图数据

        Args:
            angle_data: 角度数据列表
            mag_data: 磁场数据列表
            color: 曲线颜色
            auto_y_range: 是否自动调整Y轴范围（基于数据最大最小值）
        """
        if angle_data is not None:
            self.angle_data = angle_data
        if mag_data is not None:
            self.mag_data = mag_data

        if self.angle_data is not None and len(self.angle_data) > 0 and self.mag_data is not None and len(self.mag_data) > 0:
            # 确保数据长度一致
            min_len = min(len(self.angle_data), len(self.mag_data))
            if min_len > 0:
                self.curve.setData(
                    self.angle_data[:min_len],
                    self.mag_data[:min_len],
                    pen=mkPen(color, width=1)
                )

                # 自动调整Y轴范围
                if auto_y_range:
                    mag_values = np.array(self.mag_data[:min_len])
                    min_val = np.min(mag_values)
                    max_val = np.max(mag_values)
                    # 添加10%的边距
                    margin = (max_val - min_val) * 0.1
                    self.set_y_range(min_val - margin, max_val + margin)
                    # X轴范围固定为0-360度
                    self.set_x_range(0, 360)
    
    def add_plot_data(self, angle_data, mag_data, color='r'):
        """添加新的绘图数据点
        
        Args:
            angle_data: 角度数据
            mag_data: 磁场数据
            color: 曲线颜色
        """
        self.plot_widget.addItem(pg.PlotDataItem(angle_data, mag_data, pen=color))
    
    def clear_plot(self):
        """清除绘图数据"""
        self.plot_widget.clear()
        self.mag_data = []
        self.angle_data = []
        
        # 重新创建曲线
        self.curve = self.plot_widget.plot(pen=mkPen('r', width=1))
    
    def set_x_range(self, min_val, max_val):
        """设置X轴显示范围"""
        self.plot_widget.setXRange(min_val, max_val)
    
    def set_y_range(self, min_val, max_val):
        """设置Y轴显示范围"""
        self.plot_widget.setYRange(min_val, max_val)
    
    def auto_range(self):
        """自动调整显示范围"""
        self.plot_widget.autoRange()
    
    def get_plot_widget(self):
        """获取绘图控件"""
        return self.plot_widget
    
    def set_background_color(self, color):
        """设置背景颜色
        
        Args:
            color: 颜色值，可以是颜色名称或十六进制值
        """
        self.plot_widget.setBackground(color)
    
    def set_grid_visibility(self, x_visible=True, y_visible=True, alpha=0.5):
        """设置网格可见性
        
        Args:
            x_visible: X轴网格是否可见
            y_visible: Y轴网格是否可见
            alpha: 网格透明度
        """
        self.plot_widget.showGrid(x=x_visible, y=y_visible, alpha=alpha)
    
    def set_curve_style(self, color='r', width=1, style=None):
        """设置曲线样式
        
        Args:
            color: 曲线颜色
            width: 曲线宽度
            style: 曲线样式（如Qt.DashLine等）
        """
        if style:
            self.curve.setPen(mkPen(color, width=width, style=style))
        else:
            self.curve.setPen(mkPen(color, width=width))

    def init_plot_display(self, parent_widget):
        """初始化绘图显示到父控件中
        
        Args:
            parent_widget: 父控件
        """
        if parent_widget:
            # 设置绘图窗口到父控件中
            layout = QVBoxLayout(parent_widget)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)
            
            # 设置绘图窗口的大小策略，使其可以随父控件大小变化
            self.setSizePolicy(
                QSizePolicy.Expanding, 
                QSizePolicy.Expanding
            )
            layout.addWidget(self)
            
            logger.info("绘图窗口初始化完成")
        else:
            logger.info("错误：父控件为空，无法初始化绘图窗口")
    
    def show_text_in_center(self, text, color='red', size=20):
        """在绘图区域中心显示文本
        
        Args:
            text: 要显示的文本
            color: 文本颜色
            size: 字体大小
            
        Returns:
            TextItem: 文本项对象
        """
        if not self.plot_widget:
            return None
            
        # 创建文本项
        text_item = pg.TextItem(text=text, color=color, anchor=(0.5, 0.5))
        
        # 设置字体大小
        font = QFont()
        font.setPointSize(size)
        font.setBold(True)
        text_item.setFont(font)
        
        # 设置文本位置为固定坐标（0, 0）
        # 使用固定坐标而不是动态计算，避免空绘图区域的问题
        text_item.setPos(0, 0)
        
        # 添加到绘图区域
        self.plot_widget.addItem(text_item)
        
        logger.info(f"文本显示成功: '{text}'")
        return text_item
    
    def remove_text_item(self, text_item):
        """移除文本项
        
        Args:
            text_item: 要移除的文本项
        """
        if self.plot_widget and text_item:
            self.plot_widget.removeItem(text_item)


class PlotDataProcessor:
    """绘图数据处理类"""
    
    def __init__(self):
        self.angle_data = []
        self.mag_data = []
    
    def process_magnetic_data(self, raw_data_queue):
        """处理磁场数据
        
        Args:
            raw_data_queue: 原始数据队列
            
        Returns:
            tuple: (角度数据, 磁场数据)
        """
        # 从队列中获取所有数据
        temp_values = []
        while not raw_data_queue.empty():
            mag_value = raw_data_queue.get()
            temp_values.append(mag_value)
        
        if not temp_values:
            return [], []
        
        # 数据归一化（减去平均值）
        avg_value = sum(temp_values) / len(temp_values)
        normalized_values = [v - avg_value for v in temp_values]
        
        # 角度数据生成（假设360度均匀分布）
        data_length = len(normalized_values)
        angle_resolution = 360.0 / data_length if data_length > 0 else 0
        angle_data = [i * angle_resolution for i in range(data_length)]
        
        return angle_data, normalized_values
    
    def clear_data(self):
        """清除数据"""
        self.angle_data = []
        self.mag_data = []