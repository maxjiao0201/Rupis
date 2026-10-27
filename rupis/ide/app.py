"""Rupis IDE 主窗口。

布局：
    ┌ 菜单栏 ────────────────────────────────┐
    │ 工具栏                                  │
    ├──────────┬────────────────────────────┤
    │ 文件列表 │ 查找条（Ctrl+F 时弹出）        │
    │          ├────────────────────────────┤
    │          │ 编辑器                       │
    │          ├────────────────────────────┤
    │          │ 提示栏                       │
    │          ├────────────────────────────┤
    │          │ 输出 / 控制台 / 终端           │
    ├──────────┴────────────────────────────┤
    │ 状态栏（行:列 / 文件 / 提示）             │
    └───────────────────────────────────────┘
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path
from typing import List, Optional

from .. import RupisError, compile_source, run_source
from .. import exporters
from .console import RupisConsole
from .editor import RupisEditor
from .find import FindPanel
from .qtcompat import QAction, QtCore, QtGui, QtWidgets
from .terminal import TerminalWidget
from .theme import THEMES, stylesheet

CONFIG_PATH = Path.home() / ".rupis_ide.json"

NEW_TEMPLATE = """// 示例 Rupis 脚本
dpos base[100,64,200]
drp  high{rsig=15}

// rw 指红石粉；rrep / rco / obs / rtorch / rlamp / piston / sticky 各有各的表示
rw{high}[base]

// strudef 定义方块模板，stru 实例化它
strudef unit(facing){locked=false}:{
    rrep{facing=facing,delay=1,locked=locked}[0,0,0]
}

