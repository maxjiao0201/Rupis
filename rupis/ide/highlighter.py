"""Rupis 语法高亮器。

基于 QSyntaxHighlighter，一次扫描同时处理：
    - 单行注释 //
    - 块注释 /* ... */（可跨行，用 block state 记住）
    - 字符串 "..." / '...'
    - 关键字 / 元件 / 常量 / 数字 / 结构与函数名

上色的优先级从低到高：
    关键字 / 元件 / 常量  →  数字  →  结构名与函数名  →  字符串与注释
字符串和注释放在最后，是为了盖住它们内部那些"看起来像关键字"的字样。
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from .qtcompat import QtCore, QtGui
from .syntax import ALL_WORDS, classify

_RANGE = Tuple[int, int]  # (起点, 长度)


class RupisHighlighter(QtGui.QSyntaxHighlighter):
    """Rupis 源码的语法高亮器。

    规则是这样定的：
        * 名字命中 syntax.py 的词表 → 按关键字 / 元件 / 常量分别上色；
        * 不在词表里、但后面（跳过空格与制表符）紧跟左括号 → 当作结构名或函数名；
        * 数字只认整数和小数；
        * 字符串与注释最后上色，会盖掉前面所有颜色。

    跨行的块注释靠 previousBlockState / setCurrentBlockState 记住状态。
    """

    def __init__(self, document, theme: Dict[str, str]) -> None:
        super().__init__(document)
        self.theme = theme
        self._rx_word = QtCore.QRegularExpression(r"[A-Za-z_][A-Za-z0-9_]*")
        self._rx_number = QtCore.QRegularExpression(r"\b\d+(\.\d+)?\b")
        self._fmts = self._build_formats()

    # ------------------------------------------------------------------ 格式
    def _build_formats(self) -> Dict[str, QtGui.QTextCharFormat]:
        """按主题生成每种 token 对应的字符格式。"""

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
        """换主题：重建格式并让整篇文档重新高亮一遍。"""

        self.theme = theme
        self._fmts = self._build_formats()
        self.rehighlight()

    # ------------------------------------------------------------------ 主流程
    def highlightBlock(self, text: str) -> None:
        """高亮一整行（QSyntaxHighlighter 的回调入口）。"""

        strings, comments = self._scan(text)

        # 单词：关键字 / 元件 / 常量 / 函数名
        it = self._rx_word.globalMatch(text)
        while it.hasNext():
            match = it.next()
            start, length = match.capturedStart(), match.capturedLength()
            # 落在字符串或注释里的词不上色
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
        # 上一行结束时还停在块注释里？那这一行开头就是注释
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
                        # 转义符：跳过它和它后面那个字符
                        j += 2
                        continue
                    if text[j] == ch:
                        j += 1
                        break
                    j += 1
                else:
                    # 字符串没有闭合，撑到行尾
                    j = n
                strings.append((i, j - i))
                i = j
                continue

            i += 1

        # 行尾还停在块注释里，就把状态留给下一行
        self.setCurrentBlockState(1 if in_comment else 0)
        return strings, comments

    @staticmethod
    def _overlaps(ranges: List[_RANGE], start: int, length: int) -> bool:
        """区间 (start, start+length) 是否和 ranges 里任何一段相交。"""

        end = start + length
        for r_start, r_len in ranges:
            if start < r_start + r_len and r_start < end:
                return True
        return False


def completion_words() -> List[str]:
    """补全用的基础词表。"""

    return list(ALL_WORDS)
