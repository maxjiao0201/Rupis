"""Rupis 词法分析器。

把 .rpi 源码切成 token 流：
    - 标识符（字母/数字/下划线，不能以数字开头，区分大小写）
    - 数字（整数与小数）
    - 字符串（"..." 或 '...'）
    - 标点符号
    - 注释：// 行注释、/* ... */ 块注释（规范中的 /** ... **/ 同样适用）

token 怎么表示：
    每个 token 是一个 Token 实例，用「类型标记 + 值 + 行列」三段描述：
        type   —— 类型标记，取下面的 TOK_* 常量之一
        value  —— 字面内容：标识符和数字存字面量，标点存符号本身，
                   字符串存去掉引号并解开转义后的文本，EOF 存 None
        line   —— 起始行号（1 起算）
        col    —— 起始列号（1 起算）
    行列按字符记，注释和字符串里的字符同样占位置。

几个关键规则：
    * 注释不产生 token：// 吃到行尾，/* */ 吃到闭合的 */，两种都能跨行；
    * 数字：小数点后必须紧跟数字才算小数，否则 "." 当成属性访问符；
    * 字符串：单双引号都行，闭合要用开头那个引号；反斜杠转义只把 n、t、r
      三个字母还原成换行、制表符、回车，其余字符原样保留；
    * 本模块只管切词，不做语法判断：if、for、rw 这些关键字和普通标识符
      长得一样，究竟是关键字还是变量由语法分析器按上下文决定。
"""

from __future__ import annotations

from typing import List, Optional

from .errors import LexerError, Source

# token 的类型标记：只是普通字符串常量，打印调试时一眼就能看出类型
TOK_IDENT = "IDENT"
TOK_NUMBER = "NUMBER"
TOK_STRING = "STRING"
TOK_PUNCT = "PUNCT"
TOK_EOF = "EOF"

# 多字符符号必须排在前面（最长匹配）
# 例如 "==" 必须排在 "=" 前面，否则 "==" 会被切成两个 "="。
PUNCTUATORS = [
    "==", "!=", ">=", "<=", "&&", "||",
    "{", "}", "(", ")", "[", "]", ",", ":", ";", "=",
    ">", "<", "+", "-", "*", "/", "%", "!", ".",
]
# 注意 "//" 和 "/*" 不在这张表里：它们先被当成注释处理，
# 单独的 "/" 才是除号。

# 标识符允许的字符：首字符不能是数字，后面可以接着写数字
_IDENT_START = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_")
_IDENT_BODY = _IDENT_START | set("0123456789")
_DIGITS = set("0123456789")


class Token:
    """切出来的一个词：类型标记 + 字面值 + 起始行列。"""

    # 用 __slots__ 限制属性，既省内存也能挡住拼错的字段名
    __slots__ = ("type", "value", "line", "col")

    def __init__(self, type_: str, value, line: int, col: int) -> None:
        """构造一个 token。

        type_ —— TOK_* 之一
        value —— token 的字面内容
        line / col —— 起始行列，均从 1 开始算
        """

        self.type = type_
        self.value = value
        self.line = line
        self.col = col

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"Token({self.type}, {self.value!r}, {self.line}:{self.col})"


