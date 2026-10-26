"""导出器：把解释出来的世界数据输出成各种可用格式。

支持格式：
    commands   —— Minecraft /setblock 命令列表（最通用）
    json       —— 结构化 JSON（方便二次处理）
    structure  —— .mcstructure 文件（Java 版 结构方块可直接加载）
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple

from .interpreter import Placement, fmt_state
from .nbt import write_gzip_nbt

# .mcstructure 的方块索引顺序：index = x + y*sizeX + z*sizeX*sizeY
# （X 变化最快，其次 Y，最后 Z）
def structure_index(x: int, y: int, z: int, size_x: int, size_y: int) -> int:
    return x + y * size_x + z * size_x * size_y


def _sorted_positions(world: Dict[Tuple[int, int, int], Placement]) -> List[Tuple[int, int, int]]:
    return sorted(world.keys(), key=lambda p: (p[0], p[1], p[2]))


def export_commands(world: Dict[Tuple[int, int, int], Placement]) -> str:
    lines = [world[pos].command() for pos in _sorted_positions(world)]
    return "\n".join(lines)


def export_json(world: Dict[Tuple[int, int, int], Placement]) -> str:
    if not world:
        return json.dumps({"size": [0, 0, 0], "origin": [0, 0, 0], "blocks": []},
                          ensure_ascii=False, indent=2)
    xs = [p[0] for p in world]
    ys = [p[1] for p in world]
    zs = [p[2] for p in world]
    origin = [min(xs), min(ys), min(zs)]
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
    """导出 .mcstructure 文件，返回 (方块数, 结构尺寸)。"""

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
    """统计摘要。"""

    if not world:
        return "没有放置任何方块。"
    counts: Dict[str, int] = {}
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
