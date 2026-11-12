#!/usr/bin/env python
"""Rupis 解释器命令行入口。
    python main.py 脚本.rpi              # 输出 /setblock 命令
    python main.py 脚本.rpi --format json # 输出 JSON
    python main.py 脚本.rpi --format structure -o 结构.mcstructure
    python main.py 脚本.rpi --check       # 只检查语法，不执行

退出码：0 成功，1 脚本出错，2 命令行用法不对。
"""
from __future__ import annotations
import argparse
import sys
import os
from pathlib import Path
from rupis import __version__



from . import RupisError, compile_source, run_source
from . import exporters
from . import i18n
from .i18n import t

EXIT_OK = 0        # 一切正常
EXIT_ERROR = 1     # 脚本本身出错（语法错误、运行时报错等）
EXIT_USAGE = 2     # 命令行用法不对（缺参数、IDE 起不来等）

# flag 用绝对路径，放在 %APPDATA%\Rupis 下，与运行目录无关
_FLAG_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / "Rupis"
FLAG_PATH = _FLAG_DIR / "file_assoc.installed"

def build_parser() -> argparse.ArgumentParser:
    """构造命令行参数解析器，脚本的全部选项都写在这里。"""

    parser = argparse.ArgumentParser(
        prog="rupis",
        description=t("Rupis 红石脚本解释器（.rpi）"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=t("示例：\n"
                 "  python main.py demo.rpi\n"
                 "  python main.py demo.rpi --format json -o demo.json\n"
                 "  python main.py demo.rpi --format structure -o demo.mcstructure\n"
                 "  python main.py --ide            # 打开图形界面 IDE\n"),
    )
    parser.add_argument("script", nargs="?", help=t("要执行的 .rpi 脚本文件"))
    parser.add_argument(
        "--ide", action="store_true",
        help=t("启动 Rupis 图形界面 IDE（可跟一个脚本文件）"),
    )
    parser.add_argument(
        "-f", "--format",
        choices=["commands", "json", "structure", "summary"],
        default="commands",
        help=t("输出格式：commands（默认）/ json / structure / summary"),
    )
    parser.add_argument("-o", "--output", help=t("输出文件路径（不指定则打印到标准输出）"))
    parser.add_argument("--check", action="store_true", help=t("只做语法检查，不执行脚本"))
    parser.add_argument("-v", "--verbose", action="store_true", help=t("执行时把每条放置指令打印到标准错误"))
    parser.add_argument(
        "--data-version",
        type=int,
        default=3955,
        help=t(".mcstructure 的 DataVersion（默认 3955，对应 1.21.4）"),
    )
    parser.add_argument(
        "--lang",
        help=t("指定语言（lang 目录下的文件名，如 en）；默认用上次在 IDE 里选的"),
    )

    parser.add_argument("--version", action="version", version=f"Rupis {__version__}")
    return parser

def read_script(path_text: str) -> str:
    """读取脚本文本；文件不存在就抛 RupisError。

    先按 UTF-8 读，遇到 GBK 保存的旧脚本再退回 GBK 解码。
    """

    path = Path(path_text)
    if not path.exists():
        raise RupisError(t("找不到脚本文件：{path}", path=path))
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        # 兼容 GBK 保存的脚本
        return path.read_text(encoding="gbk", errors="replace")


def _apply_lang_option(argv) -> None:
    """先扫一遍 --lang，让解析器自己的帮助文字也用上选中的语言。

    不带 --lang 就保持 i18n 模块加载时定下的语言（上次在 IDE 里选的那个）。
    """

    argv = list(sys.argv[1:] if argv is None else argv)
    for index, item in enumerate(argv):
        if item == "--lang" and index + 1 < len(argv):
            i18n.set_language(argv[index + 1], persist=False)
            return
        if item.startswith("--lang="):
            i18n.set_language(item.split("=", 1)[1], persist=False)
            return


def main(argv=None) -> int:
    """命令行主流程，返回进程退出码。

    argv：可选的参数列表；不传就用 sys.argv[1:]。
    """

    _apply_lang_option(argv)
    args = build_parser().parse_args(argv)

    # 在这里判断flag，不会在导入阶段炸
    installed = False
    if FLAG_PATH.exists():
        installed = FLAG_PATH.read_text(encoding="utf-8").strip() == "1"

    if not installed:
        # 首次运行：注册 .rpi 文件类型（双击 .rpi 用 Rupis 打开）
        # 这块只有 Windows 有用，所以放到函数里 import
        try:
            from . import reg

            reg.init()
            # 跑源码时才需要把目录加进 PATH；打包成 exe 就不用了
            if not getattr(sys, "frozen", False):
                from . import path

                path.add_folder_to_user_environment()
        except Exception as exc:
            # 注册失败不影响使用，只是双击不会自动用 Rupis 打开
            print(t("（文件关联注册失败，不影响使用：{exc}）", exc=exc))
        try:
            _FLAG_DIR.mkdir(parents=True, exist_ok=True)
            FLAG_PATH.write_text("1", encoding="utf-8")
        except OSError:
            pass

    # Windows 控制台默认是 GBK，这里强制用 UTF-8 输出中文报错信息
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):  # pragma: no cover - 少数环境不支持
            pass

    if args.ide:
        # IDE 依赖 Qt，没装 PySide6/PyQt 时只能报错退出
        try:
            from .ide import main as ide_main
        except ImportError as exc:
            print(t("错误：{exc}", exc=exc), file=sys.stderr)
            return EXIT_USAGE
        return ide_main([args.script] if args.script else [])

    if not args.script:
        # 没有脚本文件，自动打开IDE
        try:
            from .ide import main as ide_main
        except ImportError as exc:
            print(t("错误：{exc}", exc=exc), file=sys.stderr)
            return EXIT_USAGE
        return ide_main([])


    try:
        text = read_script(args.script)
    except RupisError as exc:
        print(exc.render(), file=sys.stderr)
        return EXIT_ERROR

    try:
        if args.check:
            # 只编译不执行，用来快速检查语法
            compile_source(text, args.script)
            print(t("{script}: 语法检查通过。", script=args.script))
            return EXIT_OK
        interpreter = run_source(text, args.script, verbose=args.verbose)
    except RupisError as exc:
        print(exc.render(), file=sys.stderr)
        return EXIT_ERROR

    world = interpreter.world
    # structure 是二进制文件，已经在上面的分支里写盘了，这里不再当文本处理
    if args.format == "summary":
        output = exporters.summary(world)
    elif args.format == "json":
        output = exporters.export_json(world)
    elif args.format == "structure":
        if not args.output:
            print(t("错误：structure 格式必须用 -o 指定输出文件。"), file=sys.stderr)
            return EXIT_USAGE
        count, size = exporters.export_structure(args.output, world, args.data_version)
        output = t("已写出 {path}（{count} 个方块，尺寸 {x}x{y}x{z}）",
                   path=args.output, count=count,
                   x=size[0], y=size[1], z=size[2])
    else:
        output = exporters.export_commands(world)

    if args.output and args.format != "structure":
        Path(args.output).write_text(output + ("\n" if output else ""), encoding="utf-8")
        print(t("已写出 {path}", path=args.output))
    else:
        # 没给 -o 就直接打到屏幕上
        if output:
            print(output)
    return EXIT_OK

if __name__ == "__main__":
    sys.exit(main())
