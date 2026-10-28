"""Rupis 解释器：执行 AST，产出方块世界数据。

世界模型：
    world: Dict[(x, y, z), Placement]   同一坐标只保留最后一次放置的结果
    order: List[(x, y, z)]               方块首次出现的顺序（保留放置先后）
每个 Placement 记录 Minecraft 方块 ID 与最终方块状态（已把 Rupis 状态键
翻译成 Minecraft 真实属性名）。

状态优先级（从高到低）：
    1.  指令状态槽里显式写出的键值对 {键=值}
    1'. 指令状态槽里引用的 drp 变量 {名字}
    2.  结构默认状态（strudef 的 {默认状态} 与 stru 的 {覆盖状态} 合并结果）
    —— 没有全局 drp：不写状态槽时不会自动套用任何 drp 变量

规则说明：
    * 显式状态与 drp 模板只覆盖同名的键，其余键仍由结构默认状态补齐；
    * drp 模板 / 结构默认状态里元件不支持的键 → 静默忽略；
    * 显式写出的状态键元件不支持 → 报错并给出位置（规范第九节第 5 条）。

坐标约定：
    * 全局作用域里的坐标就是世界坐标；
    * 结构里的坐标是结构局部坐标，会自动加上结构原点（stru 的调用位置）。
"""

from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .ast_nodes import (
    AssignStmt, Attr, Binary, BreakStmt, Call, ContinueStmt, Coord, DposStmt,
    DrpStmt, Expr, ExprStmt, ForStmt, FuncDef, IfStmt, LetStmt, LibStmt, Num,
    PlaceStmt, ReturnStmt, StateValue, Str, StructCall, StructDef, Target,
    Unary, Var, WhileStmt,
)
from .blocks import (
    DIRECTION_NAMES, ELEMENTS, RBL_BLOCKS, Direction, Element,
    normalize_block_id, resolve_rbl,
)
from .errors import RupisError, RuntimeErr, Source
from .lexer import Lexer
from .parser import Parser

# 函数调用层数上限：挡住无限递归，免得把 Python 的调用栈撑爆
MAX_CALL_DEPTH = 256
# 循环迭代次数上限：挡住死循环，免得解释器一直卡着不返回
MAX_LOOP_ITERATIONS = 1_000_000

# 世界坐标：(x, y, z)
Coord3 = Tuple[int, int, int]


# --------------------------------------------------------------------- 控制流信号
# break / continue / return 要能穿过任意多层嵌套的 if 与循环。
# 用返回值往下传的话，每一层都得记得判断再往上抛；用异常则能直接冒泡到
# 真正处理它的那一层（循环或函数），写起来干净很多。
class _Return(Exception):
    """函数返回信号：把 return 的值带出函数体。"""

    def __init__(self, value: Any) -> None:
        """记下要返回的值。"""

        self.value = value


class _Break(Exception):
    """跳出当前循环的信号。"""


class _Continue(Exception):
    """进入当前循环下一轮的信号。"""


# --------------------------------------------------------------------- 数据结构
@dataclass
class Placement:
    """一个已放置的方块。"""

    pos: Coord3
    block_id: str
    states: Dict[str, Any] = field(default_factory=dict)
    source: str = ""          # 产生它的 Rupis 指令，便于调试
    origin: str = "world"     # world | struct

    def command(self) -> str:
        """生成这个方块对应的 /setblock 命令。"""

        if self.states:
            state_text = ",".join(f"{k}={fmt_state(v)}" for k, v in sorted(self.states.items()))
            return f"/setblock {self.pos[0]} {self.pos[1]} {self.pos[2]} {self.block_id}[{state_text}]"
        return f"/setblock {self.pos[0]} {self.pos[1]} {self.pos[2]} {self.block_id}"


def fmt_state(value: Any) -> str:
    """把状态值格式化成 Minecraft 命令里的写法。

    布尔写成 true / false，方向写成英文名，整数值浮点数去掉小数尾巴。
    """

    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Direction):
        return value.name
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


# ----------------------------------------------------------------- 导入的 .rpi 脚本
class ModuleFunction:
    """被导入脚本里的一个 def 函数，包一层就能直接调用。"""

    def __init__(self, interp: "Interpreter", func: FuncDef) -> None:
        """记下它属于哪个解释器、对应哪个函数定义。"""

        self.interp = interp
        self.func = func
        self.name = func.name
        self.params = list(func.params)

    def __call__(self, *args: Any) -> Any:
        """被调用时转交给解释器去跑函数体。"""

        return self.interp.invoke_function(self.func, args)

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        """调试输出。"""

        return f"<函数 {self.name}/{len(self.params)}>"


class RupisModule:
    """lib 导入进来的 .rpi 脚本，充当一个命名空间。

    成员有两种：
        * def 函数     → 直接调用：util.helper(3)
        * strudef 结构 → 用 stru util.my_struct(...) 实例化
    """

    def __init__(
        self,
        name: str,
        path: Path,
        functions: Dict[str, FuncDef],
        structs: Dict[str, StructDef],
        interp: "Interpreter",
    ) -> None:
        """建好命名空间，并把脚本里的 def 包成可以直接调用的对象。"""

        self.name = name
        self.path = path
        self.functions = functions
        self.structs = structs
        self.interp = interp
        self._callables = {
            key: ModuleFunction(interp, func) for key, func in functions.items()
        }

    def __getattr__(self, item: str) -> Any:
        """按名字取出脚本里的函数（结构不走这里，要用 stru 实例化）。"""

        # 只有正常属性找不到时才会走到这里
        callables = self.__dict__.get("_callables") or {}
        if item in callables:
            return callables[item]
        raise AttributeError(item)

    def member_names(self) -> List[str]:
        """这个脚本里能拿到的所有名字（函数 + 结构）。"""

        return sorted(set(self.functions) | set(self.structs))

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        """调试输出。"""

        return f"<脚本 {self.name}（{self.path}）>"


