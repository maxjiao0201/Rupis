"""Rupis 语言的词表。

高亮、补全、帮助提示都从这里取数据，改语言只要改这一个文件。

这张表就是 IDE 的"语言知识库"：编译器那边只管按语法执行、不管提示，
"这个词长什么样、能不能用在哪个元件上"这类知识全在这里。
所以要支持一门新语言的词法提示，只需要改这个文件，
高亮器、补全器、提示栏都不用动。

表与表之间的关系：
    KEYWORDS        关键字（if / for / def ……）
    CONSTANTS       内置常量（方向、坐标轴、比较器模式、布尔）
    ELEMENTS        红石元件指令（rw / rrep / rco ……）
    ELEMENT_STATES  元件 → 它能带的状态键
    HINTS           单词 → 一行中文说明，提示栏和补全下拉共用
    ALL_WORDS       上面三类合起来排序后的总词表，补全的基础词
    KEY_OWNERS      反查表：状态键 → 能用它的元件
"""

from __future__ import annotations

from typing import Dict, List, Set

# 语句关键字
KEYWORDS: Set[str] = {
    "dpos", "drp", "stru", "strudef", "def",
    "if", "else", "for", "to", "while",
    "let", "lib", "return", "break", "continue",
}

# 内置常量：方向、坐标轴、比较器模式、布尔
CONSTANTS: Set[str] = {
    "north", "south", "east", "west", "up", "down",
    "x", "y", "z",
    "compare", "subtract",
    "true", "false",
}

# 红石元件指令
ELEMENTS: Set[str] = {
    "rw", "rrep", "rco", "obs", "rtorch", "rlamp",
    "piston", "sticky", "rbl", "block",
}

# 每个元件可用的状态键（用于补全与提示）
ELEMENT_STATES: Dict[str, List[str]] = {
    "rw": ["rsig", "len", "axis"],
    "rrep": ["facing", "delay", "locked"],
    "rco": ["facing", "mode", "powered"],
    "obs": ["facing"],
    "rtorch": ["powered"],
    "rlamp": ["powered"],
    "piston": ["facing", "extended"],
    "sticky": ["facing", "extended"],
    "rbl": [],
    "block": [],
}

# 单词 → 一行说明（提示栏和补全下拉都用它）
HINTS: Dict[str, str] = {
    # 声明
    "dpos": "dpos 名称[x,y,z] —— 声明 / 覆盖一个坐标变量",
    "drp": "drp 名称{键=值} —— 声明 / 覆盖一个状态模板变量",
    "lib": "lib 脚本名 [as 别名] —— 导入另一个 .rpi 脚本，之后用 脚本名.成员(...) 调用",
    # 结构与函数
    "stru": "stru 结构名(参数){覆盖状态}[坐标] —— 实例化一个结构模板",
    "strudef": "strudef 结构名(参数){默认状态}:{...} —— 定义方块模板",
    "def": "def 函数名(参数):{...} —— 定义逻辑函数",
    # 控制流
    "if": "if(表达式):{...} —— 条件成立时执行",
    "else": "else:{...} —— if 的否定分支",
    "for": "for 变量 = (起始 to 结束):{...} —— 闭区间循环，起始 > 结束时倒序",
    "to": "for 循环里的区间连接词：(0 to 10)",
    "while": "while(表达式):{...} —— 条件为真时持续执行",
    "let": "let 变量名 = 表达式 —— 声明变量",
    "return": "return 表达式 —— 从函数返回",
    "break": "break —— 跳出当前循环",
    "continue": "continue —— 跳过本轮循环",
    # 元件
    "rw": "红石粉（redstone_wire）—— 状态键：rsig / len / axis",
    "rrep": "红石中继器（repeater）—— 状态键：facing / delay / locked",
    "rco": "红石比较器（comparator）—— 状态键：facing / mode / powered",
    "obs": "侦测器（observer）—— 状态键：facing",
    "rtorch": "红石火把（redstone_torch）—— 状态键：powered",
    "rlamp": "红石灯（redstone_lamp）—— 状态键：powered",
    "piston": "活塞（piston）—— 状态键：facing / extended",
    "sticky": "粘性活塞（sticky_piston）—— 状态键：facing / extended",
    "rbl": "快捷方块（石头、玻璃、石英块……）—— 也可写完整命名空间 ID",
    "block": "原生方块（完整命名空间 ID，如 minecraft:iron_block）",
    # 常量
    "north": "方向：北（-Z）", "south": "方向：南（+Z）",
    "east": "方向：东（+X）", "west": "方向：西（-X）",
    "up": "方向：上（+Y）", "down": "方向：下（-Y）",
    "x": "坐标轴：X（配合 axis= 用）",
    "y": "坐标轴：Y（配合 axis= 用）",
    "z": "坐标轴：Z（配合 axis= 用）",
    "compare": "比较器模式：比较（compare）",
    "subtract": "比较器模式：减法（subtract）",
    "true": "布尔真", "false": "布尔假",
}

# 补全的总词表：关键字、常量、元件合起来去重排序
ALL_WORDS: List[str] = sorted(KEYWORDS | CONSTANTS | ELEMENTS)

# 状态键 → 能用它的元件（反查表，给"这个键是什么意思"的提示用）
KEY_OWNERS: Dict[str, List[str]] = {}
for _elem, _keys in ELEMENT_STATES.items():
    for _key in _keys:
        KEY_OWNERS.setdefault(_key, []).append(_elem)


def classify(word: str) -> str:
    """给一个单词分类：kw / elem / const / ''。

    返回的短码跟 theme.py 里配色字典的键一一对应，高亮器拿它直接取颜色。
    """

    if word in KEYWORDS:
        return "kw"
    if word in ELEMENTS:
        return "elem"
    if word in CONSTANTS:
        return "const"
    return ""


def describe(word: str) -> str:
    """给补全下拉框 / 提示栏准备一行说明文字。"""

    if word in HINTS:
        return HINTS[word]
    if word in ELEMENT_STATES:
        return "状态键：" + ", ".join(ELEMENT_STATES[word])
    return describe_state_key(word)


def describe_state_key(key: str) -> str:
    """说明某个状态键能用在哪些元件上。"""

    owners = KEY_OWNERS.get(key)
    if not owners:
        return ""
    return f"状态键 {key}：可用于 " + "、".join(sorted(owners))


def describe_symbol(name: str, kind: str) -> str:
    """说明用户自己定义的结构 / 函数。"""

    if kind == "structure":
        return f"结构模板 {name} —— 用 stru 实例化"
    if kind == "function":
        return f"函数 {name} —— 调用方式 {name}(参数…)"
    return ""


def describe_element(element: str) -> str:
    """元件的总体说明（不带状态键细节）。"""

    hint = HINTS.get(element)
    if hint:
        # HINTS 里的写法是"前半句——后半句"，只要前半句
        return hint.split("——")[0].strip()
    return ""
