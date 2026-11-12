"""Rupis 的多语言支持。

翻译表放在 lang/ 目录里，一个 JSON 文件对应一种语言，文件名就是语言代码
（比如 en.json、zh-TW.json）。文件内容是「原文 -> 译文」的字典：

    {
        "__name__": "English",
        "打开": "Open",
        "找不到脚本文件：{path}": "Script file not found: {path}"
    }

几条约定：
    * 原文就是键，翻译文是值；翻译表里多写的键会被忽略；
    * 带 {占位符} 的原文，译文要保留同名占位符，位置可以变；
    * 找不到译文时直接显示原文，所以少翻几个词也不会坏掉；
    * "__name__" 是特殊键，给这个语言起个显示名，默认用文件名。

lang/ 目录的位置：
    * 源码运行：仓库根目录下的 lang/；
    * 打包成 exe：exe 同级的 lang/（用户自己放翻译文件的地方），
      官方语言可以用 --add-data 打进 exe 内部（sys._MEIPASS/lang），
      同名语言以 exe 同级的为准。

语言选择存在 %APPDATA%\\Rupis\\settings.json 里，IDE 和命令行共用同一份。
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional

# 内置的默认语言：源码语言就是中文，所以它不需要翻译文件
DEFAULT_LANG = "zh-CN"
DEFAULT_LANG_NAME = "中文（默认）"

# 语言目录名 / 设置文件名
LANG_DIR_NAME = "lang"
SETTINGS_FILE = "settings.json"

# 翻译表里的特殊键：这个语言在 IDE 菜单里的显示名
NAME_KEY = "__name__"


class Language(NamedTuple):
    """一种可选语言。

    code：语言代码，也是语言文件名（en.json -> "en"）；
    name：菜单里显示的名字；
    path：翻译文件路径，默认语言没有文件所以是 None。
    """

    code: str
    name: str
    path: Optional[Path]


# ====================================================================== 路径
def _config_dir() -> Path:
    """用户配置目录，跟解释器的 file_assoc.installed 放在一处。"""

    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "Rupis"


SETTINGS_PATH = _config_dir() / SETTINGS_FILE


def _lang_dirs() -> List[Path]:
    """按优先级列出所有会被搜索的语言目录。

    打包成 exe 时，exe 同级的 lang/ 优先（用户自己的翻译），
    exe 内部打包进来的 lang/ 靠后（官方语言）。
    """

    dirs: List[Path] = []
    if getattr(sys, "frozen", False):
        dirs.append(Path(sys.executable).resolve().parent / LANG_DIR_NAME)
        # PyInstaller 解包出来的临时目录，里面是 --add-data 塞进去的东西
        bundle = getattr(sys, "_MEIPASS", None)
        if bundle:
            dirs.append(Path(bundle) / LANG_DIR_NAME)
    else:
        # 源码运行：rupis/i18n.py 的上一级就是仓库根
        dirs.append(Path(__file__).resolve().parent.parent / LANG_DIR_NAME)
    return dirs


def _find_lang_file(code: str) -> Optional[Path]:
    """找某个语言代码对应的翻译文件，按 _lang_dirs() 的优先级来。"""

    for directory in _lang_dirs():
        candidate = directory / f"{code}.json"
        if candidate.is_file():
            return candidate
    return None


# ====================================================================== 设置
def _read_settings() -> Dict[str, object]:
    """读 settings.json；读不到就当空设置。"""

    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_settings(data: Dict[str, object]) -> None:
    """写 settings.json；写不了就算了，不该因此让程序崩掉。"""

    try:
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError:
        pass


def saved_language() -> str:
    """上次选的语言代码，没选过就是默认语言。"""

    code = str(_read_settings().get("lang", "") or "")
    return code if code else DEFAULT_LANG


def save_language(code: str) -> None:
    """记住选中的语言，供下次启动时读取。"""

    data = _read_settings()
    data["lang"] = code
    _write_settings(data)


# ====================================================================== 语言表
_table: Dict[str, str] = {}
_current: str = DEFAULT_LANG


def _read_table(path: Path) -> Dict[str, str]:
    """读一个翻译文件；坏文件当空表，不让程序因此起不来。"""

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    table: Dict[str, str] = {}
    for key, value in data.items():
        if isinstance(key, str) and isinstance(value, str):
            table[key] = value
    return table


def _display_name(path: Path, code: str) -> str:
    """读翻译文件里的 "__name__"，没有就用文件名。"""

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return code
    if isinstance(data, dict):
        name = data.get(NAME_KEY)
        if isinstance(name, str) and name.strip():
            return name.strip()
    return code


def available_languages() -> List[Language]:
    """列出所有可选语言：默认语言，加上 lang/ 目录里的每个 JSON 文件。"""

    result = [Language(DEFAULT_LANG, t(DEFAULT_LANG_NAME), None)]
    seen = {DEFAULT_LANG}
    for directory in _lang_dirs():
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.json")):
            code = path.stem
            if code in seen:
                continue
            seen.add(code)
            result.append(Language(code, _display_name(path, code), path))
    return result


def load(code: Optional[str] = None) -> str:
    """加载某种语言的翻译表，返回语言代码。

    code 省略就用当前语言；找不到对应文件就退回默认语言。
    """

    global _table, _current

    if code is None:
        code = _current
    path = _find_lang_file(code) if code != DEFAULT_LANG else None
    if path is None and code != DEFAULT_LANG:
        # 文件没了（比如用户把它删了），退回默认语言
        code = DEFAULT_LANG
    _current = code
    _table = _read_table(path) if path is not None else {}
    return _current


def current_code() -> str:
    """当前生效的语言代码。"""

    return _current


def current_name() -> str:
    """当前生效的语言在菜单里显示的名字。"""

    for lang in available_languages():
        if lang.code == _current:
            return lang.name
    return t(DEFAULT_LANG_NAME)


def set_language(code: str, persist: bool = True) -> str:
    """切换语言，并（可选）记住选择。

    返回真正生效的语言代码：文件不存在时会退回默认语言。
    """

    effective = load(code)
    if persist:
        save_language(effective)
    return effective


# ====================================================================== 翻译
# 占位符：{名字}、{名字!r}、{名字:格式}
_PLACEHOLDER = re.compile(r"\{(\w+)(![rsa])?(:[^{}]*)?\}")


def _format(text: str, kwargs: Dict[str, object]) -> str:
    """把占位符填上。

    只替换 kwargs 里有的占位符，其余的花括号原样留着 ——
    原文里的字面花括号（syntax.py 的 HINTS 里有 "{键=值}" 这种）
    和译文里漏写、多写的占位符都不会把整段文字弄坏。
    """

    if not kwargs:
        return text

    def replace(match: "re.Match[str]") -> str:
        name, conv, spec = match.group(1), match.group(2), match.group(3)
        if name not in kwargs:
            return match.group(0)
        value = kwargs[name]
        if conv == "!r":
            value = repr(value)
        elif conv == "!s":
            value = str(value)
        elif conv == "!a":
            value = ascii(value)
        if spec:
            try:
                return format(value, spec[1:])
            except (TypeError, ValueError):
                return str(value)
        return str(value)

    return _PLACEHOLDER.sub(replace, text)


def t(_msg: str, **kwargs: object) -> str:
    """把原文翻成当前语言。

    _msg 是原文（中文）；译文里可以用 {占位符}，值通过 kwargs 传进来。
    找不到译文就用原文，翻译表缺词不会导致界面出错。

    第一个参数刻意叫 _msg：占位符的名字是普通单词，如果参数也叫 key，
    t("{key} 必须在 …", key=key) 就会撞车（多个 key）。
    """

    text = _table.get(_msg)
    if text is None:
        text = _msg
    return _format(text, kwargs)


# 导入时就按上次的选择把语言加载好，
# 这样各处直接调用 t() 就行，不用各自操心初始化。
load(saved_language())
