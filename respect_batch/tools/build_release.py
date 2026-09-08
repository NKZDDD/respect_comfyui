"""管理员构建工具：专用配置 → AES-GCM 封装 → Nuitka 原生发行包。

私密配置不会复制到暂存区。AES 密钥拆分嵌入编译代码，只提高静态提取门槛；
运行时具备解密能力，不能承诺抵御专业逆向或内存提取。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import uuid
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from tools.release_page import render as render_page

AAD = b"Respect-Batch-Release-v1"
RELEASE_MODELS = [
    {"provider": "ake", "kind": "video", "model": "minimax_h3-768p", "label": "H3 768p"},
    {"provider": "ake", "kind": "video", "model": "grok-imagine-video-1.5（按次）", "label": "Grok 1.5（按次）"},
    {"provider": "aicopy", "kind": "video", "model": "sd2.0-720满血-不卡脸（按秒）", "label": "SD2.0 720 满血不卡脸（按秒）"},
]


def make_profile(source: dict, preview: bool = False) -> dict:
    # 构建过程也不执行数据目录的外挂；不依赖管理员机器的实际 config.json。
    from core import distribution
    old = distribution.ENABLED, distribution.profile
    distribution.ENABLED = True
    distribution.profile = lambda: {"config": {"providers": {"ake": {}, "aicopy": {}}}}
    try:
        from core.providers.ake import AkeProvider
        from core.providers.aicopy import AicopyProvider
    finally:
        distribution.ENABLED, distribution.profile = old
    classes = {"ake": AkeProvider, "aicopy": AicopyProvider}
    cfg = source.get("config") or {}
    providers = cfg.get("providers") or {}
    if set(providers) != set(classes):
        raise ValueError("发行配置必须且只能包含阿珂 ake 和小裴 aicopy")
    clean_providers = {}
    for pid, cls in classes.items():
        key = providers[pid].get("api_key", "")
        if not isinstance(key, str) or (not preview and not key.strip()):
            raise ValueError(f"请在发行配置里填写 {pid} 专用 Key")
        clean_providers[pid] = {"api_key": "" if preview else key.strip(), "base_url": cls.default_base_url,
                                "proxy": "direct"}
    models = []
    selected = source.get("models")
    if selected is None:
        selected = RELEASE_MODELS
    from core.release import OPTION_KEYS
    seen = set()
    for row in selected:
        pid, kind, model = row["provider"], row["kind"], row["model"]
        if pid not in classes or kind not in classes[pid].supports or not isinstance(model, str) or not model:
            raise ValueError("模型清单含不支持的服务商、类型或空模型名")
        identity = (pid, kind, model)
        if identity not in {(r["provider"], r["kind"], r["model"]) for r in RELEASE_MODELS}:
            raise ValueError("本发行版仅开放已确定的三个视频模型")
        if identity in seen:
            raise ValueError("模型清单有重复项")
        seen.add(identity)
        provider = classes[pid]()
        caps = provider.capabilities()[kind]
        if model not in caps["models"] and not row.get("options"):
            raise ValueError("新增模型必须附带已核对的参数范围，不能猜测上限")
        opts = {**caps, **caps.get("model_options", {}).get(model, {}), **row.get("options", {})}
        opts["ref_mode"] = "url" if provider.needs_url(model, kind) else provider.ref_mode
        opts = {k: v for k, v in opts.items() if k in OPTION_KEYS}
        for key, choices in (("default_duration", "durations"), ("default_size", "sizes"),
                             ("default_ratio", "ratios")):
            if opts.get(choices) and opts.get(key) not in opts[choices]:
                opts[key] = opts[choices][0]
        models.append({"id": f"m{len(models)+1:03d}", "label": row.get("label") or model,
                       "provider": pid, "kind": kind, "model": model, "options": opts})
    if not models:
        raise ValueError("发行版至少需要一个模型")
    labels = [r["label"] for r in models]
    for item in models:
        if labels.count(item["label"]) > 1:
            item["label"] += "（线路 A）" if item["provider"] == "ake" else "（线路 B）"
    upload = dict(cfg.get("upload") or {})
    if upload.get("backend") == "aicopy":
        raise ValueError("小裴图床只能放在 aicopy 的专用上传配置，不能全局共用")
    if preview:
        upload = {}
    if not preview:
        clean_providers["aicopy"]["upload"] = {
            "backend": "aicopy", "api_key": clean_providers["aicopy"]["api_key"], "mode": "when_required"}
    upload["mode"] = "when_required"
    if not preview and any(m["options"].get("ref_mode") == "url" and
                           not clean_providers[m["provider"]].get("upload") for m in models):
        required = ("endpoint", "bucket", "access_key", "secret_key", "public_base_url")
        if any(not upload.get(k) for k in required):
            raise ValueError("视频参考图需要公网链接，请补齐发行专用对象存储配置")
        if any(not str(upload[k]).startswith("https://") for k in ("endpoint", "public_base_url")):
            raise ValueError("发行对象存储必须使用 HTTPS")
    defaults = {"concurrency": 4, "max_retry": 2, "timeout": 900,
                "poll_timeout_image": 900, "poll_timeout_video": 2400,
                "skip_existing": True, "out_dir": ""}
    for k in ("concurrency", "max_retry", "timeout", "poll_timeout_image", "poll_timeout_video"):
        if k in cfg.get("defaults", {}):
            defaults[k] = int(cfg["defaults"][k])
    if not 1 <= defaults["concurrency"] <= 128 or not 0 <= defaults["max_retry"] <= 8:
        raise ValueError("并发须为 1–128，重试须为 0–8")
    return {"preview": preview, "models": models,
            "private_names": ["阿珂", "小裴", "庄园", "AkeProvider", "AicopyProvider",
                              "snumom.com", "api.aicopy.top", "api.aione.help"],
            "config": {"providers": clean_providers, "upload": upload, "defaults": defaults,
                       "limits": {"global": defaults["concurrency"], "per_provider": {}}}}


def seal_module(profile: dict, page: bytes = b"") -> str:
    key, mask, nonce = os.urandom(32), os.urandom(32), os.urandom(12)
    other = bytes(a ^ b for a, b in zip(key, mask))
    payload = {"profile": profile, "page": page.decode("utf-8")}
    blob = AESGCM(key).encrypt(nonce, zlib.compress(json.dumps(payload, ensure_ascii=False).encode()), AAD)
    return f'''# Generated build-only module: encrypted data, never plaintext credentials.
import json
import zlib
from functools import lru_cache
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
ENABLED = True
@lru_cache(maxsize=1)
def _payload():
    a = bytes.fromhex({mask.hex()!r})
    b = bytes.fromhex({other.hex()!r})
    key = bytes(x ^ y for x, y in zip(a, b))
    raw = AESGCM(key).decrypt(bytes.fromhex({nonce.hex()!r}),
        bytes.fromhex({blob.hex()!r}), {AAD!r})
    return json.loads(zlib.decompress(raw))
def profile():
    return _payload()["profile"]
def page():
    return _payload()["page"].encode("utf-8")
'''


def stage_profile(profile: dict, reuse: str = "") -> Path:
    if reuse and not re.fullmatch(r"[0-9a-f]{12}", reuse):
        raise ValueError("复用构建号格式不正确")
    stage = ROOT / "release-build" / (reuse or uuid.uuid4().hex[:12])
    if stage.resolve().parent != (ROOT / "release-build").resolve():
        raise ValueError("构建目录必须位于项目暂存目录内")
    stage.mkdir(parents=True, exist_ok=bool(reuse))
    shutil.copytree(ROOT / "core", stage / "core", dirs_exist_ok=bool(reuse),
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for path in (stage / "core" / "providers").glob("*.py"):
        if path.stem not in {"__init__", "base", *profile["config"]["providers"]}:
            path.unlink()
    shutil.copy2(ROOT / "release_main.py", stage / "release_main.py")
    # 开发源码保留适配器名称；发行代码中的显示文案统一成 Respect。
    # 过滤规则本身的名称来自加密配置，不以明文常量留在运行模块中。
    for path in (stage / "core").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        for name in ("阿珂", "小裴", "庄园"):
            source = source.replace(name, "Respect")
        path.write_text(source, encoding="utf-8")
    page = render_page((ROOT / "web" / "index.html").read_text(encoding="utf-8"))
    (stage / "core" / "distribution.py").write_text(seal_module(profile, page), encoding="utf-8")
    return stage


def verify_output(profile: dict, bundle: Path, name: str, onefile: bool = False) -> dict:
    """扫描最终目录并记录哈希；也可用于继续构建后的独立验收。"""
    shutil.copy2(ROOT / "用户版使用说明.txt", bundle / "使用说明.txt")
    secret_values = [p["api_key"] for p in profile["config"]["providers"].values() if p["api_key"]]
    secret_values += [profile["config"]["upload"].get(k, "") for k in ("access_key", "secret_key")]
    for path in bundle.rglob("*"):
        if path.is_file():
            if path.suffix.lower() in (".py", ".pyc", ".pyw", ".map"):
                raise RuntimeError("发行目录发现 Python 源码或字节码，请检查构建结果")
            data = path.read_bytes()
            if any(secret.encode() in data or secret.encode("utf-16-le") in data for secret in secret_values if secret):
                raise RuntimeError("发行目录发现未保护的凭据，停止交付")
            if any(word.encode() in data or word.encode("utf-16-le") in data
                   for word in ("阿珂", "小裴", "庄园")):
                raise RuntimeError("发行目录发现未替换的上游名称，停止交付")
    if (bundle / "web").exists():
        raise RuntimeError("发行目录不应包含可替换的网页源码")
    payload = bundle / name
    exe = bundle.parent / name if onefile else payload
    if onefile:
        data = exe.read_bytes()
        if any(secret.encode() in data or secret.encode("utf-16-le") in data for secret in secret_values if secret):
            raise RuntimeError("单文件程序发现未保护的凭据，停止交付")
    report = {"preview": profile["preview"], "models": len(profile["models"]),
              "mode": "onefile" if onefile else "standalone",
              "exe": str(exe), "sha256": hashlib.sha256(exe.read_bytes()).hexdigest(),
              "payload_sha256": hashlib.sha256(payload.read_bytes()).hexdigest(),
              "plaintext_secret_scan": "passed" if any(secret_values) else "no_credentials_in_preview",
              "source_scan": "passed",
              "branding_scan": "passed", "encrypted_ui": True,
              "protection": "Nuitka native compilation + AES-GCM profile/UI + isolated Python; runtime extraction remains possible"}
    (bundle.parent / "build-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description="构建阿珂 + 小裴三个固定模型的本地加固发行版")
    ap.add_argument("--profile", type=Path, default=ROOT / "release-profile.example.json")
    ap.add_argument("--preview", action="store_true", help="允许缺密钥，生成不可调用的预览包")
    ap.add_argument("--stage-only", action="store_true", help="仅生成隔离暂存目录供测试")
    ap.add_argument("--onefile", action="store_true", help="生成无需附带运行目录的单文件 EXE")
    ap.add_argument("--jobs", type=int, default=4, help="C 编译并行数")
    ap.add_argument("--reuse-build", default="", help="复用未交付的构建号，加速本轮代码调整")
    args = ap.parse_args()
    profile = make_profile(json.loads(args.profile.read_text(encoding="utf-8-sig")), args.preview)
    stage = stage_profile(profile, args.reuse_build)
    print(f"已封装 {len(profile['models'])} 个模型；暂存：{stage}", flush=True)
    if args.stage_only:
        return
    name = "RespectBatch-Preview.exe" if args.preview else "RespectBatch-User.exe"
    out = ROOT / "release-dist" / stage.name
    # Store 应用重定向的 AppData 路径太长，MinGW 头文件查找可能超过 MAX_PATH。
    env = os.environ.copy()
    env.setdefault("NUITKA_CACHE_DIR_DOWNLOADS", str(ROOT / "release-build" / "tool-cache"))
    # 本工具耗时在远程生成，O1 足够；O3 编译大量 Python 转换代码的峰值内存较高。
    env.setdefault("CFLAGS", "-O1")
    cmd = [sys.executable, "-m", "nuitka", "--mode=onefile" if args.onefile else "--mode=standalone", "--mingw64",
           "--assume-yes-for-downloads", "--enable-plugin=tk-inter", "--include-package=core",
           "--nofollow-import-to=pytest,numpy,matplotlib",
           "--python-flag=isolated", "--python-flag=no_site", "--python-flag=no_docstrings",
           "--company-name=Respect Team", "--product-name=Respect Creative Service",
           "--file-description=Respect Creative Service", "--file-version=1.1.0.0",
           "--windows-console-mode=force", f"--jobs={max(1, args.jobs)}", "--lto=no",
           f"--output-dir={out}", f"--output-filename={name}", "release_main.py"]
    if args.onefile:
        cmd.insert(-1, "--onefile-no-dll")
    subprocess.run(cmd, cwd=stage, env=env, check=True)
    bundle = out / "release_main.dist"
    report = verify_output(profile, bundle, name, onefile=args.onefile)
    print(f"构建完成：{report['exe']}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        # 不打印私密配置的内容或 json 解码上下文。
        print("发行配置无效：" + (str(exc) if isinstance(exc, ValueError) and not isinstance(exc, json.JSONDecodeError)
                              else "请检查配置结构与字段"), file=sys.stderr)
        sys.exit(2)
