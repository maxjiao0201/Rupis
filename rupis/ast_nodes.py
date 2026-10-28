"""Rupis 抽象语法树（AST）节点定义。

这里只描述「语法长什么样」，不含任何求值逻辑；怎么执行由解释器负责。

节点分两大类：
    Expr —— 表达式，能算出一个值（数字、字符串、变量、算式……）
    Stmt —— 语句，做一件事（放方块、赋值、跳转、定义函数……）

字段上的通用约定：
    * 每个节点都带 line / col，指向它在源码里的位置，报错时直接用；
    * 值为 None 表示「这一项没写」（没写状态槽、没写 else 等等）；
    * 列表和字典都用 field(default_factory=...) 生成空容器，
      免得所有实例共用同一个可变默认值。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


# --------------------------------------------------------------------- 表达式
@dataclass
class Expr:
    """所有表达式的基类：只记位置，具体含义由子类补。"""

    line: int = 0            # 源码行号（1 起算）
    col: int = 0             # 源码列号（1 起算）


@dataclass
class Num(Expr):
    """数字字面量。"""

    value: Any = 0           # int 或 float


@dataclass
class Str(Expr):
    """字符串字面量：引号已去掉、转义已解开。"""

    value: str = ""


@dataclass
class Var(Expr):
    """变量名：普通变量、dpos 坐标变量、drp 状态模板变量共用这一种。"""

    name: str = ""           # 变量名


@dataclass
class Unary(Expr):
    """一元运算：负号 -x 或者取反 !x。"""

    op: str = "-"            # 运算符："-" 或 "!"
    operand: Optional[Expr] = None   # 被运算的表达式


@dataclass
class Binary(Expr):
    """二元运算：算术、比较、逻辑都用它。"""

    op: str = "+"            # 运算符：+ - * / % == != > < >= <= && ||
    left: Optional[Expr] = None    # 左操作数
    right: Optional[Expr] = None   # 右操作数


@dataclass
class Attr(Expr):
    """属性访问：对象.属性

    主要是给 lib 导入的模块用的 —— math.sqrt 里的 sqrt。
    """

    value: Optional[Expr] = None   # 被访问的对象（通常是 Var）
    name: str = ""                 # 属性名


@dataclass
class Call(Expr):
    """函数调用。name 与 func 二选一：

        name 非空 —— 按名字调用本脚本里 def 出来的函数
        func 非空 —— 按表达式调用，典型是 模块.函数(...)
    """

    name: str = ""                       # 直接按名字调用（Rupis 的 def 函数）
    args: List[Expr] = field(default_factory=list)   # 位置实参，按书写顺序
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

    kind: str = "abs"        # "var"（引用 dpos 变量）或 "abs"（绝对三元组）
    name: str = ""           # kind 为 "var" 时的 dpos 变量名
    offsets: List[Tuple[str, Expr]] = field(default_factory=list)   # 各轴要叠加的偏移


@dataclass
class StateValue:
    """状态块里的一个 `键=值`，记住键的位置以便精确报错。"""

    expr: Optional[Expr] = None   # 状态值的表达式，求值后才变成真正的值
    line: int = 0            # 键所在的行
    col: int = 0             # 键所在的列


# ----------------------------------------------------------------------- 语句
@dataclass
class Stmt:
    """所有语句的基类：只记位置，具体含义由子类补。"""

    line: int = 0            # 源码行号（1 起算）
    col: int = 0             # 源码列号（1 起算）


@dataclass
class DposStmt(Stmt):
    """声明一个 dpos 坐标变量：dpos 名称[x,y,z]"""

    name: str = ""           # 变量名
    coord: Optional[Coord] = None   # 这个变量指向的坐标


@dataclass
class DrpStmt(Stmt):
    """声明一个 drp 状态模板变量：drp 名称{键=值}"""

    name: str = ""           # 变量名
    states: Optional[Dict[str, StateValue]] = None   # None 表示引用另一个 drp 变量
    states_ref: Optional[str] = None   # 被引用的那个 drp 变量名


@dataclass
class LetStmt(Stmt):
    """声明一个普通变量：let 名称 = 表达式"""

    name: str = ""           # 变量名
    value: Optional[Expr] = None   # 初始值的表达式


@dataclass
class AssignStmt(Stmt):
    """扩展语法：直接给已有变量赋值（变量不存在则视为新建）。"""

    name: str = ""           # 变量名
    value: Optional[Expr] = None   # 要赋的值


@dataclass
class IfStmt(Stmt):
    """条件分支：if(条件){...} else{...}"""

    cond: Optional[Expr] = None    # 判断用的条件表达式
    then_body: List[Stmt] = field(default_factory=list)   # 条件成立时执行
    else_body: Optional[List[Stmt]] = None   # 条件不成立时执行；None 表示没写 else


@dataclass
class ForStmt(Stmt):
    """计数循环：for 变量 = (起始 to 结束){...}"""

    var: str = ""            # 循环变量名
    start: Optional[Expr] = None    # 起始值
    end: Optional[Expr] = None      # 结束值（含）；起始大于结束时自动倒着数
    body: List[Stmt] = field(default_factory=list)   # 循环体


@dataclass
class WhileStmt(Stmt):
    """当循环：while(条件){...}"""

    cond: Optional[Expr] = None    # 循环条件
    body: List[Stmt] = field(default_factory=list)   # 循环体


@dataclass
class ReturnStmt(Stmt):
    """从函数里返回：return [表达式]"""

    value: Optional[Expr] = None   # 返回值的表达式；None 表示不带值返回


@dataclass
class BreakStmt(Stmt):
    """跳出当前循环。"""

    pass


@dataclass
class ContinueStmt(Stmt):
    """跳到当前循环的下一轮。"""

    pass


@dataclass
class ExprStmt(Stmt):
    """只求值、不产生结果的语句（函数调用通常写成这样）。"""

    expr: Optional[Expr] = None   # 要求值的表达式


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
    name: str = ""         # 元件指令名 / rbl 缩写 / 原生方块 ID


@dataclass
class PlaceStmt(Stmt):
    """放置一个方块：元件名{状态槽}[坐标槽]。"""

    target: Optional[Target] = None   # 放的是什么方块
    # 状态槽有三种形态：
    #   states 为 None 且 states_ref 为 None → 没写状态槽
    #   states 为 {}                      → 写了空状态块
    #   states_ref 有值                    → 引用了一个 drp 变量
    states: Optional[Dict[str, StateValue]] = None   # 显式写出的键值对
    states_ref: Optional[str] = None   # 状态槽里引用的 drp 变量名
    coord: Optional[Coord] = None      # 坐标槽；None 表示放在作用域原点


@dataclass
class FuncDef(Stmt):
    """定义一个逻辑函数：def 名称(参数){...}"""

    name: str = ""           # 函数名
    params: List[str] = field(default_factory=list)   # 形参名，按位置对应
    body: List[Stmt] = field(default_factory=list)   # 函数体


@dataclass
class StructDef(Stmt):
    """定义一个方块结构模板：strudef 名称(参数){默认状态}:{...}"""

    name: str = ""           # 结构名
    params: List[str] = field(default_factory=list)   # 形参名，按位置对应
    defaults: Optional[Dict[str, StateValue]] = None   # 默认状态的键值对
    defaults_ref: Optional[str] = None   # 默认状态引用的 drp 变量名
    body: List[Stmt] = field(default_factory=list)   # 结构体，内部坐标是相对坐标


@dataclass
class StructCall(Stmt):
    """实例化一个结构：stru 名称(参数){覆盖状态}[坐标]"""

    name: str = ""           # 结构名，可以带命名空间前缀（模块.结构名）
    args: List[Expr] = field(default_factory=list)   # 位置实参
    kwargs: Dict[str, Expr] = field(default_factory=dict)   # 关键字实参（结构暂不支持）
    override: Optional[Dict[str, StateValue]] = None   # 调用时覆盖的默认状态
    override_ref: Optional[str] = None   # 覆盖状态引用的 drp 变量名
    coord: Optional[Coord] = None   # 调用位置，也就是结构原点的位置
