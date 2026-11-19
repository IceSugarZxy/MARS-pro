# -*- coding: utf-8 -*-
"""波形图控件的通用交互：双击恢复初始缩放。"""


class DoubleClickReset:
    """给 pyqtgraph 绘图控件加「双击恢复初始缩放」。

    用法：控件创建后建立本对象；每当代码设好视窗（初始状态、每次数据刷新）调用
    ``remember()`` 记录当前范围。双击绘图区即恢复到最近一次记录的范围；
    记录时若处于自动量程，恢复也回到自动量程。
    """

    def __init__(self, plot_widget):
        self._plot = plot_widget
        self._auto = (False, False)
        self._range = None
        plot_widget.scene().sigMouseClicked.connect(self._on_mouse_clicked)
        self.remember()

    def remember(self):
        """记录当前视窗（由代码设范围之后调用）。"""
        view_box = self._plot.plotItem.getViewBox()
        try:
            self._auto = tuple(bool(flag) for flag in view_box.autoRangeEnabled())
        except Exception:  # 不同 pyqtgraph 版本接口差异
            self._auto = (False, False)
        view = view_box.viewRange()
        self._range = ((float(view[0][0]), float(view[0][1])),
                       (float(view[1][0]), float(view[1][1])))
        return self

    def restore(self):
        """恢复到最近一次记录的视窗（自动量程的轴仍回到自动量程）。"""
        if self._range is None:
            return
        view_box = self._plot.plotItem.getViewBox()
        auto_x, auto_y = self._auto
        (x0, x1), (y0, y1) = self._range
        if auto_x:
            view_box.enableAutoRange('x', True)
        else:
            view_box.setXRange(x0, x1, padding=0)
        if auto_y:
            view_box.enableAutoRange('y', True)
        else:
            view_box.setYRange(y0, y1, padding=0)
        if auto_x or auto_y:
            view_box.updateAutoRange()

    def _on_mouse_clicked(self, event):
        if not event.double():
            return
        self.restore()
        accept = getattr(event, 'accept', None)
        if callable(accept):
            accept()


__all__ = ['DoubleClickReset']
