"""极简 NBT 写入器（只实现导出 .mcstructure 需要的标签类型）。

支持：TAG_Byte / Short / Int / Long / Float / Double / String /
      List / Compound / Int_Array。
"""

from __future__ import annotations

import gzip
import struct
from typing import Any, Dict, List, Sequence

TAG_END = 0
TAG_BYTE = 1
TAG_SHORT = 2
TAG_INT = 3
TAG_LONG = 4
TAG_FLOAT = 5
TAG_DOUBLE = 6
TAG_BYTE_ARRAY = 7
TAG_STRING = 8
TAG_LIST = 9
TAG_COMPOUND = 10
TAG_INT_ARRAY = 11


class IntArray:
    """标记为 TAG_Int_Array 的整数数组。"""

    def __init__(self, values: Sequence[int]) -> None:
        self.values = list(values)


def _type_of(value: Any) -> int:
    if isinstance(value, bool):
        return TAG_BYTE
    if isinstance(value, IntArray):
        return TAG_INT_ARRAY
    if isinstance(value, int):
        return TAG_INT
    if isinstance(value, float):
        return TAG_DOUBLE
    if isinstance(value, str):
        return TAG_STRING
    if isinstance(value, (list, tuple)):
        return TAG_LIST
    if isinstance(value, dict):
        return TAG_COMPOUND
    raise TypeError(f"不支持的 NBT 值类型：{type(value)!r}")


def _name(text: str) -> bytes:
    raw = text.encode("utf-8")
    return struct.pack(">H", len(raw)) + raw


def _payload(value: Any) -> bytes:
    """写入标签内容（不含标签类型字节）。"""

    if isinstance(value, bool):
        return struct.pack(">b", 1 if value else 0)
    if isinstance(value, IntArray):
        return struct.pack(">i", len(value.values)) + b"".join(
            struct.pack(">i", v) for v in value.values
        )
    if isinstance(value, int):
        return struct.pack(">i", value)
    if isinstance(value, float):
        return struct.pack(">d", value)
    if isinstance(value, str):
        return _name(value)
    if isinstance(value, (list, tuple)):
        items = list(value)
        if not items:
            return struct.pack(">i", TAG_COMPOUND) + struct.pack(">i", 0)
        element_type = _type_of(items[0])
        out = struct.pack(">i", element_type) + struct.pack(">i", len(items))
        for item in items:
            out += _payload(item)
        return out
    if isinstance(value, dict):
        out = b""
        for key, item in value.items():
            out += struct.pack(">b", _type_of(item)) + _name(key) + _payload(item)
        return out + struct.pack(">b", TAG_END)
    raise TypeError(f"不支持的 NBT 值类型：{type(value)!r}")


def to_nbt(root: Dict[str, Any], root_name: str = "") -> bytes:
    """把 Python 字典序列化成 NBT 字节流（根标签为 TAG_Compound）。"""

    return struct.pack(">b", TAG_COMPOUND) + _name(root_name) + _payload(root)


def write_gzip_nbt(path: str, root: Dict[str, Any], root_name: str = "") -> None:
    """把 NBT 以 gzip 压缩形式写入文件（Minecraft 的 .mcstructure 格式）。"""

    with gzip.open(path, "wb", compresslevel=9) as handle:
        handle.write(to_nbt(root, root_name))
