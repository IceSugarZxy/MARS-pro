# -*- coding: utf-8 -*-
"""
方案编辑对话框 - 用于编辑移动方案的步骤
"""
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                              QComboBox, QPushButton, QListWidget, QListWidgetItem,
                              QToolButton, QMessageBox)
from PyQt5.QtCore import Qt
from core.logger import get_logger
from core.config_manager import ACTION_TYPES, action_to_text

logger = get_logger('SchemeEditDialog')


class SchemeEditDialog(QDialog):
    """方案编辑对话框"""

    def __init__(self, scheme_data, parent=None):
        super().__init__(parent)
        self.scheme_data = scheme_data.copy()  # {"steps": list}
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("编辑方案")
        self.setMinimumWidth(400)
        self.setMinimumHeight(300)

        layout = QVBoxLayout(self)

        # 步骤列表
        layout.addWidget(QLabel("动作步骤:"))

        self.step_list = QListWidget()
        self.step_list.setSelectionMode(QListWidget.SingleSelection)
        self.step_list.setDragDropMode(QListWidget.InternalMove)
        layout.addWidget(self.step_list)

        # 添加步骤按钮行
        add_step_layout = QHBoxLayout()
        self.step_type_combo = QComboBox()
        for action in ACTION_TYPES:
            self.step_type_combo.addItem(action_to_text(action), action)
        add_step_layout.addWidget(self.step_type_combo)

        btn_add = QPushButton("添加")
        btn_add.clicked.connect(self.add_step)
        add_step_layout.addWidget(btn_add)

        btn_delete = QPushButton("删除")
        btn_delete.clicked.connect(self.delete_step)
        add_step_layout.addWidget(btn_delete)

        btn_move_up = QToolButton()
        btn_move_up.setText("↑")
        btn_move_up.clicked.connect(self.move_step_up)
        add_step_layout.addWidget(btn_move_up)

        btn_move_down = QToolButton()
        btn_move_down.setText("↓")
        btn_move_down.clicked.connect(self.move_step_down)
        add_step_layout.addWidget(btn_move_down)

        layout.addLayout(add_step_layout)

        # 加载当前步骤
        self.load_steps()

        # 按钮行
        button_layout = QHBoxLayout()
        btn_ok = QPushButton("确定")
        btn_ok.clicked.connect(self.accept)
        button_layout.addWidget(btn_ok)

        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        button_layout.addWidget(btn_cancel)

        layout.addLayout(button_layout)

    def load_steps(self):
        """加载步骤到列表"""
        self.step_list.clear()
        for step in self.scheme_data.get('steps', []):
            text = action_to_text(step)
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, step)
            self.step_list.addItem(item)

    def add_step(self):
        """添加步骤"""
        step = self.step_type_combo.currentData()
        text = self.step_type_combo.currentText()
        item = QListWidgetItem(text)
        item.setData(Qt.UserRole, step)
        self.step_list.addItem(item)

    def delete_step(self):
        """删除选中步骤"""
        row = self.step_list.currentRow()
        if row >= 0:
            self.step_list.takeItem(row)

    def move_step_up(self):
        """上移步骤"""
        row = self.step_list.currentRow()
        if row > 0:
            item = self.step_list.takeItem(row)
            self.step_list.insertItem(row - 1, item)
            self.step_list.setCurrentRow(row - 1)

    def move_step_down(self):
        """下移步骤"""
        row = self.step_list.currentRow()
        if row < self.step_list.count() - 1 and row >= 0:
            item = self.step_list.takeItem(row)
            self.step_list.insertItem(row + 1, item)
            self.step_list.setCurrentRow(row + 1)

    def get_result(self):
        """获取编辑结果"""
        # 获取步骤
        steps = []
        for i in range(self.step_list.count()):
            item = self.step_list.item(i)
            step = item.data(Qt.UserRole)
            if step:
                steps.append(step)

        return {"steps": steps}
