"""Rupis 内嵌终端。

下方面板的第三页：能真正敲命令的终端。
Windows 上跑 cmd.exe，别的平台跑 sh。

实现上不是"常驻一个 shell 往里灌字符"，而是**一条命令起一个进程**：

    cmd.exe 从管道里读命令时既不回显也不认 Ctrl+C —— 用常驻 shell 的话，
    ping -t 就再也停不下来，Ctrl+C 只是往管道里塞一个没人读的字符。
    一条命令一个进程就没这问题：Ctrl+C 直接把整棵进程树砍掉。

代价是 cd 得自己记。命令跑完时让 cmd 顺带打印一下当前目录，拿到就更新。
"""

from __future__ import annotations

import codecs
import locale
import os
import re
import signal
import subprocess
import threading
from pathlib import Path
from typing import Dict, List, Optional

from .qtcompat import QtCore, QtGui, QtWidgets

# 目录标记：命令跑完时让 cmd 打印一下当前目录
_CWD_MARKER = "__RUPIS_CWD__"
_CWD_PREFIX = _CWD_MARKER + ":"

# for %i in (.) 是**执行期**才去取当前目录；%CD% 是解析期就展开的，
# cd 之后的目录它取不到（实测 cd examples & echo %CD% 打印的还是旧目录）。
_CWD_PROBE = "for %i in (.) do @echo " + _CWD_PREFIX + "%~fi"

# 本地兜底：命令没带出标记时，如果就是一句 cd，自己算一下
_CD_RE = re.compile(r"^\s*(?:cd|chdir)\s+(?:/d\s+)?(.+?)\s*$", re.IGNORECASE)


def shell_encoding() -> str:
    """cmd 的输出走 OEM 代码页（中文系统是 cp936），不是 ANSI 代码页。"""
    if os.name == "nt":
        try:
            import ctypes
            code = ctypes.windll.kernel32.GetOEMCP()
            if code:
                return "cp" + str(code)
        except Exception:  # pragma: no cover - 拿不到就退回默认
            pass
    return locale.getpreferredencoding(False) or "utf-8"


def build_command_line(command: str) -> str:
    """拼出交给 shell 的整条命令行。

    Windows 上字符串形式的命令行是**原样**递给 CreateProcess 的，
    所以引号得自己配平：cmd /c "xxx" 里，cmd 会按 /s 的规矩剥掉最外层
    那对引号，里面的引号原样保留。

    末尾拼上目录探针，这样 cd 之后终端知道自己在哪。
    引号数是奇数（用户自己敲漏了）时不拼探针 —— 那条命令多半也跑不对，
    硬拼反而会把后面一整段都吞进引号里。
    """
    if os.name == "nt":
        if command.count('"') % 2 == 0:
            return f'cmd.exe /d /s /c "{command} & {_CWD_PROBE}"'
        return f'cmd.exe /d /s /c "{command}"'
    shell = os.environ.get("SHELL") or "/bin/sh"
    return f'"{shell}" -c {command}'


def _is_marker_candidate(text: str) -> bool:
    """这段文字可能是目录标记（要么是标记本身，要么是标记的前半截）。"""
    return _CWD_PREFIX.startswith(text) or text.startswith(_CWD_PREFIX)


