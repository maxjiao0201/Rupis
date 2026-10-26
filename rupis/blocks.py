"""红石元件 / 方块注册表。

这里定义 Rupis 指令名 → Minecraft 方块 ID、用户状态键 → Minecraft 方块状态名的映射。

约定：
  * 用户状态键是 Rupis 自己的名字（比如 rsig、powered），与规范一致；
  * Minecraft 真实属性名可能不同（比如红石粉是 power，火把是 lit），
    这里通过 states 映射表自动转换。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

# --------------------------------------------------------------------- 方向常量
DIRECTION_NAMES = ("north", "south", "east", "west", "up", "down")


class Direction:
    """内置方向常量。"""

    __slots__ = ("name",)
    _cache: Dict[str, "Direction"] = {}

    def __init__(self, name: str) -> None:
        self.name = name

    @classmethod
    def get(cls, name: str) -> "Direction":
        key = name.lower()
        if key not in DIRECTION_NAMES:
            raise ValueError(f"未知方向 {name!r}")
        if key not in cls._cache:
            cls._cache[key] = cls(key)
        return cls._cache[key]

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Direction) and other.name == self.name

    def __hash__(self) -> int:
        return hash(("dir", self.name))

    def __str__(self) -> str:
        return self.name

    def __repr__(self) -> str:
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
@dataclass
class Element:
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
    "rw": Element(
        key="rw",
        block_id="minecraft:redstone_wire",
        states={"rsig": "power"},
        pseudo=("len", "axis"),
        int_keys=("len",),
        ranges={"rsig": (0, 15), "len": (1, 4096)},
        choices={"axis": ("x", "y", "z")},
    ),
    # 红石中继器
    "rrep": Element(
        key="rrep",
        block_id="minecraft:repeater",
        states={"facing": "facing", "delay": "delay", "locked": "locked"},
        bool_keys=("locked",),
        int_keys=("delay",),
        ranges={"delay": (1, 4)},
    ),
    # 红石比较器
    "rco": Element(
        key="rco",
        block_id="minecraft:comparator",
        states={"facing": "facing", "mode": "mode", "powered": "powered"},
        bool_keys=("powered",),
        choices={"mode": ("compare", "subtract")},
    ),
    # 侦测器
    "obs": Element(
        key="obs",
        block_id="minecraft:observer",
        states={"facing": "facing"},
    ),
    # 红石火把
    "rtorch": Element(
        key="rtorch",
        block_id="minecraft:redstone_torch",
        states={"powered": "lit"},
        bool_keys=("powered",),
    ),
    # 红石灯
    "rlamp": Element(
        key="rlamp",
        block_id="minecraft:redstone_lamp",
        states={"powered": "lit"},
        bool_keys=("powered",),
    ),
    # 活塞
    "piston": Element(
        key="piston",
        block_id="minecraft:piston",
        states={"facing": "facing", "extended": "extended"},
        bool_keys=("extended",),
    ),
    # 粘性活塞
    "sticky": Element(
        key="sticky",
        block_id="minecraft:sticky_piston",
        states={"facing": "facing", "extended": "extended"},
        bool_keys=("extended",),
    ),
}


# ------------------------------------------------------------- rbl 快捷方块表
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
    """把 rbl 缩写解析成 (Minecraft 方块 ID, 状态映射)。"""

    key = name.lower()
    if key in RBL_BLOCKS:
        return RBL_BLOCKS[key], None
    if ":" in key:  # rbl 里也允许直接写完整命名空间 ID
        ns, _, path = key.partition(":")
        if ns and path:
            return f"{ns}:{path}", None
    raise KeyError(name)


def normalize_block_id(name: str) -> str:
    """把方块 ID 规范化成 namespace:path 形式（缺省 namespace 为 minecraft）。"""

    if ":" in name:
        ns, _, path = name.partition(":")
        return f"{ns}:{path}"
    return f"minecraft:{name}"