# ------------------------------------------------------------------------ 作用域
class Scope:
    """一层作用域：一张变量表，加上指向外层的父作用域。

    查找变量时从当前层开始沿 parent 往上冒泡，命中第一个同名变量就用它；
    一路到顶都没找到，才算"未定义的变量"。
    """

    __slots__ = ("vars", "parent", "origin", "defaults", "default_positions")

    def __init__(
        self,
        parent: Optional["Scope"] = None,
        origin: Optional[Coord3] = None,
        defaults: Optional[Dict[str, Any]] = None,
        default_positions: Optional[Dict[str, Tuple[int, int]]] = None,
    ) -> None:
        """建一层作用域。

        origin / defaults 是结构相关的信息，普通作用域不用填。
        """

        self.vars: Dict[str, Any] = {}
        self.parent = parent
        self.origin = origin          # 结构原点（局部坐标系原点）
        self.defaults = defaults or {}  # 结构默认状态
        self.default_positions = default_positions or {}

    def get(self, name: str) -> Any:
        """按名字取变量，沿父作用域链向上冒泡；没有就抛 KeyError。"""

        scope: Optional[Scope] = self
        while scope is not None:
            if name in scope.vars:
                return scope.vars[name]
            scope = scope.parent
        raise KeyError(name)

    def has(self, name: str) -> bool:
        """这个名字在这个作用域链上是否可见。"""

        scope: Optional[Scope] = self
        while scope is not None:
            if name in scope.vars:
                return True
            scope = scope.parent
        return False

    def set(self, name: str, value: Any) -> None:
        """在当前层写入变量（不会动到外层同名的变量）。"""

        self.vars[name] = value

    def unset(self, name: str) -> None:
        """从当前层删掉变量；本来就没有也不报错。"""

        self.vars.pop(name, None)

    def find_origin(self) -> Optional[Coord3]:
        """找到最近的结构原点；不在结构里返回 None。"""

        scope: Optional[Scope] = self
        while scope is not None:
            if scope.origin is not None:
                return scope.origin
            scope = scope.parent
        return None

    def find_defaults(self) -> Dict[str, Any]:
        """找到最近一层的结构默认状态；不在结构里返回空字典。"""

        scope: Optional[Scope] = self
        while scope is not None:
            if scope.defaults:
                return scope.defaults
            scope = scope.parent
        return {}

    def find_default_positions(self) -> Dict[str, Tuple[int, int]]:
        """找到结构默认状态里每个键的位置，用来把错误指到具体那行。

        与 find_defaults 取的是同一层：那一层 defaults 为空就继续往上找。
        """

        scope: Optional[Scope] = self
        while scope is not None:
            if scope.defaults:
                return scope.default_positions
            scope = scope.parent
        return {}