class _CommandThread(QtCore.QThread):
    """在后台跑一条命令，输出实时送回界面。"""

    output = QtCore.pyqtSignal(str)
    cwdFound = QtCore.pyqtSignal(str)
    commandDone = QtCore.pyqtSignal(int)

    def __init__(self, command: str, cwd: str, encoding: str, parent=None) -> None:
        super().__init__(parent)
        self.command = command
        self.cwd = cwd
        self.encoding = encoding
        self.proc: Optional[subprocess.Popen] = None
        self._kill_requested = False
        self._stop_output = False
        self._reader: Optional[threading.Thread] = None
        self._buf = ""

    # ------------------------------------------------------------------ 执行
    def run(self) -> None:  # noqa: D102
        try:
            line = build_command_line(self.command)
        except Exception as exc:  # pragma: no cover - 兜底
            self.output.emit(f"无法执行：{exc}\n")
            self.commandDone.emit(-1)
            return

        kwargs = dict(stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                      stdin=subprocess.DEVNULL, cwd=self.cwd)
        if os.name == "nt":
            # 独立进程组，Ctrl+C 时能连子孙进程一起收拾
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            kwargs["start_new_session"] = True

        try:
            self.proc = subprocess.Popen(line, **kwargs)
        except Exception as exc:
            self.output.emit(f"无法执行：{exc}\n")
            self.commandDone.emit(-1)
            return

        # Ctrl+C 来得比进程起得还早：这时候刚创建，得马上补刀
        if self._kill_requested:
            self.kill()

        # 读管道单独开一个线程：cmd 退出后管道可能还被 detach 出去的
        # 子进程攥着（比如 start notepad），那时候就该收工了，不能一直等。
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        try:
            code = self.proc.wait()
        except Exception:  # pragma: no cover
            code = -1
        self._reader.join(timeout=1.0)
        if self._reader.is_alive():
            # 管道还没关，但命令本身已经结束了 —— 别再往下发信号
            self._stop_output = True
        else:
            try:
                self.proc.stdout.close()
            except Exception:  # pragma: no cover
                pass
        self._flush()
        self.commandDone.emit(code)

    def _read_loop(self) -> None:
        """把子进程的输出读出来，边读边发。"""
        decoder = codecs.getincrementaldecoder(self.encoding)(errors="replace")
        try:
            while True:
                chunk = self.proc.stdout.read1(4096)
                if not chunk:
                    break
                text = decoder.decode(chunk)
                if text:
                    self._feed(text)
            tail = decoder.decode(b"", True)
            if tail:
                self._feed(tail)
        except Exception as exc:  # pragma: no cover - 兜底
            if not self._stop_output:
                self.output.emit(f"\n读取输出出错：{exc}\n")

    def _feed(self, text: str) -> None:
        """把一段输出拆成行，目录标记那条单独拎出来。"""
        if self._stop_output:
            return
        self._buf += text
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            self._emit_line(line)
        # 剩下的是还没换行的一段
        if self._buf and not _is_marker_candidate(self._buf):
            self.output.emit(self._buf)
            self._buf = ""

    def _emit_line(self, line: str) -> None:
        line = line.rstrip("\r")
        if line.startswith(_CWD_PREFIX):
            self.cwdFound.emit(line[len(_CWD_PREFIX):].strip())
            return
        self.output.emit(line + "\n")

    def _flush(self) -> None:
        """命令结束，把最后一段没换行的输出处理掉。"""
        if not self._buf or self._stop_output:
            return
        if self._buf.startswith(_CWD_PREFIX):
            self.cwdFound.emit(self._buf[len(_CWD_PREFIX):].strip())
        else:
            self.output.emit(self._buf)
        self._buf = ""

    # ------------------------------------------------------------------ 中断
    def kill(self) -> None:
        """把命令连同它起的子进程一起干掉。"""
        proc = self.proc
        if proc is None:
            # 进程还没创建出来 —— 记下来，等它起来马上补刀
            self._kill_requested = True
            return
        if proc.poll() is not None:
            return
        if os.name == "nt":
            # 只 kill cmd 的话，ping.exe 之类的孙进程会留下来接着跑
            try:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               timeout=5)
                return
            except Exception:  # pragma: no cover - taskkill 失败就退回普通 kill
                pass
            try:
                proc.kill()
            except Exception:  # pragma: no cover
                pass
            return
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except Exception:  # pragma: no cover
            try:
                proc.kill()
            except Exception:
                pass


