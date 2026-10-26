#!/usr/bin/env python
"""Rupis IDE 启动器。

    python ide.py             # 打开空文档
    python ide.py a.rpi       # 直接打开某个脚本
"""

import sys

from rupis.ide import main

if __name__ == "__main__":
    sys.exit(main())
