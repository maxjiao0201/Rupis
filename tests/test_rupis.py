"""Rupis 解释器测试。

运行：
    python -m unittest discover -s tests -v
    或
    python tests/test_rupis.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rupis import RupisError, run_source  # noqa: E402
from rupis import exporters  # noqa: E402


def run(code: str):
    return run_source(code, "<test>")


def state_at(world, x, y, z):
    return world.get((x, y, z))


class TestBasics(unittest.TestCase):
    def test_place_redstone_wire(self):
        interp = run('dpos p[10,64,20]\nrw{rsig=15}[p + x1]')
        block = state_at(interp.world, 11, 64, 20)
        self.assertIsNotNone(block)
        self.assertEqual(block.block_id, "minecraft:redstone_wire")
        self.assertEqual(block.states, {"power": 15})

    def test_dpos_var_is_absolute(self):
        interp = run("dpos p[1,2,3]\nrw{rsig=1}[p]")
        self.assertIsNotNone(state_at(interp.world, 1, 2, 3))

    def test_abs_coord(self):
        interp = run("rw{rsig=1}[5,6,7]")
        self.assertIsNotNone(state_at(interp.world, 5, 6, 7))

    def test_offset_negative_and_multi_axis(self):
        interp = run("dpos p[10,64,20]\nrw{rsig=1}[p + x-2,y1,z0]")
        self.assertIsNotNone(state_at(interp.world, 8, 65, 20))

    def test_offset_with_variable(self):
        interp = run(
            "dpos p[0,0,0]\n"
            "let i = 3;\n"
            "rw{rsig=1}[p + xi]\n"
        )
        self.assertIsNotNone(state_at(interp.world, 3, 0, 0))

    def test_offset_variable_on_other_axis(self):
        interp = run(
            "dpos p[0,0,0]\n"
            "let i = 4;\n"
            "rw{rsig=1}[p + zi]\n"
        )
        self.assertIsNotNone(state_at(interp.world, 0, 0, 4))

    def test_len_generates_continuous_wire(self):
        interp = run("dpos p[0,0,0]\nrw{rsig=15,len=4}[p]")
        for x in range(4):
            self.assertIsNotNone(state_at(interp.world, x, 0, 0))
        self.assertEqual(len(interp.world), 4)

    def test_len_axis(self):
        interp = run("dpos p[0,0,0]\nrw{rsig=15,len=3,axis=z}[p]")
        for z in range(3):
            self.assertIsNotNone(state_at(interp.world, 0, 0, z))

    def test_no_coord_uses_origin(self):
        interp = run("rw{rsig=1}")
        self.assertIsNotNone(state_at(interp.world, 0, 0, 0))


class TestDposVars(unittest.TestCase):
    def test_multiple_dpos_vars(self):
        interp = run(
            "dpos a[1,1,1]\n"
            "dpos b[2,2,2]\n"
            "rw{rsig=1}[a]\n"
            "rw{rsig=1}[b]\n"
        )
        self.assertIsNotNone(state_at(interp.world, 1, 1, 1))
        self.assertIsNotNone(state_at(interp.world, 2, 2, 2))

    def test_dpos_var_can_be_redeclared(self):
        interp = run("dpos a[1,1,1]\ndpos a[9,9,9]\nrw{rsig=1}[a]")
        self.assertIsNotNone(state_at(interp.world, 9, 9, 9))
        self.assertIsNone(state_at(interp.world, 1, 1, 1))

    def test_undefined_dpos_var_is_error(self):
        with self.assertRaises(RupisError) as ctx:
            run("rw{rsig=1}[nosuchvar]")
        self.assertIn("dpos 变量", str(ctx.exception))

    def test_dpos_requires_a_name(self):
        with self.assertRaises(RupisError) as ctx:
            run("dpos [1,2,3]")
        self.assertIn("变量名", str(ctx.exception))


class TestDrpVars(unittest.TestCase):
    def test_drp_var_in_state_slot(self):
        interp = run("dpos p[0,0,0]\ndrp high{rsig=15}\nrw{high}[p]")
        self.assertEqual(state_at(interp.world, 0, 0, 0).states, {"power": 15})

    def test_no_state_slot_means_no_states(self):
        """没有全局 drp 了：不写状态槽就没有任何状态。"""

        interp = run("dpos p[0,0,0]\ndrp high{rsig=15}\nrw[p]")
        self.assertEqual(state_at(interp.world, 0, 0, 0).states, {})

    def test_explicit_empty_state_slot(self):
        interp = run("dpos p[0,0,0]\ndrp high{rsig=15}\nrw{}[p]")
        self.assertEqual(state_at(interp.world, 0, 0, 0).states, {})

    def test_explicit_states_win_over_drp_var(self):
        interp = run("dpos p[0,0,0]\ndrp high{rsig=15}\nrw{rsig=3}[p]")
        self.assertEqual(state_at(interp.world, 0, 0, 0).states, {"power": 3})

    def test_drp_var_can_reference_another_drp_var(self):
        interp = run(
            "dpos p[0,0,0]\n"
            "drp low{rsig=1}\n"
            "drp off{low}\n"
            "rw{off}[p]\n"
        )
        self.assertEqual(state_at(interp.world, 0, 0, 0).states, {"power": 1})

    def test_drp_var_keys_unsupported_by_element_are_ignored(self):
        interp = run("dpos p[0,0,0]\ndrp d{rsig=15,powered=true}\nrtorch{d}[p]")
        self.assertEqual(state_at(interp.world, 0, 0, 0).states, {"lit": True})

    def test_explicit_unknown_key_is_error(self):
        with self.assertRaises(RupisError) as ctx:
            run("rw{rsig=1, nosuchkey=2}[0,0,0]")
        self.assertIn("nosuchkey", str(ctx.exception))

    def test_unknown_key_error_lists_pseudo_keys_too(self):
        with self.assertRaises(RupisError) as ctx:
            run("rw{rsig=1, nosuchkey=2}[0,0,0]")
        message = str(ctx.exception)
        self.assertIn("rsig", message)
        self.assertIn("len", message)
        self.assertIn("axis", message)

    def test_unknown_drp_var_is_error(self):
        with self.assertRaises(RupisError) as ctx:
            run("rw{nosuchdrp}[0,0,0]")
        self.assertIn("drp 变量", str(ctx.exception))

    def test_drp_var_cannot_mix_with_keys(self):
        with self.assertRaises(RupisError):
            run("drp d{rsig=1}\nrw{d, rsig=2}[0,0,0]")

    def test_drp_requires_a_name(self):
        with self.assertRaises(RupisError) as ctx:
            run("drp {rsig=1}")
        self.assertIn("变量名", str(ctx.exception))

    def test_unknown_element_is_error(self):
        with self.assertRaises(RupisError):
            run("rxyz{rsig=1}[0,0,0]")


class TestElements(unittest.TestCase):
    def test_repeater(self):
        interp = run("rrep{facing=east,delay=2,locked=false}[0,0,0]")
        block = state_at(interp.world, 0, 0, 0)
        self.assertEqual(block.block_id, "minecraft:repeater")
        self.assertEqual(block.states, {"facing": "east", "delay": 2, "locked": False})

    def test_comparator(self):
        interp = run("rco{facing=south,mode=subtract,powered=true}[0,0,0]")
        block = state_at(interp.world, 0, 0, 0)
        self.assertEqual(block.block_id, "minecraft:comparator")
        self.assertEqual(block.states, {"facing": "south", "mode": "subtract", "powered": True})

    def test_observer_torch_lamp_piston(self):
        interp = run(
            "obs{facing=north}[0,0,0]\n"
            "rtorch{powered=false}[1,0,0]\n"
            "rlamp{powered=true}[2,0,0]\n"
            "piston{facing=up,extended=false}[3,0,0]\n"
            "sticky{facing=west,extended=true}[4,0,0]\n"
        )
        self.assertEqual(state_at(interp.world, 0, 0, 0).states, {"facing": "north"})
        self.assertEqual(state_at(interp.world, 1, 0, 0).states, {"lit": False})
        self.assertEqual(state_at(interp.world, 2, 0, 0).states, {"lit": True})
        self.assertEqual(state_at(interp.world, 3, 0, 0).states, {"facing": "up", "extended": False})
        self.assertEqual(state_at(interp.world, 4, 0, 0).states, {"facing": "west", "extended": True})

    def test_rbl_shortcut(self):
        interp = run("rbl stone{}[0,0,0]")
        self.assertEqual(state_at(interp.world, 0, 0, 0).block_id, "minecraft:stone")

    def test_native_block(self):
        interp = run("block minecraft:iron_block{waterlogged=false}[0,0,0]")
        block = state_at(interp.world, 0, 0, 0)
        self.assertEqual(block.block_id, "minecraft:iron_block")
        self.assertEqual(block.states, {"waterlogged": False})

    def test_rsig_range_check(self):
        with self.assertRaises(RupisError):
            run("rw{rsig=16}[0,0,0]")

    def test_delay_range_check(self):
        with self.assertRaises(RupisError):
            run("rrep{delay=9}[0,0,0]")


class TestStructures(unittest.TestCase):
    def test_struct_uses_local_coordinates(self):
        interp = run(
            "dpos p[100,64,200]\n"
            "strudef unit(){locked=false}:{\n"
            "  rrep{facing=east,delay=1,locked=locked}[0,0,0]\n"
            "  rw{rsig=15}[1,0,0]\n"
            "}\n"
            "stru unit(){}[p + x5]\n"
        )
        self.assertIsNotNone(state_at(interp.world, 105, 64, 200))
        self.assertIsNotNone(state_at(interp.world, 106, 64, 200))

    def test_struct_params_and_defaults(self):
        interp = run(
            "dpos p[0,0,0]\n"
            "strudef rep_unit(facing, delay){locked=false}:{\n"
            "  rrep{facing=facing,delay=delay,locked=locked}[0,0,0]\n"
            "}\n"
            "stru rep_unit(east,2){}[p]\n"
        )
        block = state_at(interp.world, 0, 0, 0)
        self.assertEqual(block.states, {"facing": "east", "delay": 2, "locked": False})

    def test_struct_override_states(self):
        interp = run(
            "dpos p[0,0,0]\n"
            "strudef rep_unit(facing){locked=false,delay=1}:{\n"
            "  rrep{facing=facing,delay=delay,locked=locked}[0,0,0]\n"
            "}\n"
            "stru rep_unit(north){delay=4}[p]\n"
        )
        block = state_at(interp.world, 0, 0, 0)
        self.assertEqual(block.states, {"facing": "north", "delay": 4, "locked": False})

    def test_struct_default_fills_missing_keys(self):
        interp = run(
            "dpos p[0,0,0]\n"
            "strudef rep_unit(facing){delay=3}:{\n"
            "  rrep{facing=facing}[0,0,0]\n"
            "}\n"
            "stru rep_unit(north){}[p]\n"
        )
        block = state_at(interp.world, 0, 0, 0)
        self.assertEqual(block.states, {"facing": "north", "delay": 3})

    def test_struct_default_can_reference_drp_var(self):
        interp = run(
            "dpos p[0,0,0]\n"
            "drp tmpl{locked=false}\n"
            "strudef rep_unit(facing){tmpl}:{\n"
            "  rrep{facing=facing,locked=locked}[0,0,0]\n"
            "}\n"
            "stru rep_unit(east){}[p]\n"
        )
        block = state_at(interp.world, 0, 0, 0)
        self.assertEqual(block.states, {"facing": "east", "locked": False})

    def test_struct_nested_call(self):
        interp = run(
            "dpos p[0,0,0]\n"
            "strudef cell(){locked=false}:{ rrep{facing=east,delay=1,locked=locked}[0,0,0] }\n"
            "strudef row(){ }:{\n"
            "  for i = (0 to 2):{ stru cell(){}[p + xi] }\n"
            "}\n"
            "stru row(){}[p]\n"
        )
        for x in range(3):
            self.assertIsNotNone(state_at(interp.world, x, 0, 0))

    def test_unknown_struct_is_error(self):
        with self.assertRaises(RupisError):
            run("stru nosuch(){}[0,0,0]")

    def test_wrong_argument_count_is_error(self):
        with self.assertRaises(RupisError):
            run("strudef s(a){}:{ rw{rsig=1}[0,0,0] }\nstru s(){}[0,0,0]")


class TestControlFlow(unittest.TestCase):
    def test_if_else(self):
        interp = run(
            "dpos p[0,0,0]\n"
            "if(5>2){ rw{rsig=1}[p] } else { rw{rsig=2}[p] }\n"
        )
        self.assertEqual(state_at(interp.world, 0, 0, 0).states, {"power": 1})

    def test_if_else_branch(self):
        interp = run(
            "dpos p[0,0,0]\n"
            "if(1>2){ rw{rsig=1}[p] } else { rw{rsig=2}[p] }\n"
        )
        self.assertEqual(state_at(interp.world, 0, 0, 0).states, {"power": 2})

    def test_for_inclusive(self):
        interp = run(
            "dpos p[0,0,0]\n"
            "for i = (0 to 3){ rw{rsig=1}[p + xi] }\n"
        )
        self.assertEqual(len(interp.world), 4)

    def test_for_with_expression_end(self):
        interp = run(
            "dpos p[0,0,0]\n"
            "let n = 3;\n"
            "for i = (0 to n-1){ rw{rsig=1}[p + xi] }\n"
        )
        self.assertEqual(len(interp.world), 3)

    def test_while(self):
        interp = run(
            "dpos p[0,0,0]\n"
            "let i = 0;\n"
            "while(i < 3){ rw{rsig=1}[p + xi] i = i + 1; }\n"
        )
        self.assertEqual(len(interp.world), 3)

    def test_logical_operators(self):
        interp = run(
            "dpos p[0,0,0]\n"
            "if(true && 3>1){ rw{rsig=1}[p] }\n"
            "if(false || 2==2){ rw{rsig=2}[p + x1] }\n"
        )
        self.assertEqual(len(interp.world), 2)


class TestFunctions(unittest.TestCase):
    def test_function_with_return(self):
        interp = run(
            "def add(a, b){ return a + b; }\n"
            "dpos p[0,0,0]\n"
            "if(add(2,3)==5){ rw{rsig=5}[p] }\n"
        )
        self.assertEqual(state_at(interp.world, 0, 0, 0).states, {"power": 5})

    def test_function_can_place_blocks(self):
        interp = run(
            "def line(n){ for i = (0 to n-1){ rw{rsig=1}[p + xi] } return 0; }\n"
            "dpos p[0,0,0]\n"
            "line(4)\n"
        )
        self.assertEqual(len(interp.world), 4)

    def test_unknown_function_is_error(self):
        with self.assertRaises(RupisError):
            run("nosuchfunc(1)")

    def test_undefined_variable_is_error(self):
        with self.assertRaises(RupisError):
            run("let x = undefinedvar;")


class TestErrors(unittest.TestCase):
    def test_error_has_line_and_column(self):
        with self.assertRaises(RupisError) as ctx:
            run("rw{rsig=1}[0,0,0]\nnosuchcmd\n")
        self.assertEqual(ctx.exception.line, 2)

    def test_error_renders_snippet(self):
        with self.assertRaises(RupisError) as ctx:
            run("rw{rsig=1}[0,0,0]\nrxyz{}[0,0,0]\n")
        rendered = ctx.exception.render()
        self.assertIn("rxyz", rendered)
        self.assertIn("^", rendered)

    def test_state_error_points_at_the_key(self):
        with self.assertRaises(RupisError) as ctx:
            run("rco{facing=sideways}[0,0,0]")
        self.assertEqual(ctx.exception.line, 1)
        self.assertEqual(ctx.exception.col, 5)  # 指向 facing 这个键
        self.assertIn("north", str(ctx.exception))

    def test_value_range_error_points_at_the_key(self):
        with self.assertRaises(RupisError) as ctx:
            run("rrep{facing=east, delay=7}[0,0,0]")
        self.assertEqual(ctx.exception.col, 19)  # 指向 delay 这个键


class TestExporters(unittest.TestCase):
    def test_commands_export(self):
        interp = run("dpos p[1,2,3]\nrw{rsig=15}[p]")
        text = exporters.export_commands(interp.world)
        self.assertIn("/setblock 1 2 3 minecraft:redstone_wire[power=15]", text)

    def test_json_export(self):
        import json as _json
        interp = run("dpos p[1,2,3]\nrw{rsig=15}[p]")
        data = _json.loads(exporters.export_json(interp.world))
        self.assertEqual(data["size"], [1, 1, 1])
        self.assertEqual(data["blocks"][0]["id"], "minecraft:redstone_wire")

    def test_structure_export(self):
        import gzip
        import os
        import tempfile
        interp = run("dpos p[1,2,3]\nrw{rsig=15}[p]\nrrep{facing=east}[2,2,3]")
        path = os.path.join(tempfile.gettempdir(), "rupis_test.mcstructure")
        exporters.export_structure(path, interp.world)
        with gzip.open(path, "rb") as handle:
            data = handle.read()
        self.assertTrue(data.startswith(b"\x0a\x00\x00"))  # TAG_Compound
        os.remove(path)

    def test_structure_round_trip(self):
        """回读 .mcstructure，确认方块位置与调色板索引都对得上。"""

        import gzip
        import os
        import tempfile
        interp = run(
            "dpos p[10,20,30]\n"
            "rw{rsig=15}[p]\n"
            "rrep{facing=east,delay=2}[p + x1]\n"
        )
        path = os.path.join(tempfile.gettempdir(), "rupis_test_rt.mcstructure")
        exporters.export_structure(path, interp.world)
        with gzip.open(path, "rb") as handle:
            root = read_nbt(handle.read())
        os.remove(path)

        self.assertEqual(root["format_version"], 1)
        # 局部原点固定为 (0,0,0)，加载时结构的最小角落在放置坐标上
        self.assertEqual(root["structure"]["structure_world_origin"], [0, 0, 0])
        size_x, size_y, size_z = root["size"]
        self.assertEqual((size_x, size_y, size_z), (2, 1, 1))

        palette = root["structure"]["palette"]["default"]["block_palette"]
        indices = root["structure"]["block_indices"]
        self.assertEqual(palette[0]["name"], "minecraft:air")  # 空位必须是空气
        self.assertEqual(len(indices), size_x * size_y * size_z)

        def entry(x, y, z):
            index = x + y * size_x + z * size_x * size_y
            return palette[indices[index]]

        self.assertEqual(entry(0, 0, 0)["name"], "minecraft:redstone_wire")
        self.assertEqual(entry(0, 0, 0)["states"], {"power": "15"})
        self.assertEqual(entry(1, 0, 0)["name"], "minecraft:repeater")
        self.assertEqual(entry(1, 0, 0)["states"], {"delay": "2", "facing": "east"})


def read_nbt(data: bytes):
    """极简 NBT 读取器（只用于测试校验）。"""

    import struct

    def read_value(tag_type, pos):
        if tag_type == 1:
            return struct.unpack(">b", data[pos:pos + 1])[0], pos + 1
        if tag_type == 3:
            return struct.unpack(">i", data[pos:pos + 4])[0], pos + 4
        if tag_type == 8:
            length = struct.unpack(">H", data[pos:pos + 2])[0]
            pos += 2
            return data[pos:pos + length].decode("utf-8"), pos + length
        if tag_type == 9:
            element_type = struct.unpack(">i", data[pos:pos + 4])[0]
            pos += 4
            count = struct.unpack(">i", data[pos:pos + 4])[0]
            pos += 4
            items = []
            for _ in range(count):
                item, pos = read_value(element_type, pos)
                items.append(item)
            return items, pos
        if tag_type == 10:
            out = {}
            while True:
                child_type = data[pos]
                pos += 1
                if child_type == 0:
                    break
                length = struct.unpack(">H", data[pos:pos + 2])[0]
                pos += 2
                name = data[pos:pos + length].decode("utf-8")
                pos += length
                value, pos = read_value(child_type, pos)
                out[name] = value
            return out, pos
        raise AssertionError(f"未处理的 NBT 标签类型 {tag_type}")

    assert data[0] == 10, "根标签必须是 TAG_Compound"
    name_length = struct.unpack(">H", data[1:3])[0]
    root, _ = read_value(10, 3 + name_length)
    return root


class TestLib(unittest.TestCase):
    """lib 语句：导入另一个 .rpi 脚本。"""

    UTIL = (
        "def helper(n):{\n"
        "    return n * 2\n"
        "}\n"
        "\n"
        "def twice(n):{\n"
        "    return helper(n)\n"
        "}\n"
        "\n"
        "strudef box(v):{\n"
        "    rw{rsig=v}[0,0,0]\n"
        "}\n"
        "\n"
        "rw{rsig=99}[50,50,50]\n"
    )

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)
        self.write("util.rpi", self.UTIL)

    def write(self, name, text):
        path = os.path.join(self._tmp, *name.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def run_main(self, code, name="main.rpi", lib_paths=None):
        path = os.path.join(self._tmp, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(code)
        return run_source(code, path, lib_paths=lib_paths)

    # ------------------------------------------------------------ 导入
    def test_import_and_call_by_name(self):
        """导入进来的函数直接按原名用。"""
        interp = self.run_main("lib util\nrw{rsig=helper(3)}[0,0,0]")
        block = state_at(interp.world, 0, 0, 0)
        self.assertIsNotNone(block)
        self.assertEqual(block.states["power"], 6)

    def test_import_and_call_by_namespace(self):
        """也能用 脚本名.函数(...) 调。"""
        interp = self.run_main("lib util\nrw{rsig=util.helper(3)}[0,0,0]")
        block = state_at(interp.world, 0, 0, 0)
        self.assertIsNotNone(block)
        self.assertEqual(block.states["power"], 6)

    def test_import_with_alias(self):
        interp = self.run_main("lib util as u\nrw{rsig=u.helper(3)}[0,0,0]")
        block = state_at(interp.world, 0, 0, 0)
        self.assertIsNotNone(block)
        self.assertEqual(block.states["power"], 6)

    def test_alias_keeps_direct_names(self):
        """写了 as 也照样能直接按原名调。"""
        interp = self.run_main("lib util as u\nrw{rsig=helper(3)}[0,0,0]")
        block = state_at(interp.world, 0, 0, 0)
        self.assertIsNotNone(block)
        self.assertEqual(block.states["power"], 6)

    def test_structure_by_namespace(self):
        interp = self.run_main("lib util\nstru util.box(15)[1,0,0]")
        block = state_at(interp.world, 1, 0, 0)
        self.assertIsNotNone(block)
        self.assertEqual(block.states["power"], 15)

    def test_structure_by_name(self):
        interp = self.run_main("lib util\nstru box(13)[2,0,0]")
        block = state_at(interp.world, 2, 0, 0)
        self.assertIsNotNone(block)
        self.assertEqual(block.states["power"], 13)

    def test_function_in_module_can_call_sibling(self):
        """导入的脚本里，函数之间能互相调用。"""
        interp = self.run_main("lib util\nrw{rsig=twice(5)}[0,0,0]")
        block = state_at(interp.world, 0, 0, 0)
        self.assertIsNotNone(block)
        self.assertEqual(block.states["power"], 10)

    def test_top_level_placements_are_not_executed(self):
        """被导入的脚本只是个库，顶层放的方块不执行。"""
        interp = self.run_main("lib util\nrw{rsig=1}[0,0,0]")
        self.assertIsNone(state_at(interp.world, 50, 50, 50))

    def test_import_from_subdirectory(self):
        self.write("sub/deep.rpi", "def helper(n):{\n    return n + 1\n}\n")
        interp = self.run_main("lib sub/deep\nrw{rsig=deep.helper(4)}[0,0,0]")
        block = state_at(interp.world, 0, 0, 0)
        self.assertIsNotNone(block)
        self.assertEqual(block.states["power"], 5)

    def test_import_from_lib_paths(self):
        """当前目录找不到时，去 lib_paths 里找。"""
        other = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, other, ignore_errors=True)
        with open(os.path.join(other, "far.rpi"), "w", encoding="utf-8") as handle:
            handle.write("def helper(n):{\n    return n * 3\n}\n")
        interp = self.run_main("lib far\nrw{rsig=far.helper(2)}[0,0,0]",
                              lib_paths=[other])
        block = state_at(interp.world, 0, 0, 0)
        self.assertIsNotNone(block)
        self.assertEqual(block.states["power"], 6)

    # ------------------------------------------------------------ 报错
    def test_script_not_found(self):
        with self.assertRaises(RupisError) as ctx:
            self.run_main("lib nosuchscript_xyz")
        self.assertIn("找不到脚本", ctx.exception.message)

    def test_missing_member(self):
        with self.assertRaises(RupisError) as ctx:
            self.run_main("lib util\nlet a = util.nosuchfunction(1)")
        self.assertIn("没有", ctx.exception.message)

    def test_structure_needs_stru(self):
        with self.assertRaises(RupisError) as ctx:
            self.run_main("lib util\nlet a = util.box")
        self.assertIn("stru", ctx.exception.message)

    def test_unknown_module_in_stru(self):
        with self.assertRaises(RupisError) as ctx:
            self.run_main("stru nosuch.box(1)[0,0,0]")
        self.assertIn("未定义的模块", ctx.exception.message)

    def test_wrong_argument_count(self):
        with self.assertRaises(RupisError) as ctx:
            self.run_main("lib util\nrw{rsig=helper(1,2)}[0,0,0]")
        self.assertIn("参数", ctx.exception.message)

    def test_broken_imported_script(self):
        self.write("bad.rpi", "def f(:{\n")
        with self.assertRaises(RupisError) as ctx:
            self.run_main("lib bad")
        self.assertIn("失败", ctx.exception.message)

    def test_lib_needs_a_script_name(self):
        with self.assertRaises(RupisError):
            run("lib")

    def test_lib_inside_function_is_local(self):
        """函数里 lib 的命名空间是局部的。"""
        with self.assertRaises(RupisError) as ctx:
            self.run_main("def f(){\n  lib util\n  return 0\n}\n"
                          "rw{rsig=util.helper(1)}[0,0,0]")
        self.assertIn("未定义的变量", ctx.exception.message)

    def test_rupis_function_rejects_keyword_arguments(self):
        with self.assertRaises(RupisError) as ctx:
            run("def f(a){ return a }\nlet x = f(a=1)")
        self.assertIn("关键字参数", ctx.exception.message)

    def test_structure_rejects_keyword_arguments(self):
        with self.assertRaises(RupisError) as ctx:
            run("strudef s(a):{rw{rsig=1}[a]}\nstru s(a=1)")
        self.assertIn("关键字参数", ctx.exception.message)


class TestExamples(unittest.TestCase):
    """examples/ 里的示例脚本必须都能跑通。"""

    EXAMPLES = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "examples")

    def run_example(self, name: str):
        path = os.path.join(self.EXAMPLES, name)
        with open(path, encoding="utf-8") as handle:
            return run_source(handle.read(), path)

    def test_demo_example_runs(self):
        interp = self.run_example("demo.rpi")
        self.assertGreater(len(interp.world), 0)

    def test_lib_demo_example_runs(self):
        interp = self.run_example("lib_demo.rpi")
        # 导入的脚本里的结构：stru rep_unit(east,2){}[base]
        repeater = state_at(interp.world, 100, 64, 200)
        self.assertIsNotNone(repeater)
        self.assertEqual(repeater.block_id, "minecraft:repeater")
        # 导入的脚本里的函数：rw{rsig=decay(14)}[base + x6]
        self.assertEqual(state_at(interp.world, 106, 64, 200).states["power"], 13)
        # 子目录里的脚本：rw{rsig=subkit.boost(6)}[base + x10]
        self.assertEqual(state_at(interp.world, 110, 64, 200).states["power"], 7)

    def test_imported_script_is_not_executed(self):
        """导入的库脚本顶层的方块不该出现在世界里。"""
        interp = self.run_example("lib_demo.rpi")
        # kit.rpi 里没有任何顶层方块；这里确认 world 里没有多出来的东西
        self.assertEqual(len(interp.world), 11)


if __name__ == "__main__":
    unittest.main(verbosity=2)
