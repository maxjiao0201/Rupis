"""Rupis IDE —— Rupis 脚本语言的桌面编辑器。

启动方式：
    python -m rupis.ide            # 打开空文档
    python -m rupis.ide a.rpi      # 直接打开某个脚本
    python ide.py a.rpi            # 同上（根目录快捷方式）

依赖 PySide6 / PyQt6 / PyQt5 之一。
"""

from __future__ import annotations

from typing import List, Optional

__all__ = ["main", "BINDING"]


def main(argv: Optional[List[str]] = None) -> int:
    """启动 IDE，返回进程退出码。"""

    from .qtcompat import BINDING
    from .app import main as _main

    globals()["BINDING"] = BINDING
    return _main(argv)