class Lexer:
    """把一段 .rpi 源码切成 token 列表的词法分析器。"""

    def __init__(self, text: str, filename: str = "<string>") -> None:
        """记录源码并把扫描位置复位到开头。

        text —— 源码全文
        filename —— 报错时显示的文件名（IDE 里传真实路径）
        """

        self.text = text
        self.filename = filename
        # Source 留着源码，错误信息里要把出错的那一行打印出来
        self.source = Source(text, filename)
        # pos 是当前字符在 text 里的下标；line / col 是 1 起算的行列
        self.pos = 0
        self.line = 1
        self.col = 1
        self.tokens: List[Token] = []

    # ------------------------------------------------------------------ 工具
    def _error(self, message: str, line: Optional[int] = None, col: Optional[int] = None) -> LexerError:
        """造一个带行列位置的词法错误（不给位置就用当前扫描位置）。"""

        return LexerError(message, line or self.line, col or self.col, self.source)

    def _peek(self, offset: int = 0) -> str:
        """往前看 offset 个字符；越过文件末尾返回空串。"""

        idx = self.pos + offset
        if idx >= len(self.text):
            return ""
        return self.text[idx]

    def _advance(self) -> str:
        """吃掉当前字符并前进一位，同时维护行列号。"""

        ch = self.text[self.pos]
        self.pos += 1
        if ch == "\n":
            # 换行后列号归 1，行号加 1
            self.line += 1
            self.col = 1
        else:
            self.col += 1
        return ch

    # ------------------------------------------------------------------ 主流程
    def tokenize(self) -> List[Token]:
        """扫描全文，返回 token 列表（末尾附一个 EOF token）。"""

        n = len(self.text)
        while self.pos < n:
            ch = self.text[self.pos]

            if ch in " \t\r\n":
                # 空白直接跳过，不产生 token
                self._advance()
                continue

            # 行注释 //
            # 一直吃到行尾，行尾的换行符留给下一轮当空白处理
            if ch == "/" and self._peek(1) == "/":
                while self.pos < n and self.text[self.pos] != "\n":
                    self._advance()
                continue

            # 块注释 /* ... */ （兼容规范里的 /** ... **/ 写法）
            # 可以跨行；文件结束时还没闭合就报错，并指向注释开头
            if ch == "/" and self._peek(1) == "*":
                start_line, start_col = self.line, self.col
                self._advance()
                self._advance()
                while True:
                    if self.pos >= n:
                        raise self._error("块注释没有闭合（缺少 */）", start_line, start_col)
                    if self.text[self.pos] == "*" and self._peek(1) == "/":
                        self._advance()
                        self._advance()
                        break
                    self._advance()
                continue

            if ch in _IDENT_START:
                self._read_identifier()
                continue

            if ch in _DIGITS:
                self._read_number()
                continue

            if ch in "\"'":
                self._read_string()
                continue

            matched = None
            for punct in PUNCTUATORS:
                # startswith 就是最长匹配的前提：多字符符号已经排在前面
                if self.text.startswith(punct, self.pos):
                    matched = punct
                    break
            if matched is None:
                raise self._error(f"无法识别的字符 {ch!r}")

            line, col = self.line, self.col
            for _ in matched:
                self._advance()
            self.tokens.append(Token(TOK_PUNCT, matched, line, col))
            continue

        self.tokens.append(Token(TOK_EOF, None, self.line, self.col))
        return self.tokens

    # ------------------------------------------------------------------ 各类 token
    def _read_identifier(self) -> None:
        """读取一个标识符：字母或下划线开头，后面可以接着写数字。"""

        line, col = self.line, self.col
        start = self.pos
        while self.pos < len(self.text) and self.text[self.pos] in _IDENT_BODY:
            self._advance()
        self.tokens.append(Token(TOK_IDENT, self.text[start:self.pos], line, col))

    def _read_number(self) -> None:
        """读取一个数字字面量，转成 int 或 float。"""

        line, col = self.line, self.col
        start = self.pos
        while self.pos < len(self.text) and self.text[self.pos] in _DIGITS:
            self._advance()
        is_float = False
        # 小数点后必须还有数字，否则这个 "." 留给语法分析器当属性访问符
        if self._peek() == "." and self._peek(1) in _DIGITS:
            is_float = True
            self._advance()
            while self.pos < len(self.text) and self.text[self.pos] in _DIGITS:
                self._advance()
        raw = self.text[start:self.pos]
        value = float(raw) if is_float else int(raw)
        self.tokens.append(Token(TOK_NUMBER, value, line, col))

    def _read_string(self) -> None:
        """读取一个字符串字面量：去掉两端的引号，并解开反斜杠转义。"""

        line, col = self.line, self.col
        quote = self._advance()   # 先记住是单引号还是双引号，闭合时要用同一个
        buf = []
        while True:
            if self.pos >= len(self.text):
                raise self._error("字符串没有闭合", line, col)
            ch = self._advance()
            if ch == quote:
                break
            if ch == "\\" and self.pos < len(self.text):
                # 转义只认 n / t / r 三个字母，其余字符原样保留
                nxt = self._advance()
                buf.append({"n": "\n", "t": "\t", "r": "\r"}.get(nxt, nxt))
                continue
            buf.append(ch)
        self.tokens.append(Token(TOK_STRING, "".join(buf), line, col))
