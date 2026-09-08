"""发行包专用入口；不包含开发版命令行、导入配置或外挂入口。"""
from __future__ import annotations

import os
import sys
import threading
import webbrowser


def main() -> None:
    from core import distribution
    if not distribution.ENABLED:
        raise RuntimeError("请通过 tools/build_release.py 构建发行版")
    from core import paths, server
    os.makedirs(paths.data_dir(), exist_ok=True)
    httpd = None
    for port in range(8790, 8810):
        try:
            httpd = server.serve(port=port)
            break
        except OSError:
            continue
    if httpd is None:
        raise RuntimeError("8790–8809 端口被占用，请关闭旧程序后重试")
    url = f"http://127.0.0.1:{httpd.server_port}/"
    print(f"Respect 创作服务 · Respect 团队\n界面：{url}\n关闭窗口即可退出。", flush=True)
    # 只保留无浏览器启动以便离线验收；不接受配置路径、地址或凭据参数。
    if "--no-browser" not in sys.argv:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
