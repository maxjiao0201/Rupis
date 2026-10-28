#!/usr/bin/env python
"""Rupis 解释器入口。

    python main.py 脚本.rpi
    python -m rupis 脚本.rpi

注意：这个入口只跑命令行解释器；要开图形界面请用 ide.py。
"""

import sys
from rupis.cli import main

if __name__ == "__main__":
    sys.exit(main())