# ----------------------------------------------------------------------- 解释器
class Interpreter:
    """Rupis 解释器：持有全局状态，执行语句，把方块收进世界里。

    全局状态：
        world / order   产出的方块世界
        functions       全局函数表（def 定义的 + lib 导入的）
        structs         全局结构表
        dpos_vars       全局 dpos 坐标变量
        drp_vars        全局 drp 状态模板变量
    """

    def __init__(
        self,
        source: Optional[Source] = None,
        verbose: bool = False,
        lib_paths: Optional[List[Any]] = None,
    ) -> None:
        """新建解释器。lib_paths 是 lib 导入时额外要搜的目录。"""

        self.source = source
        self.verbose = verbose
        self.world: Dict[Coord3, Placement] = {}
        self.order: List[Coord3] = []
        self.functions: Dict[str, FuncDef] = {}
        self.structs: Dict[str, StructDef] = {}
        # dpos 坐标变量：名称 -> 坐标
        self.dpos_vars: Dict[str, Coord3] = {}
        # drp 状态模板变量：名称 -> 状态字典 或 另一个 drp 变量名
        self.drp_vars: Dict[str, Any] = {}
        self.global_scope = Scope()
        self.call_depth = 0
        # lib 导入 .rpi 脚本时额外要搜的目录
        self.lib_paths: List[Path] = [Path(item) for item in (lib_paths or [])]

    # ------------------------------------------------------------------ 工具
    def error(self, message: str, node: Any = None) -> RuntimeErr:
        """造一个带行列号的运行时错误（node 上有行列信息就用它的）。"""

        line = getattr(node, "line", None)
        col = getattr(node, "col", None)
        return RuntimeErr(message, line, col, self.source)

    # ------------------------------------------------------------------ 主流程
    def run(self, program: List) -> None:
        """执行整个程序：顶层语句逐条跑在全局作用域里。"""

        for stmt in program:
            self.exec_stmt(stmt, self.global_scope)

    def exec_block(self, body: List, scope: Scope) -> None:
        """顺序执行一串语句，共用同一个作用域（if / for 的块不另开作用域）。"""

        for stmt in body:
            self.exec_stmt(stmt, scope)

    def exec_stmt(self, stmt, scope: Scope) -> None:
        """按语句类型分派到对应的 _exec_XXX 方法。"""

        if stmt is None:
            return
        method = getattr(self, "_exec_" + type(stmt).__name__, None)
        if method is None:
            raise self.error(f"暂不支持的语句 {type(stmt).__name__}", stmt)
        method(stmt, scope)

    # ------------------------------------------------------------- 全局配置
    def _exec_DposStmt(self, stmt: DposStmt, scope: Scope) -> None:
        """声明/覆盖一个 dpos 坐标变量：dpos 名称[x,y,z]

        存的是绝对坐标（absolute=True，忽略结构原点偏移）；
        在结构里写 [base] 时，结构原点会再叠加上来。
        """

        coord = self.eval_coord(stmt.coord, scope, absolute=True)
        self.dpos_vars[stmt.name] = coord

    def _exec_DrpStmt(self, stmt: DrpStmt, scope: Scope) -> None:
        """声明/覆盖一个 drp 状态模板变量：drp 名称{键=值}

        drp a{b} 这种写法先记下另一个 drp 变量的名字，用到的时候才展开。
        """

        if stmt.states_ref is not None:
            self.drp_vars[stmt.name] = stmt.states_ref
        else:
            self.drp_vars[stmt.name] = dict(stmt.states or {})

    def _exec_LibStmt(self, stmt: LibStmt, scope: Scope) -> None:
        """导入一个 .rpi 脚本：lib 脚本名 [as 别名]

        导入的是别的 Rupis 脚本（不是 Python 模块），拿到它里面的
        def 函数和 strudef 结构：
            1. 原名直接可用：helper(...) / stru my_struct(...)
            2. 命名空间也绑上：util.helper(...) / stru util.my_struct(...)
        被导入脚本顶层的放置指令不执行 —— 它只是个库。
        搜索顺序：当前脚本所在目录 → lib_paths → 当前工作目录。
        """

        path = self.find_lib_file(stmt.script)
        if path is None:
            searched = "、".join(str(item) for item in self.lib_search_dirs())
            raise self.error(
                f"找不到脚本 '{stmt.script}.rpi'（找过的目录：{searched}）", stmt)

        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise self.error(f"读不了 '{path}'：{exc}", stmt)

        try:
            lexer = Lexer(text, str(path))
            program = Parser(lexer.tokenize(), lexer.source).parse_program()
        except RupisError as exc:
            raise self.error(f"导入 '{path.name}' 失败：{exc.message}", stmt)

        functions: Dict[str, FuncDef] = {}
        structs: Dict[str, StructDef] = {}
        for item in program:
            if isinstance(item, FuncDef):
                functions[item.name] = item
            elif isinstance(item, StructDef):
                structs[item.name] = item

        # 原名直接可用（同名的以后来导入的为准）
        # 函数 / 结构登记在全局表里，任何作用域都能用
        self.functions.update(functions)
        self.structs.update(structs)

        # 命名空间：绑在当前作用域上，写在函数里的 lib 只在该函数里可见
        scope.set(stmt.name, RupisModule(stmt.name, path, functions, structs, self))

    def lib_search_dirs(self) -> List[Path]:
        """lib 找 .rpi 脚本时会搜的目录（按顺序）。

        顺序是：当前脚本所在目录 → lib_paths → 当前工作目录。
        """

        dirs: List[Path] = []
        if self.source is not None and self.source.filename:
            base = Path(self.source.filename).parent
            if str(base) and not base.is_absolute():
                base = base.resolve()
            dirs.append(base)
        dirs.extend(self.lib_paths)
        dirs.append(Path.cwd())
        # 去重但保持顺序
        seen = set()
        unique: List[Path] = []
        for item in dirs:
            key = str(item)
            if key not in seen:
                seen.add(key)
                unique.append(item)
        return unique

    def find_lib_file(self, script: str) -> Optional[Path]:
        """按名字找 .rpi 脚本：先找当前脚本所在的目录，再找 lib 目录、当前目录。

        脚本名里的 / 当子目录处理；没写 .rpi 后缀时自动补上。
        """

        relative = Path(*script.split("/")) if script else Path()
        for folder in self.lib_search_dirs():
            candidate = folder / relative
            if candidate.suffix != ".rpi":
                candidate = candidate.with_suffix(".rpi")
            if candidate.is_file():
                return candidate
        return None

    # ------------------------------------------------------- dpos / drp 查找
    def lookup_dpos_var(self, name: str, node: Any) -> Coord3:
        """取 dpos 坐标变量的坐标；没声明过就报错并列出已声明的。"""

        if name not in self.dpos_vars:
            known = ", ".join(sorted(self.dpos_vars)) or "（还没有声明任何 dpos 变量）"
            raise self.error(f"未定义的 dpos 变量 '{name}'（已声明：{known}）", node)
        return self.dpos_vars[name]

    def lookup_drp_var(
        self,
        name: str,
        scope: Scope,
        node: Any,
        depth: int = 0,
    ) -> Tuple[Dict[str, Any], Dict[str, Tuple[int, int]]]:
        """取出 drp 变量的状态模板，返回 (求值后的状态, 每个键的位置)。

        drp a{b} 的引用形式会递归展开，depth 用来挡住循环引用。
        """

        if depth > 16:
            raise self.error(f"drp 变量 '{name}' 存在循环引用", node)
        if name not in self.drp_vars:
            known = ", ".join(sorted(self.drp_vars)) or "（还没有声明任何 drp 变量）"
            raise self.error(f"未定义的 drp 变量 '{name}'（已声明：{known}）", node)
        entry = self.drp_vars[name]
        if isinstance(entry, str):  # drp a{b} 这种引用形式
            return self.lookup_drp_var(entry, scope, node, depth + 1)
        values: Dict[str, Any] = {}
        positions: Dict[str, Tuple[int, int]] = {}
        for key, state_value in entry.items():
            values[key] = self.eval_expr(state_value.expr, scope)
            positions[key] = (state_value.line, state_value.col)
        return values, positions

    # ----------------------------------------------------------------- 变量
    def _exec_LetStmt(self, stmt: LetStmt, scope: Scope) -> None:
        """声明一个普通变量，写在当前作用域。"""

        scope.set(stmt.name, self.eval_expr(stmt.value, scope))

    def _exec_AssignStmt(self, stmt: AssignStmt, scope: Scope) -> None:
        """给变量赋值。"""

        value = self.eval_expr(stmt.value, scope)
        # 已存在的变量：就地赋值；否则在当前作用域新建
        target_scope: Optional[Scope] = scope
        walker: Optional[Scope] = scope
        while walker is not None:
            if stmt.name in walker.vars:
                target_scope = walker
                break
            walker = walker.parent
        if target_scope is None:
            target_scope = scope
        target_scope.set(stmt.name, value)

    # --------------------------------------------------------------- 控制流
    def _exec_IfStmt(self, stmt: IfStmt, scope: Scope) -> None:
        """if / else 分支。"""

        if truthy(self.eval_expr(stmt.cond, scope)):
            self.exec_block(stmt.then_body, scope)
        elif stmt.else_body is not None:
            self.exec_block(stmt.else_body, scope)

    def _exec_ForStmt(self, stmt: ForStmt, scope: Scope) -> None:
        """for 循环：闭区间，可以正着数也可以倒着数。

        循环变量写在当前作用域，循环结束后恢复成原来的值
        （原来没有这个变量就删掉）。
        """

        start = int(self.eval_expr(stmt.start, scope))
        end = int(self.eval_expr(stmt.end, scope))
        had_var = scope.has(stmt.var)
        old_value = scope.get(stmt.var) if had_var else None
        try:
            if start <= end:
                values = range(start, end + 1)
            else:
                values = range(start, end - 1, -1)
            count = 0
            for value in values:
                count += 1
                if count > MAX_LOOP_ITERATIONS:
                    raise self.error("for 循环迭代次数过多，疑似死循环", stmt)
                scope.set(stmt.var, value)
                try:
                    self.exec_block(stmt.body, scope)
                except _Continue:
                    continue
                except _Break:
                    break
        finally:
            if had_var:
                scope.set(stmt.var, old_value)
            else:
                scope.unset(stmt.var)

    def _exec_WhileStmt(self, stmt: WhileStmt, scope: Scope) -> None:
        """while 循环。"""

        count = 0
        while truthy(self.eval_expr(stmt.cond, scope)):
            count += 1
            if count > MAX_LOOP_ITERATIONS:
                raise self.error("while 循环迭代次数过多，疑似死循环", stmt)
            try:
                self.exec_block(stmt.body, scope)
            except _Continue:
                continue
            except _Break:
                break

    def _exec_ReturnStmt(self, stmt: ReturnStmt, scope: Scope) -> None:
        """return：把返回值带出函数体。"""

        value = self.eval_expr(stmt.value, scope) if stmt.value is not None else None
        raise _Return(value)

    def _exec_BreakStmt(self, stmt: BreakStmt, scope: Scope) -> None:
        """break：跳出当前循环。"""

        raise _Break()

    def _exec_ContinueStmt(self, stmt: ContinueStmt, scope: Scope) -> None:
        """continue：进入当前循环的下一轮。"""

        raise _Continue()

    def _exec_ExprStmt(self, stmt: ExprStmt, scope: Scope) -> None:
        """只求值的语句（结果丢掉不要）。"""

        self.eval_expr(stmt.expr, scope)

    # ---------------------------------------------------------- 函数 / 结构
    def _exec_FuncDef(self, stmt: FuncDef, scope: Scope) -> None:
        """登记一个 def 函数（函数体要等到被调用时才执行）。"""

        self.functions[stmt.name] = stmt

    def _exec_StructDef(self, stmt: StructDef, scope: Scope) -> None:
        """登记一个 strudef 结构定义。"""

        self.structs[stmt.name] = stmt

    def lookup_struct(self, name: str, scope: Scope, node: Any) -> StructDef:
        """找结构定义。既支持本脚本的结构，也支持 lib 导入的：模块.结构名。"""

        if "." not in name:
            struct = self.structs.get(name)
            if struct is None:
                raise self.error(f"未定义的结构 '{name}'", node)
            return struct

        head, tail = name.split(".", 1)
        if not scope.has(head):
            raise self.error(f"未定义的模块 '{head}'", node)
        module = scope.get(head)
        if not isinstance(module, RupisModule):
            raise self.error(f"'{head}' 不是导入的脚本", node)
        struct = module.structs.get(tail)
        if struct is None:
            raise self.error(f"脚本 '{head}' 里没有结构 '{tail}'", node)
        return struct

    def _exec_StructCall(self, stmt: StructCall, scope: Scope) -> None:
        """执行 stru 调用：建一个结构作用域，把结构体跑一遍。

        结构默认状态 = strudef 里的 {默认状态} 与本次调用的 {覆盖状态} 合并，
        覆盖值优先；这些键同时也能当局部变量读。
        """

        struct = self.lookup_struct(stmt.name, scope, stmt)

        if stmt.kwargs:
            raise self.error(f"结构 '{stmt.name}' 不支持关键字参数", stmt)

        args = [self.eval_expr(arg, scope) for arg in stmt.args]
        if len(args) != len(struct.params):
            raise self.error(
                f"结构 '{stmt.name}' 需要 {len(struct.params)} 个参数，实际传入 {len(args)} 个", stmt
            )

        # 调用位置即结构原点
        origin = self.eval_coord(stmt.coord, scope)

        # 结构默认状态：strudef 的默认值 + stru 调用时的覆盖值
        defaults: Dict[str, Any] = {}
        default_positions: Dict[str, Tuple[int, int]] = {}
        if struct.defaults_ref is not None:
            defaults, default_positions = self.lookup_drp_var(
                struct.defaults_ref, self.global_scope, struct
            )
        elif struct.defaults:
            for key, entry in struct.defaults.items():
                defaults[key] = self.eval_expr(entry.expr, self.global_scope)
                default_positions[key] = (entry.line, entry.col)
        if stmt.override_ref is not None:
            override_values, override_positions = self.lookup_drp_var(
                stmt.override_ref, scope, stmt
            )
            defaults.update(override_values)
            default_positions.update(override_positions)
        elif stmt.override:
            for key, entry in stmt.override.items():
                defaults[key] = self.eval_expr(entry.expr, scope)
                default_positions[key] = (entry.line, entry.col)

        # 结构作用域的父级也是全局作用域：结构体看得到全局变量
        struct_scope = Scope(
            parent=self.global_scope,
            origin=origin,
            defaults=defaults,
            default_positions=default_positions,
        )
        for name, value in zip(struct.params, args):
            struct_scope.set(name, value)
        # 默认状态里的键也可以当变量用（例如 locked=locked）
        for key, value in defaults.items():
            if key not in struct_scope.vars:
                struct_scope.set(key, value)

        self.exec_block(struct.body, struct_scope)

    # ------------------------------------------------------------- 放置指令
    def _exec_PlaceStmt(self, stmt: PlaceStmt, scope: Scope) -> None:
        """执行一条放置指令：算出方块 ID 与最终状态，再写进世界。

        指令名分三类：元件（rw / rrep …）、rbl 快捷方块、block 原生方块。
        只有元件才校验状态键，原生方块的状态键原样透传。
        """

        target = stmt.target
        element: Optional[Element] = None
        supported: Optional[Dict[str, str]] = None

        if target.kind == "element":
            element = ELEMENTS.get(target.name)
            if element is None:
                raise self.error(f"未知的元件指令 '{target.name}'", stmt)
            block_id = element.block_id
            supported = element.states
        elif target.kind == "rbl":
            try:
                block_id, supported = resolve_rbl(target.name)
            except KeyError:
                raise self.error(
                    f"未知的方块缩写 '{target.name}'"
                    f"（可用缩写：{', '.join(sorted(RBL_BLOCKS))[:160]} ...）",
                    stmt,
                )
        else:
            block_id = normalize_block_id(target.name)
            supported = None  # 原生方块：状态键不校验，原样透传

        states, positions = self.resolve_states(stmt, scope, element, supported)

        # rw 的 len：连续长线
        length = states.pop("len", None) if element is not None else None
        axis = states.pop("axis", "x") if element is not None else "x"
        positions.pop("len", None)
        positions.pop("axis", None)
        if element is not None:
            if length is None and "axis" in (stmt.states or {}):
                raise self.error("'axis' 只能与 'len' 一起使用", stmt)
        if length is not None:
            length = int(length)
            if axis not in ("x", "y", "z"):
                raise self.error(f"未知的坐标轴 '{axis}'（可选 x / y / z）", stmt)
            if length < 1:
                raise self.error("len 必须大于等于 1", stmt)

        pos = self.eval_coord(stmt.coord, scope)

        if length is None:
            self.place(pos, block_id, states, target, scope, positions)
        else:
            step = {"x": (1, 0, 0), "y": (0, 1, 0), "z": (0, 0, 1)}[axis]
            for i in range(length):
                offset = (step[0] * i, step[1] * i, step[2] * i)
                self.place(
                    (pos[0] + offset[0], pos[1] + offset[1], pos[2] + offset[2]),
                    block_id, states, target, scope, positions,
                )

    def resolve_states(
        self,
        stmt: PlaceStmt,
        scope: Scope,
        element: Optional[Element],
        supported: Optional[Dict[str, str]],
    ) -> Tuple[Dict[str, Any], Dict[str, Tuple[int, int]]]:
        """算出最终状态（键仍是 Rupis 状态键）。

        优先级：
            1. 状态槽里显式写的键值对 / 引用的 drp 变量
            2. 结构默认状态（只填补上面没写的键）
        没有全局 drp：不写状态槽时，最终状态就只有结构默认状态。
        drp 模板里元件不支持的键会被忽略；显式写出的不支持键则报错。
        """

        defaults = scope.find_defaults()
        positions: Dict[str, Tuple[int, int]] = {}
        positions.update(scope.find_default_positions())

        explicit: Optional[Dict[str, Any]] = None
        from_template = False
        if stmt.states_ref is not None:
            # {drp变量名}：取 drp 模板
            explicit, template_positions = self.lookup_drp_var(stmt.states_ref, scope, stmt)
            positions.update(template_positions)
            from_template = True
        elif stmt.states is not None:
            explicit = {}
            for key, entry in stmt.states.items():
                explicit[key] = self.eval_state_value(key, entry, scope, element)
                positions[key] = (entry.line, entry.col)

        final: Dict[str, Any] = {}
        # 结构默认状态打底，显式状态 / drp 模板覆盖同名的键
        final.update(defaults)
        if explicit is not None:
            final.update(explicit)

        # 过滤掉元件不支持的键
        if supported is not None:
            for key in list(final.keys()):
                if key in supported or (element is not None and key in element.pseudo):
                    continue
                if explicit is not None and key in explicit and not from_template:
                    # 显式写出的陌生键 → 报错
                    line, col = positions.get(key, (stmt.line, stmt.col))
                    usable = sorted(supported)
                    if element is not None and element.pseudo:
                        usable += [f"{p}（扩展）" for p in sorted(element.pseudo)]
                    raise RuntimeErr(
                        f"元件 '{stmt.target.name}' 不支持状态键 '{key}'"
                        f"（支持：{', '.join(usable)}）",
                        line, col, self.source,
                    )
                del final[key]  # drp 模板 / 结构默认状态里的陌生键：忽略

        return final, positions

    def eval_state_value(
        self,
        key: str,
        entry: StateValue,
        scope: Scope,
        element: Optional[Element],
    ) -> Any:
        """求值一个状态值；顺手把"变量不存在"翻译成更贴切的提示。

        状态值写了一个没定义的变量，多半是想写某个枚举值，
        所以这里补一句该键的合法取值，比光说"未定义的变量"有用。
        """

        try:
            return self.eval_expr(entry.expr, scope)
        except RuntimeErr as exc:
            if "未定义的变量" in exc.message and isinstance(entry.expr, Var):
                hint = self.valid_values_hint(key, element)
                message = f"状态键 '{key}' 的值 '{entry.expr.name}' 无效"
                if hint:
                    message += f"（{hint}）"
                raise RuntimeErr(message, entry.line, entry.col, self.source) from None
            raise

    def valid_values_hint(self, key: str, element: Optional[Element]) -> str:
        """给出某个状态键的合法取值提示（元件没定义就返回空串）。"""

        if element is not None:
            if key in element.choices:
                return f"{key} 可取：{', '.join(element.choices[key])}"
            if key in element.ranges:
                low, high = element.ranges[key]
                return f"{key} 可取：{low}~{high} 之间的整数"
        if key == "facing":
            return f"facing 可取：{', '.join(DIRECTION_NAMES)}"
        return ""

    def place(
        self,
        pos: Coord3,
        block_id: str,
        states: Dict[str, Any],
        target: Target,
        scope: Scope,
        positions: Optional[Dict[str, Tuple[int, int]]] = None,
    ) -> None:
        """把一个方块写进世界，同一坐标重复放置时后者覆盖前者。

        元件的状态键要翻译成 Minecraft 的真实属性名（rsig → power），
        解释器专用的伪键（rw 的 len / axis）不发出去。
        """

        positions = positions or {}
        element = ELEMENTS.get(target.name) if target.kind == "element" else None
        mc_states: Dict[str, Any] = {}
        if element is not None:
            for key, value in states.items():
                if key in element.pseudo:
                    continue
                mc_name = element.states.get(key, key)
                mc_states[mc_name] = self.convert_state(
                    element, key, value, target, positions.get(key)
                )
        else:
            for key, value in states.items():
                mc_states[key] = self.convert_generic(value)

        placement = Placement(
            pos=pos,
            block_id=block_id,
            states=mc_states,
            source=target.name,
            origin="struct" if scope.find_origin() is not None else "world",
        )
        if pos in self.world:
            self.world[pos] = placement
        else:
            self.world[pos] = placement
            self.order.append(pos)
        if self.verbose:
            print(placement.command(), file=sys.stderr)

    # ------------------------------------------------------------- 状态转换
    def convert_state(
        self,
        element: Element,
        key: str,
        value: Any,
        target: Target,
        position: Optional[Tuple[int, int]] = None,
    ) -> Any:
        """把状态值转成 Minecraft 要的类型，顺便做取值校验。

        判定顺序：区间 → 枚举取值 → 布尔 → 整数 → facing → 原样返回。
        """

        # 先做区间/取值校验，再做通用类型转换
        if key in element.ranges:
            number = to_int(value)
            low, high = element.ranges[key]
            if not (low <= number <= high):
                raise self.state_error(
                    f"{key} 必须在 {low}~{high} 之间，收到 {number}", position, target
                )
            return number
        if key in element.choices:
            text = str(value).lower()
            if text not in element.choices[key]:
                raise self.state_error(
                    f"未知的 {key} 值 '{value}'（可选：{', '.join(element.choices[key])}）",
                    position, target,
                )
            return text
        if key in element.bool_keys:
            return to_bool(value)
        if key in element.int_keys:
            return to_int(value)
        if key == "facing":
            if isinstance(value, Direction):
                return value.name
            text = str(value).lower()
            if text not in DIRECTION_NAMES:
                raise self.state_error(
                    f"未知的朝向 '{value}'（可选：{', '.join(DIRECTION_NAMES)}）", position, target
                )
            return text
        return value

    def state_error(
        self,
        message: str,
        position: Optional[Tuple[int, int]],
        target: Target,
    ) -> RuntimeErr:
        """状态相关的错误：优先指向出错的键。"""

        if position is not None:
            return RuntimeErr(message, position[0], position[1], self.source)
        return self.error(message, target)

    def convert_generic(self, value: Any) -> Any:
        """原生方块的状态值：方向转字符串，其余原样保留。"""

        if isinstance(value, Direction):
            return value.name
        return value

    # ----------------------------------------------------------------- 坐标
    def resolve_origin(self, scope: Scope) -> Coord3:
        """作用域的原点偏移：结构内部 = 结构原点，全局 = (0,0,0)。"""

        return scope.find_origin() or (0, 0, 0)

    def eval_coord(
        self,
        coord: Optional[Coord],
        scope: Scope,
        absolute: bool = False,
    ) -> Coord3:
        """求值坐标槽。

        坐标 = dpos 变量的坐标（没写就当 0,0,0）+ 各轴偏移量，
        最后再加上作用域的原点偏移（结构里就是结构原点）。
        absolute=True 时忽略结构原点偏移（用于 dpos 变量声明本身）。
        """

        offset = (0, 0, 0) if absolute else self.resolve_origin(scope)
        if coord is None:
            return offset
        if coord.kind == "var":
            x, y, z = self.lookup_dpos_var(coord.name, coord)
        else:
            x = y = z = 0
        for axis, expr in coord.offsets:
            value = self.eval_expr(expr, scope)
            number = to_int(value)
            if axis == "x":
                x += number
            elif axis == "y":
                y += number
            else:
                z += number
        return (int(x) + offset[0], int(y) + offset[1], int(z) + offset[2])

    # --------------------------------------------------------------- 表达式
    def eval_expr(self, expr: Optional[Expr], scope: Scope) -> Any:
        """求值一个表达式，按节点类型分派。"""

        if expr is None:
            return None
        if isinstance(expr, Num):
            return expr.value
        if isinstance(expr, Str):
            return expr.value
        if isinstance(expr, Var):
            return self.eval_var(expr, scope)
        if isinstance(expr, Attr):
            return self.eval_attr(expr, scope)
        if isinstance(expr, Unary):
            value = self.eval_expr(expr.operand, scope)
            if expr.op == "-":
                return -to_number(value)
            if expr.op == "!":
                return not truthy(value)
            raise self.error(f"未知的运算符 '{expr.op}'", expr)
        if isinstance(expr, Binary):
            return self.eval_binary(expr, scope)
        if isinstance(expr, Call):
            return self.call_function(expr, scope)
        raise self.error(f"无法求值的表达式 {type(expr).__name__}", expr)

    def eval_var(self, expr: Var, scope: Scope) -> Any:
        """取变量的值；作用域链上没有就看是不是内置常量。"""

        name = expr.name
        if scope.has(name):
            return scope.get(name)
        lowered = name.lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
        if lowered in DIRECTION_NAMES:
            return Direction.get(lowered)
        if lowered in ("x", "y", "z"):
            # 轴名常量，方便写 axis=z 这样的状态值
            return lowered
        if lowered in ("compare", "subtract"):
            # 比较器模式常量
            return lowered
        raise self.error(f"未定义的变量 '{name}'", expr)

    def eval_attr(self, expr: Attr, scope: Scope) -> Any:
        """取属性：脚本.成员（lib 导入的脚本就靠这个用）"""

        obj = self.eval_expr(expr.value, scope)
        try:
            return getattr(obj, expr.name)
        except AttributeError:
            if isinstance(obj, RupisModule):
                if expr.name in obj.structs:
                    raise self.error(
                        f"结构 '{expr.name}' 要用 stru {obj.name}.{expr.name}(...) 来实例化", expr)
                known = "、".join(obj.member_names()) or "（空）"
                raise self.error(
                    f"脚本 '{obj.name}' 里没有 '{expr.name}'（有：{known}）", expr)
            raise self.error(
                f"{describe_object(obj)} 没有属性 '{expr.name}'", expr)

    def eval_binary(self, expr: Binary, scope: Scope) -> Any:
        """二元运算：&& / || 先短路，其余再按运算符分派。

        短路必须在求值右操作数之前判断，否则 a && f() 里的 f() 照样会被调用。
        """

        op = expr.op
        if op == "&&":
            return truthy(self.eval_expr(expr.left, scope)) and truthy(self.eval_expr(expr.right, scope))
        if op == "||":
            return truthy(self.eval_expr(expr.left, scope)) or truthy(self.eval_expr(expr.right, scope))

        left = self.eval_expr(expr.left, scope)
        right = self.eval_expr(expr.right, scope)

        if op == "+":
            if isinstance(left, str) and isinstance(right, str):
                return left + right
            if isinstance(left, Direction) or isinstance(right, Direction):
                raise self.error("方向常量不能参与加减运算", expr)
            return to_number(left) + to_number(right)
        if op == "-":
            return to_number(left) - to_number(right)
        if op == "*":
            return to_number(left) * to_number(right)
        if op == "/":
            divisor = to_number(right)
            if divisor == 0:
                raise self.error("除数不能为 0", expr)
            return to_number(left) / divisor
        if op == "%":
            divisor = to_int(right)
            if divisor == 0:
                raise self.error("取余的除数不能为 0", expr)
            return to_int(left) % divisor
        if op == "==":
            return values_equal(left, right)
        if op == "!=":
            return not values_equal(left, right)
        if op in (">", "<", ">=", "<="):
            return compare_values(op, left, right, expr, self)
        raise self.error(f"未知的运算符 '{op}'", expr)

    # ----------------------------------------------------------------- 函数
    def call_function(self, expr: Call, scope: Scope) -> Any:
        """调用函数：按名字调本脚本的函数，表达式形式的调用转给 call_value。"""

        # 通过表达式调用：多半是 lib 导入的脚本里的函数
        if expr.func is not None:
            return self.call_value(expr, scope)
        func = self.functions.get(expr.name)
        if func is None:
            raise self.error(f"未定义的函数 '{expr.name}'", expr)
        args = [self.eval_expr(arg, scope) for arg in expr.args]
        return self.invoke_function(func, args, expr, kwargs=expr.kwargs,
                                    origin=scope.find_origin())

    def invoke_function(
        self,
        func: FuncDef,
        args: List[Any],
        node: Any = None,
        kwargs: Optional[Dict[str, Any]] = None,
        origin: Optional[Coord3] = None,
    ) -> Any:
        """真正去执行一个 def 函数的函数体。

        本脚本的函数、lib 导入的脚本里的函数，走的都是这一条路。
        函数体的父作用域固定是全局作用域（不是调用它的那个函数），
        所以函数只看得到全局变量，不会顺手改到调用者的局部变量。
        origin 传进来时，函数里的坐标就相对该原点（在结构里调用函数的情形）。
        """

        if kwargs:
            raise self.error(f"函数 '{func.name}' 不支持关键字参数", node)
        if len(args) != len(func.params):
            raise self.error(
                f"函数 '{func.name}' 需要 {len(func.params)} 个参数，实际传入 {len(args)} 个", node
            )
        if self.call_depth >= MAX_CALL_DEPTH:
            # 无限递归的保险丝：宁可报错，也别把 Python 的栈撑爆
            raise self.error("函数调用层数过深（可能存在无限递归）", node)

        func_scope = Scope(
            parent=self.global_scope,
            origin=origin,
        )
        for name, value in zip(func.params, args):
            func_scope.set(name, value)

        self.call_depth += 1
        try:
            self.exec_block(func.body, func_scope)
        except _Return as ret:
            return ret.value
        finally:
            self.call_depth -= 1
        return None

    def call_value(self, expr: Call, scope: Scope) -> Any:
        """调用一个表达式算出来的可调用对象。

        lib 导入的脚本就靠这条路用：lib util 之后写 util.helper(3)。
        """
        callee = self.eval_expr(expr.func, scope)
        if not callable(callee):
            raise self.error(f"{describe_object(callee)} 不是可调用的", expr)
        args = [self.eval_expr(arg, scope) for arg in expr.args]
        kwargs = {key: self.eval_expr(value, scope)
                  for key, value in expr.kwargs.items()}
        try:
            return callee(*args, **kwargs)
        except RupisError:
            raise
        except TypeError as exc:
            raise self.error(f"调用参数不对：{exc}", expr)
        except Exception as exc:
            raise self.error(f"调用时出错：{exc}", expr)


