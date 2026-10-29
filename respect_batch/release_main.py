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
    from core import paths, server, updates
    # Separate application identity: Studio has a different mutex and installer.
    mutex = None
    if os.name == 'nt' and getattr(distribution, 'MANAGED', False):
        import ctypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
        kernel.CreateMutexW.restype = ctypes.c_void_p
        mutex = kernel.CreateMutexW(None, False, 'Local\\Respect.Batch.User')
        if not mutex or ctypes.get_last_error() == 183:
            raise RuntimeError('对外批量版已经运行，请使用已打开的窗口')
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
    def install(candidate):
        updates.launch_installer(candidate)
        timer = threading.Timer(1, httpd.shutdown)
        timer.daemon = True
        timer.start()
    if getattr(distribution, 'MANAGED', False):
        updates.manager.install_callback = install
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
