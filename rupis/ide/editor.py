"""Rupis IDE 的编辑器控件。

QPlainTextEdit 子类，左侧自己画行号（经典的 LineNumberArea 做法），
另外负责：自动缩进、Tab/Shift+Tab 整块缩进、括号自动配对、当前行高亮、Ctrl+Space 补全，
以及括号配对高亮、查找替换、跳转到定义、整行搬移、字号缩放、右键菜单。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .. import compile_source
from ..ast_nodes import FuncDef, StructDef
from .highlighter import RupisHighlighter, completion_words
from .qtcompat import QtCore, QtGui, QtWidgets
from .syntax import (ELEMENTS, ELEMENT_STATES, describe, describe_state_key,
                     describe_symbol)

INDENT = "    "
PAIRS = {"(": ")", "[": "]", "{": "}"}
CLOSERS = {")": "(", "]": "[", "}": "{"}
WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
DEF_RE = re.compile(r"^\s*(?:strudef|def)\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)
STRUCT_RE = re.compile(r"^\s*strudef\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)
FUNC_RE = re.compile(r"^\s*def\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)
# lib 脚本名 [as 别名] —— 脚本名里可以用 / 指子目录
LIB_RE = re.compile(
    r"^\s*lib\s+([A-Za-z_][A-Za-z0-9_]*(?:/[A-Za-z_][A-Za-z0-9_]*)*)"
    r"(?:\s+as\s+([A-Za-z_][A-Za-z0-9_]*))?\s*;?\s*$",
    re.MULTILINE,
)
# 光标前面的 点号链.半截词  —— 用来做脚本成员补全
MEMBER_RE = re.compile(
    r"([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)\.([A-Za-z0-9_]*)$"
)

# 缩放区间
FONT_MIN = 8
FONT_MAX = 28
FONT_STEP = 1

Span = Tuple[int, int]


class LineNumberArea(QtWidgets.QWidget):
    """行号槽，画在编辑器左边。"""

    def __init__(self, editor: "RupisEditor") -> None:
        super().__init__(editor)
        self.editor = editor

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        self.editor.paint_line_numbers(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.editor.line_number_clicked(event)


class RupisEditor(QtWidgets.QPlainTextEdit):
    """Rupis 脚本编辑器。"""

    # 光标移动 / 补全预览时把提示文字抛给主窗口显示
    hintChanged = QtCore.pyqtSignal(str)
    # 右键菜单里点"查找"时通知主窗口弹出查找面板
    findRequested = QtCore.pyqtSignal()
    # 按 Esc 时通知主窗口收起查找面板
    escapePressed = QtCore.pyqtSignal()

    def __init__(self, theme: Dict[str, str], parent=None) -> None:
        super().__init__(parent)
        self.theme = theme
        self.ln_area = LineNumberArea(self)
        self.highlighter = RupisHighlighter(self.document(), theme)

        self.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.NoWrap)
        self._font_size = 11
        self.setFont(QtGui.QFont("Consolas", self._font_size))
        self.setTabStopDistance(4 * self.fontMetrics().horizontalAdvance(" "))
        self.setPlaceholderText("在这里写 Rupis 脚本…（F5 运行，F9 检查语法）")

        # 行号
        self.blockCountChanged.connect(self._update_ln_width)
        self.updateRequest.connect(self._update_ln_area)
        self.cursorPositionChanged.connect(self._on_cursor_moved)
        self._update_ln_width()

        # 补全
        self._base_words = completion_words()
        self._completer = QtWidgets.QCompleter(list(self._base_words), self)
        self._completer.setWidget(self)
        self._completer.setCompletionMode(QtWidgets.QCompleter.CompletionMode.PopupCompletion)
        self._completer.activated.connect(self._insert_completion)
        # 补全弹窗里高亮到某个词时，提示栏跟着显示它的说明。
        # 注意：QCompleter 自己没有"当前高亮项变了"的信号（PyQt6 就没有），
        # 得听弹窗那个 QListView 的 currentChanged。
        try:
            self._completer.popup().currentChanged.connect(self._on_completion_previewed)
        except AttributeError:  # pragma: no cover - 少数绑定没有 popup()
            pass

        self._current_word = ""
        self._find_matches: List[Span] = []
        self._code_cache: Tuple[str, str] = ("", "")   # (原文, 去掉注释与字符串后的版本)

    # ================================================================ 主题
    def apply_theme(self, theme: Dict[str, str]) -> None:
        self.theme = theme
        palette = self.palette()
        palette.setColor(QtGui.QPalette.ColorRole.Base, QtGui.QColor(theme["bg"]))
        palette.setColor(QtGui.QPalette.ColorRole.Text, QtGui.QColor(theme["fg"]))
        palette.setColor(QtGui.QPalette.ColorRole.Highlight, QtGui.QColor(theme["sel_bg"]))
        palette.setColor(QtGui.QPalette.ColorRole.HighlightedText, QtGui.QColor(theme["fg"]))
        self.setPalette(palette)
        self.highlighter.retheme(theme)
        self.ln_area.update()
        self._highlight_current_line()

    # ================================================================ 行号
    def _update_ln_width(self) -> None:
        self.setViewportMargins(self._ln_width(), 0, 0, 0)

    def _update_ln_area(self, rect, dy) -> None:
        if dy:
            self.ln_area.scroll(0, dy)
        else:
            self.ln_area.update(0, rect.y(), self.ln_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_ln_width()

    def _ln_width(self) -> int:
        digits = max(2, len(str(max(1, self.blockCount()))))
        return 12 + self.fontMetrics().horizontalAdvance("9") * digits

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        rect = self.contentsRect()
        self.ln_area.setGeometry(
            QtCore.QRect(rect.left(), rect.top(), self._ln_width(), rect.height())
        )

    def paint_line_numbers(self, event) -> None:
        painter = QtGui.QPainter(self.ln_area)
        painter.fillRect(event.rect(), QtGui.QColor(self.theme["gutter_bg"]))
        painter.setFont(self.font())

        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = self.blockBoundingGeometry(block).translated(self.contentOffset()).top()
        bottom = top + self.blockBoundingRect(block).height()
        current = self.textCursor().blockNumber()

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and block_number != current:
                painter.setPen(QtGui.QColor(self.theme["gutter_fg"]))
                painter.drawText(
                    0, int(top), self.ln_area.width() - 6, self.fontMetrics().height(),
                    QtCore.Qt.AlignmentFlag.AlignRight, str(block_number + 1),
                )
            block = block.next()
            top = bottom
            bottom = top + self.blockBoundingRect(block).height()
            block_number += 1

    def line_number_clicked(self, event) -> None:
        """点行号跳到那一行。"""
        block = self.firstVisibleBlock()
        top = self.blockBoundingGeometry(block).translated(self.contentOffset()).top()
        height = self.blockBoundingRect(block).height()
        number = max(1, self.firstVisibleBlock().blockNumber() +
                     int((event.position().y() - top) // max(height, 1)) + 1)
        cursor = self.textCursor()
        cursor.movePosition(QtGui.QTextCursor.MoveOperation.Start)
        for _ in range(number - 1):
            cursor.movePosition(QtGui.QTextCursor.MoveOperation.Down)
        self.setTextCursor(cursor)
        self.setFocus()

    # ================================================================ 高亮
    def _on_cursor_moved(self) -> None:
        self._highlight_current_line()
        self.hintChanged.emit(self.hint_text())

    def _highlight_current_line(self) -> None:
        selections = []
        if not self.isReadOnly():
            sel = QtWidgets.QTextEdit.ExtraSelection()
            sel.format.setBackground(QtGui.QColor(self.theme["curline"]))
            sel.format.setProperty(QtGui.QTextFormat.Property.FullWidthSelection, True)
            cursor = self.textCursor()
            cursor.clearSelection()
            sel.cursor = cursor
            selections.append(sel)

        # 查找命中的部分
        for start, end in self._find_matches:
            sel = QtWidgets.QTextEdit.ExtraSelection()
            sel.format.setBackground(QtGui.QColor(self.theme["match_bg"]))
            sel.format.setForeground(QtGui.QColor(self.theme["match_fg"]))
            cursor = QtGui.QTextCursor(self.document())
            cursor.setPosition(start)
            cursor.setPosition(end, QtGui.QTextCursor.MoveMode.KeepAnchor)
            sel.cursor = cursor
            selections.append(sel)

        if self._error_line:
            block = self.document().findBlockByNumber(self._error_line - 1)
            if block.isValid():
                sel = QtWidgets.QTextEdit.ExtraSelection()
                sel.format.setBackground(QtGui.QColor(self.theme["err"]))
                sel.format.setForeground(QtGui.QColor(self.theme["err_fg"]))
                # 整行标红：只选一个字符的话底纹根本看不出来
                cursor = QtGui.QTextCursor(self.document())
                cursor.setPosition(block.position())
                cursor.setPosition(block.position() + len(block.text()),
                                   QtGui.QTextCursor.MoveMode.KeepAnchor)
                sel.cursor = cursor
                selections.append(sel)

        # 括号配对
        for start, end in self._bracket_matches():
            sel = QtWidgets.QTextEdit.ExtraSelection()
            sel.format.setForeground(QtGui.QColor(self.theme["bracket"]))
            sel.format.setFontWeight(QtGui.QFont.Weight.Bold)
            cursor = QtGui.QTextCursor(self.document())
            cursor.setPosition(start)
            cursor.setPosition(end, QtGui.QTextCursor.MoveMode.KeepAnchor)
            sel.cursor = cursor
            selections.append(sel)

        self.setExtraSelections(selections)

    # ================================================================ 错误标记
    def mark_error(self, line: int = 0, col: int = 0) -> None:
        """标记出错的行与列。"""
        if line and line <= self.blockCount():
            block = self.document().findBlockByLineNumber(line - 1)
            pos = block.position() + max(col - 1, 0)
            self._error_line = line
            self._error_pos = pos
        else:
            self._error_line = 0
            self._error_pos = 0
        self._highlight_current_line()

    def clear_error(self) -> None:
        self._error_line = 0
        self._error_pos = 0
        self._highlight_current_line()

    _error_line = 0
    _error_pos = 0

    # ================================================================ 编辑
    def keyPressEvent(self, event) -> None:  # noqa: N802
        key = event.key()
        modifiers = event.modifiers()

        # Ctrl+Space → 补全
        if key == QtCore.Qt.Key.Key_Space and modifiers & QtCore.Qt.KeyboardModifier.ControlModifier:
            self._start_completion()
            return
        # Ctrl+/ → 注释/取消注释
        if key == QtCore.Qt.Key.Key_Slash and modifiers & QtCore.Qt.KeyboardModifier.ControlModifier:
            self._toggle_comment()
            return
        # F12 → 跳转到定义
        if key == QtCore.Qt.Key.Key_F12:
            self.jump_to_definition()
            return
        # Esc → 通知外部收起查找面板（补全弹窗自己也要能关，所以照常往下传）
        if key == QtCore.Qt.Key.Key_Escape:
            self.escapePressed.emit()
            super().keyPressEvent(event)
            return
        # Alt+↑ / Alt+↓ → 整行上下搬移
        if key in (QtCore.Qt.Key.Key_Up, QtCore.Qt.Key.Key_Down) and \
                modifiers & QtCore.Qt.KeyboardModifier.AltModifier:
            self.move_lines(-1 if key == QtCore.Qt.Key.Key_Up else 1)
            return
        # Ctrl+Shift+D → 复制当前行
        if key == QtCore.Qt.Key.Key_D and modifiers & QtCore.Qt.KeyboardModifier.ControlModifier \
                and modifiers & QtCore.Qt.KeyboardModifier.ShiftModifier:
            self.duplicate_lines()
            return
        # Ctrl+Shift+K → 删除当前行
        if key == QtCore.Qt.Key.Key_K and modifiers & QtCore.Qt.KeyboardModifier.ControlModifier \
                and modifiers & QtCore.Qt.KeyboardModifier.ShiftModifier:
            self.delete_lines()
            return
        # Tab / Shift+Tab
        if key == QtCore.Qt.Key.Key_Tab:
            if modifiers & QtCore.Qt.KeyboardModifier.ShiftModifier:
                self._indent_selection(dedent=True)
            elif self.textCursor().hasSelection():
                self._indent_selection(dedent=False)
            else:
                self.insertPlainText(INDENT)
            return
        if key == QtCore.Qt.Key.Key_Backtab:
            self._indent_selection(dedent=True)
            return
        # Backspace：行首缩进整块删
        if key == QtCore.Qt.Key.Key_Backspace and not self.textCursor().hasSelection():
            cursor = self.textCursor()
            if cursor.positionInBlock() and cursor.positionInBlock() % len(INDENT) == 0:
                head = self.document().findBlock(cursor.blockNumber()).text()[
                    :cursor.positionInBlock()]
                if head and not head.strip():
                    cursor.movePosition(
                        QtGui.QTextCursor.MoveOperation.Left,
                        QtGui.QTextCursor.MoveMode.KeepAnchor,
                        len(INDENT),
                    )
                    cursor.removeSelectedText()
                    return

        # 回车自动缩进
        if key in (QtCore.Qt.Key.Key_Return, QtCore.Qt.Key.Key_Enter):
            cursor = self.textCursor()
            block_text = cursor.block().text()
            indent = re.match(r"[ \t]*", block_text).group(0)
            prefix = block_text[:cursor.positionInBlock()]
            if prefix.rstrip().endswith("{"):
                indent += INDENT
            cursor.insertText("\n" + indent)
            return

        text = event.text()
        # 括号自动配对
        if text and text in PAIRS:
            cursor = self.textCursor()
            cursor.insertText(text + PAIRS[text])
            cursor.movePosition(QtGui.QTextCursor.MoveOperation.Left)
            self.setTextCursor(cursor)
            return
        if text and text in CLOSERS:
            cursor = self.textCursor()
            probe = QtGui.QTextCursor(cursor)
            probe.movePosition(QtGui.QTextCursor.MoveOperation.Right,
                               QtGui.QTextCursor.MoveMode.KeepAnchor)
            if probe.selectedText() == text:
                cursor.movePosition(QtGui.QTextCursor.MoveOperation.Right)
                self.setTextCursor(cursor)
                return  # 跳过已经存在的右括号
            cursor.insertText(text)
            return

        super().keyPressEvent(event)

    def insertPlainText(self, text: str) -> None:  # noqa: N802
        super().insertPlainText(text)
        self._after_edit()

    def setPlainText(self, text: str) -> None:  # noqa: N802
        # setPlainText 不会走 insertPlainText，得自己收尾
        super().setPlainText(text)
        self._after_edit()

    def _after_edit(self) -> None:
        self.refresh_definitions()

    # ================================================================ 行操作
    def _selected_lines(self) -> Tuple[int, int]:
        """返回选中范围覆盖的行号区间 (首行, 末行)，行号从 1 开始。"""
        cursor = self.textCursor()
        start = cursor.selectionStart()
        end = cursor.selectionEnd()
        if start == end:
            start = end = cursor.position()
        first_block = self.document().findBlock(start)
        last_block = self.document().findBlock(max(end - 1, start))
        return first_block.blockNumber() + 1, last_block.blockNumber() + 1

    def _get_lines(self, first: int, last: int) -> List[str]:
        block = self.document().findBlockByNumber(first - 1)
        lines = []
        for _ in range(first, last + 1):
            lines.append(block.text())
            block = block.next()
        return lines

    def _replace_lines(self, first: int, last: int, new_lines: List[str],
                       *, eat_newline: bool = False) -> None:
        """把第 first..last 行整体替换成 new_lines。"""
        if first > last:
            return
        first_block = self.document().findBlockByNumber(first - 1)
        last_block = self.document().findBlockByNumber(last - 1)
        start_pos = first_block.position()
        end_pos = last_block.position() + len(last_block.text())
        if eat_newline:
            if last_block.next().isValid():
                # 后面还有行，把这行末尾的换行一起吃掉
                end_pos += 1
            else:
                # 删的是最后一行，改吃前面那个换行，否则会多留一个空行
                start_pos = max(start_pos - 1, 0)
        cursor = QtGui.QTextCursor(self.document())
        cursor.setPosition(start_pos)
        cursor.setPosition(end_pos, QtGui.QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText("\n".join(new_lines))

    def _select_line(self, line: int) -> None:
        """把光标放到第 line 行上（不选中，只定位）。"""
        block = self.document().findBlockByNumber(max(line - 1, 0))
        if not block.isValid():
            return
        cursor = self.textCursor()
        cursor.setPosition(block.position())
        self.setTextCursor(cursor)
        self.ensureCursorVisible()

    def move_lines(self, delta: int) -> bool:
        """把选中的行整体上移（delta=-1）或下移（delta=1）一行。"""
        if delta == 0:
            return False
        first, last = self._selected_lines()
        lines = self._get_lines(first, last)
        total = self.blockCount()

        if delta < 0:
            if first <= 1:
                return False
            above = self._get_lines(first - 1, first - 1)[0]
            self._replace_lines(first - 1, last, lines + [above])
            self._select_line(first - 1)
        else:
            if last >= total:
                return False
            below = self._get_lines(last + 1, last + 1)[0]
            self._replace_lines(first, last + 1, [below] + lines)
            self._select_line(first + 1)
        return True

    def duplicate_lines(self) -> bool:
        """复制选中的行到下面一份。"""
        first, last = self._selected_lines()
        lines = self._get_lines(first, last)
        self._replace_lines(first, last, lines + lines)
        self._select_line(first + len(lines))
        return True

    def delete_lines(self) -> bool:
        """删掉选中的行。"""
        first, last = self._selected_lines()
        self._replace_lines(first, last, [], eat_newline=True)
        remaining = max(self.blockCount(), 1)
        self._select_line(min(first, remaining))
        return True

    # ================================================================ 缩进
    def _toggle_comment(self) -> None:
        """选中行批量加 / 去 // 注释。"""
        first, last = self._selected_lines()
        lines = self._get_lines(first, last)
        all_commented = all(line.strip().startswith("//") or not line.strip()
                            for line in lines)
        new_lines = []
        for line in lines:
            if not line.strip():
                new_lines.append(line)
            elif all_commented:
                new_lines.append(line.replace("//", "", 1).lstrip(" "))
            else:
                new_lines.append("// " + line)
        self._replace_lines(first, last, new_lines)

    def _indent_selection(self, *, dedent: bool) -> None:
        first, last = self._selected_lines()
        lines = self._get_lines(first, last)
        if dedent:
            new_lines = [
                line[len(INDENT):] if line.startswith(INDENT)
                else (line[1:] if line.startswith(" ") else line)
                for line in lines
            ]
        else:
            new_lines = [(INDENT + line) if line.strip() else line for line in lines]
        self._replace_lines(first, last, new_lines)

    # ================================================================ 补全
    def refresh_definitions(self) -> None:
        """扫描脚本里的结构名 / 函数名，加进补全词表。"""
        text = self.toPlainText()
        names = sorted(set(DEF_RE.findall(text)))
        # lib 导入的脚本里的名字也能直接补出来
        for path in self._lib_files().values():
            names.extend(self._script_members(path))
        words = sorted(set(self._base_words) | set(names))
        model = self._completer.model()
        if isinstance(model, QtCore.QStringListModel):
            model.setStringList(words)
        else:
            self._completer.setModel(QtCore.QStringListModel(words))

    _base_words: List[str] = []

    # ------------------------------------------------------------ lib 导入
    def set_lib_paths(self, paths: List[Path]) -> None:
        """设置 lib 找 .rpi 脚本时搜索的目录。"""

        self._lib_paths = [Path(item) for item in paths]

    _lib_paths: List[Path] = []

    def _find_lib_file(self, script: str) -> Optional[Path]:
        """按名字找 .rpi 脚本（跟解释器的搜索顺序一致）。"""

        relative = Path(*script.split("/")) if script else Path()
        for folder in self._lib_paths:
            candidate = folder / relative
            if candidate.suffix != ".rpi":
                candidate = candidate.with_suffix(".rpi")
            if candidate.is_file():
                return candidate
        return None

    def _lib_files(self) -> Dict[str, Path]:
        """扫描脚本里的 lib 语句：绑定的名字 → .rpi 文件路径。

        ``lib util`` 绑的是 util，``lib util as u`` 绑的是 u，
        ``lib sub/util`` 绑的是 util。
        """

        found: Dict[str, Path] = {}
        for match in LIB_RE.finditer(self.toPlainText()):
            script = match.group(1)
            alias = match.group(2)
            name = alias or script.rsplit("/", 1)[-1]
            path = self._find_lib_file(script)
            if path is not None:
                found[name] = path
        return found

    def _script_members(self, path: Path) -> List[str]:
        """读一个 .rpi 脚本，返回它里面的函数名和结构名。"""

        try:
            text = path.read_text(encoding="utf-8")
            program, _source = compile_source(text, str(path))
        except Exception:
            return []
        names: List[str] = []
        for item in program:
            if isinstance(item, (FuncDef, StructDef)):
                names.append(item.name)
        return sorted(set(names))

    def _member_completion(self) -> Optional[Tuple[List[str], str]]:
        """光标前面是 ``脚本名.`` 时，补全这个脚本里的成员。

        返回 (候选词表, 已输入的前缀)；不适用时返回 None。
        """

        cursor = self.textCursor()
        head = cursor.block().text()[:cursor.positionInBlock()]
        match = MEMBER_RE.search(head)
        if not match:
            return None
        chain, prefix = match.group(1), match.group(2)
        parts = chain.split(".")
        if len(parts) > 1:
            # 导入的脚本没有二级命名空间
            return None
        path = self._lib_files().get(parts[0])
        if path is None:
            return None
        members = self._script_members(path)
        if not members:
            return None
        return members, prefix

    def _start_completion(self) -> None:
        self.refresh_definitions()
        members = self._member_completion()
        if members is not None:
            words, prefix = members
            model = self._completer.model()
            if isinstance(model, QtCore.QStringListModel):
                model.setStringList(words)
            else:
                self._completer.setModel(QtCore.QStringListModel(words))
            self._completer.setCompletionPrefix(prefix)
            self._completer.complete(self.cursorRect())
            return
        cursor = self.textCursor()
        cursor.select(QtGui.QTextCursor.SelectionType.WordUnderCursor)
        self._completer.setCompletionPrefix(cursor.selectedText())
        self._completer.complete(self.cursorRect())

    def _insert_completion(self, completion: str) -> None:
        cursor = self.textCursor()
        cursor.select(QtGui.QTextCursor.SelectionType.WordUnderCursor)
        cursor.insertText(completion)
        self.setTextCursor(cursor)

    def _on_completion_previewed(self, index) -> None:
        """下拉框里高亮到某个词时，提示栏跟着显示它的说明。"""
        if index is None or not index.isValid():
            return
        word = str(index.data())
        if word:
            self.hintChanged.emit(describe(word) or f"补全：{word}")

    # ================================================================ 查找替换
    def find_matches(self, needle: str, *, case_sensitive: bool = False,
                     regex: bool = False) -> List[Span]:
        """返回所有匹配区间；正则非法时抛 ValueError。"""
        text = self.toPlainText()
        if not needle:
            return []
        if regex:
            flags = 0 if case_sensitive else re.IGNORECASE
            try:
                pattern = re.compile(needle, flags)
            except re.error as exc:
                raise ValueError(f"正则表达式无效：{exc}") from exc
            out = []
            for m in pattern.finditer(text):
                if m.end() == m.start():   # 跳过空匹配，避免死循环
                    continue
                out.append((m.start(), m.end()))
            return out

        haystack = text if case_sensitive else text.lower()
        key = needle if case_sensitive else needle.lower()
        out = []
        step = max(len(key), 1)
        idx = haystack.find(key)
        while idx != -1:
            out.append((idx, idx + len(needle)))
            idx = haystack.find(key, idx + step)
        return out

    def set_find_highlights(self, matches: List[Span]) -> None:
        self._find_matches = list(matches)
        self._highlight_current_line()

    @property
    def match_count(self) -> int:
        """当前高亮的命中数量。"""
        return len(self._find_matches)

    def clear_find_highlights(self) -> None:
        self.set_find_highlights([])

    def select_span(self, start: int, end: int) -> None:
        cursor = QtGui.QTextCursor(self.document())
        cursor.setPosition(start)
        cursor.setPosition(end, QtGui.QTextCursor.MoveMode.KeepAnchor)
        self.setTextCursor(cursor)
        self.ensureCursorVisible()

    def find_next(self, needle: str, *, case_sensitive: bool = False,
                  regex: bool = False, backward: bool = False) -> Optional[Span]:
        """跳到下一个（或上一个）匹配处，返回命中的区间；没有则返回 None。"""
        matches = self.find_matches(needle, case_sensitive=case_sensitive, regex=regex)
        self.set_find_highlights(matches)
        if not matches:
            return None
        anchor = self.textCursor().position()
        if backward:
            before = [m for m in matches if m[0] < anchor]
            target = before[-1] if before else matches[-1]
        else:
            target = matches[0]
            for span in matches:
                if span[1] > anchor:
                    target = span
                    break
        self.select_span(*target)
        return target

    def replace_current(self, needle: str, replacement: str, *,
                        case_sensitive: bool = False, regex: bool = False) -> bool:
        """替换当前选中的那一处；选中的不是匹配项时，先跳到下一个。"""
        matches = self.find_matches(needle, case_sensitive=case_sensitive, regex=regex)
        self.set_find_highlights(matches)
        if not matches:
            return False
        cursor = self.textCursor()
        span = None
        for start, end in matches:
            if start == cursor.selectionStart() and end == cursor.selectionEnd():
                span = (start, end)
                break
        if span is None:
            return self.find_next(needle, case_sensitive=case_sensitive,
                                  regex=regex) is not None
        self._replace_span(span, replacement, needle, case_sensitive, regex)
        self.set_find_highlights(
            self.find_matches(needle, case_sensitive=case_sensitive, regex=regex)
        )
        return True

    def replace_all(self, needle: str, replacement: str, *,
                    case_sensitive: bool = False, regex: bool = False) -> int:
        """替换全部匹配，返回替换次数。"""
        matches = self.find_matches(needle, case_sensitive=case_sensitive, regex=regex)
        if not matches:
            return 0
        # 从后往前改，前面的改动才不会影响后面的位置
        for span in reversed(matches):
            self._replace_span(span, replacement, needle, case_sensitive, regex)
        self.set_find_highlights(
            self.find_matches(needle, case_sensitive=case_sensitive, regex=regex)
        )
        return len(matches)

    def _replace_span(self, span: Span, replacement: str, needle: str,
                      case_sensitive: bool, regex: bool) -> None:
        text = self.toPlainText()
        expanded = replacement
        if regex:
            expanded = self._expand_replacement(text, needle, span, replacement,
                                                case_sensitive)
        cursor = QtGui.QTextCursor(self.document())
        cursor.setPosition(span[0])
        cursor.setPosition(span[1], QtGui.QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText(expanded)

    @staticmethod
    def _expand_replacement(text: str, pattern: str, span: Span,
                            replacement: str, case_sensitive: bool) -> str:
        """正则模式下展开 \\1 这样的反向引用。"""
        try:
            rx = re.compile(pattern, 0 if case_sensitive else re.IGNORECASE)
        except re.error:
            return replacement
        m = rx.search(text, span[0], span[0] + max(span[1] - span[0], 1))
        if m is None or m.start() != span[0] or m.end() != span[1]:
            return replacement
        try:
            return m.expand(replacement)
        except re.error:
            return replacement

    # ================================================================ 括号配对
    def _code_text(self) -> str:
        """返回去掉注释与字符串后的源码（长度与原文一致）。

        做括号配对时得跳过字符串和注释，否则 "{" 这种字符会算错深度。
        """
        text = self.toPlainText()
        cached, stripped = self._code_cache
        if cached == text:
            return stripped
        stripped = _strip_comments_and_strings(text)
        self._code_cache = (text, stripped)
        return stripped

    def _bracket_matches(self) -> List[Span]:
        """返回光标两侧配对括号的区间（找不到就是空列表）。"""
        cursor = self.textCursor()
        pos = cursor.position()
        code = self._code_text()
        if not code:
            return []

        # 先看光标左边，再看右边
        for probe in (pos - 1, pos):
            if 0 <= probe < len(code) and code[probe] in PAIRS:
                other = self._match_bracket(code, probe)
                if other is not None:
                    return [(probe, probe + 1), (other, other + 1)]
            if 0 <= probe < len(code) and code[probe] in CLOSERS:
                other = self._match_bracket(code, probe)
                if other is not None:
                    return [(probe, probe + 1), (other, other + 1)]
        return []

    @staticmethod
    def _match_bracket(code: str, pos: int) -> Optional[int]:
        """在"去注释去字符串"的文本里找 pos 处括号的配对位置。"""
        ch = code[pos]
        if ch in PAIRS:
            depth = 0
            for i in range(pos, len(code)):
                c = code[i]
                if c in PAIRS:
                    depth += 1
                elif c in CLOSERS:
                    depth -= 1
                    if depth == 0:
                        return i
            return None
        if ch in CLOSERS:
            depth = 0
            for i in range(pos, -1, -1):
                c = code[i]
                if c in CLOSERS:
                    depth += 1
                elif c in PAIRS:
                    depth -= 1
                    if depth == 0:
                        return i
            return None
        return None

    # ================================================================ 跳转定义
    def word_at(self, pos: int) -> str:
        """取 pos 处的单词。"""
        text = self.toPlainText()
        pos = max(0, min(pos, len(text)))
        start = pos
        while start > 0 and (text[start - 1].isalnum() or text[start - 1] == "_"):
            start -= 1
        end = pos
        while end < len(text) and (text[end].isalnum() or text[end] == "_"):
            end += 1
        return text[start:end]

    def symbol_kind(self, name: str) -> str:
        """name 是结构（structure）、函数（function）还是普通标识符（""）。"""
        text = self.toPlainText()
        if re.search(r"^\s*strudef\s+" + re.escape(name) + r"\b", text, re.MULTILINE):
            return "structure"
        if re.search(r"^\s*def\s+" + re.escape(name) + r"\b", text, re.MULTILINE):
            return "function"
        return ""

    def find_definition(self, name: str) -> int:
        """返回 name 的定义所在行号（从 1 开始），找不到返回 0。"""
        text = self.toPlainText()
        for regex in (STRUCT_RE, FUNC_RE):
            for m in regex.finditer(text):
                if m.group(1) == name:
                    return text.count("\n", 0, m.start()) + 1
        return 0

    def jump_to_definition(self) -> bool:
        """跳到光标处单词的定义处。"""
        name = self.word_at(self.textCursor().position())
        if not name:
            return False
        line = self.find_definition(name)
        if not line:
            self.hintChanged.emit(f"找不到 {name} 的定义")
            return False
        self.goto_line(line)
        self.hintChanged.emit(f"跳转到 {name} 的定义（第 {line} 行）")
        return True

    # ================================================================ 提示
    def hint_text(self) -> str:
        """光标处的提示文字。"""
        pos = self.textCursor().position()
        word = self.word_at(pos)
        if word:
            kind = self.symbol_kind(word)
            if kind:
                return describe_symbol(word, kind)
            text = describe(word)
            if text:
                return text
            key_text = describe_state_key(word)
            if key_text:
                return key_text

        element = self._element_in_state_slot(pos)
        if element:
            keys = ELEMENT_STATES.get(element, [])
            if keys:
                return f"{element} 可用状态键：{'、'.join(keys)}"
            return f"{element} 不接受自定义状态键"
        return ""

    def _element_in_state_slot(self, pos: int) -> Optional[str]:
        """光标是否落在某个元件的状态槽里？是的话返回该元件名。"""
        code = self._code_text()
        pos = max(0, min(pos, len(code)))
        open_idx = code.rfind("{", 0, pos)
        if open_idx == -1:
            return None
        if "{" in code[open_idx + 1:pos]:      # 中间又开了槽，说明光标在更深的槽里
            return None
        prefix = code[:open_idx]
        found = None
        for m in re.finditer(r"[A-Za-z_][A-Za-z0-9_]*", prefix):
            if m.group(0) in ELEMENTS:
                found = m.group(0)
        return found

    # ================================================================ 字号
    @property
    def font_size(self) -> int:
        return self._font_size

    def set_font_size(self, size: int) -> None:
        self._font_size = max(FONT_MIN, min(FONT_MAX, int(size)))
        self.setFont(QtGui.QFont("Consolas", self._font_size))
        self.setTabStopDistance(4 * self.fontMetrics().horizontalAdvance(" "))
        self._update_ln_width()

    def zoom_in(self) -> None:
        self.set_font_size(self._font_size + FONT_STEP)

    def zoom_out(self) -> None:
        self.set_font_size(self._font_size - FONT_STEP)

    def reset_zoom(self) -> None:
        self.set_font_size(11)

    # ================================================================ 右键菜单
    def contextMenuEvent(self, event) -> None:  # noqa: N802
        menu = self.createStandardContextMenu()
        menu.addSeparator()
        act_def = menu.addAction("跳转到定义  (F12)")
        act_def.triggered.connect(self.jump_to_definition)
        act_comment = menu.addAction("注释 / 取消注释  (Ctrl+/)")
        act_comment.triggered.connect(self._toggle_comment)
        act_find = menu.addAction("查找…  (Ctrl+F)")
        act_find.triggered.connect(self.findRequested.emit)
        runner = getattr(menu, "exec", None) or getattr(menu, "exec_")
        runner(event.globalPos())

    # ================================================================ 其它
    def goto_line(self, line: int, col: int = 1) -> None:
        block = self.document().findBlockByLineNumber(max(line - 1, 0))
        if not block.isValid():
            return
        cursor = self.textCursor()
        cursor.setPosition(block.position() + max(col - 1, 0))
        self.setTextCursor(cursor)
        self.centerCursor()
        self.setFocus()


def _strip_comments_and_strings(text: str) -> str:
    """把字符串与注释替换成空格，长度不变。

    括号配对、状态槽判断都靠它，避免字符串里的括号算进嵌套层数。
    """
    out = list(text)
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        two = text[i:i + 2]
        if two == "//":
            while i < n and text[i] != "\n":
                out[i] = " "
                i += 1
            continue
        if two == "/*":
            j = text.find("*/", i + 2)
            j = n if j == -1 else j + 2
            while i < j:
                if text[i] != "\n":
                    out[i] = " "
                i += 1
            continue
        if ch in "\"'":
            j = i + 1
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == ch:
                    j += 1
                    break
                j += 1
            else:
                j = n
            while i < j:
                if text[i] != "\n":
                    out[i] = " "
                i += 1
            continue
        i += 1
    return "".join(out)
