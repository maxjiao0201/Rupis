#!/usr/bin/env python
"""Rupis 解释器入口。

    python main.py 脚本.rpi
    python -m rupis 脚本.rpi
"""

import sys
from rupis.cli import main

if __name__ == "__main__":
    sys.exit(main())
