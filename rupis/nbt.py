"""极简 NBT 写入器（只实现导出 .mcstructure 需要的标签类型）。

支持：TAG_Byte / Short / Int / Long / Float / Double / String /
      List / Compound / Int_Array。

NBT 是 Minecraft 用来存方块状态的二进制格式：整棵树由「标签」组成，
每个标签 = 1 字节类型编号 + 2 字节名字长度 + 名字 + 负载。
所有整数都用大端序（Minecraft 的历史原因）。
"""

from __future__ import annotations

import gzip
import struct
from typing import Any, Dict, List, Sequence

# 标签类型编号，写文件时按标准单字节传出，不能自创
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
    """标记为 TAG_Int_Array 的整数数组。

    普通 list 会被写成 TAG_List，要写成 TAG_Int_Array 就得先包一层。
    """

    def __init__(self, values: Sequence[int]) -> None:
        self.values = list(values)


def _type_of(value: Any) -> int:
    """判断一个 Python 值该写成哪种 NBT 标签。

    规则：
        bool         → TAG_Byte（必须先判 bool，它是 int 的子类）；
        IntArray     → TAG_Int_Array；
        int          → TAG_Int；
        float        → TAG_Double；
        str          → TAG_String；
        list / tuple → TAG_List；
        dict         → TAG_Compound。
    """

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
    """把标签名编码成 NBT 的「2 字节长度 + UTF-8 字节」形式。"""

    raw = text.encode("utf-8")
    return struct.pack(">H", len(raw)) + raw


def _payload(value: Any) -> bytes:
    """写入标签内容（不含标签类型字节）。

    整棵树的顺序是：类型编号 → 名字 → 负载。
    """

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
            # 空列表也得写元素类型，Minecraft 才认；这里用最通用的 TAG_Compound
            return struct.pack(">i", TAG_COMPOUND) + struct.pack(">i", 0)
        # 列表里所有元素必须是同一种类型，类型取第一个元素的
        element_type = _type_of(items[0])
        out = struct.pack(">i", element_type) + struct.pack(">i", len(items))
        for item in items:
            out += _payload(item)
        return out
    if isinstance(value, dict):
        out = b""
        for key, item in value.items():
            out += struct.pack(">b", _type_of(item)) + _name(key) + _payload(item)
        # TAG_End 收尾，表示这个复合标签到此结束
        return out + struct.pack(">b", TAG_END)
    raise TypeError(f"不支持的 NBT 值类型：{type(value)!r}")


def to_nbt(root: Dict[str, Any], root_name: str = "") -> bytes:
    """把 Python 字典序列化成 NBT 字节流（根标签为 TAG_Compound）。

    根标签也要带名字，Minecraft 的 .mcstructure 用的是空串。
    """

    return struct.pack(">b", TAG_COMPOUND) + _name(root_name) + _payload(root)


def write_gzip_nbt(path: str, root: Dict[str, Any], root_name: str = "") -> None:
    """把 NBT 以 gzip 压缩形式写入文件（Minecraft 的 .mcstructure 格式）。

    .mcstructure 就是 gzip 压缩过的 NBT，压缩等级取 9 让文件尽量小。
    """

    with gzip.open(path, "wb", compresslevel=9) as handle:
        handle.write(to_nbt(root, root_name))