# ------------------------------------------------------------------ 取值辅助
def import_dotted(dotted: str) -> Any:
    """（已废弃）按点号路径导入 Python 模块：os.path → 先 import os，再取 os.path。

    不用 importlib.import_module("os.path")，因为路径最后一段未必是模块
    （math.sqrt 是个函数，import_module 会直接报找不到模块）。

    注意：lib 语句现在导入的是 .rpi 脚本，不再用得上这个函数。
    它保留在这里，供将来做"从 Python 侧调用 Rupis"之类的高级用法。
    """
    parts = dotted.split(".")
    obj = importlib.import_module(parts[0])
    for part in parts[1:]:
        obj = getattr(obj, part)
    return obj


def describe_object(obj: Any) -> str:
    """给对象起个能看懂的名字，报错时用。"""

    if isinstance(obj, RupisModule):
        return f"脚本 '{obj.name}'"
    if isinstance(obj, type(sys)):
        return f"模块 '{getattr(obj, '__name__', obj)}'"
    return f"'{type(obj).__name__}' 对象"


def truthy(value: Any) -> bool:
    """Rupis 的真值判断：0、空串、None 都算假。"""

    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value != ""
    return bool(value)


def to_number(value: Any) -> Any:
    """转成数字；字符串会先试整数、再试浮点。"""

    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, Direction):
        raise RupisError("方向常量不能当数字用")
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            try:
                return float(value)
            except ValueError:
                raise RupisError(f"'{value}' 不是数字")
    raise RupisError(f"{value!r} 不是数字")