class TerminalWidget(QtWidgets.QWidget):
    """下方面板的终端页。"""

    def __init__(self, cwd=None, theme: Optional[Dict[str, str]] = None,
                 parent=None) -> None:
        super().__init__(parent)
        self.theme = theme or {}
        self._cwd = Path(cwd) if cwd else Path.cwd()
        self.script_dir: Optional[Path] = None
        self._thread: Optional[_CommandThread] = None
        self._encoding = shell_encoding()
        self._history: List[str] = []
        self._history_index = 0
        self.last_exit_code = 0
        self._build()
        self._update_prompt()

    # ------------------------------------------------------------------ 界面
    def _build(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)

        # ---- 上面一排：工作目录
        bar = QtWidgets.QHBoxLayout()
        bar.setSpacing(4)
        self.dir_label = QtWidgets.QLabel("")
        self.dir_label.setTextInteractionFlags(
            QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        bar.addWidget(self.dir_label, 1)
        self.btn_script_dir = QtWidgets.QPushButton("转到脚本目录")
        self.btn_script_dir.clicked.connect(self.goto_script_dir)
        bar.addWidget(self.btn_script_dir)
        self.btn_pick_dir = QtWidgets.QPushButton("选择目录…")
        self.btn_pick_dir.clicked.connect(self.pick_dir)
        bar.addWidget(self.btn_pick_dir)
        self.btn_clear = QtWidgets.QPushButton("清屏")
        self.btn_clear.clicked.connect(self.clear)
        bar.addWidget(self.btn_clear)
        layout.addLayout(bar)

        # ---- 中间：输出
        self.transcript = QtWidgets.QPlainTextEdit()
        self.transcript.setReadOnly(True)
        self.transcript.setFont(QtGui.QFont("Consolas", 10))
        self.transcript.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.NoWrap)
        self.transcript.document().setMaximumBlockCount(5000)
        layout.addWidget(self.transcript, 1)

        # ---- 下面：提示符 + 输入
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(2)
        self.prompt_label = QtWidgets.QLabel("")
        self.prompt_label.setFont(QtGui.QFont("Consolas", 10))
        self.input = QtWidgets.QLineEdit()
        self.input.setFont(QtGui.QFont("Consolas", 10))
        self.input.setPlaceholderText("在这里敲命令，回车执行（Ctrl+C 中断，Ctrl+L 清屏）")
        self.input.returnPressed.connect(self.submit)
        self.input.installEventFilter(self)
        row.addWidget(self.prompt_label)
        row.addWidget(self.input, 1)
        layout.addLayout(row)

    def apply_theme(self, theme: Dict[str, str]) -> None:
        self.theme = theme
        self.dir_label.setStyleSheet(f"color: {theme.get('dim', '#858585')};")

    # ------------------------------------------------------------------ 目录
    @property
    def cwd(self) -> Path:
        """终端当前所在的目录。"""
        return self._cwd

    def set_cwd(self, path) -> None:
        """换工作目录（下一条命令就在新目录里跑）。"""
        if not path:
            return
        path = Path(path)
        if not path.is_dir():
            return
        self._cwd = path
        self._update_prompt()

    def set_script_dir(self, path) -> None:
        """IDE 打开的脚本文件夹 —— "转到脚本目录"按钮用的就是这个。"""
        self.script_dir = Path(path) if path else None
        self.btn_script_dir.setEnabled(self.script_dir is not None)

    def goto_script_dir(self) -> None:
        if self.script_dir is not None:
            self.set_cwd(self.script_dir)

    def pick_dir(self) -> None:
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self, "选择终端工作目录", str(self._cwd))
        if folder:
            self.set_cwd(folder)

    def prompt_text(self) -> str:
        """提示符：Windows 用 >，别的平台用 $。"""
        if os.name == "nt":
            return f"{self._cwd}>"
        return f"{self._cwd}$ "

    def _update_prompt(self) -> None:
        self.prompt_label.setText(self.prompt_text())
        self.dir_label.setText(f"工作目录：{self._cwd}")

    # ------------------------------------------------------------------ 输入
    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        """上下键翻历史，Ctrl+C 中断，Ctrl+L 清屏。"""
        if obj is self.input and event.type() == QtCore.QEvent.Type.KeyPress:
            key = event.key()
            ctrl = bool(event.modifiers() & QtCore.Qt.KeyboardModifier.ControlModifier)
            if ctrl and key == QtCore.Qt.Key.Key_C:
                self.interrupt()
                return True
            if ctrl and key == QtCore.Qt.Key.Key_L:
                self.clear()
                return True
            if key == QtCore.Qt.Key.Key_Up:
                self._history_move(-1)
                return True
            if key == QtCore.Qt.Key.Key_Down:
                self._history_move(1)
                return True
        return super().eventFilter(obj, event)

    def _history_move(self, delta: int) -> None:
        if not self._history:
            return
        index = max(0, min(len(self._history), self._history_index + delta))
        self._history_index = index
        if index >= len(self._history):
            self.input.setText("")
        else:
            self.input.setText(self._history[index])

    def submit(self) -> None:
        """回车：执行当前输入。"""
        text = self.input.text()
        self.input.clear()
        if not text.strip():
            return
        self._history.append(text)
        self._history_index = len(self._history)
        self._echo(text)
        self.run_command(text)

    def run_command(self, text: str) -> None:
        """跑一条命令。"""
        if self._thread is not None and self._thread.isRunning():
            self._append("（上一条命令还在跑，Ctrl+C 可以中断）\n")
            return
        thread = _CommandThread(text, str(self._cwd), self._encoding, self)
        thread.output.connect(self._on_output)
        thread.cwdFound.connect(self._on_cwd_found)
        thread.commandDone.connect(self._on_command_done)
        thread.finished.connect(thread.deleteLater)
        self._thread = thread
        thread.start()

    def interrupt(self) -> None:
        """Ctrl+C：把正在跑的命令连同子进程一起砍掉。"""
        thread = self._thread
        if thread is None or not thread.isRunning():
            self._append("^C\n")
            return
        thread.kill()
        self._append("^C\n")

    # ------------------------------------------------------------------ 输出
    def _on_output(self, text: str) -> None:
        self._append(text)

    def _on_cwd_found(self, path_text: str) -> None:
        if not path_text:
            return
        path = Path(path_text)
        if path.is_dir():
            self.set_cwd(path)
        else:
            # 探针没给准，就自己按 cd 算一下
            self._local_cd(path_text)

    def _on_command_done(self, code: int) -> None:
        self.last_exit_code = code
        self._ensure_newline()
        if self._thread is not None:
            self._thread = None

    def _local_cd(self, target: str) -> None:
        """命令没带出目录标记时，按 cd 自己算。"""
        match = _CD_RE.match(target)
        if not match:
            return
        raw = match.group(1).strip().strip('"')
        if not raw:
            return
        try:
            path = Path(raw)
            if not path.is_absolute():
                path = self._cwd / path
            path = path.resolve()
        except Exception:  # pragma: no cover
            return
        if path.is_dir():
            self.set_cwd(path)

    def _echo(self, text: str) -> None:
        """把敲进去的命令回显到记录里，像真的终端那样。"""
        self._ensure_newline()
        self._append(self.prompt_text() + text + "\n")

    def _ensure_newline(self) -> None:
        block = self.transcript.document().lastBlock()
        if block.isValid() and block.text():
            self._append("\n")

    def _append(self, text: str) -> None:
        cursor = self.transcript.textCursor()
        cursor.movePosition(QtGui.QTextCursor.MoveOperation.End)
        cursor.insertText(text)
        self.transcript.setTextCursor(cursor)
        self.transcript.ensureCursorVisible()

    def clear(self) -> None:
        """清屏（不动工作目录）。"""
        self.transcript.clear()

    def shutdown(self) -> None:
        """关窗口前把正在跑的命令停掉。

        不停的话 QThread 会在运行中被析构，Qt 会直接崩掉。
        """
        thread = self._thread
        if thread is None:
            return
        thread.kill()
        thread.wait(3000)
        self._thread = None

    def focus_input(self) -> None:
        self.input.setFocus()
