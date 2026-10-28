#!/usr/bin/env python
"""Rupis IDE 启动器。

    python ide.py             # 打开空文档
    python ide.py a.rpi       # 直接打开某个脚本

等价于 python -m rupis.ide，只是省得记包名。
命令行解释器请用 main.py。
"""

import sys

from rupis.ide import main

if __name__ == "__main__":
    sys.exit(main())