def to_int(value: Any) -> int:
    """转成整数（浮点会四舍五入）。"""

    number = to_number(value)
    if isinstance(number, float):
        return int(round(number))
    return int(number)


def to_bool(value: Any) -> bool:
    """转成布尔：true / yes / on / 1 之类算真，false / no / off / 0 算假。"""

    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        lowered = value.lower()
        if lowered in ("true", "yes", "on", "1"):
            return True
        if lowered in ("false", "no", "off", "0"):
            return False
    return bool(value)


def values_equal(left: Any, right: Any) -> bool:
    """比较两个值是否相等：布尔按真值比，其余按类型比。"""

    if isinstance(left, bool) or isinstance(right, bool):
        return to_bool(left) == to_bool(right)
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return left == right
    if isinstance(left, Direction) and isinstance(right, Direction):
        return left == right
    if isinstance(left, str) and isinstance(right, str):
        return left == right
    return left == right


def compare_values(op: str, left: Any, right: Any, expr: Binary, interp: Interpreter) -> bool:
    """大小比较；两边必须都是数字或都是字符串。"""

    try:
        if isinstance(left, (int, float)) and isinstance(right, (int, float)):
            pass
        elif isinstance(left, str) and isinstance(right, str):
            pass
        else:
            raise RupisError(f"无法比较 {left!r} 和 {right!r}")
        if op == ">":
            return left > right
        if op == "<":
            return left < right
        if op == ">=":
            return left >= right
        return left <= right
    except TypeError:
        raise interp.error(f"无法比较 {left!r} 和 {right!r}", expr)
