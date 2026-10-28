"""Rupis IDE —— Rupis 脚本语言的桌面编辑器。

启动方式：
    python -m rupis.ide            # 打开空文档
    python -m rupis.ide a.rpi      # 直接打开某个脚本
    python ide.py a.rpi            # 同上（根目录快捷方式）

依赖 PySide6 / PyQt6 / PyQt5 之一。

模块划分：
    app.py          主窗口：菜单栏、工具栏、左侧文件列表、底部三页、状态栏
    editor.py       编辑器控件：行号槽、语法高亮、补全、缩进、跳转定义
    console.py      交互式 Rupis 控制台（会话状态整个会话里保留）
    terminal.py     内嵌的真实 shell 终端（一条命令起一个进程）
    find.py         查找 / 替换面板
    highlighter.py  语法高亮器
    syntax.py       语言词表：关键字、元件、常量、提示文案
    theme.py        深色 / 浅色两套配色
    qtcompat.py     PySide6 / PyQt6 / PyQt5 的兼容层
"""

from __future__ import annotations

from typing import List, Optional

__all__ = ["main", "BINDING"]


def main(argv: Optional[List[str]] = None) -> int:
    """启动 IDE，返回进程退出码。"""

    from .qtcompat import BINDING
    from .app import main as _main

    # 写回模块级名字，这样 `from rupis.ide import BINDING` 也能拿到当前用的绑定
    globals()["BINDING"] = BINDING
    return _main(argv)
