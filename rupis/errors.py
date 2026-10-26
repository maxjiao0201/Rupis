"""Rupis 错误类型与源码定位支持。

所有解释器错误都会携带尽可能精确的行列信息，方便用户定位 .rpi 源码。
"""

from __future__ import annotations

from typing import List, Optional


class Source:
    """保存源码文本，用于错误信息里打印出错的行。"""

    def __init__(self, text: str, filename: str = "<string>") -> None:
        self.text = text
        self.filename = filename
        self.lines: List[str] = text.splitlines()

    def snippet(self, line: int, col: Optional[int] = None) -> str:
        """返回出错行（以及箭头指示）的可视化片段。"""
        if line < 1 or line > len(self.lines):
            return ""
        text = self.lines[line - 1]
        gutter = f"{line:>4} | "
        out = gutter + text
        if col and col > 0:
            out += "\n" + " " * len(gutter) + " " * (col - 1) + "^"
        return out


class RupisError(Exception):
    """Rupis 解释器的通用错误基类。"""

    def __init__(
        self,
        message: str,
        line: Optional[int] = None,
        col: Optional[int] = None,
        source: Optional[Source] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.line = line
        self.col = col
        self.source = source

    def render(self) -> str:
        head = "错误"
        if self.line is not None:
            head += f"（第 {self.line} 行"
            head += f"，第 {self.col} 列）" if self.col is not None else "）"
        out = f"{head}: {self.message}"
        if self.source is not None and self.line is not None:
            snippet = self.source.snippet(self.line, self.col)
            if snippet:
                out += "\n" + snippet
        return out


class LexerError(RupisError):
    """词法分析阶段出错。"""


class ParserError(RupisError):
    """语法分析阶段出错。"""


class RuntimeErr(RupisError):
    """运行阶段出错（未定义变量、参数不匹配等）。"""
