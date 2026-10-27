import winreg
import subprocess
import os
import sys

# ===================== 在这里修改配置 =====================
ext = ".rpi"
progid = "MinecraftRupisFileType"
display_name = "Rupis脚本文件"
icon_filename = "rupis.ico"
# ==========================================================

def is_frozen() -> bool:
    """是不是打包成 exe 之后在跑（PyInstaller 会设这个属性）。"""

    return bool(getattr(sys, "frozen", False))


def open_command() -> str:
    """双击 .rpi 时要执行的命令。

    打包成 exe 时，sys.executable 就是 rupis.exe 自己；
    直接跑源码时是 python + main.py。
    """

    if is_frozen():
        return f'"{sys.executable}" "%1"'
    script_dir = os.path.abspath(os.path.dirname(__file__))   # ...\Rupis\rupis
    root_dir = os.path.dirname(script_dir)                      # ...\Rupis
    main_py = os.path.join(root_dir, "main.py")
    return f'"{sys.executable}" "{main_py}" "%1"'


def icon_path() -> str:
    """.rpi 文件的图标。打包后图标就在 exe 里。"""

    if is_frozen():
        return f"{sys.executable},0"
    script_dir = os.path.abspath(os.path.dirname(__file__))
    return os.path.join(script_dir, icon_filename) + ",0"


def _restart_explorer():
    """重启Windows资源管理器，刷新文件类型显示"""
    try:
        subprocess.run(["taskkill", "/f", "/im", "explorer.exe"], check=True)
        subprocess.Popen(["explorer.exe"])
        print("资源管理器已重启，文件类型刷新成功！")
    except Exception as e:
        print(f"重启explorer失败：{e}，你可以手动在任务管理器重启资源管理器")


def init():
    """注册 .rpi 文件类型、图标、双击打开"""
    icon = icon_path()
    open_cmd = open_command()

    print("正在初始化Rupis解释器,请稍后......")

    hkcu = winreg.HKEY_CURRENT_USER
    base = r"Software\Classes"

    try:
        # 1. 后缀关联到 ProgID
        with winreg.CreateKey(hkcu, f"{base}\\{ext}") as key:
            winreg.SetValue(key, "", winreg.REG_SZ, progid)

        # 2. ProgID，设置类型名称
        with winreg.CreateKey(hkcu, f"{base}\\{progid}") as key:
            winreg.SetValue(key, "", winreg.REG_SZ, display_name)

        # 3. 设置图标 DefaultIcon
        with winreg.CreateKey(hkcu, f"{base}\\{progid}\\DefaultIcon") as key:
            winreg.SetValue(key, "", winreg.REG_SZ, icon)

        # 4. 双击打开命令
        with winreg.CreateKey(hkcu, f"{base}\\{progid}\\shell\\open\\command") as key:
            winreg.SetValue(key, "", winreg.REG_SZ, open_cmd)

        print(f"注册表写入完成！双击命令：{open_cmd}")
        _restart_explorer()
    except Exception as e:
        print(f"出错：{e}")