// def 是逻辑函数
def chain(n, f):{
    for i = (0 to n-1):{
        stru unit(f){}[base + xi]
    }
    return 0
}
chain(4, east)
"""


# ====================================================================== 后台任务
class Job(QtCore.QThread):
    """在后台线程里跑脚本，结果用信号送回主线程。"""

    ok = QtCore.pyqtSignal(str)
    bad = QtCore.pyqtSignal(str, int, int)

    def __init__(self, text: str, filename: str, mode: str, parent=None,
                 lib_paths=None) -> None:
        super().__init__(parent)
        self.text = text
        self.filename = filename
        self.mode = mode
        self.lib_paths = list(lib_paths or [])

    def run(self) -> None:  # noqa: D102
        try:
            if self.mode == "check":
                compile_source(self.text, self.filename)
                self.ok.emit("语法检查通过。")
                return
            interpreter = run_source(self.text, self.filename,
                                     lib_paths=self.lib_paths)
            summary = exporters.summary(interpreter.world)
            commands = exporters.export_commands(interpreter.world)
            self.ok.emit(summary + "\n\n" + commands)
        except RupisError as exc:
            self.bad.emit(exc.render(), exc.line or 0, exc.col or 0)
        except Exception as exc:  # pragma: no cover - 兜底
            self.bad.emit("内部错误：\n" + traceback.format_exc(), 0, 0)


# ====================================================================== 主窗口
class RupisIDE(QtWidgets.QMainWindow):
    # QSettings 用的组织名 / 应用名；测试里会换掉，免得污染用户自己的设置
    ORG_NAME = "Rupis"
    ORG_APP = "Rupis IDE"

    def __init__(self, path: Optional[str] = None) -> None:
        super().__init__()
        self.setWindowTitle("Rupis IDE")
        self.resize(1180, 760)

        self._settings = QtCore.QSettings(self.ORG_NAME, self.ORG_APP)
        self.theme_name = str(self._settings.value("theme", "dark"))
        if self.theme_name not in THEMES:
            self.theme_name = "dark"
        self.theme = THEMES[self.theme_name]

        self.current_path: Optional[Path] = None
        self.folder: Optional[Path] = None
        self._job: Optional[Job] = None
        self._recent: List[str] = self._load_recent()

        self._build_actions()
        self._build_menu()
        self._build_toolbar()
        self._build_central()
        self._build_status()
        self._apply_theme()

        # 上次记住的文件夹
        last_folder = str(self._settings.value("folder", ""))
        if last_folder and Path(last_folder).is_dir():
            self.folder = Path(last_folder)

        # 终端的工作目录跟着 IDE 的工作路径走
        self._sync_terminal_cwd()

        # lib 导入 .rpi 脚本时搜索的目录
        self._sync_lib_paths()

        if path:
            self.open_file(path)
        else:
            self.editor.setPlainText(NEW_TEMPLATE)
        self._refresh_file_list()
        self._restore_state()

    # ================================================================ 动作
    def _build_actions(self) -> None:
        self.act_new = QAction("新建", self)
        self.act_new.setShortcut("Ctrl+N")
        self.act_new.triggered.connect(lambda: self.new_file())

        self.act_open = QAction("打开…", self)
        self.act_open.setShortcut("Ctrl+O")
        self.act_open.triggered.connect(lambda: self.open_dialog())

        self.act_folder = QAction("打开文件夹…", self)
        self.act_folder.triggered.connect(lambda: self.open_folder())

        self.act_save = QAction("保存", self)
        self.act_save.setShortcut("Ctrl+S")
        self.act_save.triggered.connect(lambda: self.save_file())

        self.act_save_as = QAction("另存为…", self)
        self.act_save_as.setShortcut("Ctrl+Shift+S")
        self.act_save_as.triggered.connect(lambda: self.save_as_dialog())

        self.act_quit = QAction("退出", self)
        self.act_quit.setShortcut("Ctrl+Q")
        self.act_quit.triggered.connect(self.close)

        # ---- 编辑
        self.act_undo = QAction("撤销", self)
        self.act_undo.setShortcut("Ctrl+Z")
        self.act_undo.triggered.connect(lambda: self.editor.undo())

        self.act_redo = QAction("重做", self)
        self.act_redo.setShortcuts([QtGui.QKeySequence("Ctrl+Shift+Z"),
                                    QtGui.QKeySequence("Ctrl+Y")])
        self.act_redo.triggered.connect(lambda: self.editor.redo())

        self.act_cut = QAction("剪切", self)
        self.act_cut.setShortcut("Ctrl+X")
        self.act_cut.triggered.connect(lambda: self.editor.cut())

        self.act_copy = QAction("复制", self)
        self.act_copy.setShortcut("Ctrl+C")
        self.act_copy.triggered.connect(lambda: self.editor.copy())

        self.act_paste = QAction("粘贴", self)
        self.act_paste.setShortcut("Ctrl+V")
        self.act_paste.triggered.connect(lambda: self.editor.paste())

        self.act_select_all = QAction("全选", self)
        self.act_select_all.setShortcut("Ctrl+A")
        self.act_select_all.triggered.connect(lambda: self.editor.selectAll())

        self.act_find = QAction("查找…", self)
        self.act_find.setShortcut("Ctrl+F")
        self.act_find.triggered.connect(lambda: self.show_find(replace=False))

        self.act_replace = QAction("替换…", self)
        self.act_replace.setShortcut("Ctrl+H")
        self.act_replace.triggered.connect(lambda: self.show_find(replace=True))

        self.act_find_next = QAction("查找下一个", self)
        self.act_find_next.setShortcut("F3")
        self.act_find_next.triggered.connect(lambda: self.find_panel.find_next())

        self.act_find_prev = QAction("查找上一个", self)
        self.act_find_prev.setShortcut("Shift+F3")
        self.act_find_prev.triggered.connect(lambda: self.find_panel.find_previous())

        self.act_goto = QAction("跳转到行…", self)
        self.act_goto.setShortcut("Ctrl+G")
        self.act_goto.triggered.connect(lambda: self.goto_line_dialog())

        self.act_goto_def = QAction("跳转到定义", self)
        self.act_goto_def.setShortcut("F12")
        self.act_goto_def.triggered.connect(lambda: self.editor.jump_to_definition())

        self.act_comment = QAction("注释/取消注释", self)
        self.act_comment.setShortcut("Ctrl+/")
        self.act_comment.triggered.connect(lambda: self.editor._toggle_comment())

        self.act_line_up = QAction("上移一行", self)
        self.act_line_up.setShortcut("Alt+Up")
        self.act_line_up.triggered.connect(lambda: self.editor.move_lines(-1))

        self.act_line_down = QAction("下移一行", self)
        self.act_line_down.setShortcut("Alt+Down")
        self.act_line_down.triggered.connect(lambda: self.editor.move_lines(1))

        self.act_dup_line = QAction("复制当前行", self)
        self.act_dup_line.setShortcut("Ctrl+Shift+D")
        self.act_dup_line.triggered.connect(lambda: self.editor.duplicate_lines())

        self.act_del_line = QAction("删除当前行", self)
        self.act_del_line.setShortcut("Ctrl+Shift+K")
        self.act_del_line.triggered.connect(lambda: self.editor.delete_lines())

        # ---- 运行
        self.act_run = QAction("运行", self)
        self.act_run.setShortcut("F5")
        self.act_run.triggered.connect(lambda: self.run_script())

        self.act_check = QAction("检查语法", self)
        self.act_check.setShortcut("F9")
        self.act_check.triggered.connect(lambda: self.check_script())

        self.act_export = QAction("导出 .mcstructure…", self)
        self.act_export.setShortcut("Ctrl+E")
        self.act_export.triggered.connect(lambda: self.export_structure())

        self.act_export_cmds = QAction("导出 /setblock 命令…", self)
        self.act_export_cmds.triggered.connect(lambda: self.export_text("commands"))

        self.act_export_json = QAction("导出 JSON…", self)
        self.act_export_json.triggered.connect(lambda: self.export_text("json"))

        self.act_clear = QAction("清除输出", self)
        self.act_clear.setShortcut("Ctrl+L")
        self.act_clear.triggered.connect(lambda: self.console.clear())

        self.act_copy_output = QAction("复制输出", self)
        self.act_copy_output.triggered.connect(self.copy_output)

        # ---- 底部面板切换
        self.act_tab_output = QAction("显示输出", self)
        self.act_tab_output.setShortcut("Ctrl+1")
        self.act_tab_output.triggered.connect(lambda: self._select_bottom_tab(0))

        self.act_tab_console = QAction("显示控制台", self)
        self.act_tab_console.setShortcut("Ctrl+2")
        self.act_tab_console.triggered.connect(lambda: self._select_bottom_tab(1))

        self.act_tab_terminal = QAction("显示终端", self)
        self.act_tab_terminal.setShortcut("Ctrl+3")
        self.act_tab_terminal.triggered.connect(lambda: self._select_bottom_tab(2))

        self.act_console_clear = QAction("清空控制台屏幕", self)
        self.act_console_clear.triggered.connect(self._console_clear)

        # ---- 视图
        self.act_zoom_in = QAction("放大字号", self)
        self.act_zoom_in.setShortcut(QtGui.QKeySequence("Ctrl+="))
        self.act_zoom_in.triggered.connect(lambda: self.editor.zoom_in())

        self.act_zoom_out = QAction("缩小字号", self)
        self.act_zoom_out.setShortcut(QtGui.QKeySequence("Ctrl+-"))
        self.act_zoom_out.triggered.connect(lambda: self.editor.zoom_out())

        self.act_zoom_reset = QAction("复位字号", self)
        self.act_zoom_reset.setShortcut(QtGui.QKeySequence("Ctrl+0"))
        self.act_zoom_reset.triggered.connect(lambda: self.editor.reset_zoom())

        self.act_theme = QAction("切换到浅色主题", self)
        self.act_theme.triggered.connect(lambda: self.toggle_theme())

        self.act_about = QAction("关于", self)
        self.act_about.triggered.connect(lambda: self.show_about())

        self.act_shortcuts = QAction("快捷键一览", self)
        self.act_shortcuts.triggered.connect(lambda: self.show_shortcuts())

    def _build_menu(self) -> None:
        bar = self.menuBar()

        m_file = bar.addMenu("文件")
        m_file.addAction(self.act_new)
        m_file.addAction(self.act_open)
        m_file.addAction(self.act_folder)
        m_file.addSeparator()
        self.recent_menu = m_file.addMenu("最近打开")
        m_file.addSeparator()
        m_file.addAction(self.act_save)
        m_file.addAction(self.act_save_as)
        m_file.addSeparator()
        m_file.addAction(self.act_quit)

        m_edit = bar.addMenu("编辑")
        m_edit.addAction(self.act_undo)
        m_edit.addAction(self.act_redo)
        m_edit.addSeparator()
        m_edit.addAction(self.act_cut)
        m_edit.addAction(self.act_copy)
        m_edit.addAction(self.act_paste)
        m_edit.addAction(self.act_select_all)
        m_edit.addSeparator()
        m_edit.addAction(self.act_find)
        m_edit.addAction(self.act_replace)
        m_edit.addAction(self.act_find_next)
        m_edit.addAction(self.act_find_prev)
        m_edit.addSeparator()
        m_edit.addAction(self.act_goto)
        m_edit.addAction(self.act_goto_def)
        m_edit.addAction(self.act_comment)
        m_edit.addSeparator()
        m_edit.addAction(self.act_line_up)
        m_edit.addAction(self.act_line_down)
        m_edit.addAction(self.act_dup_line)
        m_edit.addAction(self.act_del_line)

        m_run = bar.addMenu("运行")
        m_run.addAction(self.act_run)
        m_run.addAction(self.act_check)
        m_run.addSeparator()
        m_run.addAction(self.act_export)
        m_run.addAction(self.act_export_cmds)
        m_run.addAction(self.act_export_json)
        m_run.addSeparator()
        m_run.addAction(self.act_copy_output)
        m_run.addAction(self.act_clear)
        m_run.addSeparator()
        m_run.addAction(self.act_tab_output)
        m_run.addAction(self.act_tab_console)
        m_run.addAction(self.act_tab_terminal)
        m_run.addAction(self.act_console_clear)

        m_view = bar.addMenu("视图")
        m_view.addAction(self.act_zoom_in)
        m_view.addAction(self.act_zoom_out)
        m_view.addAction(self.act_zoom_reset)
        m_view.addSeparator()
        m_view.addAction(self.act_theme)

        m_help = bar.addMenu("帮助")
        m_help.addAction(self.act_shortcuts)
        m_help.addAction(self.act_about)

        self._refresh_recent_menu()

    def _build_toolbar(self) -> None:
        tb = QtWidgets.QToolBar("主工具栏")
        tb.setMovable(False)
        tb.setIconSize(QtCore.QSize(18, 18))
        tb.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.addToolBar(tb)
        self.toolbar = tb

        def short_action(label: str, slot, tip: str) -> QAction:
            """工具栏上用短标签，菜单里保留完整说法。"""
            action = QAction(label, self)
            action.setToolTip(tip)
            action.triggered.connect(slot)
            return action

        tb.addAction(short_action("新建", lambda: self.new_file(), "新建脚本 (Ctrl+N)"))
        tb.addAction(short_action("打开", lambda: self.open_dialog(), "打开脚本 (Ctrl+O)"))
        tb.addAction(short_action("保存", lambda: self.save_file(), "保存 (Ctrl+S)"))
        tb.addSeparator()
        tb.addAction(short_action("▶ 运行", lambda: self.run_script(), "运行脚本 (F5)"))
        tb.addAction(short_action("✓ 检查", lambda: self.check_script(), "检查语法 (F9)"))
        tb.addAction(short_action("导出结构", lambda: self.export_structure(),
                                  "导出 .mcstructure (Ctrl+E)"))
        tb.addSeparator()
        tb.addAction(short_action("查找", lambda: self.show_find(False), "查找 (Ctrl+F)"))
        tb.addAction(short_action("主题", lambda: self.toggle_theme(), "深色 / 浅色主题"))

    def _build_central(self) -> None:
        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)

        # 左：文件列表
        left = QtWidgets.QWidget()
        left_layout = QtWidgets.QVBoxLayout(left)
        left_layout.setContentsMargins(4, 4, 4, 4)
        left_layout.setSpacing(4)

        title = QtWidgets.QLabel("脚本")
        title.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        left_layout.addWidget(title)

        self.file_list = QtWidgets.QListWidget()
        # 点一下就打开，不用双击
        self.file_list.itemClicked.connect(
            lambda item: self.open_file(item.data(QtCore.Qt.ItemDataRole.UserRole))
        )
        left_layout.addWidget(self.file_list, 1)

        btn_folder = QtWidgets.QPushButton("打开文件夹…")
        btn_folder.clicked.connect(lambda: self.open_folder())
        left_layout.addWidget(btn_folder)

        self.folder_label = QtWidgets.QLabel("—")
        self.folder_label.setWordWrap(True)
        left_layout.addWidget(self.folder_label)

        # 右：查找条 + 编辑器 + 提示栏 + 控制台
        right = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        # 编辑器要先建好：查找面板要拿它做匹配
        self.editor = RupisEditor(self.theme)
        self.editor.cursorPositionChanged.connect(self._update_position)
        self.editor.textChanged.connect(self._on_text_changed)
        self.editor.hintChanged.connect(self._on_hint)
        self.editor.findRequested.connect(lambda: self.show_find(False))
        self.editor.escapePressed.connect(self._on_escape)

        self.find_panel = FindPanel(self.editor, parent=right)
        right_layout.addWidget(self.find_panel)

        vertical = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        vertical.addWidget(self.editor)

        # 提示栏：显示光标处关键字 / 元件 / 状态键的说明
        self.hint_bar = QtWidgets.QLabel("")
        self.hint_bar.setObjectName("hintBar")
        vertical.addWidget(self.hint_bar)

        # 底部面板：「输出」和「控制台」两页，用标签切换
        self.bottom_tabs = QtWidgets.QTabWidget()

        # ---- 第 1 页：运行输出
        output_box = QtWidgets.QWidget()
        output_layout = QtWidgets.QVBoxLayout(output_box)
        output_layout.setContentsMargins(2, 2, 2, 2)
        output_layout.setSpacing(2)
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(4)
        label = QtWidgets.QLabel("运行结果")
        row.addWidget(label)
        row.addStretch(1)
        btn_copy = QtWidgets.QPushButton("复制")
        btn_copy.clicked.connect(self.copy_output)
        row.addWidget(btn_copy)
        btn_clear = QtWidgets.QPushButton("清除")
        btn_clear.clicked.connect(lambda: self.console.clear())
        row.addWidget(btn_clear)
        output_layout.addLayout(row)

        self.console = QtWidgets.QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setFont(QtGui.QFont("Consolas", 10))
        self.console.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.NoWrap)
        output_layout.addWidget(self.console, 1)
        self.bottom_tabs.addTab(output_box, "输出")

        # ---- 第 2 页：交互式控制台
        self.console_panel = RupisConsole(self.theme)
        self.console_panel.loadCurrentRequested.connect(self._console_load_current)
        self.bottom_tabs.addTab(self.console_panel, "控制台")

        # ---- 第 3 页：终端
        # 工作目录就是 IDE 的工作路径（打开的脚本文件夹；还没打开时是启动目录）
        self.terminal = TerminalWidget(Path.cwd(), self.theme)
        self.bottom_tabs.addTab(self.terminal, "终端")

        vertical.addWidget(self.bottom_tabs)

        vertical.setStretchFactor(0, 3)
        vertical.setStretchFactor(1, 0)
        vertical.setStretchFactor(2, 1)

        right_layout.addWidget(vertical, 1)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([190, 990])
        self.setCentralWidget(splitter)

    def _build_status(self) -> None:
        status = self.statusBar()
        self.lbl_pos = QtWidgets.QLabel("行 1, 列 1")
        self.lbl_file = QtWidgets.QLabel("未命名")
        self.lbl_msg = QtWidgets.QLabel("")
        status.addWidget(self.lbl_msg, 1)
        status.addPermanentWidget(self.lbl_file)
        status.addPermanentWidget(self.lbl_pos)

    # ================================================================ 主题
    def _apply_theme(self) -> None:
        theme = self.theme

        # 注意顺序：先套样式表，再设调色板。
        # 反过来的话，setStyleSheet 会重新 polish 子控件，把刚设好的调色板打回原形。
        self.setStyleSheet(stylesheet(theme))

        app = QtWidgets.QApplication.instance()
        if app is not None:
            palette = QtGui.QPalette()
            palette.setColor(QtGui.QPalette.ColorRole.Window, QtGui.QColor(theme["panel"]))
            palette.setColor(QtGui.QPalette.ColorRole.WindowText, QtGui.QColor(theme["panel_fg"]))
            palette.setColor(QtGui.QPalette.ColorRole.Base, QtGui.QColor(theme["bg"]))
            palette.setColor(QtGui.QPalette.ColorRole.Text, QtGui.QColor(theme["fg"]))
            palette.setColor(QtGui.QPalette.ColorRole.Button, QtGui.QColor(theme["btn"]))
            palette.setColor(QtGui.QPalette.ColorRole.ButtonText, QtGui.QColor(theme["btn_fg"]))
            palette.setColor(QtGui.QPalette.ColorRole.Highlight, QtGui.QColor(theme["sel_bg"]))
            palette.setColor(QtGui.QPalette.ColorRole.HighlightedText, QtGui.QColor(theme["fg"]))
            palette.setColor(QtGui.QPalette.ColorRole.ToolTipBase, QtGui.QColor(theme["bg"]))
            palette.setColor(QtGui.QPalette.ColorRole.ToolTipText, QtGui.QColor(theme["fg"]))
            self._apply_palette(palette)

        # 编辑器有自己的一套配色（行号槽、当前行高亮），单独再刷一次
        self.editor.apply_theme(theme)
        self.console_panel.apply_theme(theme)
        self.terminal.apply_theme(theme)

        self.act_theme.setText("切换到浅色主题" if self.theme_name == "dark" else "切换到深色主题")

    @staticmethod
    def _apply_palette(palette: QtGui.QPalette) -> None:
        """把调色板下发到所有控件。

        光调 QApplication.setPalette() 是不够的：已经建好的控件（尤其是套了样式表的）
        不会跟着刷新，界面就会一半深一半浅。所以逐个再设一遍。
        """
        app = QtWidgets.QApplication.instance()
        if app is None:
            return
        app.setPalette(palette)
        for widget in app.allWidgets():
            try:
                widget.setPalette(palette)
            except TypeError:  # pragma: no cover - 少数非 QWidget 对象
                pass

    def toggle_theme(self) -> None:
        self.theme_name = "light" if self.theme_name == "dark" else "dark"
        self.theme = THEMES[self.theme_name]
        self._settings.setValue("theme", self.theme_name)
        self._apply_theme()

    # ================================================================ 文件
    def _confirm_discard(self) -> bool:
        if not self.editor.document().isModified():
            return True
        answer = QtWidgets.QMessageBox.question(
            self, "Rupis IDE", "当前文件还没保存，要先保存吗？",
            QtWidgets.QMessageBox.StandardButton.Yes |
            QtWidgets.QMessageBox.StandardButton.No |
            QtWidgets.QMessageBox.StandardButton.Cancel,
        )
        if answer == QtWidgets.QMessageBox.StandardButton.Yes:
            return self.save_file()
        if answer == QtWidgets.QMessageBox.StandardButton.No:
            return True
        return False

    def new_file(self) -> None:
        if not self._confirm_discard():
            return
        self.editor.document().setModified(False)
        self.editor.setPlainText(NEW_TEMPLATE)
        self.current_path = None
        self.file_list.clearSelection()
        self.lbl_file.setText("未命名")
        self.setWindowTitle("Rupis IDE — 未命名")

    def open_dialog(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "打开 Rupis 脚本", "", "Rupis 脚本 (*.rpi);;所有文件 (*)"
        )
        if path:
            self.open_file(path)

    def open_folder(self) -> None:
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, "选择脚本文件夹")
        if folder:
            self.folder = Path(folder)
            self._settings.setValue("folder", str(self.folder))
            self._refresh_file_list()
            self._sync_terminal_cwd()
            self._sync_lib_paths()

    def open_file(self, path) -> None:
        if not path:
            return
        path = Path(path)
        if not path.exists():
            QtWidgets.QMessageBox.critical(self, "Rupis IDE", f"找不到文件：\n{path}")
            return
        # 换文件前先问一句，免得把没保存的改动丢了
        if not self._confirm_discard():
            return
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = path.read_text(encoding="gbk", errors="replace")
        self.editor.document().setModified(False)
        self.editor.setPlainText(text)
        self.editor.document().setModified(False)
        self.current_path = path
        self.lbl_file.setText(path.name)
        self.setWindowTitle(f"Rupis IDE — {path.name}")
        self.editor.mark_error()
        self._push_recent(str(path))
        self._refresh_recent_menu()
        if self.folder is None or path.parent != self.folder:
            self.folder = path.parent
            self._settings.setValue("folder", str(self.folder))
            self._refresh_file_list()
            self._sync_terminal_cwd()
        else:
            self._highlight_current_file()
        self._sync_lib_paths()

    def save_file(self) -> bool:
        if self.current_path is None:
            return self.save_as_dialog()
        try:
            self.current_path.write_text(self.editor.toPlainText(), encoding="utf-8")
        except OSError as exc:
            QtWidgets.QMessageBox.critical(self, "Rupis IDE", f"保存失败：\n{exc}")
            return False
        self.editor.document().setModified(False)
        self.lbl_msg.setText(f"已保存 {self.current_path}")
        self._refresh_file_list()
        return True

    def save_as_dialog(self) -> bool:
        suggestion = str(self.current_path) if self.current_path else str(Path.cwd() / "未命名.rpi")
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "另存为", suggestion, "Rupis 脚本 (*.rpi)"
        )
        if not path:
            return False
        path = Path(path)
        if path.suffix == "":
            path = path.with_suffix(".rpi")
        self.current_path = path
        ok = self.save_file()
        if ok:
            self.lbl_file.setText(path.name)
            self.setWindowTitle(f"Rupis IDE — {path.name}")
            self._push_recent(str(path))
            self._refresh_recent_menu()
            self._highlight_current_file()
        return ok

    def _refresh_file_list(self) -> None:
        self.file_list.clear()
        if self.folder is None or not self.folder.is_dir():
            self.folder_label.setText("—")
            return
        self.folder_label.setText(str(self.folder))
        for item in sorted(self.folder.glob("*.rpi")):
            entry = QtWidgets.QListWidgetItem(item.name)
            entry.setData(QtCore.Qt.ItemDataRole.UserRole, str(item))
            self.file_list.addItem(entry)
        self._highlight_current_file()

    def _highlight_current_file(self) -> None:
        """在左侧列表里选中当前打开的文件。"""
        if self.current_path is None:
            return
        for row in range(self.file_list.count()):
            item = self.file_list.item(row)
            if item.data(QtCore.Qt.ItemDataRole.UserRole) == str(self.current_path):
                self.file_list.setCurrentRow(row)
                return

    # ================================================================ 最近文件
    def _load_recent(self) -> List[str]:
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            recent = data.get("recent", [])
            return [str(item) for item in recent]
        except Exception:
            return []

    def _push_recent(self, path: str) -> None:
        if path in self._recent:
            self._recent.remove(path)
        self._recent.insert(0, path)
        del self._recent[10:]
        try:
            CONFIG_PATH.write_text(
                json.dumps({"recent": self._recent}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass

    def _refresh_recent_menu(self) -> None:
        self.recent_menu.clear()
        if not self._recent:
            action = self.recent_menu.addAction("（空）")
            action.setEnabled(False)
            return
        for path in self._recent:
            action = self.recent_menu.addAction(path)
            action.triggered.connect(lambda _checked=False, p=path: self.open_file(p))

    # ================================================================ 查找
    def show_find(self, replace: bool = False) -> None:
        self.find_panel.show_panel(replace=replace)

    def _on_escape(self) -> None:
        if self.find_panel.isVisible():
            self.find_panel.hide_panel()

    # ================================================================ 底部面板
    def _select_bottom_tab(self, index: int) -> None:
        """切换底部面板：0 = 输出，1 = 控制台，2 = 终端。"""
        self.bottom_tabs.setCurrentIndex(index)
        if index == 1:
            self.console_panel.focus_input()
        elif index == 2:
            self.terminal.focus_input()

    def _console_load_current(self) -> None:
        """把编辑器里正在写的脚本载入控制台会话。"""
        text = self.editor.toPlainText()
        name = self.current_path.name if self.current_path else "<编辑器>"
        self._select_bottom_tab(1)
        self.console_panel.run_source(text, name)

    def _console_clear(self) -> None:
        self.console_panel.clear()

    def _sync_terminal_cwd(self) -> None:
        """终端的工作目录 = IDE 的工作路径。

        IDE 打开了脚本文件夹就用那个文件夹；还没打开就用启动 IDE 时的目录。
        """
        target = self.folder if (self.folder and self.folder.is_dir()) else Path.cwd()
        self.terminal.set_cwd(target)
        self.terminal.set_script_dir(self.folder)

    # ================================================================ 运行
    def _lib_search_dirs(self) -> List[Path]:
        """lib 导入 .rpi 脚本时搜索的目录。

        当前脚本所在的文件夹优先，然后是 IDE 打开的文件夹。
        """

        dirs: List[Path] = []
        if self.current_path is not None:
            dirs.append(self.current_path.parent)
        if self.folder is not None and self.folder not in dirs:
            dirs.append(self.folder)
        return [item for item in dirs if item.is_dir()]

    def _sync_lib_paths(self) -> None:
        """把 lib 的搜索目录同步给编辑器和控制台。"""

        dirs = self._lib_search_dirs()
        self.editor.set_lib_paths(dirs)
        self.console_panel.interpreter.lib_paths = list(dirs)

    def _start_job(self, mode: str) -> None:
        if self._job is not None and self._job.isRunning():
            self.lbl_msg.setText("上一个任务还在跑…")
            return
        text = self.editor.toPlainText()
        filename = str(self.current_path) if self.current_path else "<编辑器>"
        self.editor.mark_error()
        self.console.setPlainText("正在运行…" if mode == "run" else "正在检查语法…")
        self.act_run.setEnabled(False)
        self.act_check.setEnabled(False)
        self.act_export.setEnabled(False)

        self._job = Job(text, filename, mode, self, lib_paths=self._lib_search_dirs())
        self._job.ok.connect(self._on_job_ok)
        self._job.bad.connect(self._on_job_bad)
        self._job.finished.connect(self._on_job_finished)
        self._job.start()

    def run_script(self) -> None:
        self._start_job("run")

    def check_script(self) -> None:
        self._start_job("check")

    def _on_job_ok(self, output: str) -> None:
        try:
            self.console.setPlainText(output)
            self.lbl_msg.setText("运行完成")
        except Exception:  # pragma: no cover - 兜底，别让界面直接崩掉
            traceback.print_exc()

    def _on_job_bad(self, message: str, line: int, col: int) -> None:
        try:
            self.console.setPlainText(message)
            self.editor.mark_error(line, col)
            if line:
                self.editor.goto_line(line, col or 1)
                self.lbl_msg.setText(f"出错：第 {line} 行，第 {col} 列")
            else:
                self.lbl_msg.setText("出错")
        except Exception:  # pragma: no cover
            traceback.print_exc()

    def _on_job_finished(self) -> None:
        self.act_run.setEnabled(True)
        self.act_check.setEnabled(True)
        self.act_export.setEnabled(True)

    # ================================================================ 导出
    def export_structure(self) -> None:
        self._export("structure")

    def export_text(self, fmt: str) -> None:
        """fmt: 'commands' 或 'json'。"""
        self._export(fmt)

    def _export(self, fmt: str) -> None:
        base = str(self.current_path) if self.current_path else str(Path.cwd() / "未命名.rpi")
        base = Path(base)
        if fmt == "structure":
            suggestion = str(base.with_suffix(".mcstructure"))
            flt = "Minecraft 结构 (*.mcstructure)"
        elif fmt == "commands":
            suggestion = str(base.with_suffix(".mcfunction"))
            flt = "Minecraft 函数 (*.mcfunction);;文本文件 (*.txt)"
        else:
            suggestion = str(base.with_suffix(".json"))
            flt = "JSON 文件 (*.json)"

        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "导出", suggestion, flt)
        if not path:
            return

        try:
            interpreter = run_source(self.editor.toPlainText(),
                                     str(self.current_path or "<编辑器>"))
        except RupisError as exc:
            self._show_error(exc)
            return

        try:
            if fmt == "structure":
                count, size = exporters.export_structure(path, interpreter.world)
                message = (f"已写出 {path}\n"
                           f"{count} 个方块，尺寸 {size[0]}x{size[1]}x{size[2]}")
            else:
                text = (exporters.export_commands(interpreter.world)
                        if fmt == "commands" else exporters.export_json(interpreter.world))
                Path(path).write_text(text + "\n", encoding="utf-8")
                message = f"已写出 {path}\n{len(interpreter.world)} 个方块"
        except OSError as exc:
            QtWidgets.QMessageBox.critical(self, "Rupis IDE", f"导出失败：\n{exc}")
            return

        self.console.setPlainText(message)
        self.lbl_msg.setText(f"已导出 {Path(path).name}")

    def _show_error(self, exc: RupisError) -> None:
        self.console.setPlainText(exc.render())
        self.editor.mark_error(exc.line or 0, exc.col or 0)
        if exc.line:
            self.editor.goto_line(exc.line, exc.col or 1)
            self.lbl_msg.setText(f"出错：第 {exc.line} 行，第 {exc.col} 列")

    def copy_output(self) -> None:
        text = self.console.toPlainText()
        if not text:
            self.lbl_msg.setText("输出是空的，没什么可复制")
            return
        QtWidgets.QApplication.clipboard().setText(text)
        self.lbl_msg.setText("输出已复制到剪贴板")

    # ================================================================ 其它
    def _update_position(self) -> None:
        cursor = self.editor.textCursor()
        self.lbl_pos.setText(f"行 {cursor.blockNumber() + 1}, 列 {cursor.columnNumber() + 1}")

    def _on_text_changed(self) -> None:
        if self.current_path is not None:
            self.lbl_msg.setText(f"{self.current_path.name}（已修改）")

    def _on_hint(self, text: str) -> None:
        self.hint_bar.setText(text)

    def goto_line_dialog(self) -> None:
        number, ok = QtWidgets.QInputDialog.getInt(
            self, "跳转到行", "行号：", self.editor.textCursor().blockNumber() + 1, 1, 100000
        )
        if ok:
            self.editor.goto_line(number)
            self._update_position()

    def show_about(self) -> None:
        QtWidgets.QMessageBox.information(
            self, "关于 Rupis IDE",
            "Rupis IDE —— 面向 Minecraft 红石结构的脚本语言编辑器\n\n"
            "快捷键：\n"
            "  F5            运行脚本\n"
            "  F9            检查语法\n"
            "  Ctrl+S        保存\n"
            "  Ctrl+E        导出 .mcstructure\n"
            "  Ctrl+F / H    查找 / 替换\n"
            "  F12           跳转到定义\n"
            "  Ctrl+Space    补全\n"
            "  Ctrl+/        注释 / 取消注释\n"
            "  Alt+↑ / ↓     上移 / 下移整行\n"
            "  Ctrl+Shift+D  复制当前行\n"
            "  Ctrl+Shift+K  删除当前行\n"
            "  Ctrl+G        跳转到行\n",
        )

    def show_shortcuts(self) -> None:
        rows = [
            ("Ctrl+N / Ctrl+O / Ctrl+S", "新建 / 打开 / 保存"),
            ("Ctrl+Shift+S", "另存为"),
            ("Ctrl+Z / Ctrl+Shift+Z", "撤销 / 重做"),
            ("Ctrl+X / Ctrl+C / Ctrl+V", "剪切 / 复制 / 粘贴"),
            ("Ctrl+A", "全选"),
            ("Ctrl+F / Ctrl+H", "查找 / 替换"),
            ("F3 / Shift+F3", "查找下一个 / 上一个"),
            ("Ctrl+G", "跳转到行"),
            ("F12", "跳转到定义"),
            ("Ctrl+/", "注释 / 取消注释"),
            ("Tab / Shift+Tab", "缩进 / 反缩进"),
            ("Alt+↑ / Alt+↓", "上移 / 下移整行"),
            ("Ctrl+Shift+D", "复制当前行"),
            ("Ctrl+Shift+K", "删除当前行"),
            ("Ctrl+Space", "补全"),
            ("Ctrl+= / Ctrl+- / Ctrl+0", "放大 / 缩小 / 复位字号"),
            ("F5 / F9", "运行 / 检查语法"),
            ("Ctrl+E", "导出 .mcstructure"),
            ("Ctrl+L", "清除输出"),
            ("Ctrl+1 / Ctrl+2 / Ctrl+3", "底部面板：输出 / 控制台 / 终端"),
            ("Ctrl+C / Ctrl+L（终端里）", "中断命令 / 清屏"),
        ]
        html = "<table cellpadding='3'>" + "".join(
            f"<tr><td><b>{k}</b></td><td>{v}</td></tr>" for k, v in rows
        ) + "</table>"
        QtWidgets.QMessageBox.information(self, "快捷键一览", html)

    # ================================================================ 设置持久化
    def _restore_state(self) -> None:
        size = int(self._settings.value("font_size", 11))
        self.editor.set_font_size(size)

        geometry = self._settings.value("geometry")
        if geometry:
            try:
                self.restoreGeometry(geometry)
            except (TypeError, ValueError):  # pragma: no cover - 存的是别的类型
                pass

    def _save_state(self) -> None:
        self._settings.setValue("theme", self.theme_name)
        self._settings.setValue("font_size", self.editor.font_size)
        self._settings.setValue("geometry", self.saveGeometry())
        if self.folder is not None:
            self._settings.setValue("folder", str(self.folder))

    def closeEvent(self, event) -> None:  # noqa: N802
        # 后台线程还在跑就先等它结束，否则 QThread 会在运行中被析构
        if self._job is not None and self._job.isRunning():
            self._job.wait(3000)
        # 终端里正在跑的命令也得停下来
        self.terminal.shutdown()
        self._save_state()
        if self._confirm_discard():
            event.accept()
        else:
            event.ignore()


# ====================================================================== 启动
def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(argv)
    app.setApplicationName("Rupis IDE")
    app.setStyle("Fusion")

    window = RupisIDE(argv[0] if argv else None)
    window.show()
    return app.exec()
