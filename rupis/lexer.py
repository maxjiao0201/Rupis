"""Rupis 词法分析器。

把 .rpi 源码切成 token 流：
    - 标识符（字母/数字/下划线，不能以数字开头，区分大小写）
    - 数字（整数与小数）
    - 字符串（"..." 或 '...'）
    - 标点符号
    - 注释：// 行注释、/* ... */ 块注释（规范中的 /** ... **/ 同样适用）
"""

from __future__ import annotations

from typing import List, Optional

from .errors import LexerError, Source

TOK_IDENT = "IDENT"
TOK_NUMBER = "NUMBER"
TOK_STRING = "STRING"
TOK_PUNCT = "PUNCT"
TOK_EOF = "EOF"

# 多字符符号必须排在前面（最长匹配）
PUNCTUATORS = [
    "==", "!=", ">=", "<=", "&&", "||",
    "{", "}", "(", ")", "[", "]", ",", ":", ";", "=",
    ">", "<", "+", "-", "*", "/", "%", "!", ".",
]

_IDENT_START = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_")
_IDENT_BODY = _IDENT_START | set("0123456789")
_DIGITS = set("0123456789")


class Token:
    __slots__ = ("type", "value", "line", "col")

    def __init__(self, type_: str, value, line: int, col: int) -> None:
        self.type = type_
        self.value = value
        self.line = line
        self.col = col

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"Token({self.type}, {self.value!r}, {self.line}:{self.col})"


class Lexer:
    def __init__(self, text: str, filename: str = "<string>") -> None:
        self.text = text
        self.filename = filename
        self.source = Source(text, filename)
        self.pos = 0
        self.line = 1
        self.col = 1
        self.tokens: List[Token] = []

    # ------------------------------------------------------------------ 工具
    def _error(self, message: str, line: Optional[int] = None, col: Optional[int] = None) -> LexerError:
        return LexerError(message, line or self.line, col or self.col, self.source)

    def _peek(self, offset: int = 0) -> str:
        idx = self.pos + offset
        if idx >= len(self.text):
            return ""
        return self.text[idx]

    def _advance(self) -> str:
        ch = self.text[self.pos]
        self.pos += 1
        if ch == "\n":
            self.line += 1
            self.col = 1
        else:
            self.col += 1
        return ch

    # ------------------------------------------------------------------ 主流程
    def tokenize(self) -> List[Token]:
        n = len(self.text)
        while self.pos < n:
            ch = self.text[self.pos]

            if ch in " \t\r\n":
                self._advance()
                continue

            # 行注释 //
            if ch == "/" and self._peek(1) == "/":
                while self.pos < n and self.text[self.pos] != "\n":
                    self._advance()
                continue

            # 块注释 /* ... */ （兼容规范里的 /** ... **/ 写法）
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
        line, col = self.line, self.col
        start = self.pos
        while self.pos < len(self.text) and self.text[self.pos] in _IDENT_BODY:
            self._advance()
        self.tokens.append(Token(TOK_IDENT, self.text[start:self.pos], line, col))

    def _read_number(self) -> None:
        line, col = self.line, self.col
        start = self.pos
        while self.pos < len(self.text) and self.text[self.pos] in _DIGITS:
            self._advance()
        is_float = False
        if self._peek() == "." and self._peek(1) in _DIGITS:
            is_float = True
            self._advance()
            while self.pos < len(self.text) and self.text[self.pos] in _DIGITS:
                self._advance()
        raw = self.text[start:self.pos]
        value = float(raw) if is_float else int(raw)
        self.tokens.append(Token(TOK_NUMBER, value, line, col))

    def _read_string(self) -> None:
        line, col = self.line, self.col
        quote = self._advance()
        buf = []
        while True:
            if self.pos >= len(self.text):
                raise self._error("字符串没有闭合", line, col)
            ch = self._advance()
            if ch == quote:
                break
            if ch == "\\" and self.pos < len(self.text):
                nxt = self._advance()
                buf.append({"n": "\n", "t": "\t", "r": "\r"}.get(nxt, nxt))
                continue
            buf.append(ch)
        self.tokens.append(Token(TOK_STRING, "".join(buf), line, col))
