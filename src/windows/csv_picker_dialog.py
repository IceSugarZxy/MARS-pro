# -*- coding: utf-8 -*-
"""选择 plot_data CSV 的列表对话框（界面在 ui/csv_picker_dialog.ui）。

列表口径与「历史数据」页面一致：扫描 data/plot_data 下的全部 CSV，按保存时间倒序，
列名、取值规则都照搬历史列表；不做极对数过滤，也不做内外圈自动配对。
"""

import os

from PyQt5 import uic
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QDialog, QDialogButtonBox, QHeaderView,
                             QTableWidgetItem)

from core.logger import get_logger
from core.path_utils import get_data_dir
from core.plot_data_reader import (TABLE_COLUMNS, pole_count_text,
                                   scan_plot_data_records)

logger = get_logger('CsvPickerDialog')


class CsvPickerDialog(QDialog):
    """显示全部历史数据的列表对话框，选中一条后返回其路径。

    Args:
        initial_path: 初始选中的文件，用于列表定位与预选行
        title: 对话框标题
    """

    def __init__(self, initial_path='', title='选择数据', parent=None):
        super().__init__(parent)

        ui_file_path = os.path.join(os.path.dirname(__file__), '..', 'ui',
                                    'csv_picker_dialog.ui')
        uic.loadUi(ui_file_path, self)

        self.setWindowTitle(title)
        self._initial_path = initial_path
        self._records = []
        self.selected_path = ''

        self.button_box.button(QDialogButtonBox.Ok).setText('确定')
        self.button_box.button(QDialogButtonBox.Cancel).setText('取消')
        self.button_box.accepted.connect(self._accept_selection)
        self.button_box.rejected.connect(self.reject)
        self.btn_refresh.clicked.connect(self._reload)
        self.table.itemDoubleClicked.connect(lambda _item: self._accept_selection())
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

        self._reload()

    # ---------------------------------------------------------------- 数据
    def _plot_data_root(self):
        return get_data_dir('plot_data')

    def _reload(self):
        root = self._plot_data_root()
        self.setCursor(Qt.WaitCursor)
        try:
            records = scan_plot_data_records(root)
        except Exception as exc:
            logger.warning(f'扫描 {root} 失败: {exc}')
            records = []
        finally:
            self.unsetCursor()
        self._records = records

        self.table.blockSignals(True)
        self.table.clearSelection()
        self.table.setRowCount(len(records))
        preselect = -1
        for row, record in enumerate(records):
            for column, field in enumerate(TABLE_COLUMNS):
                if field == 'polar_num':
                    # CSV 存的是极对数，列表与历史数据页面一样显示极数（×2）
                    value = pole_count_text(record.get(field, ''))
                else:
                    value = str(record.get(field, '') or '')
                item = QTableWidgetItem(value)
                if column == 0:
                    file_path = record.get('file_path', '')
                    item.setData(Qt.UserRole, file_path)
                    item.setToolTip(file_path)
                self.table.setItem(row, column, item)
            if (self._initial_path
                    and os.path.abspath(record.get('file_path', ''))
                    == os.path.abspath(self._initial_path)):
                preselect = row
        self.table.blockSignals(False)

        if preselect >= 0:
            self.table.selectRow(preselect)
            self.table.scrollToItem(self.table.item(preselect, 0))
        self.count_label.setText(f'共 {len(records)} 条数据，双击或选中后点“确定”')

    # ---------------------------------------------------------------- 交互
    def _accept_selection(self):
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows:
            return
        item = self.table.item(rows[0].row(), 0)
        if not item:
            return
        self.selected_path = item.data(Qt.UserRole) or ''
        self.accept()


def pick_csv(parent, initial_path='', title='选择数据'):
    """打开对话框并返回选中的文件路径（取消返回空串）。"""
    dialog = CsvPickerDialog(initial_path=initial_path, title=title, parent=parent)
    if dialog.exec_() == QDialog.Accepted:
        return dialog.selected_path
    return ''
