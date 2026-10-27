"""Rupis 抽象语法树（AST）节点定义。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


# --------------------------------------------------------------------- 表达式
@dataclass
class Expr:
    line: int = 0
    col: int = 0


@dataclass
class Num(Expr):
    value: Any = 0


@dataclass
class Str(Expr):
    value: str = ""


@dataclass
class Var(Expr):
    name: str = ""


@dataclass
class Unary(Expr):
    op: str = "-"
    operand: Optional[Expr] = None


@dataclass
class Binary(Expr):
    op: str = "+"
    left: Optional[Expr] = None
    right: Optional[Expr] = None


@dataclass
class Attr(Expr):
    """属性访问：对象.属性

    主要是给 lib 导入的模块用的 —— math.sqrt 里的 sqrt。
    """

    value: Optional[Expr] = None
    name: str = ""


@dataclass
class Call(Expr):
    name: str = ""                       # 直接按名字调用（Rupis 的 def 函数）
    args: List[Expr] = field(default_factory=list)
    kwargs: Dict[str, Expr] = field(default_factory=dict)   # 关键字参数
    func: Optional[Expr] = None          # 按表达式调用（模块.函数(...)）


# ----------------------------------------------------------------------- 坐标
@dataclass
class Coord(Expr):
    """坐标表达式。

    kind == "var"  : 以 dpos 变量（name）的坐标为基准，再叠加 offsets
    kind == "abs"  : 以作用域原点（世界原点或结构原点）为基准，再叠加 offsets
    offsets        : [(轴, 表达式)]，轴为 "x" / "y" / "z"
    """

    kind: str = "abs"
    name: str = ""
    offsets: List[Tuple[str, Expr]] = field(default_factory=list)


@dataclass
class StateValue:
    """状态块里的一个 `键=值`，记住键的位置以便精确报错。"""

    expr: Optional[Expr] = None
    line: int = 0
    col: int = 0


# ----------------------------------------------------------------------- 语句
@dataclass
class Stmt:
    line: int = 0
    col: int = 0


@dataclass
class DposStmt(Stmt):
    """声明一个 dpos 坐标变量：dpos 名称[x,y,z]"""

    name: str = ""
    coord: Optional[Coord] = None


@dataclass
class DrpStmt(Stmt):
    """声明一个 drp 状态模板变量：drp 名称{键=值}"""

    name: str = ""
    states: Optional[Dict[str, StateValue]] = None   # None 表示引用另一个 drp 变量
    states_ref: Optional[str] = None


@dataclass
class LetStmt(Stmt):
    name: str = ""
    value: Optional[Expr] = None


@dataclass
class AssignStmt(Stmt):
    """扩展语法：直接给已有变量赋值（变量不存在则视为新建）。"""

    name: str = ""
    value: Optional[Expr] = None


@dataclass
class IfStmt(Stmt):
    cond: Optional[Expr] = None
    then_body: List[Stmt] = field(default_factory=list)
    else_body: Optional[List[Stmt]] = None


@dataclass
class ForStmt(Stmt):
    var: str = ""
    start: Optional[Expr] = None
    end: Optional[Expr] = None
    body: List[Stmt] = field(default_factory=list)


@dataclass
class WhileStmt(Stmt):
    cond: Optional[Expr] = None
    body: List[Stmt] = field(default_factory=list)


@dataclass
class ReturnStmt(Stmt):
    value: Optional[Expr] = None


@dataclass
class BreakStmt(Stmt):
    pass


@dataclass
class ContinueStmt(Stmt):
    pass


@dataclass
class ExprStmt(Stmt):
    expr: Optional[Expr] = None


@dataclass
class LibStmt(Stmt):
    """导入一个 .rpi 脚本：lib 脚本名 [as 别名]

    导入的是别的 Rupis 脚本，不是 Python 模块：
        lib util          导入 util.rpi
        lib util as u     还是 util.rpi，但绑成 u
        lib sub/util      导入子目录里的 util.rpi

    导入后会得到两样东西：
        1. 一个命名空间对象（util / u），用 util.函数(...) 调
        2. 脚本里的 def / strudef 直接按原名出现在当前脚本里
    """

    script: str = ""      # 要导入的脚本名，如 "util" 或 "sub/util"
    name: str = ""        # 绑定到作用域里的命名空间名字
    alias: str = ""       # 写了 as 时的别名（没写就是空）


@dataclass
class Target:
    """放置目标。"""

    kind: str = "element"  # element | rbl | block
    name: str = ""


@dataclass
class PlaceStmt(Stmt):
    target: Optional[Target] = None
    # 状态槽有三种形态：
    #   states 为 None 且 states_ref 为 None → 没写状态槽
    #   states 为 {}                      → 写了空状态块
    #   states_ref 有值                    → 引用了一个 drp 变量
    states: Optional[Dict[str, StateValue]] = None
    states_ref: Optional[str] = None
    coord: Optional[Coord] = None


@dataclass
class FuncDef(Stmt):
    name: str = ""
    params: List[str] = field(default_factory=list)
    body: List[Stmt] = field(default_factory=list)


@dataclass
class StructDef(Stmt):
    name: str = ""
    params: List[str] = field(default_factory=list)
    defaults: Optional[Dict[str, StateValue]] = None
    defaults_ref: Optional[str] = None
    body: List[Stmt] = field(default_factory=list)


@dataclass
class StructCall(Stmt):
    name: str = ""
    args: List[Expr] = field(default_factory=list)
    kwargs: Dict[str, Expr] = field(default_factory=dict)
    override: Optional[Dict[str, StateValue]] = None
    override_ref: Optional[str] = None
    coord: Optional[Coord] = None
