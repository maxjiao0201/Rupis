"""让 `python -m rupis 脚本.rpi` 生效。

有了这个文件，整个解释器包就能当成可执行模块运行；真正的逻辑都在 cli.main 里。
"""

import sys

from .cli import main

if __name__ == "__main__":
    # 把 main 的返回值当成进程退出码交给系统
    sys.exit(main())
