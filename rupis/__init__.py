"""Rupis —— 面向 Minecraft 红石结构的脚本语言。

用法（作为库）：

    from rupis import run_source
    interp = run_source(open("demo.rpi", encoding="utf-8").read(), "demo.rpi")
    for placement in interp.world.values():
        print(placement.command())
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from .ast_nodes import Expr, Stmt
from .errors import LexerError, ParserError, RupisError, RuntimeErr, Source
from .interpreter import Interpreter, Placement
from .lexer import Lexer
from .parser import Parser

__all__ = [
    "RupisError",
    "LexerError",
    "ParserError",
    "RuntimeErr",
    "Source",
    "Interpreter",
    "Placement",
    "parse_source",
    "run_source",
    "compile_source",
]

__version__ = "0.1"


def compile_source(text: str, filename: str = "<string>") -> Tuple[List[Stmt], Source]:
    """词法 + 语法分析，返回 (AST, 源码)。"""

    lexer = Lexer(text, filename)
    tokens = lexer.tokenize()
    parser = Parser(tokens, lexer.source)
    program = parser.parse_program()
    return program, lexer.source


def parse_source(text: str, filename: str = "<string>") -> List[Stmt]:
    """只做语法分析（不执行），用于 --check 语法检查。"""

    return compile_source(text, filename)[0]


def run_source(
    text: str,
    filename: str = "<string>",
    verbose: bool = False,
    lib_paths: Optional[List[str]] = None,
) -> Interpreter:
    """编译并执行一段 Rupis 源码，返回解释器（里面带着 world）。

    lib_paths：lib 导入 .rpi 脚本时额外要搜的目录（当前脚本所在目录、
    当前工作目录之外的地方）。
    """

    program, source = compile_source(text, filename)
    interpreter = Interpreter(source=source, verbose=verbose, lib_paths=lib_paths)
    interpreter.run(program)
    return interpreter
