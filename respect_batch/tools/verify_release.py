"""启动真正的发行 EXE，验证本地接口、资源与凭据边界；不调用生成服务。"""
from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request


def verify(exe: Path, isolated_copy: bool = False) -> dict:
    root = Path(__file__).resolve().parents[1]
    scratch = Path(tempfile.mkdtemp(prefix="exe-check-", dir=root / "release-build"))
    if isolated_copy:
        single_dir = scratch / "single-exe"
        single_dir.mkdir()
        exe = Path(shutil.copy2(exe, single_dir / exe.name))
        assert len(list(single_dir.iterdir())) == 1
    env = os.environ.copy()
    env["LOCALAPPDATA"] = str(scratch / "data")
    runtime_temp = scratch / "runtime-temp"
    runtime_temp.mkdir()
    env["TEMP"] = env["TMP"] = str(runtime_temp)
    injection = scratch / "injected"
    injection.mkdir()
    marker = scratch / "unexpected-python-code"
    (injection / "sitecustomize.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\n", encoding="utf-8")
    env["PYTHONPATH"] = str(injection)
    log = scratch / "startup.log"
    with log.open("wb") as stream:
        process = subprocess.Popen([str(exe.resolve()), "--no-browser"], cwd=exe.parent,
            env=env, stdout=stream, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    checks = []
    try:
        deadline = time.monotonic() + 60
        url = None
        while time.monotonic() < deadline:
            text = log.read_bytes().decode("utf-8", errors="replace")
            match = re.search(r"http://127\.0\.0\.1:\d+/", text)
            if match:
                url = match.group()
                break
            if process.poll() is not None:
                raise RuntimeError(f"程序提前退出；启动记录：{log}")
            time.sleep(.1)
        assert url, f"60 秒内未启动；记录：{log}"
        token = ""
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        def request(route, body=None, headers=None):
            req = urllib.request.Request(url + route, data=body,
                headers={"X-Respect-Session": token, **(headers or {})})
            try:
                with opener.open(req, timeout=5) as response:
                    return response.status, response.read()
            except urllib.error.HTTPError as exc:
                return exc.code, exc.read()
        status, home = request("")
        assert status == 200 and b'<body class="distribution">' in home
        assert 'Respect 创作服务'.encode() in home and not marker.exists()
        assert not (exe.parent / 'web').exists()
        assert all(term.encode() not in home for term in (
            '阿珂', '小裴', '庄园', 'id="tab-set"', 'id="up_secret_key"', 'api/config'))
        token = re.search(rb"const SESSION='([^']+)'", home).group(1).decode()
        assert not token.startswith("__")
        status, boot = request("api/boot")
        data = json.loads(boot)
        assert status == 200 and data["distribution"]
        assert "api_key" not in data["config"]["providers"]["preset"]
        catalog = data["providers"][0]
        total = sum(len(catalog[k]["models"]) for k in catalog["supports"])
        assert total == 3 and catalog["supports"] == ["video"]
        assert set(catalog["video"]["model_labels"].values()) == {
            "H3 768p", "Grok 1.5（按次）", "SD2.0 720 满血不卡脸（按秒）"}
        if not data["preview"]:
            assert all(x["upload_ready"] for x in catalog["video"]["model_options"].values())
        checks.append("native_startup_encrypted_profile_and_web")
        checks.append("respect_brand_encrypted_ui_and_python_environment_isolation")
        for route in ("api/config", "api/import_studio", "api/rescan", "api/models", "api/selftest"):
            assert request(route, b"{}")[0] == 403
        assert request("api/boot", headers={"X-Respect-Session": ""})[0] == 403
        assert request("api/boot", headers={"Origin": "https://other.invalid"})[0] == 403
        checks.append("admin_routes_and_cross_origin_blocked")
        png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=")
        status, uploaded = request("api/upload?name=preview-test.png", png)
        assert status == 200
        assert json.loads(uploaded)["ok"]
        checks.append("local_reference_upload")
        status, blocked = request("api/start", json.dumps({"spec": {
            "provider": "preset", "kind": "video", "model": "UNAPPROVED_MODEL",
            "tasks": [{"prompt": "preview test"}]}}).encode())
        assert status == 400 and ("预览版" if data["preview"] else "开放清单") in json.loads(blocked)["msg"]
        assert json.loads(request("api/run")[1])["idle"]
        checks.append("unapproved_generation_blocked_without_network")
        if isolated_copy:
            checks.append("single_exe_runs_from_empty_folder")
        return {"ok": True, "preview": data["preview"], "models": total, "checks": checks, "startup_log": str(log)}
    finally:
        if process.poll() is None:
            if os.name == "nt":
                # 单文件启动器会创建子进程，仅结束本次验证创建的进程树。
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW, check=False)
            else:
                process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("exe", type=Path)
    parser.add_argument("--isolated-copy", action="store_true", help="只复制 EXE 到空目录再验证")
    args = parser.parse_args()
    print(json.dumps(verify(args.exe, args.isolated_copy), ensure_ascii=False, indent=2))
