"""Rupis 解释器的单元测试。

覆盖 Rupis 脚本从源码到方块世界的完整链路：坐标与状态变量、红石元件与状态键、
结构模板、控制流、函数、错误定位，以及三种导出格式。

运行：
    python -m unittest discover -s tests -v
    或
    python tests/test_rupis.py

文件按语言特性分成若干测试类：
    TestBasics       —— 基本放置指令、绝对坐标与相对偏移。
    TestDposVars     —— dpos 坐标变量的声明、覆盖与错误处理。
    TestDrpVars      —— drp 状态变量的定义、引用、继承与优先级。
    TestElements     —— 红石元件及其状态键的取值与范围校验。
    TestStructures   —— strudef / stru 结构模板的参数、默认值与嵌套。
    TestControlFlow  —— if / for / while 与逻辑运算符。
    TestFunctions    —— def 函数的定义、调用与返回值。
    TestErrors       —— 报错信息里的行列定位与源码片段渲染。
    TestExporters    —— /setblock 命令、JSON 与 .mcstructure 三种导出。
    TestLib          —— lib 导入别的 .rpi 脚本并调用它的成员。
    TestExamples     —— examples/ 里的示例脚本必须能跑通。
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
    """执行一段 Rupis 源码，返回解释器；文件名统一叫 "<test>"。"""

    return run_source(code, "<test>")


def state_at(world, x, y, z):
    """按坐标从世界里取方块，没放过的位置返回 None。"""

    return world.get((x, y, z))


class TestBasics(unittest.TestCase):
    """放置指令与坐标：绝对坐标、相对偏移、len 连续铺设。"""

    def test_place_redstone_wire(self):
        """rw 放置红石粉，rsig=15 对应元件状态 power=15。"""

        interp = run('dpos p[10,64,20]\nrw{rsig=15}[p + x1]')
        block = state_at(interp.world, 11, 64, 20)
        self.assertIsNotNone(block)
        self.assertEqual(block.block_id, "minecraft:redstone_wire")
        self.assertEqual(block.states, {"power": 15})

    def test_dpos_var_is_absolute(self):
        """坐标槽里写 dpos 变量时按绝对坐标算，不会再叠加偏移量。"""

        interp = run("dpos p[1,2,3]\nrw{rsig=1}[p]")
        self.assertIsNotNone(state_at(interp.world, 1, 2, 3))

    def test_abs_coord(self):
        """坐标槽里直接写三个数字，就是世界的绝对坐标。"""

        interp = run("rw{rsig=1}[5,6,7]")
        self.assertIsNotNone(state_at(interp.world, 5, 6, 7))

    def test_offset_negative_and_multi_axis(self):
        """相对偏移支持负数，而且 x/y/z 三个轴可以一次写全。"""

        interp = run("dpos p[10,64,20]\nrw{rsig=1}[p + x-2,y1,z0]")
        self.assertIsNotNone(state_at(interp.world, 8, 65, 20))

    def test_offset_with_variable(self):
        """偏移量可以写成变量，xi 表示沿 x 轴偏移 i 格。"""

        interp = run(
            "dpos p[0,0,0]\n"
            "let i = 3;\n"
            "rw{rsig=1}[p + xi]\n"
        )
        self.assertIsNotNone(state_at(interp.world, 3, 0, 0))

    def test_offset_variable_on_other_axis(self):
        """偏移变量跟在哪一轴就作用在哪一轴，zi 只挪动 z。"""

        interp = run(
            "dpos p[0,0,0]\n"
            "let i = 4;\n"
            "rw{rsig=1}[p + zi]\n"
        )
        self.assertIsNotNone(state_at(interp.world, 0, 0, 4))

    def test_len_generates_continuous_wire(self):
        """len=N 沿默认的 x 轴连着铺 N 格红石粉，世界里正好 N 个方块。"""

        interp = run("dpos p[0,0,0]\nrw{rsig=15,len=4}[p]")
        for x in range(4):
            self.assertIsNotNone(state_at(interp.world, x, 0, 0))
        self.assertEqual(len(interp.world), 4)

    def test_len_axis(self):
        """axis=z 让 len 改沿 z 轴铺设，而不是默认的 x 轴。"""

        interp = run("dpos p[0,0,0]\nrw{rsig=15,len=3,axis=z}[p]")
        for z in range(3):
            self.assertIsNotNone(state_at(interp.world, 0, 0, z))

    def test_no_coord_uses_origin(self):
        """省略坐标槽时默认放在原点 (0,0,0)。"""

        interp = run("rw{rsig=1}")
        self.assertIsNotNone(state_at(interp.world, 0, 0, 0))


class TestDposVars(unittest.TestCase):
    """dpos 坐标变量：声明、覆盖、引用与错误提示。"""

    def test_multiple_dpos_vars(self):
        """多个 dpos 变量可以同时存在，并各自被引用。"""

        interp = run(
            "dpos a[1,1,1]\n"
            "dpos b[2,2,2]\n"
            "rw{rsig=1}[a]\n"
            "rw{rsig=1}[b]\n"
        )
        self.assertIsNotNone(state_at(interp.world, 1, 1, 1))
        self.assertIsNotNone(state_at(interp.world, 2, 2, 2))

    def test_dpos_var_can_be_redeclared(self):
        """同名 dpos 重新声明后指向新坐标，旧坐标不再有效。"""

        interp = run("dpos a[1,1,1]\ndpos a[9,9,9]\nrw{rsig=1}[a]")
        self.assertIsNotNone(state_at(interp.world, 9, 9, 9))
        self.assertIsNone(state_at(interp.world, 1, 1, 1))

    def test_undefined_dpos_var_is_error(self):
        """引用没声明过的 dpos 变量要报错，并说清是 dpos 变量。"""

        with self.assertRaises(RupisError) as ctx:
            run("rw{rsig=1}[nosuchvar]")
        self.assertIn("dpos 变量", str(ctx.exception))

    def test_dpos_requires_a_name(self):
        """dpos 少了变量名要报错，提示里要出现"变量名"。"""

        with self.assertRaises(RupisError) as ctx:
            run("dpos [1,2,3]")
        self.assertIn("变量名", str(ctx.exception))


class TestDrpVars(unittest.TestCase):
    """drp 状态变量：状态槽引用、显式覆盖与未知键报错。"""

    def test_drp_var_in_state_slot(self):
        """状态槽里写 drp 变量名，元件就带上该变量定义的状态。"""

        interp = run("dpos p[0,0,0]\ndrp high{rsig=15}\nrw{high}[p]")
        self.assertEqual(state_at(interp.world, 0, 0, 0).states, {"power": 15})

    def test_no_state_slot_means_no_states(self):
        """没有全局 drp 了：不写状态槽就没有任何状态。"""

        interp = run("dpos p[0,0,0]\ndrp high{rsig=15}\nrw[p]")
        self.assertEqual(state_at(interp.world, 0, 0, 0).states, {})

    def test_explicit_empty_state_slot(self):
        """写空的 {} 表示显式不要任何状态，会压过 drp 变量。"""

        interp = run("dpos p[0,0,0]\ndrp high{rsig=15}\nrw{}[p]")
        self.assertEqual(state_at(interp.world, 0, 0, 0).states, {})

    def test_explicit_states_win_over_drp_var(self):
        """显式写出的状态键优先级高于 drp 变量里的同名键。"""

        interp = run("dpos p[0,0,0]\ndrp high{rsig=15}\nrw{rsig=3}[p]")
        self.assertEqual(state_at(interp.world, 0, 0, 0).states, {"power": 3})

    def test_drp_var_can_reference_another_drp_var(self):
        """drp 变量可以引用另一个 drp 变量，状态会被合并继承。"""

        interp = run(
            "dpos p[0,0,0]\n"
            "drp low{rsig=1}\n"
            "drp off{low}\n"
            "rw{off}[p]\n"
        )
        # off 自己一个键都没写，power=1 是从 low 继承来的
        self.assertEqual(state_at(interp.world, 0, 0, 0).states, {"power": 1})

    def test_drp_var_keys_unsupported_by_element_are_ignored(self):
        """drp 里该元件不支持的键被安静忽略，不当作错误。"""

        interp = run("dpos p[0,0,0]\ndrp d{rsig=15,powered=true}\nrtorch{d}[p]")
        self.assertEqual(state_at(interp.world, 0, 0, 0).states, {"lit": True})

    def test_explicit_unknown_key_is_error(self):
        """显式写出的状态键不存在时要报错，并在消息里点名该键。"""

        with self.assertRaises(RupisError) as ctx:
            run("rw{rsig=1, nosuchkey=2}[0,0,0]")
        self.assertIn("nosuchkey", str(ctx.exception))

    def test_unknown_key_error_lists_pseudo_keys_too(self):
        """未知键的报错还要顺带列出 rsig / len / axis 这些伪键。"""

        with self.assertRaises(RupisError) as ctx:
            run("rw{rsig=1, nosuchkey=2}[0,0,0]")
        message = str(ctx.exception)
        # rsig / len / axis 是元件之外的伪键，也得列进提示里，否则用户不知道往哪写
        self.assertIn("rsig", message)
        self.assertIn("len", message)
        self.assertIn("axis", message)

    def test_unknown_drp_var_is_error(self):
        """状态槽里引用没定义过的 drp 变量要报错。"""

        with self.assertRaises(RupisError) as ctx:
            run("rw{nosuchdrp}[0,0,0]")
        self.assertIn("drp 变量", str(ctx.exception))

    def test_drp_var_cannot_mix_with_keys(self):
        """状态槽里不能既写 drp 变量名又写状态键。"""

        with self.assertRaises(RupisError):
            run("drp d{rsig=1}\nrw{d, rsig=2}[0,0,0]")

    def test_drp_requires_a_name(self):
        """drp 少了变量名要报错。"""

        with self.assertRaises(RupisError) as ctx:
            run("drp {rsig=1}")
        self.assertIn("变量名", str(ctx.exception))

    def test_unknown_element_is_error(self):
        """不存在的元件名要报错，不能被悄悄跳过。"""

        with self.assertRaises(RupisError):
            run("rxyz{rsig=1}[0,0,0]")


class TestElements(unittest.TestCase):
    """各类红石元件及其状态键的取值、默认值与范围校验。"""

    def test_repeater(self):
        """中继器的 facing / delay / locked 三个状态键都能正确写入。"""

        interp = run("rrep{facing=east,delay=2,locked=false}[0,0,0]")
        block = state_at(interp.world, 0, 0, 0)
        self.assertEqual(block.block_id, "minecraft:repeater")
        self.assertEqual(block.states, {"facing": "east", "delay": 2, "locked": False})

    def test_comparator(self):
        """比较器的 facing / mode / powered 三个状态键都能正确写入。"""

        interp = run("rco{facing=south,mode=subtract,powered=true}[0,0,0]")
        block = state_at(interp.world, 0, 0, 0)
        self.assertEqual(block.block_id, "minecraft:comparator")
        self.assertEqual(block.states, {"facing": "south", "mode": "subtract", "powered": True})

    def test_observer_torch_lamp_piston(self):
        """观察者、火把、红石灯、活塞、黏性活塞各自的键名映射都正确。"""

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
        """rbl 是"红石方块"元件的简写形式。"""

        interp = run("rbl stone{}[0,0,0]")
        self.assertEqual(state_at(interp.world, 0, 0, 0).block_id, "minecraft:stone")

    def test_native_block(self):
        """block 可以直接放原版方块，并带上它自己的状态键。"""

        interp = run("block minecraft:iron_block{waterlogged=false}[0,0,0]")
        block = state_at(interp.world, 0, 0, 0)
        self.assertEqual(block.block_id, "minecraft:iron_block")
        self.assertEqual(block.states, {"waterlogged": False})

    def test_rsig_range_check(self):
        """rsig 超出 0-15 的合法范围要报错。"""

        with self.assertRaises(RupisError):
            run("rw{rsig=16}[0,0,0]")

    def test_delay_range_check(self):
        """中继器 delay 超出 0-4 的合法范围要报错。"""

        with self.assertRaises(RupisError):
            run("rrep{delay=9}[0,0,0]")


class TestStructures(unittest.TestCase):
    """结构模板：strudef 定义、stru 调用、参数与默认值的合并规则。"""

    def test_struct_uses_local_coordinates(self):
        """模板内部用局部坐标放置，整体按调用点平移。"""

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
        """stru 调用时的实参按位置绑定到形参，没给的用默认值补上。"""

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
        """调用时显式写出的状态键覆盖模板里的默认值。"""

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
        """模板默认值会补齐调用时没写到的状态键。"""

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
        """模板的默认值也可以引用 drp 变量。"""

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
        """结构模板的体内可以再调用别的结构模板。"""

        interp = run(
            "dpos p[0,0,0]\n"
            "strudef cell(){locked=false}:{ rrep{facing=east,delay=1,locked=locked}[0,0,0] }\n"
            "strudef row(){ }:{\n"
            "  for i = (0 to 2):{ stru cell(){}[p + xi] }\n"
            "}\n"
            "stru row(){}[p]\n"
        )
        # row 里循环三次调用 cell，所以 x=0/1/2 各有一个中继器
        for x in range(3):
            self.assertIsNotNone(state_at(interp.world, x, 0, 0))

    def test_unknown_struct_is_error(self):
        """调用没定义过的结构模板要报错。"""

        with self.assertRaises(RupisError):
            run("stru nosuch(){}[0,0,0]")

    def test_wrong_argument_count_is_error(self):
        """实参个数和形参个数对不上要报错。"""

        with self.assertRaises(RupisError):
            run("strudef s(a){}:{ rw{rsig=1}[0,0,0] }\nstru s(){}[0,0,0]")


class TestControlFlow(unittest.TestCase):
    """条件分支、循环与逻辑运算符的行为。"""

    def test_if_else(self):
        """条件为真时执行 if 分支。"""

        interp = run(
            "dpos p[0,0,0]\n"
            "if(5>2){ rw{rsig=1}[p] } else { rw{rsig=2}[p] }\n"
        )
        self.assertEqual(state_at(interp.world, 0, 0, 0).states, {"power": 1})

    def test_if_else_branch(self):
        """条件为假时执行 else 分支。"""

        interp = run(
            "dpos p[0,0,0]\n"
            "if(1>2){ rw{rsig=1}[p] } else { rw{rsig=2}[p] }\n"
        )
        self.assertEqual(state_at(interp.world, 0, 0, 0).states, {"power": 2})

    def test_for_inclusive(self):
        """for 的区间两端都算上，(0 to 3) 一共跑四轮。"""

        interp = run(
            "dpos p[0,0,0]\n"
            "for i = (0 to 3){ rw{rsig=1}[p + xi] }\n"
        )
        # 如果两端不含，len 就会是 3，这里正好卡住"闭区间"这个语义
        self.assertEqual(len(interp.world), 4)

    def test_for_with_expression_end(self):
        """for 的上界可以写成表达式，n-1 让循环少跑一轮。"""

        interp = run(
            "dpos p[0,0,0]\n"
            "let n = 3;\n"
            "for i = (0 to n-1){ rw{rsig=1}[p + xi] }\n"
        )
        self.assertEqual(len(interp.world), 3)

    def test_while(self):
        """while 按条件重复执行，直到条件不再成立。"""

        interp = run(
            "dpos p[0,0,0]\n"
            "let i = 0;\n"
            "while(i < 3){ rw{rsig=1}[p + xi] i = i + 1; }\n"
        )
        self.assertEqual(len(interp.world), 3)

    def test_logical_operators(self):
        """&& 与 || 都能正确判断，并驱动不同的分支。"""

        interp = run(
            "dpos p[0,0,0]\n"
            "if(true && 3>1){ rw{rsig=1}[p] }\n"
            "if(false || 2==2){ rw{rsig=2}[p + x1] }\n"
        )
        self.assertEqual(len(interp.world), 2)


class TestFunctions(unittest.TestCase):
    """def 函数的定义、调用、返回值与未定义符号的报错。"""

    def test_function_with_return(self):
        """函数可以用 return 返回计算结果。"""

        interp = run(
            "def add(a, b){ return a + b; }\n"
            "dpos p[0,0,0]\n"
            "if(add(2,3)==5){ rw{rsig=5}[p] }\n"
        )
        self.assertEqual(state_at(interp.world, 0, 0, 0).states, {"power": 5})

    def test_function_can_place_blocks(self):
        """函数体内也能执行放置指令，副作用照常生效。"""

        interp = run(
            "def line(n){ for i = (0 to n-1){ rw{rsig=1}[p + xi] } return 0; }\n"
            "dpos p[0,0,0]\n"
            "line(4)\n"
        )
        self.assertEqual(len(interp.world), 4)

    def test_unknown_function_is_error(self):
        """调用不存在的函数要报错。"""

        with self.assertRaises(RupisError):
            run("nosuchfunc(1)")

    def test_undefined_variable_is_error(self):
        """引用不存在的变量要报错。"""

        with self.assertRaises(RupisError):
            run("let x = undefinedvar;")


class TestErrors(unittest.TestCase):
    """错误信息里的行列定位与源码片段渲染。"""

    def test_error_has_line_and_column(self):
        """报错要指出出错的是第几行。"""

        with self.assertRaises(RupisError) as ctx:
            run("rw{rsig=1}[0,0,0]\nnosuchcmd\n")
        # 出错的指令在第 2 行，行号从 1 开始算
        self.assertEqual(ctx.exception.line, 2)

    def test_error_renders_snippet(self):
        """报错要渲染出错的那一行，并用 ^ 标出出错位置。"""

        with self.assertRaises(RupisError) as ctx:
            run("rw{rsig=1}[0,0,0]\nrxyz{}[0,0,0]\n")
        rendered = ctx.exception.render()
        self.assertIn("rxyz", rendered)
        self.assertIn("^", rendered)

    def test_state_error_points_at_the_key(self):
        """状态取值非法时，报错的列号要指向出错的那个键。"""

        with self.assertRaises(RupisError) as ctx:
            run("rco{facing=sideways}[0,0,0]")
        self.assertEqual(ctx.exception.line, 1)
        self.assertEqual(ctx.exception.col, 5)  # 指向 facing 这个键
        self.assertIn("north", str(ctx.exception))

    def test_value_range_error_points_at_the_key(self):
        """状态值越界时，报错的列号要指向越界的那个键，而不是整条指令。"""

        with self.assertRaises(RupisError) as ctx:
            run("rrep{facing=east, delay=7}[0,0,0]")
        self.assertEqual(ctx.exception.col, 19)  # 指向 delay 这个键


class TestExporters(unittest.TestCase):
    """三种导出格式：/setblock 命令、JSON 与 .mcstructure。"""

    def test_commands_export(self):
        """导出成 /setblock 命令行，坐标和状态都要写对。"""

        interp = run("dpos p[1,2,3]\nrw{rsig=15}[p]")
        text = exporters.export_commands(interp.world)
        self.assertIn("/setblock 1 2 3 minecraft:redstone_wire[power=15]", text)

    def test_json_export(self):
        """导出成 JSON，包围盒尺寸和方块信息都要正确。"""

        import json as _json
        interp = run("dpos p[1,2,3]\nrw{rsig=15}[p]")
        data = _json.loads(exporters.export_json(interp.world))
        self.assertEqual(data["size"], [1, 1, 1])
        self.assertEqual(data["blocks"][0]["id"], "minecraft:redstone_wire")

    def test_structure_export(self):
        """导出的 .mcstructure 是 gzip 压缩过的 NBT。"""

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
            """按 (x, y, z) 算出调色板下标，返回该位置方块的 NBT 字典。"""

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
        """按 NBT 标签类型读取一个值，返回 (值, 新的读入位置)。"""

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
        """每个用例都在自己的临时目录里准备一个可被 lib 导入的 util.rpi。"""

        self._tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)
        self.write("util.rpi", self.UTIL)

    def write(self, name, text):
        """在临时目录里写一个 .rpi 文件（名字里的 / 表示子目录），返回完整路径。"""

        path = os.path.join(self._tmp, *name.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def run_main(self, code, name="main.rpi", lib_paths=None):
        """把主脚本写到临时目录再执行，这样 lib 才会以该目录为基准去找文件。"""

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
        """lib ... as ... 可以给模块起一个短别名。"""

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
        """导入的结构模板用 模块名.模板名(...) 调用。"""

        interp = self.run_main("lib util\nstru util.box(15)[1,0,0]")
        block = state_at(interp.world, 1, 0, 0)
        self.assertIsNotNone(block)
        self.assertEqual(block.states["power"], 15)

    def test_structure_by_name(self):
        """导入的结构模板也能直接按名字调用，不必带模块名。"""

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
        """lib 可以导入子目录里的脚本，模块名取自文件名。"""

        self.write("sub/deep.rpi", "def helper(n):{\n    return n + 1\n}\n")
        # 路径写成 sub/deep，但命名空间是 deep（不带目录）
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
        """找不到要导入的脚本时报错。"""

        with self.assertRaises(RupisError) as ctx:
            self.run_main("lib nosuchscript_xyz")
        self.assertIn("找不到脚本", ctx.exception.message)

    def test_missing_member(self):
        """访问模块里不存在的成员时报错。"""

        with self.assertRaises(RupisError) as ctx:
            self.run_main("lib util\nlet a = util.nosuchfunction(1)")
        self.assertIn("没有", ctx.exception.message)

    def test_structure_needs_stru(self):
        """模块里的结构模板必须用 stru 调用，不能当普通变量取值。"""

        with self.assertRaises(RupisError) as ctx:
            self.run_main("lib util\nlet a = util.box")
        self.assertIn("stru", ctx.exception.message)

    def test_unknown_module_in_stru(self):
        """stru 里写了未定义的模块名要报错。"""

        with self.assertRaises(RupisError) as ctx:
            self.run_main("stru nosuch.box(1)[0,0,0]")
        self.assertIn("未定义的模块", ctx.exception.message)

    def test_wrong_argument_count(self):
        """给导入进来的函数传错参数个数要报错。"""

        with self.assertRaises(RupisError) as ctx:
            self.run_main("lib util\nrw{rsig=helper(1,2)}[0,0,0]")
        self.assertIn("参数", ctx.exception.message)

    def test_broken_imported_script(self):
        """被导入的脚本自身语法错误时，报错要说明是导入失败。"""

        self.write("bad.rpi", "def f(:{\n")
        with self.assertRaises(RupisError) as ctx:
            self.run_main("lib bad")
        self.assertIn("失败", ctx.exception.message)

    def test_lib_needs_a_script_name(self):
        """lib 后面不写脚本名要报错。"""

        with self.assertRaises(RupisError):
            run("lib")

    def test_lib_inside_function_is_local(self):
        """函数里 lib 的命名空间是局部的。"""
        with self.assertRaises(RupisError) as ctx:
            self.run_main("def f(){\n  lib util\n  return 0\n}\n"
                          "rw{rsig=util.helper(1)}[0,0,0]")
        self.assertIn("未定义的变量", ctx.exception.message)

    def test_rupis_function_rejects_keyword_arguments(self):
        """Rupis 的函数不支持关键字参数，传入要报错。"""

        with self.assertRaises(RupisError) as ctx:
            run("def f(a){ return a }\nlet x = f(a=1)")
        self.assertIn("关键字参数", ctx.exception.message)

    def test_structure_rejects_keyword_arguments(self):
        """结构模板的调用同样不支持关键字参数。"""

        with self.assertRaises(RupisError) as ctx:
            run("strudef s(a):{rw{rsig=1}[a]}\nstru s(a=1)")
        self.assertIn("关键字参数", ctx.exception.message)


class TestExamples(unittest.TestCase):
    """examples/ 里的示例脚本必须都能跑通。"""

    EXAMPLES = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "examples")

    def run_example(self, name: str):
        """读取并执行 examples/ 里的一个示例脚本。"""

        path = os.path.join(self.EXAMPLES, name)
        with open(path, encoding="utf-8") as handle:
            return run_source(handle.read(), path)

    def test_demo_example_runs(self):
        """demo.rpi 要能跑完，并且真的在世界里放下方块。"""

        interp = self.run_example("demo.rpi")
        self.assertGreater(len(interp.world), 0)

    def test_lib_demo_example_runs(self):
        """lib_demo.rpi 里导入的结构、函数、子目录脚本都要真的生效。"""

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
