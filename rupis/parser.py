"""Rupis 语法分析器（递归下降）。

处理的语法要点：
  * 状态块紧贴指令名书写：rw{rsig=15}[dpos + x1]
  * 状态块可以省略（None）与显式写空（{}）必须区分——语义不同
  * 坐标偏移 dpos + x1 / x-2,y1,z0 / xi（xi 表示 x + 变量 i）
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from .ast_nodes import (
    AssignStmt, Attr, Binary, BreakStmt, Call, ContinueStmt, Coord, DposStmt,
    DrpStmt, Expr, ExprStmt, ForStmt, FuncDef, IfStmt, LetStmt, LibStmt, Num,
    PlaceStmt, ReturnStmt, StateValue, Str, StructCall, StructDef, Target,
    Unary, Var, WhileStmt,
)
from .blocks import ELEMENTS
from .errors import ParserError, Source
from .lexer import TOK_EOF, TOK_IDENT, TOK_NUMBER, TOK_PUNCT, TOK_STRING, Lexer, Token

# 语句开头会被当成“放置指令”的关键字
_PLACE_KEYWORDS = {"rbl", "block"}
_AXES = ("x", "y", "z")


class Parser:
    def __init__(self, tokens: List[Token], source: Optional[Source] = None) -> None:
        self.tokens = tokens
        self.i = 0
        self.source = source

    # ------------------------------------------------------------------ 工具
    def peek(self, offset: int = 0) -> Token:
        idx = self.i + offset
        if idx >= len(self.tokens):
            return self.tokens[-1]
        return self.tokens[idx]

    def advance(self) -> Token:
        tok = self.peek()
        if tok.type != TOK_EOF:
            self.i += 1
        return tok

    def check_punct(self, value: str) -> bool:
        tok = self.peek()
        return tok.type == TOK_PUNCT and tok.value == value

    def check_ident(self, value: str) -> bool:
        tok = self.peek()
        return tok.type == TOK_IDENT and tok.value == value

    def accept_punct(self, value: str) -> Optional[Token]:
        if self.check_punct(value):
            return self.advance()
        return None

    def accept_ident(self, value: str) -> Optional[Token]:
        if self.check_ident(value):
            return self.advance()
        return None

    def expect_punct(self, value: str) -> Token:
        if not self.check_punct(value):
            self.error(f"期望 '{value}'，实际得到 {self._describe(self.peek())}")
        return self.advance()

    def expect_ident(self, what: str = "标识符") -> Token:
        tok = self.peek()
        if tok.type != TOK_IDENT:
            self.error(f"期望{what}，实际得到 {self._describe(tok)}")
        return self.advance()

    def expect_keyword(self, word: str) -> Token:
        tok = self.peek()
        if tok.type != TOK_IDENT or tok.value != word:
            self.error(f"期望关键字 '{word}'，实际得到 {self._describe(tok)}")
        return self.advance()

    @staticmethod
    def _describe(tok: Token) -> str:
        if tok.type == TOK_EOF:
            return "文件结尾"
        if tok.type == TOK_STRING:
            return f"字符串 {tok.value!r}"
        return f"'{tok.value}'"

    def error(self, message: str, tok: Optional[Token] = None):
        """抛出语法错误（带行列位置）。"""

        tok = tok or self.peek()
        raise ParserError(message, tok.line, tok.col, self.source)

    # ------------------------------------------------------------------ 入口
    def parse_program(self) -> List:
        stmts = []
        while self.peek().type != TOK_EOF:
            stmt = self.parse_statement()
            if stmt is not None:
                stmts.append(stmt)
        return stmts

    def parse_block(self) -> List:
        """解析 {...} 代码块，返回其中的语句列表。"""

        self.expect_punct("{")
        stmts = []
        while not self.check_punct("}"):
            if self.peek().type == TOK_EOF:
                self.error("代码块没有闭合（缺少 }）")
            stmt = self.parse_statement()
            if stmt is not None:
                stmts.append(stmt)
        self.expect_punct("}")
        return stmts

    # ------------------------------------------------------------------ 语句
    def parse_statement(self):
        tok = self.peek()

        if tok.type == TOK_PUNCT and tok.value == ";":
            self.advance()
            return None

        if tok.type == TOK_IDENT:
            word = tok.value
            handler = {
                "dpos": self._parse_dpos,
                "drp": self._parse_drp,
                "lib": self._parse_lib,
                "let": self._parse_let,
                "if": self._parse_if,
                "for": self._parse_for,
                "while": self._parse_while,
                "def": self._parse_def,
                "strudef": self._parse_strudef,
                "stru": self._parse_stru_call,
                "return": self._parse_return,
                "break": self._parse_break,
                "continue": self._parse_continue,
            }.get(word)
            if handler is not None:
                return handler()

            if word in _PLACE_KEYWORDS:
                return self._parse_special_place()

            if word in ELEMENTS:
                return self._parse_element_place()

            # 未知标识符：如果后面紧跟 { 或 [，那它一定是想写放置指令
            nxt = self.peek(1)
            if nxt.type == TOK_PUNCT and nxt.value in ("{", "["):
                self.error(f"未知的元件指令 '{word}'", tok)

            # 扩展语法：变量赋值 name = expr;
            if nxt.type == TOK_PUNCT and nxt.value == "=":
                self.advance()
                self.advance()
                value = self.parse_expr()
                self.accept_punct(";")
                return AssignStmt(name=word, value=value, line=tok.line, col=tok.col)

        expr = self.parse_expr()
        self.accept_punct(";")
        return ExprStmt(expr=expr, line=tok.line, col=tok.col)

    # ------------------------------------------------------------- 全局配置
    def _parse_dpos(self):
        tok = self.expect_keyword("dpos")
        name_tok = self.expect_ident("dpos 变量名（例如 dpos base[100,64,200]）")
        coord = self.parse_coord()
        self.accept_punct(";")
        return DposStmt(name=name_tok.value, coord=coord, line=tok.line, col=tok.col)

    def _parse_lib(self):
        """解析 lib 语句：lib 脚本名 [as 别名]"""

        tok = self.expect_keyword("lib")
        name_tok = self.expect_ident("脚本名（例如 lib util）")
        script = name_tok.value
        # 支持 lib sub/util 这样的相对路径
        while self.check_punct("/"):
            self.advance()
            part = self.expect_ident("脚本名的一部分")
            script += "/" + part.value
        alias = ""
        if self.accept_ident("as"):
            alias = self.expect_ident("别名（例如 lib util as u）").value
        self.accept_punct(";")
        # 命名空间的名字：写了 as 就用别名，否则用脚本名最后一段
        name = alias or script.rsplit("/", 1)[-1]
        return LibStmt(script=script, name=name, alias=alias,
                       line=tok.line, col=tok.col)

    def _parse_drp(self):
        tok = self.expect_keyword("drp")
        name_tok = self.expect_ident("drp 变量名（例如 drp high{rsig=15}）")
        states, ref = self.parse_state_slot()
        self.accept_punct(";")
        return DrpStmt(name=name_tok.value, states=states, states_ref=ref,
                       line=tok.line, col=tok.col)

    # --------------------------------------------------------------- 变量
    def _parse_let(self):
        tok = self.expect_keyword("let")
        name_tok = self.expect_ident("变量名")
        self.expect_punct("=")
        value = self.parse_expr()
        self.accept_punct(";")
        return LetStmt(name=name_tok.value, value=value, line=tok.line, col=tok.col)

    # ------------------------------------------------------------- 控制流
    def _parse_if(self):
        tok = self.expect_keyword("if")
        self.expect_punct("(")
        cond = self.parse_expr()
        self.expect_punct(")")
        self.accept_punct(":")   # 冒号可省略
        then_body = self.parse_block()
        else_body = None
        if self.accept_ident("else"):
            if self.check_ident("if"):
                else_body = [self._parse_if()]
            else:
                self.accept_punct(":")   # 冒号可省略
                else_body = self.parse_block()
        return IfStmt(cond=cond, then_body=then_body, else_body=else_body,
                      line=tok.line, col=tok.col)

    def _parse_for(self):
        tok = self.expect_keyword("for")
        var_tok = self.expect_ident("循环变量名")
        self.expect_punct("=")
        self.expect_punct("(")
        start = self.parse_expr()
        self.expect_keyword("to")
        end = self.parse_expr()
        self.expect_punct(")")
        self.accept_punct(":")   # 冒号可省略
        body = self.parse_block()
        return ForStmt(var=var_tok.value, start=start, end=end, body=body,
                       line=tok.line, col=tok.col)

    def _parse_while(self):
        tok = self.expect_keyword("while")
        self.expect_punct("(")
        cond = self.parse_expr()
        self.expect_punct(")")
        self.accept_punct(":")   # 冒号可省略
        body = self.parse_block()
        return WhileStmt(cond=cond, body=body, line=tok.line, col=tok.col)

    def _parse_return(self):
        tok = self.expect_keyword("return")
        value = None
        nxt = self.peek()
        if not (nxt.type == TOK_PUNCT and nxt.value in ("}", ";")) and nxt.type != TOK_EOF:
            value = self.parse_expr()
        self.accept_punct(";")
        return ReturnStmt(value=value, line=tok.line, col=tok.col)

    def _parse_break(self):
        tok = self.expect_keyword("break")
        self.accept_punct(";")
        return BreakStmt(line=tok.line, col=tok.col)

    def _parse_continue(self):
        tok = self.expect_keyword("continue")
        self.accept_punct(";")
        return ContinueStmt(line=tok.line, col=tok.col)

    # --------------------------------------------------------- 函数 / 结构
    def _parse_def(self):
        tok = self.expect_keyword("def")
        name_tok = self.expect_ident("函数名")
        params = self.parse_param_list()
        self.accept_punct(":")   # 规范写作 def f(...):{...}，冒号可省略
        body = self.parse_block()
        return FuncDef(name=name_tok.value, params=params, body=body,
                       line=tok.line, col=tok.col)

    def _parse_strudef(self):
        tok = self.expect_keyword("strudef")
        name_tok = self.expect_ident("结构名")
        params = self.parse_param_list()
        defaults, defaults_ref = self.parse_state_slot()
        self.expect_punct(":")
        body = self.parse_block()
        return StructDef(name=name_tok.value, params=params, defaults=defaults,
                         defaults_ref=defaults_ref, body=body, line=tok.line, col=tok.col)

    def _parse_stru_call(self):
        tok = self.expect_keyword("stru")
        name_tok = self.expect_ident("结构名")
        name = name_tok.value
        # 支持 stru 模块.结构名(...) —— 用 lib 导入的脚本里的结构
        while self.check_punct("."):
            self.advance()
            name += "." + self.expect_ident("结构名的一部分").value
        args, kwargs = self.parse_call_args()
        override, override_ref = self.parse_state_slot()
        coord = None
        if self.check_punct("["):
            coord = self.parse_coord()
        self.accept_punct(";")
        return StructCall(name=name, args=args, kwargs=kwargs, override=override,
                          override_ref=override_ref, coord=coord, line=tok.line, col=tok.col)

    def parse_param_list(self) -> List[str]:
        self.expect_punct("(")
        params: List[str] = []
        if not self.check_punct(")"):
            while True:
                params.append(self.expect_ident("参数名").value)
                if not self.accept_punct(","):
                    break
        self.expect_punct(")")
        return params

    def parse_call_args(self) -> Tuple[List[Expr], Dict[str, Expr]]:
        """解析调用实参，返回 (位置参数, 关键字参数)。

        关键字参数的写法跟 Python 一样：f(a, b=1)
        """
        self.expect_punct("(")
        args: List[Expr] = []
        kwargs: Dict[str, Expr] = {}
        if not self.check_punct(")"):
            while True:
                # 形如 名字 = 表达式 → 关键字参数
                if (self.peek().type == TOK_IDENT
                        and self.peek(1).type == TOK_PUNCT
                        and self.peek(1).value == "="):
                    key = self.advance().value
                    self.advance()  # 吃掉 =
                    kwargs[key] = self.parse_expr()
                else:
                    args.append(self.parse_expr())
                if not self.accept_punct(","):
                    break
        self.expect_punct(")")
        return args, kwargs

    # ------------------------------------------------------------- 放置指令
    def _parse_element_place(self):
        tok = self.advance()  # 元件指令名
        target = Target(kind="element", name=tok.value)
        return self._finish_place(target, tok)

    def _parse_special_place(self):
        tok = self.advance()  # rbl / block
        if tok.value == "rbl":
            name_tok = self.expect_ident("方块缩写")
            target = Target(kind="rbl", name=name_tok.value)
        else:  # block
            target = Target(kind="block", name=self._parse_block_id())
        return self._finish_place(target, tok)

    def _parse_block_id(self) -> str:
        first = self.expect_ident("方块 ID")
        if self.check_punct(":"):
            self.advance()
            second = self.expect_ident("方块 ID")
            return f"{first.value}:{second.value}"
        return first.value

    def _finish_place(self, target: Target, tok: Token) -> PlaceStmt:
        states, ref = self.parse_state_slot()
        coord = None
        if self.check_punct("["):
            coord = self.parse_coord()
        self.accept_punct(";")
        return PlaceStmt(target=target, states=states, states_ref=ref, coord=coord,
                         line=tok.line, col=tok.col)

    # --------------------------------------------------------------- 状态块
    def parse_state_slot(self):
        """解析状态槽，返回 (显式状态字典 或 None, drp 变量名 或 None)。

        两种写法：
            {键=值, 键2=值2}   显式状态
            {drp变量名}         引用一个 drp 状态模板变量
        没写状态槽时返回 (None, None)。
        """

        if not self.check_punct("{"):
            return None, None

        self.expect_punct("{")
        if self.check_punct("}"):
            self.advance()
            return {}, None  # 显式空状态块

        tok = self.peek()
        nxt = self.peek(1)
        is_reference = tok.type == TOK_IDENT and not (
            nxt.type == TOK_PUNCT and nxt.value == "="
        )
        if is_reference:
            self.advance()
            name = tok.value
            if self.check_punct(","):
                self.error("状态槽里不能把 drp 变量名和键值对混在一起", tok)
            self.expect_punct("}")
            return None, name

        states = self.parse_state_pairs()
        return states, None

    def parse_state_pairs(self) -> dict:
        states: dict = {}
        while not self.check_punct("}"):
            if self.peek().type == TOK_EOF:
                self.error("状态块没有闭合（缺少 }）")
            key_tok = self.expect_ident("状态键名")
            self.expect_punct("=")
            # 用完整的表达式，状态值里也能写 math.floor(3.7) 这种
            value = self.parse_expr()
            states[key_tok.value] = StateValue(
                expr=value, line=key_tok.line, col=key_tok.col
            )
            if not self.accept_punct(","):
                break
        self.expect_punct("}")
        return states

    # ----------------------------------------------------------------- 坐标
    def parse_coord(self) -> Coord:
        """解析坐标槽。

        三种写法：
            [x,y,z]            绝对三元组
            [dpos变量名]        引用一个 dpos 坐标变量
            [dpos变量名 + x1]   引用变量后再叠加偏移
        """

        start = self.peek()
        self.expect_punct("[")

        # 变量引用形式：[名称] 或 [名称 + 偏移]
        if self.peek().type == TOK_IDENT:
            nxt = self.peek(1)
            if nxt.type == TOK_PUNCT and nxt.value in ("]", "+"):
                tok = self.advance()
                offsets: List[Tuple[str, Expr]] = []
                if self.accept_punct("+"):
                    offsets = self.parse_coord_offsets()
                self.expect_punct("]")
                return Coord(kind="var", name=tok.value, offsets=offsets,
                             line=start.line, col=start.col)

        # 绝对三元组 [x,y,z]
        offsets = []
        for axis in _AXES:
            expr = self.parse_expr()
            offsets.append((axis, expr))
            if axis != "z":
                self.expect_punct(",")
        self.expect_punct("]")
        return Coord(kind="abs", offsets=offsets, line=start.line, col=start.col)

    def parse_coord_offsets(self) -> List[Tuple[str, Expr]]:
        """解析坐标变量后面跟的偏移列表。

        支持的写法：
            x1        常数偏移
            x-2       负数偏移
            xi        用变量 i 作为该轴的偏移量（i 是变量名）
            x20+3     带算术运算的偏移
            z+i       等价于 zi
            x0,y1,z0 同时给出三个轴
        """

        offsets: List[Tuple[str, Expr]] = []
        while True:
            tok = self.expect_ident("坐标偏移（形如 x1、xi）")
            axis = tok.value[0].lower()
            if axis not in _AXES:
                self.error(f"坐标偏移轴只能是 x / y / z，收到 '{tok.value}'", tok)
            rest = tok.value[1:]

            if rest.isdigit():
                value: Expr = Num(value=int(rest), line=tok.line, col=tok.col)
            elif rest and (rest[0].isalpha() or rest[0] == "_"):
                value = Var(name=rest, line=tok.line, col=tok.col)
            elif rest == "":
                # 形如 x-2 / x 5 / x i / z+i
                if self.check_punct("+"):
                    self.advance()
                    value = self.parse_unary()
                else:
                    value = self.parse_unary()
            else:
                self.error(f"无法解析的坐标偏移 '{tok.value}'", tok)

            # 允许继续写算术运算，例如 x20+3
            while self.check_punct("+") or self.check_punct("-") or self.check_punct("*") or self.check_punct("/"):
                op_tok = self.advance()
                right = self.parse_mul()
                value = Binary(op=op_tok.value, left=value, right=right,
                               line=op_tok.line, col=op_tok.col)

            offsets.append((axis, value))
            if not self.accept_punct(","):
                break
        return offsets

    # --------------------------------------------------------------- 表达式
    def parse_expr(self) -> Expr:
        return self.parse_or()

    def parse_or(self) -> Expr:
        left = self.parse_and()
        while self.check_punct("||"):
            tok = self.advance()
            right = self.parse_and()
            left = Binary(op="||", left=left, right=right, line=tok.line, col=tok.col)
        return left

    def parse_and(self) -> Expr:
        left = self.parse_cmp()
        while self.check_punct("&&"):
            tok = self.advance()
            right = self.parse_cmp()
            left = Binary(op="&&", left=left, right=right, line=tok.line, col=tok.col)
        return left

    def parse_cmp(self) -> Expr:
        left = self.parse_add()
        for op in ("==", "!=", ">=", "<=", ">", "<"):
            if self.check_punct(op):
                tok = self.advance()
                right = self.parse_add()
                left = Binary(op=op, left=left, right=right, line=tok.line, col=tok.col)
                break
        return left

    def parse_add(self) -> Expr:
        left = self.parse_mul()
        while self.check_punct("+") or self.check_punct("-"):
            tok = self.advance()
            right = self.parse_mul()
            left = Binary(op=tok.value, left=left, right=right, line=tok.line, col=tok.col)
        return left

    def parse_mul(self) -> Expr:
        left = self.parse_unary()
        while self.check_punct("*") or self.check_punct("/") or self.check_punct("%"):
            tok = self.advance()
            right = self.parse_unary()
            left = Binary(op=tok.value, left=left, right=right, line=tok.line, col=tok.col)
        return left

    def parse_unary(self) -> Expr:
        if self.check_punct("-"):
            tok = self.advance()
            operand = self.parse_unary()
            return Unary(op="-", operand=operand, line=tok.line, col=tok.col)
        if self.check_punct("!"):
            tok = self.advance()
            operand = self.parse_unary()
            return Unary(op="!", operand=operand, line=tok.line, col=tok.col)
        return self.parse_primary()

    def parse_primary(self) -> Expr:
        tok = self.peek()
        if tok.type == TOK_NUMBER:
            self.advance()
            return Num(value=tok.value, line=tok.line, col=tok.col)
        if tok.type == TOK_STRING:
            self.advance()
            return Str(value=tok.value, line=tok.line, col=tok.col)
        if tok.type == TOK_IDENT:
            self.advance()
            expr: Expr = Var(name=tok.value, line=tok.line, col=tok.col)
            # 属性访问：math.sqrt 这种（lib 导入的模块靠它用）
            while self.check_punct("."):
                dot = self.advance()
                attr = self.expect_ident("属性名")
                expr = Attr(value=expr, name=attr.value, line=dot.line, col=dot.col)
            if self.check_punct("("):
                args, kwargs = self.parse_call_args()
                if isinstance(expr, Var):
                    return Call(name=expr.name, args=args, kwargs=kwargs,
                                line=tok.line, col=tok.col)
                return Call(func=expr, args=args, kwargs=kwargs,
                            line=tok.line, col=tok.col)
            return expr
        if tok.type == TOK_PUNCT and tok.value == "(":
            self.advance()
            expr = self.parse_expr()
            self.expect_punct(")")
            return expr
        self.error(f"无法解析的表达式 {self._describe(tok)}", tok)


def parse(text: str, filename: str = "<string>") -> List:
    """词法 + 语法分析，返回 AST 顶层语句列表。"""

    lexer = Lexer(text, filename)
    tokens = lexer.tokenize()
    parser = Parser(tokens, lexer.source)
    return parser.parse_program()
