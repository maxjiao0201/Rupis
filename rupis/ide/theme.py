"""Rupis IDE 配色。

整套界面共用同一份字典；换主题就是换字典 + 重新刷一次控件。

字典里的键大致分成四类：
    * 底色 / 文字：bg、fg、panel、panel_fg、gutter_bg、gutter_fg、curline、
      sel_bg、hint_bg、hint_fg、status_bg、status_fg、border；
    * 语法高亮：kw（关键字）、elem（元件指令）、const（内置常量）、
      func（结构名 / 函数名）、number、string、comment；
    * 状态标记：err / err_fg（出错行）、match_bg / match_fg（查找命中）、
      bracket（括号配对）；
    * 按钮：btn、btn_active、btn_fg，另外 name 是主题自己的名字。

按键名取值，不要按位置取值 —— 加一个新颜色时不必打乱已有顺序。
"""

from __future__ import annotations

from typing import Dict

DARK: Dict[str, str] = {
    "name": "深色",
    "bg": "#1e1e1e",           # 代码区背景
    "panel": "#252526",       # 面板 / 侧栏
    "panel_fg": "#cccccc",
    "fg": "#d4d4d4",          # 默认前景
    "dim": "#858585",
    "gutter_bg": "#1e1e1e",
    "gutter_fg": "#6a737d",
    "curline": "#282a2b",     # 当前行高亮
    "sel_bg": "#264f78",
    "kw": "#569cd6",          # 关键字
    "elem": "#c586c0",        # 元件指令
    "const": "#4ec9b0",       # 内置常量
    "func": "#dcdcaa",        # 结构名 / 函数名
    "number": "#b5cea8",
    "string": "#ce9178",
    "comment": "#6a9955",
    "err": "#f44747",         # 错误行
    "err_fg": "#ffffff",
    "btn": "#3c3c3c",
    "btn_active": "#4c4c4c",
    "btn_fg": "#e0e0e0",
    "status_bg": "#007acc",
    "status_fg": "#ffffff",
    "border": "#3c3c3c",
    "match_bg": "#514700",    # 查找命中的方块
    "match_fg": "#ffffff",
    "bracket": "#dcdcaa",     # 括号配对高亮
    "hint_bg": "#2d2d30",     # 提示栏
    "hint_fg": "#9d9d9d",
}

LIGHT: Dict[str, str] = {
    "name": "浅色",
    "bg": "#ffffff",
    "panel": "#f3f3f3",
    "panel_fg": "#1f1f1f",
    "fg": "#1f1f1f",
    "dim": "#8a8a8a",
    "gutter_bg": "#f3f3f3",
    "gutter_fg": "#9aa0a6",
    "curline": "#f5f5f5",
    "sel_bg": "#b4d5fe",
    "kw": "#0000ff",
    "elem": "#af00db",
    "const": "#0070c1",
    "func": "#795e26",
    "number": "#098658",
    "string": "#a31515",
    "comment": "#008000",
    "err": "#c62828",
    "err_fg": "#ffffff",
    "btn": "#e8e8e8",
    "btn_active": "#d8d8d8",
    "btn_fg": "#1f1f1f",
    "status_bg": "#e8e8e8",
    "status_fg": "#1f1f1f",
    "border": "#c8c8c8",
    "match_bg": "#ffe08a",
    "match_fg": "#3b3000",
    "bracket": "#7a5c00",
    "hint_bg": "#f0f0f0",
    "hint_fg": "#5f5f5f",
}

# 主题名 → 配色字典；主窗口按名字从这里取
THEMES = {"dark": DARK, "light": LIGHT}


def stylesheet(theme: Dict[str, str]) -> str:
    """按主题生成整份 Qt 样式表。

    注意大括号要写成 {{ }} —— 这是 str.format() 的转义，不是 CSS 的。
    （早期版本这里用 % 格式化却照抄了 {{ }}，Qt 解析器吃到的是字面双括号，
    整份规则其实没生效。）
    """

    return (
        "QWidget {{ color: {panel_fg}; }}"
        "QToolBar {{ background: {panel}; border: none; spacing: 2px; }}"
        "QToolBar QToolButton {{ padding: 4px 10px; border-radius: 3px; }}"
        "QToolBar QToolButton:hover {{ background: {btn_active}; }}"
        "QMenuBar {{ background: {panel}; }}"
        "QMenuBar::item:selected {{ background: {sel_bg}; }}"
        "QMenu {{ background: {panel}; border: 1px solid {border}; }}"
        "QMenu::item:selected {{ background: {sel_bg}; }}"
        "QListWidget {{ background: {bg}; border: 1px solid {border}; }}"
        "QListWidget::item:selected {{ background: {sel_bg}; }}"
        "QPlainTextEdit {{ background: {bg}; color: {fg}; }}"
        "QStatusBar {{ background: {status_bg}; color: {status_fg}; }}"
        "QPushButton {{ background: {btn}; color: {btn_fg}; border: 1px solid {border};"
        "               border-radius: 3px; padding: 4px 8px; }}"
        "QPushButton:hover {{ background: {btn_active}; }}"
        "QPushButton:pressed {{ background: {btn}; }}"
        "QCheckBox {{ color: {panel_fg}; spacing: 4px; }}"
        "QLineEdit {{ background: {bg}; color: {fg};"
        "             border: 1px solid {border}; border-radius: 3px; padding: 3px 6px; }}"
        "QLineEdit:focus {{ border: 1px solid {sel_bg}; }}"
        "QLabel#hintBar {{ background: {hint_bg}; color: {hint_fg};"
        "                 padding: 3px 8px; border-top: 1px solid {border}; }}"
        "QSplitter::handle {{ background: {border}; }}"
    ).format(**theme)
