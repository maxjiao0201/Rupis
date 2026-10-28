"""Rupis 交互式控制台。

下方面板的第二页：一行一行地写 Rupis，回车就执行。
会话状态（dpos / drp 变量、函数、结构、已放置的方块）整个会话里保留，
所以可以先声明再调用，像个小型 REPL。

支持的命令（以 : 开头）：
    :help      列出命令
    :reset     清空会话状态
    :world     看当前放了多少方块
    :vars      看当前有哪些 dpos / drp 变量
    :load 文件  把一个 .rpi 脚本载入当前会话

跨行输入的判断：攒下来的行拼起来以后，花括号还没配平就说明代码块没写完，
提示符会变成 "… "，等用户补上收尾的 } 再一起执行。
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from .. import RupisError, compile_source
from ..ast_nodes import AssignStmt, ExprStmt, LetStmt
from ..interpreter import Interpreter
from .qtcompat import QtCore, QtGui, QtWidgets

PROMPT = "› "

HELP_TEXT = """可用的命令：
  :help          显示这份帮助
  :reset         清空会话状态（变量、函数、方块）
  :world         统计当前放置的方块
  :vars          列出当前的 dpos / drp 变量
  :load 文件路径  把 .rpi 脚本载入当前会话

其余内容按 Rupis 语法写，回车即执行。
代码块可以跨行写（{ 之后接着写，} 收尾）。"""


class RupisConsole(QtWidgets.QWidget):
    """交互式 Rupis 控制台。

    整个控件由三部分组成：上面的记录区（transcript）、下面的提示符与输入框，
    以及一个"载入当前脚本"按钮。

    内部状态：
        interpreter  当前会话的解释器，变量 / 函数 / 方块都存在这里
        _pending     还没写完、正在等待续行的代码行
        _history     敲过的命令，用上下键翻
    """

    # 点"载入当前脚本"时通知主窗口把编辑器里的内容送进来
    loadCurrentRequested = QtCore.pyqtSignal()

    def __init__(self, theme: Optional[Dict[str, str]] = None, parent=None) -> None:
        super().__init__(parent)
        self.theme = theme or {}
        self._build()
        self.reset_session()
        self._history: List[str] = []
        self._history_index = 0
        self._pending: List[str] = []

    # ------------------------------------------------------------------ 界面
    def _build(self) -> None:
        """搭出记录区 + 输入行。"""

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)

        self.transcript = QtWidgets.QPlainTextEdit()
        self.transcript.setReadOnly(True)
        self.transcript.setFont(QtGui.QFont("Consolas", 10))
        self.transcript.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.NoWrap)
        # 别让记录无限长
        self.transcript.document().setMaximumBlockCount(5000)
        layout.addWidget(self.transcript, 1)

        row = QtWidgets.QHBoxLayout()
        row.setSpacing(4)
        self.prompt_label = QtWidgets.QLabel(PROMPT)
        self.input = QtWidgets.QLineEdit()
        self.input.setPlaceholderText("写一行 Rupis，回车执行；:help 看命令")
        self.input.returnPressed.connect(self.execute)
        self.input.installEventFilter(self)
        row.addWidget(self.prompt_label)
        row.addWidget(self.input, 1)
        btn_load = QtWidgets.QPushButton("载入当前脚本")
        btn_load.clicked.connect(self.loadCurrentRequested.emit)
        row.addWidget(btn_load)
        btn_clear = QtWidgets.QPushButton("清空")
        btn_clear.clicked.connect(self.clear)
        row.addWidget(btn_clear)
        layout.addLayout(row)

    def apply_theme(self, theme: Dict[str, str]) -> None:
        """换主题：记录区用的是控件自己的调色板，这里只留一份备用配色。"""

        self.theme = theme

    # ------------------------------------------------------------------ 事件
    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        """上下键翻历史。"""

        if obj is self.input and event.type() == QtCore.QEvent.Type.KeyPress:
            if event.key() == QtCore.Qt.Key.Key_Up:
                self._history_move(-1)
                return True
            if event.key() == QtCore.Qt.Key.Key_Down:
                self._history_move(1)
                return True
        return super().eventFilter(obj, event)

    def _history_move(self, delta: int) -> None:
        """在历史记录里前后翻；翻到最下面就回到空输入。"""

        if not self._history:
            return
        index = max(0, min(len(self._history), self._history_index + delta))
        self._history_index = index
        if index >= len(self._history):
            self.input.setText("")
        else:
            self.input.setText(self._history[index])

    # ------------------------------------------------------------------ 会话
    def reset_session(self) -> None:
        """清空会话状态，重新开始。"""

        self.interpreter = Interpreter()
        self._pending = []

    def clear(self) -> None:
        """只清屏，不动会话状态。"""

        self.transcript.clear()

    # ------------------------------------------------------------------ 执行
    def execute(self) -> None:
        """回车：执行当前输入行。"""

        text = self.input.text()
        self.input.clear()
        if not text.strip():
            return

        self._history.append(text)
        self._history_index = len(self._history)
        self._write(PROMPT + text)

        if text.strip().startswith(":"):
            self._run_command(text.strip())
            return

        # 不是命令就当代码：先攒着，攒够一个完整的代码块再执行
        self._pending.append(text)
        source = "\n".join(self._pending)
        if not _braces_balanced(source):
            self.prompt_label.setText("… ")
            self._write("  … 还没写完（结尾的 } 闭合代码块）")
            return
        self._pending = []
        self.prompt_label.setText(PROMPT)
        self._run(source, "<控制台>")

    def run_source(self, text: str, filename: str = "<控制台>") -> None:
        """在当前会话里执行一整段脚本。"""

        try:
            program, source = compile_source(text, filename)
        except RupisError as exc:
            self._write(exc.render(), error=True)
            return
        interpreter = self.interpreter
        interpreter.source = source
        try:
            interpreter.run(program)
        except RupisError as exc:
            self._write(exc.render(), error=True)
            return
        except Exception as exc:  # pragma: no cover - 兜底
            self._write(f"内部错误：{exc}", error=True)
            return
        self._write(f"已载入 {filename}（当前共 {len(interpreter.world)} 个方块）")

    def _run(self, source: str, filename: str) -> None:
        """执行一段代码，并根据语句种类回显结果。"""

        interpreter = self.interpreter

        # 光敲一个 dpos / drp 变量名，就把它显示出来。
        # （语言本身不允许把 dpos 当普通表达式用，但 REPL 里查一下很常见）
        stripped = source.strip()
        if stripped.isidentifier():
            if stripped in interpreter.dpos_vars:
                self._write(self._format_value(interpreter.dpos_vars[stripped]))
                return
            if stripped in interpreter.drp_vars:
                self._write(self._format_states(interpreter.drp_vars[stripped]))
                return

        try:
            program, src = compile_source(source, filename)
        except RupisError as exc:
            self._write(exc.render(), error=True)
            return

        interpreter.source = src
        try:
            # 只有一条表达式时自己求值，好把结果显示出来
            if len(program) == 1 and isinstance(program[0], ExprStmt):
                value = interpreter.eval_expr(program[0].expr, interpreter.global_scope)
                self._write(self._format_value(value))
                return
            # 赋值语句回显一下，像 Python 的交互式解释器
            if len(program) == 1 and isinstance(program[0], (LetStmt, AssignStmt)):
                interpreter.run(program)
                name = program[0].name
                try:
                    value = interpreter.global_scope.get(name)
                except KeyError:
                    value = None
                self._write(f"{name} = {self._format_value(value)}")
                return
            before = len(interpreter.world)
            interpreter.run(program)
            added = len(interpreter.world) - before
            if added:
                self._write(f"已放置 {added} 个方块（当前共 {len(interpreter.world)} 个）")
        except RupisError as exc:
            self._write(exc.render(), error=True)
        except Exception as exc:  # pragma: no cover - 兜底
            self._write(f"内部错误：{exc}", error=True)

    # ------------------------------------------------------------------ 命令
    def _run_command(self, text: str) -> None:
        """分发以 : 开头的命令。"""

        name, _, arg = text.partition(" ")
        name = name.lower()
        arg = arg.strip()

        if name in (":help", ":h", ":?"):
            for line in HELP_TEXT.splitlines():
                self._write(line)
        elif name == ":reset":
            self.reset_session()
            self._write("会话已重置")
        elif name == ":world":
            self._write(self._world_summary())
        elif name == ":vars":
            self._write(self._vars_summary())
        elif name == ":load":
            self._load_file(arg)
        else:
            self._write(f"未知命令 {name}，:help 看可用命令", error=True)

    def _load_file(self, path_text: str) -> None:
        """把一个 .rpi 脚本读进来，在当前会话里执行。"""

        if not path_text:
            self._write("用法：:load 文件路径", error=True)
            return
        path = Path(path_text)
        if not path.is_file():
            self._write(f"找不到文件：{path}", error=True)
            return
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = path.read_text(encoding="gbk", errors="replace")
        except OSError as exc:
            self._write(f"读取失败：{exc}", error=True)
            return
        self.run_source(text, str(path))

    def _world_summary(self) -> str:
        """统计当前放了多少方块，按方块种类分组。"""

        world = self.interpreter.world
        if not world:
            return "当前还没有放置任何方块"
        counts: Dict[str, int] = {}
        for placement in world.values():
            counts[placement.block_id] = counts.get(placement.block_id, 0) + 1
        lines = [f"共放置 {len(world)} 个方块："]
        # 数量多的排前面，数量一样按方块 ID 排，保证输出稳定
        for block_id, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
            lines.append(f"  {block_id}: {count}")
        return "\n".join(lines)

    def _vars_summary(self) -> str:
        """列出当前的 dpos / drp 变量、函数和结构。"""

        interpreter = self.interpreter
        lines = []
        if interpreter.dpos_vars:
            lines.append("dpos 坐标变量：")
            for name, coord in sorted(interpreter.dpos_vars.items()):
                lines.append(f"  {name} = {self._format_value(coord)}")
        if interpreter.drp_vars:
            lines.append("drp 状态模板：")
            for name, value in sorted(interpreter.drp_vars.items()):
                lines.append(f"  {name} = {self._format_states(value)}")
        if interpreter.functions:
            lines.append("函数：" + "、".join(sorted(interpreter.functions)))
        if interpreter.structs:
            lines.append("结构：" + "、".join(sorted(interpreter.structs)))
        if not lines:
            return "当前还没有任何变量"
        return "\n".join(lines)

    # ------------------------------------------------------------------ 输出
    @staticmethod
    def _format_value(value) -> str:
        """把一个值格式成给人看的样子。"""

        if isinstance(value, tuple):
            return "(" + ", ".join(str(item) for item in value) + ")"
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

    def _format_states(self, states) -> str:
        """把 drp 状态模板显示成人能看懂的样子。

        模板里存的是还没求值的表达式节点，直接 str() 会打印出一堆 AST 细节。
        """

        if not isinstance(states, dict):
            return str(states)
        parts = []
        for key, entry in states.items():
            value = entry
            if hasattr(entry, "expr"):
                try:
                    value = self.interpreter.eval_expr(
                        entry.expr, self.interpreter.global_scope)
                except Exception:      # 求不了就退回原始表示
                    value = entry
            parts.append(f"{key}={self._format_value(value)}")
        return "{" + ", ".join(parts) + "}"

    def _write(self, text: str, error: bool = False) -> None:
        """往记录区追加一行；error=True 时用错误色写，写完再把颜色改回来。"""

        cursor = self.transcript.textCursor()
        cursor.movePosition(QtGui.QTextCursor.MoveOperation.End)
        if error:
            fmt = QtGui.QTextCharFormat()
            fmt.setForeground(QtGui.QColor(self.theme.get("err", "#f44747")))
            cursor.setCharFormat(fmt)
        cursor.insertText(text + "\n")
        if error:
            fmt = QtGui.QTextCharFormat()
            fmt.setForeground(QtGui.QColor(self.theme.get("fg", "#d4d4d4")))
            cursor.setCharFormat(fmt)
        self.transcript.setTextCursor(cursor)
        self.transcript.ensureCursorVisible()

    def focus_input(self) -> None:
        """把焦点挪到输入框（切到控制台页时用）。"""

        self.input.setFocus()


def _braces_balanced(text: str) -> bool:
    """判断代码块的花括号是否配平（没配平就说明还没写完）。"""

    depth = 0
    for ch in text:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
    return depth <= 0
