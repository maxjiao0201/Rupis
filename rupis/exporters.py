"""导出器：把解释出来的世界数据输出成各种可用格式。

支持格式：
    commands   —— Minecraft /setblock 命令列表（最通用）
    json       —— 结构化 JSON（方便二次处理）
    structure  —— .mcstructure 文件（Java 版 结构方块可直接加载）

另外 summary() 会生成一段人类可读的统计摘要，供命令行 --format summary 使用。

输入统一是「世界」字典：坐标 (x, y, z) → 该坐标上的 Placement。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple

from .interpreter import Placement, fmt_state
from .nbt import write_gzip_nbt

# .mcstructure 的方块索引顺序：index = x + y*sizeX + z*sizeX*sizeY
# （X 变化最快，其次 Y，最后 Z）
def structure_index(x: int, y: int, z: int, size_x: int, size_y: int) -> int:
    """算出结构里某个局部坐标对应的方块索引。

    .mcstructure 要求 X 变化最快、Z 最慢，这样游戏里的结构方块预览方向才对得上。
    export_structure 里的三重循环就是按这个顺序往 block_indices 里填的。
    """

    return x + y * size_x + z * size_x * size_y


def _sorted_positions(world: Dict[Tuple[int, int, int], Placement]) -> List[Tuple[int, int, int]]:
    """按 (x, y, z) 排好序的坐标列表，保证导出结果每次都一样。"""

    return sorted(world.keys(), key=lambda p: (p[0], p[1], p[2]))


def export_commands(world: Dict[Tuple[int, int, int], Placement]) -> str:
    """导出一行一个的 /setblock 命令，整段复制进游戏聊天栏就能用。"""

    lines = [world[pos].command() for pos in _sorted_positions(world)]
    return "\n".join(lines)


def export_json(world: Dict[Tuple[int, int, int], Placement]) -> str:
    """导出结构化 JSON：包围盒尺寸、原点坐标，以及每个方块的位置与状态。"""

    if not world:
        return json.dumps({"size": [0, 0, 0], "origin": [0, 0, 0], "blocks": []},
                          ensure_ascii=False, indent=2)
    xs = [p[0] for p in world]
    ys = [p[1] for p in world]
    zs = [p[2] for p in world]
    origin = [min(xs), min(ys), min(zs)]
    # origin 是包围盒的最小角，size 是包围盒的三条边长
    size = [max(xs) - origin[0] + 1, max(ys) - origin[1] + 1, max(zs) - origin[2] + 1]
    blocks = []
    for pos in _sorted_positions(world):
        placement = world[pos]
        blocks.append(
            {
                "pos": [pos[0], pos[1], pos[2]],
                "id": placement.block_id,
                "states": {k: fmt_state(v) for k, v in sorted(placement.states.items())},
            }
        )
    return json.dumps(
        {"size": size, "origin": origin, "blocks": blocks},
        ensure_ascii=False,
        indent=2,
    )


def export_structure(
    path: str,
    world: Dict[Tuple[int, int, int], Placement],
    data_version: int = 3955,
) -> Tuple[int, Tuple[int, int, int]]:
    """导出 .mcstructure 文件，返回 (方块数, 结构尺寸)。

    文件里不直接存方块，而是先做「调色板」去重：block_indices 里存的是调色板下标，
    调色板的每一项才是真正的方块 ID + 状态。0 号必须是 air，所有空位都指向它。
    """

    if not world:
        size = (0, 0, 0)
        # 0 号调色板必须是空气：空位置全部指向它
        palette_entries: List[Dict[str, Any]] = [
            {"name": "minecraft:air", "states": {}, "version": data_version}
        ]
        indices: List[int] = []
        origin = (0, 0, 0)
    else:
        xs = [p[0] for p in world]
        ys = [p[1] for p in world]
        zs = [p[2] for p in world]
        origin = (min(xs), min(ys), min(zs))
        size = (max(xs) - origin[0] + 1, max(ys) - origin[1] + 1, max(zs) - origin[2] + 1)

        palette_index: Dict[Tuple[str, str], int] = {}
        # 0 号调色板必须是空气：空位置全部指向它
        palette_entries = [{"name": "minecraft:air", "states": {}, "version": data_version}]
        indices = []
        size_x, size_y, size_z = size
        # 按索引顺序遍历：z 最外层、y 中间、x 最内层
        for z in range(size_z):
            for y in range(size_y):
                for x in range(size_x):
                    placement = world.get((origin[0] + x, origin[1] + y, origin[2] + z))
                    if placement is None:
                        indices.append(0)  # 空气
                        continue
                    states = tuple(sorted((k, fmt_state(v)) for k, v in placement.states.items()))
                    # 方块 ID + 状态完全一样才算同一个调色板项
                    key = (placement.block_id, repr(states))
                    idx = palette_index.get(key)
                    if idx is None:
                        idx = len(palette_entries)
                        palette_index[key] = idx
                        palette_entries.append(
                            {
                                "name": placement.block_id,
                                "states": {k: v for k, v in states},
                                "version": data_version,
                            }
                        )
                    indices.append(idx)

    # 整个文件就是一棵 NBT 树，根是 TAG_Compound
    root = {
        "format_version": 1,
        "DataVersion": data_version,
        "size": [size[0], size[1], size[2]],
        "structure": {
            "block_indices": indices,
            "palette": {
                "default": {
                    "block_palette": palette_entries,
                }
            },
            "entities": [],
            # 结构局部原点固定为 (0,0,0)：加载时结构的最小角就落在放置坐标上
            "structure_world_origin": [0, 0, 0],
        },
    }
    write_gzip_nbt(path, root)
    return len(world), size


def summary(world: Dict[Tuple[int, int, int], Placement]) -> str:
    """统计摘要：方块总数、包围盒范围，以及每种方块各放了多少个。"""

    if not world:
        return "没有放置任何方块。"
    counts: Dict[str, int] = {}
    # 按方块 ID 分组计数
    for placement in world.values():
        counts[placement.block_id] = counts.get(placement.block_id, 0) + 1
    xs = [p[0] for p in world]
    ys = [p[1] for p in world]
    zs = [p[2] for p in world]
    lines = [
        f"共放置 {len(world)} 个方块。",
        f"包围盒：X[{min(xs)}..{max(xs)}] Y[{min(ys)}..{max(ys)}] Z[{min(zs)}..{max(zs)}]",
        "按方块统计：",
    ]
    for block_id, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"  {block_id}: {count}")
    return "\n".join(lines)
