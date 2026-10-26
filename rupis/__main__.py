"""让 `python -m rupis 脚本.rpi` 生效。"""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
