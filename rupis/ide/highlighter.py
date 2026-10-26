"""Rupis 语法高亮器。

基于 QSyntaxHighlighter，一次扫描同时处理：
    - 单行注释 //
    - 块注释 /* ... */（可跨行，用 block state 记住）
    - 字符串 "..." / '...'
    - 关键字 / 元件 / 常量 / 数字 / 结构与函数名
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from .qtcompat import QtCore, QtGui
from .syntax import ALL_WORDS, classify

_RANGE = Tuple[int, int]  # (起点, 长度)


class RupisHighlighter(QtGui.QSyntaxHighlighter):
    def __init__(self, document, theme: Dict[str, str]) -> None:
        super().__init__(document)
        self.theme = theme
        self._rx_word = QtCore.QRegularExpression(r"[A-Za-z_][A-Za-z0-9_]*")
        self._rx_number = QtCore.QRegularExpression(r"\b\d+(\.\d+)?\b")
        self._fmts = self._build_formats()

    # ------------------------------------------------------------------ 格式
    def _build_formats(self) -> Dict[str, QtGui.QTextCharFormat]:
        theme = self.theme

        def fmt(color: str, bold: bool = False) -> QtGui.QTextCharFormat:
            f = QtGui.QTextCharFormat()
            f.setForeground(QtGui.QColor(color))
            if bold:
                f.setFontWeight(QtGui.QFont.Weight.Bold)
            return f

        return {
            "kw": fmt(theme["kw"], True),
            "elem": fmt(theme["elem"], True),
            "const": fmt(theme["const"]),
            "func": fmt(theme["func"]),
            "number": fmt(theme["number"]),
            "string": fmt(theme["string"]),
            "comment": fmt(theme["comment"]),
        }

    def retheme(self, theme: Dict[str, str]) -> None:
        self.theme = theme
        self._fmts = self._build_formats()
        self.rehighlight()

    # ------------------------------------------------------------------ 主流程
    def highlightBlock(self, text: str) -> None:
        strings, comments = self._scan(text)

        # 单词：关键字 / 元件 / 常量 / 函数名
        it = self._rx_word.globalMatch(text)
        while it.hasNext():
            match = it.next()
            start, length = match.capturedStart(), match.capturedLength()
            if self._overlaps(strings, start, length) or self._overlaps(comments, start, length):
                continue
            word = match.captured()
            kind = classify(word)
            if kind:
                self.setFormat(start, length, self._fmts[kind])
                continue
            # 后面紧跟左括号 → 当作结构名 / 函数名
            j = match.capturedEnd()
            while j < len(text) and text[j] in " \t":
                j += 1
            if j < len(text) and text[j] == "(":
                self.setFormat(start, length, self._fmts["func"])

        # 数字
        it = self._rx_number.globalMatch(text)
        while it.hasNext():
            match = it.next()
            start, length = match.capturedStart(), match.capturedLength()
            if self._overlaps(strings, start, length) or self._overlaps(comments, start, length):
                continue
            self.setFormat(start, length, self._fmts["number"])

        # 字符串与注释最后上色，优先级最高
        for start, length in strings:
            self.setFormat(start, length, self._fmts["string"])
        for start, length in comments:
            self.setFormat(start, length, self._fmts["comment"])

    # ------------------------------------------------------------------ 扫描
    def _scan(self, text: str) -> Tuple[List[_RANGE], List[_RANGE]]:
        """一次扫描找出本行的字符串区间与注释区间。

        返回 (strings, comments)，注释用 previousBlockState 记住跨行的块注释。
        """
        strings: List[_RANGE] = []
        comments: List[_RANGE] = []
        n = len(text)
        i = 0
        in_comment = self.previousBlockState() == 1

        while i < n:
            if in_comment:
                end = text.find("*/", i)
                if end == -1:
                    comments.append((i, n - i))
                    i = n
                    break
                comments.append((i, end + 2 - i))
                i = end + 2
                in_comment = False
                continue

            two = text[i:i + 2]
            if two == "//":
                comments.append((i, n - i))
                i = n
                break
            if two == "/*":
                in_comment = True
                i += 2
                continue

            ch = text[i]
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
                strings.append((i, j - i))
                i = j
                continue

            i += 1

        self.setCurrentBlockState(1 if in_comment else 0)
        return strings, comments

    @staticmethod
    def _overlaps(ranges: List[_RANGE], start: int, length: int) -> bool:
        end = start + length
        for r_start, r_len in ranges:
            if start < r_start + r_len and r_start < end:
                return True
        return False


def completion_words() -> List[str]:
    """补全用的基础词表。"""

    return list(ALL_WORDS)
