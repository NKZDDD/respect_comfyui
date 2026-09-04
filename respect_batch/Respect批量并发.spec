# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置。用法：

    pip install pyinstaller
    pyinstaller "Respect批量并发.spec" --noconfirm

出来的东西在 dist/ 下，是**一个目录**不是单文件 exe —— 单文件每次启动都要把
自己解压到临时目录，17 家服务商加上 boto3 有几十 MB，冷启动要好几秒，
而这个程序是"想起来就双击一下"的用法，慢在启动上最难受。

两个**必须显式带上、漏了不报错只是少东西**的地方：

  1. `web/index.html` —— 界面。不带的话程序照常起、浏览器打开是 500，
     日志里才有一句"找不到界面文件"。
  2. `core.providers.*` —— 17 家服务商。它们是 importlib 动态加载的，
     PyInstaller 静态扫依赖**扫不到任何一家**，打出来的包能跑、服务商下拉框
     是空的、一句报错都没有。所以下面 hiddenimports 里一家一家列。
     （providers/__init__.py 里还有一道 frozen 兜底，两处要对得上。）
"""

import os

block_cipher = None

PROVIDERS = ["paisio", "lingganya", "zeroapi", "m86", "aicopy", "kunji",
             "octopus", "ake", "wuxianhuabu", "gate", "yishou",
             "chaomo", "xiaobalong", "hvtald", "zhi", "haomanju", "julun"]

a = Analysis(
    ["run.py"],
    pathex=[],
    binaries=[],
    datas=[("web", "web")],
    hiddenimports=(
        [f"core.providers.{n}" for n in PROVIDERS]
        + ["core.providers.base",
           # boto3/botocore 的数据文件靠它自己的 hook 带，但 s3 那份 client
           # 是运行时按名字找的，显式点一下更保险
           "boto3", "botocore", "PIL.Image"]
    ),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy", "pytest"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="Respect批量并发",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,          # 黑窗口留着：它显示界面地址，也是"关掉=退出"的开关
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe, a.binaries, a.zipfiles, a.datas,
    strip=False, upx=False, upx_exclude=[],
    name="Respect批量并发",
)
