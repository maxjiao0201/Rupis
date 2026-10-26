# -*- coding: utf-8 -*-
import os
import sys
import winreg
import glob

# 自动获取固定值
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PYTHON_EXE = sys.executable
ENV_REG_PATH = r"Environment"


def add_folder_to_user_environment():
    """
    无参函数：自动把【本脚本所在文件夹】加入用户PATH，同时添加 .PY 到PATHEXT
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

        path_parts = [p for p in cur_path.split(";") if p.strip()]
        if folder in path_parts:
            print(f"[PATH] 已存在，跳过: {folder}")
        else:
            path_parts.append(folder)
            new_path = ";".join(path_parts)
            winreg.SetValueEx(key, "Path", 0, path_type, new_path)
            print(f"[PATH] 已追加: {folder}")

        # 处理 PATHEXT
        try:
            cur_ext, ext_type = winreg.QueryValueEx(key, "PATHEXT")
        except FileNotFoundError:
            cur_ext = ".COM;.EXE;.BAT;.CMD;.VBS;.VBE;.JS;.JSE;.WSF;.WSH;.MSC"
            ext_type = winreg.REG_EXPAND_SZ

        ext_list = cur_ext.split(";")
        has_py = any(e.upper() == ".PY" for e in ext_list)
        if has_py:
            print("[PATHEXT] 已包含 .PY，跳过")
        else:
            ext_list.insert(0, ".PY")
            new_ext = ";".join(ext_list)
            winreg.SetValueEx(key, "PATHEXT", 0, ext_type, new_ext)
            print("[PATHEXT] 已前置 .PY")
    finally:
        winreg.CloseKey(key)


