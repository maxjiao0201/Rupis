
"""Windows 用户环境变量（PATH / PATHEXT）修改工具。

把 Rupis 的安装目录写进当前用户的 PATH，用户在任意目录下都能直接敲 `rupis`；
再把 .PY 加进 PATHEXT，Windows 才会把 .py 认成可以执行的脚本类型。

只改 HKCU\\Environment，不碰系统级变量，所以不需要管理员权限。
注意：本模块依赖 winreg，只能在 Windows 上使用。
"""

import os
import sys
import winreg
import glob

# 自动获取固定值
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))  # rupis 包自己所在的目录
PYTHON_EXE = sys.executable
ENV_REG_PATH = r"Environment"  # 用户环境变量在注册表里的子键名


def add_folder_to_user_environment():
    """
    无参函数：自动把【本脚本所在文件夹】加入用户PATH，同时添加 .PY 到PATHEXT

    两步的作用：
      * PATH —— 让任意目录下都能直接敲 `rupis`，不用写完整路径；
      * PATHEXT —— 让 Windows 认得 .py 是可执行类型（放在最前面优先匹配）。

    已经有对应项时会跳过，不会重复添加。
    """
    folder = os.path.abspath(SCRIPT_DIR)
    key = winreg.OpenKey(
        winreg.HKEY_CURRENT_USER, ENV_REG_PATH, 0,
        winreg.KEY_READ | winreg.KEY_WRITE
    )

    try:
        # 处理 PATH
        try:
            cur_path, path_type = winreg.QueryValueEx(key, "Path")
        except FileNotFoundError:
            cur_path, path_type = "", winreg.REG_EXPAND_SZ

        # PATH 是用分号分隔的，先拆开、去空白，再看看安装目录在不在里面
        path_parts = [p for p in cur_path.split(";") if p.strip()]
        if folder in path_parts:
            print(f"[PATH] 已存在，跳过: {folder}")
        else:
            path_parts.append(folder)
            new_path = ";".join(path_parts)
            # 写回时沿用原来的注册表类型，别把 REG_EXPAND_SZ 降级成 REG_SZ
            winreg.SetValueEx(key, "Path", 0, path_type, new_path)
            print(f"[PATH] 已追加: {folder}")

        # 处理 PATHEXT
        try:
            cur_ext, ext_type = winreg.QueryValueEx(key, "PATHEXT")
        except FileNotFoundError:
            # 系统里没有这一项时的兜底值，和 Windows 默认的一致
            cur_ext = ".COM;.EXE;.BAT;.CMD;.VBS;.VBE;.JS;.JSE;.WSF;.WSH;.MSC"
            ext_type = winreg.REG_EXPAND_SZ

        ext_list = cur_ext.split(";")
        has_py = any(e.upper() == ".PY" for e in ext_list)
        if has_py:
            print("[PATHEXT] 已包含 .PY，跳过")
        else:
            # 放在最前面，.py 的匹配优先级最高
            ext_list.insert(0, ".PY")
            new_ext = ";".join(ext_list)
            winreg.SetValueEx(key, "PATHEXT", 0, ext_type, new_ext)
            print("[PATHEXT] 已前置 .PY")
    finally:
        winreg.CloseKey(key)


