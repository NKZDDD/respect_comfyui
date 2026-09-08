"""开发版标记。发行构建在独立暂存目录将本模块替换为编译的加密配置。

没有运行时环境变量、配置文件或命令行开关可以将发行版切回开发版。
"""
ENABLED = False


def profile() -> dict:
    raise RuntimeError("当前是开发版，没有发行凭据")


def page() -> bytes:
    raise RuntimeError("当前是开发版，没有发行界面")
