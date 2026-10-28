"""python -m rupis.ide 入口。

命令行上的第一个 .rpi 文件会被 IDE 直接打开，其余参数原样忽略。
"""

import sys

from . import main

if __name__ == "__main__":
    # 把 GUI 主循环的返回值当成进程退出码
    sys.exit(main())
