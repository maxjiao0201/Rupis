"""查找 / 替换面板。

编辑器上方的一条横栏：
    Ctrl+F  只显示"查找"一行
    Ctrl+H  额外多一行"替换"

面板本身不含查找逻辑，真正的匹配由编辑器完成（编辑器用的是 Python re，
所以正则行为跟写脚本时一致）。
"""

from __future__ import annotations

from .qtcompat import QtCore, QtWidgets


class FindPanel(QtWidgets.QWidget):
    """查找 / 替换条。"""

    def __init__(self, editor, parent=None) -> None:
        super().__init__(parent)
        self.editor = editor
        self._build()
        self.hide()

        # 编辑器内容变了以后，之前算好的命中位置会失效，重新算一遍
        editor.textChanged.connect(self._refresh_highlights)

    # ------------------------------------------------------------------ 界面
    def _build(self) -> None:
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(6, 4, 6, 4)
        outer.setSpacing(4)

        # ---- 第一行：查找
        row1 = QtWidgets.QHBoxLayout()
        row1.setSpacing(4)

        self.find_edit = QtWidgets.QLineEdit()
        self.find_edit.setPlaceholderText("查找内容")
        self.find_edit.setClearButtonEnabled(True)
        self.find_edit.returnPressed.connect(self.find_next)
        self.find_edit.textChanged.connect(self._refresh_highlights)

        self.case_box = QtWidgets.QCheckBox("区分大小写")
        self.regex_box = QtWidgets.QCheckBox("正则")
        self.case_box.toggled.connect(self._refresh_highlights)
        self.regex_box.toggled.connect(self._refresh_highlights)

        self.count_label = QtWidgets.QLabel("")
        self.count_label.setMinimumWidth(90)

        btn_prev = QtWidgets.QPushButton("上一个")
        btn_prev.clicked.connect(self.find_previous)
        btn_next = QtWidgets.QPushButton("下一个")
        btn_next.clicked.connect(self.find_next)
        btn_close = QtWidgets.QPushButton("关闭")
        btn_close.clicked.connect(self.hide_panel)

        row1.addWidget(QtWidgets.QLabel("查找"))
        row1.addWidget(self.find_edit, 1)
        row1.addWidget(self.case_box)
        row1.addWidget(self.regex_box)
        row1.addWidget(btn_prev)
        row1.addWidget(btn_next)
        row1.addWidget(self.count_label)
        row1.addWidget(btn_close)
        outer.addLayout(row1)

        # ---- 第二行：替换（包一层 QWidget，才能整体隐藏）
        row2 = QtWidgets.QHBoxLayout()
        row2.setSpacing(4)

        self.replace_edit = QtWidgets.QLineEdit()
        self.replace_edit.setPlaceholderText("替换为")
        self.replace_edit.returnPressed.connect(self.replace_current)

        btn_replace = QtWidgets.QPushButton("替换")
        btn_replace.clicked.connect(self.replace_current)
        btn_all = QtWidgets.QPushButton("全部替换")
        btn_all.clicked.connect(self.replace_all)

        row2.addWidget(QtWidgets.QLabel("替换"))
        row2.addWidget(self.replace_edit, 1)
        row2.addWidget(btn_replace)
        row2.addWidget(btn_all)
        row2.addStretch(1)

        self.replace_row = QtWidgets.QWidget()
        self.replace_row.setLayout(row2)
        self.replace_row.setVisible(False)
        outer.addWidget(self.replace_row)

        # 在查找框里按 Esc 也要能收起面板
        self.find_edit.installEventFilter(self)
        self.replace_edit.installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if event.type() == QtCore.QEvent.Type.KeyPress and \
                event.key() == QtCore.Qt.Key.Key_Escape:
            self.hide_panel()
            return True
        return super().eventFilter(obj, event)

    # ------------------------------------------------------------------ 显示
    def show_panel(self, replace: bool = False) -> None:
        """弹出面板；replace=True 时同时显示替换那一行。"""
        self.replace_row.setVisible(replace)
        self.show()
        # 光标处有词就拿来当查找关键字
        word = self.editor.word_at(self.editor.textCursor().position())
        if word:
            self.find_edit.setText(word)
            self.find_edit.selectAll()
        self.find_edit.setFocus()
        self.find_edit.selectAll()
        self._refresh_highlights()

    def hide_panel(self) -> None:
        self.editor.clear_find_highlights()
        self.hide()
        self.editor.setFocus()

    # ------------------------------------------------------------------ 查找
    def _options(self) -> dict:
        return {
            "case_sensitive": self.case_box.isChecked(),
            "regex": self.regex_box.isChecked(),
        }

    def _refresh_highlights(self) -> None:
        """按当前条件重新算命中位置并高亮。"""
        needle = self.find_edit.text()
        if not needle:
            self.editor.clear_find_highlights()
            self.count_label.setText("")
            return
        try:
            matches = self.editor.find_matches(needle, **self._options())
        except ValueError as exc:
            self.editor.clear_find_highlights()
            self.count_label.setText("正则无效")
            self.count_label.setToolTip(str(exc))
            return
        self.count_label.setToolTip("")
        self.editor.set_find_highlights(matches)
        self.count_label.setText(f"共 {len(matches)} 处")

    def find_next(self) -> None:
        needle = self.find_edit.text()
        if not needle:
            return
        try:
            span = self.editor.find_next(needle, **self._options())
        except ValueError as exc:
            self._show_regex_error(exc)
            return
        if span is None:
            self.count_label.setText("没有匹配")
        else:
            self.count_label.setText(f"共 {self.editor.match_count} 处")

    def find_previous(self) -> None:
        needle = self.find_edit.text()
        if not needle:
            return
        try:
            span = self.editor.find_next(needle, backward=True, **self._options())
        except ValueError as exc:
            self._show_regex_error(exc)
            return
        if span is None:
            self.count_label.setText("没有匹配")

    # ------------------------------------------------------------------ 替换
    def replace_current(self) -> None:
        needle = self.find_edit.text()
        if not needle:
            return
        replacement = self.replace_edit.text()
        try:
            ok = self.editor.replace_current(needle, replacement, **self._options())
        except ValueError as exc:
            self._show_regex_error(exc)
            return
        if not ok:
            self.count_label.setText("没有匹配")

    def replace_all(self) -> None:
        needle = self.find_edit.text()
        if not needle:
            return
        replacement = self.replace_edit.text()
        try:
            count = self.editor.replace_all(needle, replacement, **self._options())
        except ValueError as exc:
            self._show_regex_error(exc)
            return
        self.count_label.setText(f"已替换 {count} 处")

    def _show_regex_error(self, exc: Exception) -> None:
        self.count_label.setText("正则无效")
        self.count_label.setToolTip(str(exc))
