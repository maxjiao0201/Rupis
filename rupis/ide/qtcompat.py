"""Qt 绑定兼容层。

优先用 PySide6（Qt 官方），其次 PyQt6，最后 PyQt5。
代码里统一使用 Qt6 的"作用域枚举"写法（如 Qt.AlignmentFlag.AlignLeft），
PyQt5 是旧式无作用域枚举，这里补一层别名，保证同一份代码两边都能跑。

为什么要单独做这一层：
    * 三个绑定提供的模块名一致（QtCore / QtGui / QtWidgets），业务代码不用关心
      底下到底装的是哪一个；
    * 但枚举写法不一样：Qt6 起改成带作用域的形式，Qt5 只有扁平的 Qt.AlignLeft。
      IDE 里到处要设对齐方式、按键修饰符、滚动条策略这些枚举，所以统一按 Qt6 的
      写法写，再在这里给 PyQt5 补出等价的名字；
    * QAction 的位置三家也不一样：PySide6 / PyQt6 在 QtGui 里，PyQt5 在 QtWidgets 里，
      所以下面每次都顺手 import 一次。
"""

from __future__ import annotations

BINDING = ""

try:
    # 按优先级挨个试，全失败了才算真的没装任何 Qt 绑定
    from PySide6 import QtCore, QtGui, QtWidgets  # noqa: F401
    from PySide6.QtGui import QAction  # noqa: F401
    BINDING = "PySide6"
except ImportError:
    try:
        from PyQt6 import QtCore, QtGui, QtWidgets  # noqa: F401
        from PyQt6.QtGui import QAction  # noqa: F401
        BINDING = "PyQt6"
    except ImportError:
        try:
            from PyQt5 import QtCore, QtGui, QtWidgets  # noqa: F401
            from PyQt5.QtWidgets import QAction  # noqa: F401
            BINDING = "PyQt5"
        except ImportError:
            raise ImportError(
                "Rupis IDE 需要 PySide6 / PyQt6 / PyQt5 之一。\n"
                "  pip install PySide6      # 推荐\n"
                "  pip install PyQt6"
            )


def _patch_pyqt5() -> None:
    """给 PyQt5 补上 Qt6 风格的命名空间枚举。

    做法是在宿主类上挂一个空壳类，把成员原样搬过去：

        Qt.AlignmentFlag.AlignLeft    ←  Qt5 原本只有扁平的 Qt.AlignLeft

    搬过去的是同一批值，所以比较、判断、传给 setEnum 之类都能正常工作。
    """

    def ns(owner, name: str, members) -> None:
        """在 owner 上造出一个叫 name 的命名空间，里面放上 members 这些成员。"""

        obj = type(name, (), {})
        for member in members:
            setattr(obj, member, getattr(owner, member))
        setattr(owner, name, obj)

    # 下面这些就是 IDE 实际用到的那几组枚举，按 Qt6 的作用域一一补齐
    ns(QtCore.Qt, "AlignmentFlag",
       ["AlignLeft", "AlignRight", "AlignTop", "AlignBottom",
        "AlignHCenter", "AlignVCenter", "AlignCenter"])
    ns(QtCore.Qt, "Orientation", ["Horizontal", "Vertical"])
    ns(QtCore.Qt, "ScrollBarPolicy",
       ["ScrollBarAsNeeded", "ScrollBarAlwaysOn", "ScrollBarAlwaysOff"])
    ns(QtCore.Qt, "TextFormat", ["PlainText", "RichText"])
    ns(QtCore.Qt, "ItemDataRole", ["UserRole", "DisplayRole"])
    ns(QtCore.Qt, "KeyModifier", ["ControlModifier", "ShiftModifier", "AltModifier"])
    ns(QtCore.Qt, "KeyboardModifier", ["ControlModifier", "ShiftModifier", "AltModifier"])
    ns(QtCore.Qt, "TextInteractionFlag",
       ["TextEditorInteraction", "NoTextInteraction", "TextSelectableByMouse"])
    ns(QtCore.Qt, "CheckState", ["Unchecked", "Checked"])
    ns(QtCore.Qt, "GlobalColor", ["black", "white", "red", "green", "blue", "gray"])
    ns(QtCore.Qt, "Key",
       ["Key_Space", "Key_Slash", "Key_Tab", "Key_Backtab", "Key_Return", "Key_Enter",
        "Key_Escape", "Key_F3", "Key_F5", "Key_F9", "Key_F12",
        "Key_S", "Key_G", "Key_O", "Key_N", "Key_D", "Key_K", "Key_C", "Key_L",
        "Key_Up", "Key_Down", "Key_Backspace", "Key_Equal", "Key_Minus"])

    ns(QtWidgets.QPlainTextEdit, "LineWrapMode", ["NoWrap", "WidgetWidth"])
    ns(QtWidgets.QMessageBox, "StandardButton", ["Ok", "Cancel", "Yes", "No"])
    ns(QtWidgets.QMessageBox, "Icon", ["Information", "Warning", "Critical", "Question"])
    ns(QtGui.QTextFormat, "Property", ["FullWidthSelection"])
    ns(QtGui.QFont, "Weight", ["Normal", "Bold"])
    ns(QtGui.QPalette, "ColorRole",
       ["Base", "Text", "Highlight", "HighlightedText", "Window", "WindowText",
        "Button", "ButtonText", "ToolTipBase", "ToolTipText", "PlaceholderText", "Link"])
    ns(QtGui.QTextCursor, "MoveOperation",
       ["Left", "Right", "Up", "Down", "Start", "End", "NextBlock", "PreviousBlock"])
    ns(QtGui.QTextCursor, "MoveMode", ["MoveAnchor", "KeepAnchor"])
    ns(QtGui.QTextCursor, "SelectionType",
       ["LineUnderCursor", "WordUnderCursor", "Document", "BlockUnderCursor"])
    ns(QtWidgets.QCompleter, "CompletionMode",
       ["UnfilteredPopupCompletion", "PopupCompletion", "InlineCompletion"])


if BINDING == "PyQt5":
    # 只有 PyQt5 缺作用域枚举，另外两家原生就支持，不用动
    _patch_pyqt5()


__all__ = ["QtCore", "QtGui", "QtWidgets", "QAction", "BINDING"]
