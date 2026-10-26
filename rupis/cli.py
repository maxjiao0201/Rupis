#!/usr/bin/env python
"""Rupis 解释器命令行入口。
    python main.py 脚本.rpi              # 输出 /setblock 命令
    python main.py 脚本.rpi --format json # 输出 JSON
    python main.py 脚本.rpi --format structure -o 结构.mcstructure
    python main.py 脚本.rpi --check       # 只检查语法，不执行
"""
from __future__ import annotations
import argparse
import sys
import os
from pathlib import Path


from . import reg
from . import path
from . import RupisError, compile_source, run_source
from . import exporters

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2

# flag 用绝对路径，放在 %APPDATA%\Rupis 下，与运行目录无关
_FLAG_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / "Rupis"
FLAG_PATH = _FLAG_DIR / "file_assoc.installed"

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rupis",
        description="Rupis 红石脚本解释器（.rpi）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
               "  python main.py demo.rpi\n"
               "  python main.py demo.rpi --format json -o demo.json\n"
               "  python main.py demo.rpi --format structure -o demo.mcstructure\n"
               "  python main.py --ide            # 打开图形界面 IDE\n",
    )
    parser.add_argument("script", nargs="?", help="要执行的 .rpi 脚本文件")
    parser.add_argument(
        "--ide", action="store_true",
        help="启动 Rupis 图形界面 IDE（可跟一个脚本文件）",
    )
    parser.add_argument(
        "-f", "--format",
        choices=["commands", "json", "structure", "summary"],
        default="commands",
        help="输出格式：commands（默认）/ json / structure / summary",
    )
    parser.add_argument("-o", "--output", help="输出文件路径（不指定则打印到标准输出）")
    parser.add_argument("--check", action="store_true", help="只做语法检查，不执行脚本")
    parser.add_argument("-v", "--verbose", action="store_true", help="执行时把每条放置指令打印到标准错误")
    parser.add_argument(
        "--data-version",
        type=int,
        default=3955,
        help=".mcstructure 的 DataVersion（默认 3955，对应 1.21.4）",
    )
    parser.add_argument("--version", action="version", version="Rupis 1.0.0")
    return parser

def read_script(path_text: str) -> str:
    path = Path(path_text)
    if not path.exists():
        raise RupisError(f"找不到脚本文件：{path}")
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        # 兼容 GBK 保存的脚本
        return path.read_text(encoding="gbk", errors="replace")

def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    # 在这里判断flag，不会在导入阶段炸
    installed = False
    if FLAG_PATH.exists():
        installed = FLAG_PATH.read_text(encoding="utf-8").strip() == "1"

    if not installed:
        reg.init()
        path.add_folder_to_user_environment()
        _FLAG_DIR.mkdir(parents=True, exist_ok=True)
        FLAG_PATH.write_text("1", encoding="utf-8")

    # Windows 控制台默认是 GBK，这里强制用 UTF-8 输出中文报错信息
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):  # pragma: no cover - 少数环境不支持
            pass

    if args.ide:
        try:
            from .ide import main as ide_main
        except ImportError as exc:
            print(f"错误：{exc}", file=sys.stderr)
            return EXIT_USAGE
        return ide_main([args.script] if args.script else [])

    if not args.script:
        # 没有脚本文件，自动打开IDE
        try:
            from .ide import main as ide_main
        except ImportError as exc:
            print(f"错误：{exc}", file=sys.stderr)
            return EXIT_USAGE
        return ide_main([])


    try:
        text = read_script(args.script)
    except RupisError as exc:
        print(exc.render(), file=sys.stderr)
        return EXIT_ERROR

    try:
        if args.check:
            compile_source(text, args.script)
            print(f"{args.script}: 语法检查通过。")
            return EXIT_OK
        interpreter = run_source(text, args.script, verbose=args.verbose)
    except RupisError as exc:
        print(exc.render(), file=sys.stderr)
        return EXIT_ERROR

    world = interpreter.world
    if args.format == "summary":
        output = exporters.summary(world)
    elif args.format == "json":
        output = exporters.export_json(world)
    elif args.format == "structure":
        if not args.output:
            print("错误：structure 格式必须用 -o 指定输出文件。", file=sys.stderr)
            return EXIT_USAGE
        count, size = exporters.export_structure(args.output, world, args.data_version)
        output = f"已写出 {args.output}（{count} 个方块，尺寸 {size[0]}x{size[1]}x{size[2]}）"
    else:
        output = exporters.export_commands(world)

    if args.output and args.format != "structure":
        Path(args.output).write_text(output + ("\n" if output else ""), encoding="utf-8")
        print(f"已写出 {args.output}")
    else:
        if output:
            print(output)
    return EXIT_OK

if __name__ == "__main__":
    sys.exit(main())
