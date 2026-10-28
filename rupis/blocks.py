"""红石元件 / 方块注册表。

这里定义 Rupis 指令名 → Minecraft 方块 ID、用户状态键 → Minecraft 方块状态名的映射。

约定：
  * 用户状态键是 Rupis 自己的名字（比如 rsig、powered），与规范一致；
  * Minecraft 真实属性名可能不同（比如红石粉是 power，火把是 lit），
    这里通过 states 映射表自动转换。

数据结构：
  * Element  —— 单个红石元件的完整描述（指令名、方块 ID、状态键翻译表等）；
  * ELEMENTS —— 元件注册表，字典键就是 Rupis 里能直接写的指令名；
  * RBL_BLOCKS —— rbl 指令用的方块缩写表，缩写 → Minecraft 方块 ID。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

# --------------------------------------------------------------------- 方向常量
# facing= 的合法取值，同时也是解释器内部 Direction 对象的名字表
DIRECTION_NAMES = ("north", "south", "east", "west", "up", "down")


class Direction:
    """内置方向常量。

    同一个方向名永远拿到同一个对象，所以可以直接用 == 比较、用 hash 放进集合。
    """

    __slots__ = ("name",)
    _cache: Dict[str, "Direction"] = {}

    def __init__(self, name: str) -> None:
        self.name = name

    @classmethod
    def get(cls, name: str) -> "Direction":
        """按名字取方向对象，名字不区分大小写。"""

        key = name.lower()
        if key not in DIRECTION_NAMES:
            raise ValueError(f"未知方向 {name!r}")
        if key not in cls._cache:
            # 缓存住，保证同名方向是同一个实例
            cls._cache[key] = cls(key)
        return cls._cache[key]

    def __eq__(self, other: object) -> bool:
        """按方向名判断是否同一个方向。"""

        return isinstance(other, Direction) and other.name == self.name

    def __hash__(self) -> int:
        """配合 __eq__，让 Direction 能放进 set / dict 当键。"""

        return hash(("dir", self.name))

    def __str__(self) -> str:
        """字符串化时只给方向名，方便拼进 /setblock 命令。"""

        return self.name

    def __repr__(self) -> str:
        """调试用的可读表示。"""

        return f"Direction({self.name})"


# ------------------------------------------------------------- 内置常量（关键字）
# 这些标识符可以直接写进状态块里，例如 facing=east、mode=subtract、axis=z
BUILTIN_CONSTANTS = {
    "north", "south", "east", "west", "up", "down",   # 方向
    "x", "y", "z",                                    # 坐标轴
    "compare", "subtract",                            # 比较器模式
    "true", "false",                                  # 布尔
}


# ------------------------------------------------------------------- 元件定义
# 键就是 Rupis 里能直接写的指令名；states 负责把用户键翻译成 Minecraft 的真实属性名，
# 例如用户写 powered，Minecraft 里红石火把的属性其实叫 lit。
@dataclass
class Element:
    """一个红石元件的完整描述。

    字段：
        key       —— Rupis 指令名，也是 ELEMENTS 的键；
        block_id  —— 对应的 Minecraft 方块 ID（命名空间形式）；
        states    —— 用户状态键 → Minecraft 真实状态名 的翻译表；
        pseudo    —— 解释器专用状态键，只在 Rupis 内部生效，不会写进方块状态；
        bool_keys —— 需要强制转成布尔的键；
        int_keys  —— 需要强制转成整数的键；
        ranges    —— 限定整数区间的键 → (最小值, 最大值)；
        choices   —— 限定枚举取值的键 → 合法取值元组。
    """

    key: str                                  # Rupis 指令名
    block_id: str                             # Minecraft 方块 ID
    states: Dict[str, str] = field(default_factory=dict)   # 用户键 -> MC 状态名
    pseudo: Tuple[str, ...] = ()              # 解释器专用状态，不发给 MC
    bool_keys: Tuple[str, ...] = ()           # 需要转成布尔的键
    int_keys: Tuple[str, ...] = ()            # 需要转成整数的键
    ranges: Dict[str, Tuple[int, int]] = field(default_factory=dict)  # 合法区间
    choices: Dict[str, Tuple[str, ...]] = field(default_factory=dict)  # 合法取值


ELEMENTS: Dict[str, Element] = {
    # 红石粉（redstone wire）—— rw 专属于红石粉
    # 用户写 rsig=5，发给游戏的是 power=5；len / axis 属于解释器专用状态，
    # 只用来把一根粉展开成连续的一长条，不会出现在方块状态里
    "rw": Element(
        key="rw",
        block_id="minecraft:redstone_wire",
        states={"rsig": "power"},
        pseudo=("len", "axis"),
        int_keys=("len",),
        ranges={"rsig": (0, 15), "len": (1, 4096)},
        choices={"axis": ("x", "y", "z")},
    ),
    # 红石中继器：状态名和游戏里完全一致，只有 locked 需要转成布尔
    "rrep": Element(
        key="rrep",
        block_id="minecraft:repeater",
        states={"facing": "facing", "delay": "delay", "locked": "locked"},
        bool_keys=("locked",),
        int_keys=("delay",),
        ranges={"delay": (1, 4)},
    ),
    # 红石比较器：mode 只能取 compare / subtract，powered 是布尔
    "rco": Element(
        key="rco",
        block_id="minecraft:comparator",
        states={"facing": "facing", "mode": "mode", "powered": "powered"},
        bool_keys=("powered",),
        choices={"mode": ("compare", "subtract")},
    ),
    # 侦测器：只有朝向这一个状态
    "obs": Element(
        key="obs",
        block_id="minecraft:observer",
        states={"facing": "facing"},
    ),
    # 红石火把：用户写 powered，游戏那边的真实属性叫 lit
    "rtorch": Element(
        key="rtorch",
        block_id="minecraft:redstone_torch",
        states={"powered": "lit"},
        bool_keys=("powered",),
    ),
    # 红石灯：同样把 powered 翻译成 lit
    "rlamp": Element(
        key="rlamp",
        block_id="minecraft:redstone_lamp",
        states={"powered": "lit"},
        bool_keys=("powered",),
    ),
    # 活塞：extended=true 表示活塞杆已经伸出来
    "piston": Element(
        key="piston",
        block_id="minecraft:piston",
        states={"facing": "facing", "extended": "extended"},
        bool_keys=("extended",),
    ),
    # 粘性活塞：状态和普通活塞一样
    "sticky": Element(
        key="sticky",
        block_id="minecraft:sticky_piston",
        states={"facing": "facing", "extended": "extended"},
        bool_keys=("extended",),
    ),
}


# ------------------------------------------------------------- rbl 快捷方块表
# rbl 指令用的缩写 → Minecraft 方块 ID；这里只登记纯方块，不带任何状态
RBL_BLOCKS: Dict[str, str] = {
    "stone": "minecraft:stone",
    "smoothstone": "minecraft:smooth_stone",
    "smooth_stone": "minecraft:smooth_stone",
    "cobblestone": "minecraft:cobblestone",
    "cobble": "minecraft:cobblestone",
    "stonebrick": "minecraft:stone_bricks",
    "stone_bricks": "minecraft:stone_bricks",
    "brick": "minecraft:bricks",
    "bricks": "minecraft:bricks",
    "quartz": "minecraft:quartz_block",
    "smoothquartz": "minecraft:smooth_quartz",
    "glass": "minecraft:glass",
    "glasspane": "minecraft:glass_pane",
    "glass_pane": "minecraft:glass_pane",
    "obsidian": "minecraft:obsidian",
    "netherrack": "minecraft:netherrack",
    "iron": "minecraft:iron_block",
    "gold": "minecraft:gold_block",
    "diamond": "minecraft:diamond_block",
    "emerald": "minecraft:emerald_block",
    "wool": "minecraft:white_wool",
    "concrete": "minecraft:white_concrete",
    "terracotta": "minecraft:white_terracotta",
    "slab": "minecraft:oak_slab",
    "stairs": "minecraft:oak_stairs",
    "ironbars": "minecraft:iron_bars",
    "iron_bars": "minecraft:iron_bars",
    "chest": "minecraft:chest",
    "furnace": "minecraft:furnace",
    "hopper": "minecraft:hopper",
    "target": "minecraft:target",
    "noteblock": "minecraft:note_block",
    "note_block": "minecraft:note_block",
    "redstone_block": "minecraft:redstone_block",
    "lever": "minecraft:lever",
    "button": "minecraft:stone_button",
    "daylight": "minecraft:daylight_detector",
    "lamplike": "minecraft:sea_lantern",
    "sea_lantern": "minecraft:sea_lantern",
    "glowstone": "minecraft:glowstone",
    "snow": "minecraft:snow_block",
    "sand": "minecraft:sand",
    "dirt": "minecraft:dirt",
    "planks": "minecraft:oak_planks",
    "log": "minecraft:oak_log",
}


def resolve_rbl(name: str) -> Tuple[str, Optional[Dict[str, str]]]:
    """把 rbl 缩写解析成 (Minecraft 方块 ID, 状态映射)。

    状态映射返回 None，表示这个方块的状态键不做校验，原样透传给游戏。
    """

    key = name.lower()
    if key in RBL_BLOCKS:
        return RBL_BLOCKS[key], None
    if ":" in key:  # rbl 里也允许直接写完整命名空间 ID
        ns, _, path = key.partition(":")
        if ns and path:
            return f"{ns}:{path}", None
    raise KeyError(name)


def normalize_block_id(name: str) -> str:
    """把方块 ID 规范化成 namespace:path 形式（缺省 namespace 为 minecraft）。

    这样 "stone" 和 "minecraft:stone" 会被当成同一个方块。
    """

    if ":" in name:
        ns, _, path = name.partition(":")
        return f"{ns}:{path}"
    return f"minecraft:{name}"
