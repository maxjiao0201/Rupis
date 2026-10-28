"""Rupis IDE 的自动化测试。

用 Qt 的 offscreen 平台跑，不需要真实显示器。

文件分成四块：
    TestIDE                —— IDE 主窗口与代码编辑器：括号补全、注释切换、
                              补全、查找替换、整行操作、提示、字号、控制台、
                              底部面板、脚本列表、查找面板、主题与运行。
    TestSyntaxVocabulary   —— 高亮词表本身：关键字、元件、常量与说明文字。
    TestTerminal           —— 终端页：执行命令、切换目录、中断与历史。
    TestTerminalCommandLine —— 命令行拼接的纯字符串测试，不真的跑命令。
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

# 必须在导入 Qt 之前设置
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from PyQt6.QtCore import Qt, QSettings
    from PyQt6.QtGui import QKeyEvent, QTextCursor
    from PyQt6.QtWidgets import QApplication
    HAVE_QT = True
except ImportError:  # pragma: no cover - 没装 Qt 就跳过
    HAVE_QT = False


@unittest.skipUnless(HAVE_QT, "没有安装 PyQt6 / PySide6，跳过 IDE 测试")
class TestIDE(unittest.TestCase):
    app = None

    @classmethod
    def setUpClass(cls) -> None:
        """整个测试类共用一个 QApplication 实例（Qt 不允许有多个）。"""

        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        """每个用例都开一个全新的 IDE 窗口，并清掉上一轮留下的设置。"""

        import rupis.ide.app as appmod
        from rupis.ide.app import RupisIDE

        # 换掉 QSettings 的组织名，别把测试里的主题 / 字号写进用户自己的设置
        RupisIDE.ORG_NAME = "RupisTest"
        RupisIDE.ORG_APP = "Rupis IDE Test"
        # 每次都从干净的设置开始（主题、字号、窗口大小）
        QSettings(RupisIDE.ORG_NAME, RupisIDE.ORG_APP).clear()
        # "最近打开"也写到临时目录，别动用户自己的 ~/.rupis_ide.json
        self._tmp = tempfile.mkdtemp()
        appmod.CONFIG_PATH = Path(self._tmp) / "rupis_ide.json"
        self.win = RupisIDE()
        self.ed = self.win.editor

    def tearDown(self) -> None:
        """关掉窗口，不留下悬空的控件。"""

        # 关闭前先清掉"已修改"标记，否则 closeEvent 会弹模态框问要不要保存
        self.win.editor.document().setModified(False)
        self.win.close()
        self.win.deleteLater()
        self.app.processEvents()

    # ------------------------------------------------------------ 工具
    def press(self, key, text="", mod=Qt.KeyboardModifier.NoModifier) -> None:
        """模拟按下一个按键。"""

        self.ed.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, key, mod, text))

    def at_end(self) -> None:
        """把光标移到文末。"""

        self.ed.moveCursor(QTextCursor.MoveOperation.End)

    def at(self, line: int, col: int = 1) -> None:
        """把光标放到第 line 行第 col 列。"""
        self.ed.goto_line(line, col)

    # ------------------------------------------------------------ 编辑器
    def test_bracket_auto_close(self):
        """输入左括号时自动补上右括号，光标停在两个括号中间。"""

        self.ed.setPlainText("")
        self.at_end()
        self.press(Qt.Key.Key_ParenLeft, "(")
        self.assertEqual(self.ed.toPlainText(), "()")
        self.assertEqual(self.ed.textCursor().position(), 1)

    def test_bracket_skip_closer(self):
        """紧接着再按右括号时直接跳过，不重复插入一个。"""

        self.ed.setPlainText("")
        self.at_end()
        self.press(Qt.Key.Key_ParenLeft, "(")
        self.press(Qt.Key.Key_ParenRight, ")")
        self.assertEqual(self.ed.toPlainText(), "()")
        self.assertEqual(self.ed.textCursor().position(), 2)

    def test_enter_auto_indent_after_brace(self):
        """在 { 后回车会自动缩进一级，方便接着写块内容。"""

        self.ed.setPlainText("def f():{")
        self.at_end()
        self.press(Qt.Key.Key_Return, "\r")
        self.assertEqual(self.ed.toPlainText(), "def f():{\n    ")

    def test_enter_keeps_indent(self):
        """回车时保留上一行的缩进，不多不少。"""

        self.ed.setPlainText("    rw{rsig=1}[0,0,0]")
        self.at_end()
        self.press(Qt.Key.Key_Return, "\r")
        self.assertEqual(self.ed.toPlainText(), "    rw{rsig=1}[0,0,0]\n    ")

    def test_tab_indents_selection(self):
        """有选区时按 Tab，给选区每一行都加一级缩进。"""

        self.ed.setPlainText("rw{rsig=1}[0,0,0]\nrw{rsig=2}[1,0,0]")
        self.ed.selectAll()
        self.press(Qt.Key.Key_Tab, "\t")
        self.assertEqual(self.ed.toPlainText(),
                         "    rw{rsig=1}[0,0,0]\n    rw{rsig=2}[1,0,0]")

    def test_shift_tab_outdents_selection(self):
        """Shift+Tab 给选区每一行都减一级缩进。"""

        self.ed.setPlainText("    a\n    b")
        self.ed.selectAll()
        self.press(Qt.Key.Key_Backtab, "")
        self.assertEqual(self.ed.toPlainText(), "a\nb")

    def test_tab_without_selection_inserts_spaces(self):
        """没有选区时 Tab 插入 4 个空格，而不是缩进整行。"""

        self.ed.setPlainText("x")
        self.at_end()
        self.press(Qt.Key.Key_Tab, "\t")
        self.assertEqual(self.ed.toPlainText(), "x    ")

    def test_toggle_comment(self):
        """切换注释：已注释的恢复原样，没注释的加上 //。"""

        self.ed.setPlainText("rw{rsig=1}[0,0,0]\nrw{rsig=2}[1,0,0]")
        self.ed.selectAll()
        self.ed._toggle_comment()
        self.assertEqual(self.ed.toPlainText(),
                         "// rw{rsig=1}[0,0,0]\n// rw{rsig=2}[1,0,0]")
        self.ed.selectAll()
        self.ed._toggle_comment()
        self.assertEqual(self.ed.toPlainText(),
                         "rw{rsig=1}[0,0,0]\nrw{rsig=2}[1,0,0]")

    def test_completion_includes_user_definitions(self):
        """补全列表里要同时有用户定义的模板名、内置关键字和元件名。"""

        self.ed.setPlainText("strudef my_unit(facing):{\n}\n")
        self.ed.refresh_definitions()
        words = self.ed._completer.model().stringList()
        self.assertIn("my_unit", words)
        self.assertIn("strudef", words)
        self.assertIn("rw", words)

    # ------------------------------------------------------------ lib 补全
    def make_lib(self, name="util.rpi", text=None):
        """建一个能被 lib 导入的 .rpi 脚本，返回它所在的目录。"""

        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        if text is None:
            text = ("def helper(n):{\n    return n * 2\n}\n"
                    "strudef box(v):{\n    rw{rsig=v}[0,0,0]\n}\n")
        path = Path(tmp)
        for part in name.split("/"):
            path = path / part
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        self.ed.set_lib_paths([Path(tmp)])
        return Path(tmp)

    def test_lib_file_is_scanned(self):
        """设好 lib 路径后，编辑器要能扫到里面的 .rpi 文件。"""

        self.make_lib()
        self.ed.setPlainText("lib util\n")
        files = self.ed._lib_files()
        self.assertEqual(list(files), ["util"])
        self.assertEqual(files["util"].name, "util.rpi")

    def test_lib_file_with_alias(self):
        """写了 as 别名时，补全用的模块名是别名而不是原名。"""

        self.make_lib()
        self.ed.setPlainText("lib util as u\n")
        self.assertEqual(list(self.ed._lib_files()), ["u"])

    def test_lib_file_in_subdirectory(self):
        """子目录里的脚本也要被扫到，模块名仍然只取文件名。"""

        self.make_lib("sub/util.rpi")
        self.ed.setPlainText("lib sub/util\n")
        files = self.ed._lib_files()
        self.assertEqual(list(files), ["util"])

    def test_member_completion_lists_script_members(self):
        """在 模块名. 后面补全时，要列出该脚本里的函数与结构模板。"""

        self.make_lib()
        self.ed.setPlainText("lib util\nutil.he")
        self.at_end()
        members = self.ed._member_completion()
        self.assertIsNotNone(members)
        words, prefix = members
        self.assertIn("helper", words)
        self.assertIn("box", words)
        self.assertEqual(prefix, "he")

    def test_member_completion_uses_alias(self):
        """用了别名就按别名去做成员补全。"""

        self.make_lib()
        self.ed.setPlainText("lib util as u\nu.he")
        self.at_end()
        words, prefix = self.ed._member_completion()
        self.assertIn("helper", words)
        self.assertEqual(prefix, "he")

    def test_member_completion_ignores_unknown_script(self):
        """模块名不在 lib 里时不触发成员补全，免得凭空补出不存在的东西。"""

        self.make_lib()
        self.ed.setPlainText("lib nosuchscript_xyz\nnosuchscript_xyz.")
        self.at_end()
        self.assertIsNone(self.ed._member_completion())

    def test_member_completion_ignores_plain_word(self):
        """光标前是普通单词（没跟点号）时不触发成员补全。"""

        self.make_lib()
        self.ed.setPlainText("lib util\nrw")
        self.at_end()
        self.assertIsNone(self.ed._member_completion())

    def test_start_completion_switches_to_script_members(self):
        """触发补全时，如果光标在 模块名. 后面，就补该脚本的成员。"""

        self.make_lib()
        self.ed.setPlainText("lib util\nutil.he")
        self.at_end()
        self.ed._start_completion()
        self.assertIn("helper", self.ed._completer.model().stringList())
        self.assertEqual(self.ed._completer.completionPrefix(), "he")

    def test_start_completion_falls_back_to_words(self):
        """不是成员补全的场景就退回普通单词补全。"""

        self.make_lib()
        self.ed.setPlainText("rw")
        self.at_end()
        self.ed._start_completion()
        self.assertIn("rw", self.ed._completer.model().stringList())

    def test_imported_names_are_in_the_word_list(self):
        """导入进来的函数名也能直接补出来。"""
        self.make_lib()
        self.ed.setPlainText("lib util\n")
        self.ed.refresh_definitions()
        words = self.ed._completer.model().stringList()
        self.assertIn("helper", words)
        self.assertIn("box", words)

    def test_hint_bar_explains_lib(self):
        """光标落在 lib 上时，提示栏要说明 lib 的用法。"""

        self.ed.setPlainText("lib util")
        cursor = self.ed.textCursor()
        cursor.setPosition(1)
        self.ed.setTextCursor(cursor)
        self.assertIn("lib", self.ed.hint_text())

    def test_goto_line(self):
        """goto_line 要能把光标跳到指定的行。"""

        self.ed.setPlainText("a\nb\nc\nd")
        self.ed.goto_line(3)
        self.assertEqual(self.ed.textCursor().blockNumber(), 2)

    def test_mark_error_marks_line(self):
        """mark_error 要把出错行记下来，供运行出错后跳转过去。"""

        self.ed.setPlainText("a\nb\nc")
        self.ed.mark_error(2, 1)
        self.assertEqual(self.ed._error_line, 2)

    # ------------------------------------------------------------ 整行操作
    def test_move_line_down(self):
        """把当前行往下移一行。"""

        self.ed.setPlainText("a\nb\nc")
        self.at(1)
        self.assertTrue(self.ed.move_lines(1))
        self.assertEqual(self.ed.toPlainText(), "b\na\nc")

    def test_move_line_up(self):
        """把当前行往上移一行。"""

        self.ed.setPlainText("a\nb\nc")
        self.at(2)
        self.assertTrue(self.ed.move_lines(-1))
        self.assertEqual(self.ed.toPlainText(), "b\na\nc")

    def test_move_line_up_at_top_is_noop(self):
        """已经在第一行时上移是空操作，并且要返回 False 让调用方知道没动。"""

        self.ed.setPlainText("a\nb")
        self.at(1)
        self.assertFalse(self.ed.move_lines(-1))
        self.assertEqual(self.ed.toPlainText(), "a\nb")

    def test_move_line_down_at_bottom_is_noop(self):
        """已经在最后一行时下移是空操作，同样要返回 False。"""

        self.ed.setPlainText("a\nb")
        self.at(2)
        self.assertFalse(self.ed.move_lines(1))
        self.assertEqual(self.ed.toPlainText(), "a\nb")

    def test_duplicate_line(self):
        """复制当前行，副本紧跟在原行后面。"""

        self.ed.setPlainText("a\nb")
        self.at(1)
        self.ed.duplicate_lines()
        self.assertEqual(self.ed.toPlainText(), "a\na\nb")

    def test_delete_line(self):
        """删除当前行。"""

        self.ed.setPlainText("a\nb\nc")
        self.at(2)
        self.ed.delete_lines()
        self.assertEqual(self.ed.toPlainText(), "a\nc")

    def test_delete_last_line(self):
        """删掉最后一行时，前面剩下的内容要保留。"""

        self.ed.setPlainText("a\nb")
        self.at(2)
        self.ed.delete_lines()
        self.assertEqual(self.ed.toPlainText(), "a")

    # ------------------------------------------------------------ 查找替换
    def test_find_matches_plain(self):
        """普通文本查找要找出全部匹配。"""

        self.ed.setPlainText("rw{rsig=1}\nrw{rsig=2}\nrw{rsig=3}")
        spans = self.ed.find_matches("rw")
        self.assertEqual(len(spans), 3)

    def test_find_matches_case_insensitive(self):
        """默认忽略大小写，只有显式要求时才区分。"""

        self.ed.setPlainText("RW\nrw\nRw")
        self.assertEqual(len(self.ed.find_matches("rw")), 3)
        self.assertEqual(len(self.ed.find_matches("rw", case_sensitive=True)), 1)

    def test_find_matches_regex(self):
        """正则模式下要按模式匹配，而不是按字面量。"""

        self.ed.setPlainText("rsig=1\nrsig=22\nrsig=333")
        spans = self.ed.find_matches(r"rsig=\d+", regex=True)
        self.assertEqual(len(spans), 3)

    def test_find_invalid_regex_raises(self):
        """非法正则要抛 ValueError，而不是静默返回零结果。"""

        self.ed.setPlainText("abc")
        with self.assertRaises(ValueError):
            self.ed.find_matches("(unclosed", regex=True)

    def test_find_next_moves_cursor(self):
        """find_next 要把光标移到并选中下一个匹配。"""

        self.ed.setPlainText("a\nb\na\nb")
        self.at(1)
        span = self.ed.find_next("a")
        self.assertIsNotNone(span)
        self.assertEqual(self.ed.textCursor().selectedText(), "a")

    def test_find_next_wraps_around(self):
        """后面没有匹配时要绕回开头继续找，而不是直接失败。"""

        self.ed.setPlainText("x\na\nb")
        self.at(2)          # 已经过了唯一的 "a"
        span = self.ed.find_next("a")
        self.assertIsNotNone(span)
        self.assertEqual(span[0], 2)

    def test_replace_all(self):
        """全部替换要改掉所有出现的地方，并返回替换次数。"""

        self.ed.setPlainText("rsig=1\nrsig=2")
        count = self.ed.replace_all("rsig", "power")
        self.assertEqual(count, 2)
        self.assertEqual(self.ed.toPlainText(), "power=1\npower=2")

    def test_replace_all_with_regex_backreference(self):
        """正则替换要支持 \\1 这样的反向引用。"""

        self.ed.setPlainText("name=alpha\nname=beta")
        count = self.ed.replace_all(r"name=(\w+)", r"\1", regex=True)
        self.assertEqual(count, 2)
        self.assertEqual(self.ed.toPlainText(), "alpha\nbeta")

    def test_find_highlight_count(self):
        """查找时高亮的匹配数要记在 match_count 上。"""

        self.ed.setPlainText("a\na\na")
        self.ed.find_next("a")
        self.assertEqual(self.ed.match_count, 3)

    def test_clear_find_highlights(self):
        """清掉查找高亮之后，匹配数要归零。"""

        self.ed.setPlainText("a\na")
        self.ed.find_next("a")
        self.ed.clear_find_highlights()
        self.assertEqual(self.ed.match_count, 0)

    # ------------------------------------------------------------ 括号配对
    def test_bracket_match_found(self):
        """光标落在括号上时，要标出配对的那一对括号。"""

        self.ed.setPlainText("rw{rsig=15}[0,0,0]")
        self.at(1, 3)        # 光标落在 { 上
        spans = self.ed._bracket_matches()
        self.assertEqual(len(spans), 2)
        self.assertEqual(spans[0][0], 2)

    def test_bracket_match_ignores_strings(self):
        self.ed.setPlainText('dpos p["{"]')
        self.at(1, 9)        # 光标落在字符串里的 { 上
        self.assertEqual(self.ed._bracket_matches(), [])

    # ------------------------------------------------------------ 跳转定义
    def test_find_definition_of_structure(self):
        """按名字能找到结构模板的定义行。"""

        self.ed.setPlainText("strudef unit(f):{\n}\n\nstru unit(e){}\n")
        self.assertEqual(self.ed.find_definition("unit"), 1)

    def test_find_definition_of_function(self):
        """按名字能找到函数的定义行。"""

        self.ed.setPlainText("def go(n):{\n}\n")
        self.assertEqual(self.ed.find_definition("go"), 1)

    def test_find_definition_missing(self):
        """找不到定义时返回 0（表示"没找到"）。"""

        self.ed.setPlainText("rw{rsig=1}[0,0,0]")
        self.assertEqual(self.ed.find_definition("nothing"), 0)

    def test_jump_to_definition(self):
        """在调用处触发跳转，光标要落到定义那一行上。"""

        self.ed.setPlainText("strudef unit(f):{\n}\n\nstru unit(e){}\n")
        self.at(4, 6)        # 光标在第 4 行的 unit 上
        self.assertTrue(self.ed.jump_to_definition())
        self.assertEqual(self.ed.textCursor().blockNumber(), 0)

    def test_symbol_kind(self):
        """要能区分结构模板、函数和不认识的符号。"""

        self.ed.setPlainText("strudef unit(f):{\n}\ndef go():{\n}\n")
        self.assertEqual(self.ed.symbol_kind("unit"), "structure")
        self.assertEqual(self.ed.symbol_kind("go"), "function")
        self.assertEqual(self.ed.symbol_kind("other"), "")

    # ------------------------------------------------------------ 提示
    def test_hint_for_keyword(self):
        """光标在关键字上时，给出对应的中文说明。"""

        self.ed.setPlainText("def go():{")
        self.at(1, 1)
        self.assertIn("函数", self.ed.hint_text())

    def test_hint_for_element(self):
        """光标在元件名上时，给出元件的中文说明。"""

        self.ed.setPlainText("rw{rsig=15}[0,0,0]")
        self.at(1, 1)
        self.assertIn("红石粉", self.ed.hint_text())

    def test_hint_for_state_key(self):
        self.ed.setPlainText("rw{rsig=15}[0,0,0]")
        self.at(1, 5)        # 光标在 rsig 上
        self.assertIn("rsig", self.ed.hint_text())

    def test_hint_for_structure_name(self):
        self.ed.setPlainText("strudef unit(f):{\n}\n")
        self.at(1, 10)
        self.assertIn("结构模板", self.ed.hint_text())

    def test_hint_for_state_slot_lists_keys(self):
        self.ed.setPlainText("rw{}[0,0,0]")
        self.at(1, 4)        # 光标在状态槽里，不在任何键上
        self.assertIn("len", self.ed.hint_text())

    # ------------------------------------------------------------ 字号
    def test_zoom_in_and_out(self):
        base = self.ed.font_size
        self.ed.zoom_in()
        self.assertEqual(self.ed.font_size, base + 1)
        self.ed.zoom_out()
        self.assertEqual(self.ed.font_size, base)

    def test_zoom_is_clamped(self):
        self.ed.set_font_size(999)
        self.assertLessEqual(self.ed.font_size, 28)
        self.ed.set_font_size(1)
        self.assertGreaterEqual(self.ed.font_size, 8)

    # ------------------------------------------------------------ 控制台
    def console_run(self, line: str) -> str:
        """在控制台里执行一行，返回执行后的记录文本。"""
        panel = self.win.console_panel
        panel.input.setText(line)
        panel.execute()
        return panel.transcript.toPlainText()

    def test_console_evaluates_expression(self):
        out = self.console_run("1 + 2 * 3")
        self.assertIn("7", out)

    def test_console_places_block_and_reports_count(self):
        out = self.console_run("rw{rsig=15}[0,0,0]")
        self.assertIn("已放置 1 个方块", out)
        self.assertEqual(len(self.win.console_panel.interpreter.world), 1)

    def test_console_keeps_state_between_lines(self):
        self.console_run("dpos base[10,20,30]")
        self.console_run("rw{rsig=15}[base]")
        out = self.console_run(":world")
        self.assertIn("共放置 1 个方块", out)

    def test_console_shows_dpos_value(self):
        self.console_run("dpos base[1,2,3]")
        out = self.console_run("base")
        self.assertIn("(1, 2, 3)", out)

    def test_console_shows_drp_value_readably(self):
        self.console_run("drp hi{rsig=15}")
        out = self.console_run("hi")
        self.assertIn("{rsig=15}", out)
        self.assertNotIn("StateValue", out)

    def test_console_reports_error_without_crashing(self):
        out = self.console_run("rw{rsig=99}[0,0,0]")
        self.assertIn("错误", out)
        self.assertIn("rsig", out)

    def test_console_assignment_echoes_value(self):
        out = self.console_run("let x = 5")
        self.assertIn("x = 5", out)

    def test_console_multi_line_block(self):
        self.console_run("def f(n):{")
        out = self.console_run("  return n * 2")
        self.assertIn("还没写完", out)
        self.console_run("}")
        out = self.console_run("f(21)")
        self.assertIn("42", out)

    def test_console_reset_clears_state(self):
        self.console_run("dpos base[0,0,0]")
        self.console_run(":reset")
        out = self.console_run(":vars")
        self.assertIn("还没有任何变量", out)

    def test_console_help_lists_commands(self):
        out = self.console_run(":help")
        for command in (":reset", ":world", ":vars", ":load"):
            self.assertIn(command, out)

    def test_console_unknown_command_is_reported(self):
        out = self.console_run(":nope")
        self.assertIn("未知命令", out)

    def test_console_loads_current_script(self):
        self.ed.setPlainText("dpos p[7,8,9]\n")
        self.win._console_load_current()
        out = self.win.console_panel.transcript.toPlainText()
        self.assertIn("已载入", out)
        self.assertIn("7, 8, 9", self.console_run(":vars"))

    # ------------------------------------------------------------ 底部面板
    def test_bottom_panel_has_output_console_and_terminal_tabs(self):
        tabs = self.win.bottom_tabs
        self.assertEqual(tabs.count(), 3)
        self.assertEqual(tabs.tabText(0), "输出")
        self.assertEqual(tabs.tabText(1), "控制台")
        self.assertEqual(tabs.tabText(2), "终端")

    def test_switch_to_console_tab(self):
        self.win._select_bottom_tab(1)
        self.assertEqual(self.win.bottom_tabs.currentIndex(), 1)
        self.win._select_bottom_tab(0)
        self.assertEqual(self.win.bottom_tabs.currentIndex(), 0)

    def test_switch_to_terminal_tab(self):
        self.win._select_bottom_tab(2)
        self.assertEqual(self.win.bottom_tabs.currentIndex(), 2)

    def test_terminal_working_directory_follows_ide_folder(self):
        """终端路径就是 IDE 的工作路径。"""
        folder = tempfile.mkdtemp()
        self.win.folder = Path(folder)
        self.win._sync_terminal_cwd()
        self.assertEqual(self.win.terminal.cwd, Path(folder))
        self.assertEqual(self.win.terminal.script_dir, Path(folder))

    def test_terminal_falls_back_to_launch_directory(self):
        """还没打开文件夹时，终端在 IDE 的启动目录。"""
        self.win.folder = None
        self.win._sync_terminal_cwd()
        self.assertEqual(self.win.terminal.cwd, Path.cwd())

    def test_run_output_still_goes_to_output_tab(self):
        self.ed.setPlainText("dpos p[0,0,0]\nrw{rsig=15}[p]\n")
        self.win.run_script()
        output = self.wait_for_job()
        self.assertIn("/setblock", output)
        self.assertIn("/setblock", self.win.console.toPlainText())

    # ------------------------------------------------------------ 脚本列表
    def make_script(self, folder, name, text):
        path = Path(folder) / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_clicking_file_list_item_opens_it(self):
        """单击左侧列表里的脚本就该打开它（不用双击）。"""
        folder = tempfile.mkdtemp()
        path = self.make_script(folder, "hello.rpi", "rw{rsig=1}[0,0,0]\n")
        self.win.folder = Path(folder)
        self.win._refresh_file_list()
        self.assertEqual(self.win.file_list.count(), 1)

        item = self.win.file_list.item(0)
        self.win.file_list.itemClicked.emit(item)

        self.assertEqual(self.win.current_path, path)
        self.assertIn("rsig=1", self.win.editor.toPlainText())
        self.assertEqual(self.win.lbl_file.text(), "hello.rpi")

    def test_file_list_highlights_current_file(self):
        folder = tempfile.mkdtemp()
        self.make_script(folder, "aaa.rpi", "rw{rsig=1}[0,0,0]\n")
        path = self.make_script(folder, "bbb.rpi", "rw{rsig=2}[1,0,0]\n")
        self.win.folder = Path(folder)
        self.win._refresh_file_list()
        self.win.open_file(path)
        self.assertEqual(self.win.file_list.currentItem().text(), "bbb.rpi")

    def test_open_file_asks_before_discarding_changes(self):
        """有未保存的改动时，换文件要拦一下。"""
        folder = tempfile.mkdtemp()
        path = self.make_script(folder, "hello.rpi", "rw{rsig=1}[0,0,0]\n")
        self.win.folder = Path(folder)
        self.win._refresh_file_list()

        # setPlainText 会把"已修改"标记清掉，得真的敲进去才算改动过
        self.ed.setPlainText("")
        self.ed.insertPlainText("改过了\n")
        self.assertTrue(self.ed.document().isModified())

        # 假装用户点了"取消"
        self.win._confirm_discard = lambda: False
        self.win.open_file(path)
        self.assertNotEqual(self.win.current_path, path)
        self.assertEqual(self.ed.toPlainText(), "改过了\n")

    # ------------------------------------------------------------ 查找面板
    def test_find_panel_shows_and_hides(self):
        panel = self.win.find_panel
        # 窗口本身没 show()，所以只能看"显式隐藏"这个状态
        self.assertTrue(panel.isHidden())
        self.win.show_find(replace=False)
        self.assertFalse(panel.isHidden())
        self.assertTrue(panel.replace_row.isHidden())
        self.win.show_find(replace=True)
        self.assertFalse(panel.replace_row.isHidden())
        panel.hide_panel()
        self.assertTrue(panel.isHidden())

    def test_find_panel_replace_all(self):
        panel = self.win.find_panel
        self.ed.setPlainText("rsig=1\nrsig=2")
        panel.find_edit.setText("rsig")
        panel.replace_edit.setText("power")
        panel.replace_all()
        self.assertEqual(self.ed.toPlainText(), "power=1\npower=2")

    # ------------------------------------------------------------ 主题
    def test_theme_switch(self):
        self.assertEqual(self.win.theme_name, "dark")
        self.win.toggle_theme()
        self.assertEqual(self.win.theme_name, "light")
        self.win.toggle_theme()
        self.assertEqual(self.win.theme_name, "dark")

    def test_theme_switch_repaints_widgets(self):
        """换主题后，编辑器与侧栏都要真的换成新配色（曾经踩过的坑）。"""
        from PyQt6.QtGui import QPalette

        def base_of(widget):
            return widget.palette().color(QPalette.ColorRole.Base).name()

        self.win.toggle_theme()
        self.assertEqual(base_of(self.win.editor), "#ffffff")
        self.assertEqual(base_of(self.win.file_list), "#ffffff")
        self.win.toggle_theme()
        self.assertEqual(base_of(self.win.editor), "#1e1e1e")
        self.assertEqual(base_of(self.win.file_list), "#1e1e1e")

    def test_highlighter_follows_theme(self):
        self.win.toggle_theme()
        fmt = self.win.editor.highlighter._fmts["kw"]
        self.assertEqual(fmt.foreground().color().name(), "#0000ff")

    def test_stylesheet_has_single_braces(self):
        """样式表里的大括号不能被写成双份（早期版本用 % 格式化踩过这个坑）。"""
        from rupis.ide.theme import DARK, stylesheet

        sheet = stylesheet(DARK)
        self.assertNotIn("{{", sheet)
        self.assertNotIn("}}", sheet)
        self.assertIn("QWidget { color:", sheet)

    # ------------------------------------------------------------ 运行
    def wait_for_job(self) -> str:
        """等后台任务跑完并把结果送回界面，返回控制台文本。"""
        for _ in range(500):
            self.app.processEvents()
            text = self.win.console.toPlainText()
            if text and not text.startswith("正在"):
                return text
        self.fail("后台任务没有在预期时间内结束")

    def test_run_reports_success(self):
        self.ed.setPlainText("dpos p[0,0,0]\nrw{rsig=15}[p]\n")
        self.win.run_script()
        output = self.wait_for_job()
        self.assertIn("/setblock 0 0 0 minecraft:redstone_wire[power=15]", output)

    def test_run_reports_error_and_jumps_to_line(self):
        self.ed.setPlainText("rw{rsig=99}[0,0,0]\n")
        self.win.run_script()
        output = self.wait_for_job()
        self.assertIn("错误", output)
        self.assertEqual(self.ed._error_line, 1)

    def test_check_reports_syntax_ok(self):
        self.ed.setPlainText("dpos p[0,0,0]\n")
        self.win.check_script()
        output = self.wait_for_job()
        self.assertIn("语法检查通过", output)


class TestSyntaxVocabulary(unittest.TestCase):
    """词表本身不依赖 Qt，单独测。"""

    def test_keywords(self):
        from rupis.ide.syntax import KEYWORDS

        for word in ("dpos", "drp", "stru", "strudef", "def", "if", "for", "while"):
            self.assertIn(word, KEYWORDS)

    def test_lib_is_a_keyword_with_a_hint(self):
        from rupis.ide.syntax import KEYWORDS, describe

        self.assertIn("lib", KEYWORDS)
        self.assertIn("lib", describe("lib"))

    def test_elements(self):
        from rupis.ide.syntax import ELEMENTS

        for word in ("rw", "rrep", "rco", "obs", "rtorch", "rlamp", "piston", "sticky"):
            self.assertIn(word, ELEMENTS)

    def test_constants(self):
        from rupis.ide.syntax import CONSTANTS

        for word in ("north", "south", "east", "west", "up", "down",
                     "x", "y", "z", "compare", "subtract", "true", "false"):
            self.assertIn(word, CONSTANTS)

    def test_describe_covers_every_element(self):
        from rupis.ide.syntax import ELEMENTS, describe

        for word in ELEMENTS:
            self.assertTrue(describe(word), f"{word} 应该有说明")

    def test_describe_state_key(self):
        from rupis.ide.syntax import describe_state_key

        text = describe_state_key("facing")
        self.assertIn("rrep", text)
        self.assertEqual(describe_state_key("nosuchkey"), "")


@unittest.skipUnless(HAVE_QT, "没有安装 PyQt6 / PySide6，跳过 IDE 测试")
class TestTerminal(unittest.TestCase):
    """终端页的测试。

    终端是真的在跑 shell 命令，所以用临时目录当工作目录，
    免得 cd 之后把测试环境弄乱。
    """

    app = None

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        from rupis.ide.terminal import TerminalWidget

        self._tmp = tempfile.mkdtemp()
        self.term = TerminalWidget(self._tmp)

    def tearDown(self) -> None:
        # 有关着的命令就先停掉，不然 QThread 会在运行中被析构
        self.term.shutdown()
        self.term.deleteLater()
        self.app.processEvents()

    # ------------------------------------------------------------ 工具
    def wait(self, timeout=20.0) -> bool:
        """等命令跑完（把事件循环转起来，信号才送得回来）。"""
        end = time.time() + timeout
        while time.time() < end:
            self.app.processEvents()
            if self.term._thread is None:
                self.app.processEvents()
                return True
            time.sleep(0.01)
        return False

    def run_cmd(self, command: str, timeout=20.0) -> str:
        self.term.input.setText(command)
        self.term.submit()
        self.assertTrue(self.wait(timeout), f"命令没在超时前跑完：{command}")
        return self.term.transcript.toPlainText()

    # ------------------------------------------------------------ 用例
    def test_echoes_command_and_shows_output(self):
        out = self.run_cmd("echo hello-rupis")
        self.assertIn("hello-rupis", out)
        # 敲进去的命令要回显出来，像真的终端那样
        self.assertIn("echo hello-rupis", out)

    def test_prompt_shows_working_directory(self):
        self.assertIn(str(self._tmp), self.term.prompt_text())

    def test_cd_changes_working_directory(self):
        target = Path(self._tmp) / "sub"
        target.mkdir()
        self.run_cmd(f"cd {target}")
        self.assertEqual(self.term.cwd, target)
        self.assertIn(str(target), self.term.prompt_text())

    def test_working_directory_is_kept_between_commands(self):
        target = Path(self._tmp) / "sub2"
        target.mkdir()
        self.run_cmd(f"cd {target}")
        out = self.run_cmd("cd")
        self.assertIn("sub2", out)

    def test_clear_empties_transcript(self):
        self.run_cmd("echo x")
        self.term.clear()
        self.assertEqual(self.term.transcript.toPlainText().strip(), "")

    def test_interrupt_stops_long_command(self):
        if os.name == "nt":
            command = "ping -n 60 127.0.0.1"
        else:
            command = "sleep 60"
        self.term.input.setText(command)
        self.term.submit()
        # 等它真的跑起来
        end = time.time() + 10
        while time.time() < end and (self.term._thread is None
                                     or not self.term._thread.isRunning()):
            self.app.processEvents()
            time.sleep(0.01)
        self.assertIsNotNone(self.term._thread)
        self.assertTrue(self.term._thread.isRunning())
        self.term.interrupt()
        self.assertTrue(self.wait(15), "Ctrl+C 之后命令没停下来")
        self.assertIn("^C", self.term.transcript.toPlainText())

    def test_history_navigates_with_arrow_keys(self):
        self.run_cmd("echo first")
        self.run_cmd("echo second")
        self.term._history_move(-1)
        self.assertEqual(self.term.input.text(), "echo second")
        self.term._history_move(-1)
        self.assertEqual(self.term.input.text(), "echo first")

    def test_second_command_while_busy_is_refused(self):
        if os.name == "nt":
            command = "ping -n 60 127.0.0.1"
        else:
            command = "sleep 60"
        self.term.input.setText(command)
        self.term.submit()
        end = time.time() + 10
        while time.time() < end and (self.term._thread is None
                                     or not self.term._thread.isRunning()):
            self.app.processEvents()
            time.sleep(0.01)
        self.term.input.setText("echo nope")
        self.term.submit()
        self.assertIn("还在跑", self.term.transcript.toPlainText())
        self.term.interrupt()
        self.wait(15)

    def test_set_cwd_ignores_missing_directory(self):
        before = self.term.cwd
        self.term.set_cwd(Path(self._tmp) / "no-such-dir")
        self.assertEqual(self.term.cwd, before)

    def test_shutdown_stops_running_command(self):
        """关窗口时正在跑的命令得停下来，不然 QThread 会被析构。"""
        if os.name == "nt":
            command = "ping -n 60 127.0.0.1"
        else:
            command = "sleep 60"
        self.term.input.setText(command)
        self.term.submit()
        end = time.time() + 10
        while time.time() < end and (self.term._thread is None
                                     or not self.term._thread.isRunning()):
            self.app.processEvents()
            time.sleep(0.01)
        self.term.shutdown()
        self.assertIsNone(self.term._thread)


class TestTerminalCommandLine(unittest.TestCase):
    """命令行拼接的单元测试（不跑命令，只看拼出来的东西）。"""

    def test_windows_command_keeps_quotes(self):
        from rupis.ide.terminal import build_command_line

        if os.name != "nt":
            self.skipTest("只有 Windows 上才是 cmd")
        line = build_command_line('echo "hi there"')
        # 用户敲的引号要原样保留
        self.assertIn('"hi there"', line)
        self.assertIn("/c", line)

    def test_unbalanced_quotes_do_not_break_the_line(self):
        from rupis.ide.terminal import build_command_line

        if os.name != "nt":
            self.skipTest("只有 Windows 上才是 cmd")
        line = build_command_line('echo "hi')
        # 引号是奇数时不能再拼目录探针，不然整段会被吞进引号里
        self.assertNotIn("__RUPIS_CWD__", line)
        self.assertTrue(line.endswith('"'))

    def test_cwd_probe_is_appended(self):
        from rupis.ide.terminal import build_command_line

        if os.name != "nt":
            self.skipTest("只有 Windows 上才是 cmd")
        self.assertIn("__RUPIS_CWD__", build_command_line("dir"))


if __name__ == "__main__":
    unittest.main()
