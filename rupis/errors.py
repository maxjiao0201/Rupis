"""Rupis 错误类型与源码定位支持。

所有解释器错误都会携带尽可能精确的行列信息，方便用户定位 .rpi 源码。

错误层次：
    RupisError   —— 基类，带行列号和源码；
    LexerError   —— 词法分析阶段；
    ParserError  —— 语法分析阶段；
    RuntimeErr   —— 运行阶段（未定义变量、参数不匹配等）。
"""

from __future__ import annotations

from typing import List, Optional


class Source:
    """保存源码文本，用于错误信息里打印出错的行。

    text：完整脚本文本；
    filename：报错时显示的文件名；
    lines：按行切开的源码，方便按行号取出错行。
    """

    def __init__(self, text: str, filename: str = "<string>") -> None:
        self.text = text
        self.filename = filename
        self.lines: List[str] = text.splitlines()

    def snippet(self, line: int, col: Optional[int] = None) -> str:
        """返回出错行（以及箭头指示）的可视化片段。

        片段最多两行：第一行是「右对齐到 4 位的行号 + " | " + 出错那行的原文」；
        给了 col 才有第二行，用同样宽度的空白加一个 ^，把出错的那一列指出来。
        行号超出源码范围时返回空串。
        """
        if line < 1 or line > len(self.lines):
            return ""
        text = self.lines[line - 1]
        gutter = f"{line:>4} | "
        out = gutter + text
        if col and col > 0:
            # 箭头先跳过行号栏，再空出 col-1 个空格对准出错的那一列
            out += "\n" + " " * len(gutter) + " " * (col - 1) + "^"
        return out


class RupisError(Exception):
    """Rupis 解释器的通用错误基类。

    message：错误描述；
    line / col：出错的行号与列号（1 开始，没有就留空）；
    source：源码对象，给出后 render() 能附带出错行。
    """

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
        """把错误渲染成给用户看的多行文本。

        第一行是「错误（第 N 行，第 M 列）: 消息」，行列号没有就不写；
        后面如果有源码，再接一行 snippet() 生成的出错行片段。
        """

        head = "错误"
        if self.line is not None:
            # 列号可能有也可能没有，所以要分开拼
            head += f"（第 {self.line} 行"
            head += f"，第 {self.col} 列）" if self.col is not None else "）"
        out = f"{head}: {self.message}"
        # 只有拿到了源码、且知道行号，才能附上出错的那一行
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
