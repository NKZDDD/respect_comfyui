"""Upload a built installer to configured R2, verify public bytes, then emit a manifest.

This batch-only local publishing tool never logs credentials or changes the online version policy.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core import paths, uploader
from core.updates import validate_release


def verify_public(release):
    digest, total = hashlib.sha256(), 0
    with requests.get(release["url"], stream=True, timeout=(15, 60),
                      allow_redirects=False, headers={"Accept-Encoding": "identity"}) as response:
        if response.status_code != 200:
            raise ValueError(f"公网下载校验失败（HTTP {response.status_code}），未生成发布清单")
        for chunk in response.iter_content(1024 * 1024):
            total += len(chunk)
            if total > release["bytes"]:
                raise ValueError("公网安装包大小不符，未生成发布清单")
            digest.update(chunk)
    if total != release["bytes"] or digest.hexdigest() != release["sha256"]:
        raise ValueError("公网安装包大小或 SHA256 不符，未生成发布清单")


def upload_release(manifest, cfg, *, public_base_url=None):
    manifest = Path(manifest).resolve()
    release = json.loads(manifest.read_text(encoding="utf-8-sig"))
    notes = str(release.get("notes", ""))
    if not uploader.configured(cfg):
        raise ValueError("本地未配置完整 R2 上传凭据")
    if not re.fullmatch(r"[a-f0-9]{64}", str(release.get("build_sha256", ""))):
        raise ValueError("缺少打包生成的程序构建校验码")
    base = (public_base_url or cfg.get("public_base_url") or "").rstrip("/")
    if not base:
        raise ValueError("未配置 R2 公开域名；不能使用 S3 API 地址")
    name = "Respect-Batch-Setup-" + str(release.get("version", "")) + ".exe"
    candidate = manifest.parent / name
    release["url"] = base + "/batch-updates/" + str(release.get("flavor", "")) + "/" + name
    validate_release(release)
    if not candidate.is_file() or candidate.stat().st_size != release["bytes"]:
        raise ValueError("清单旁的安装包不存在或大小不符")
    with candidate.open("rb") as fp:
        if hashlib.file_digest(fp, "sha256").hexdigest() != release["sha256"]:
            raise ValueError("本地安装包 SHA256 不符，未上传")
    key = "batch-updates/" + release["flavor"] + "/" + name
    client = uploader._client(cfg)
    try:
        existing = client.head_object(Bucket=cfg["bucket"], Key=key)
    except Exception as exc:
        code = str(getattr(exc, "response", {}).get("Error", {}).get("Code", ""))
        if code not in ("404", "NoSuchKey", "NotFound"):
            raise
        existing = None
    if existing is not None:
        if (existing["ContentLength"] != release["bytes"] or
                existing.get("Metadata", {}).get("sha256") != release["sha256"]):
            raise ValueError("R2 已有同版本的不同文件；请提高版本号，不覆盖旧安装包")
        print("R2 已有相同安装包，验证公网下载。", flush=True)
    else:
        print("正在上传安装包到 R2…", flush=True)
        with candidate.open("rb") as fp:
            client.put_object(Bucket=cfg["bucket"], Key=key, Body=fp,
                IfNoneMatch="*", ContentLength=release["bytes"],
                ContentType="application/octet-stream",
                ContentDisposition=f'attachment; filename="{name}"',
                CacheControl="public, max-age=31536000, immutable",
                Metadata={"sha256": release["sha256"]})
    print("正在从公开地址下载并核对完整 SHA256…", flush=True)
    verify_public(release)
    # Never export config.json or storage credentials. The manifest contains public release fields only.
    release = {k: release[k] for k in
               ("application", "version", "flavor", "url", "sha256", "bytes", "build_sha256")}
    release["mandatory"] = False
    release["notes"] = notes
    output = manifest.with_name("release.r2.json")
    partial = output.with_suffix(".json.tmp")
    partial.write_text(json.dumps(release, ensure_ascii=False, indent=2), encoding="utf-8")
    partial.replace(output)
    return output, release


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", required=True, type=Path, help="build output release.json")
    parser.add_argument("--config", required=True, type=Path, help="管理员本地 R2 配置文件，读取 upload 字段")
    parser.add_argument("--public-base-url", help="override the public domain without changing local config")
    args = parser.parse_args()
    try:
        config = args.config or Path(paths.config_path())
        cfg = json.loads(config.read_text(encoding="utf-8-sig")).get("upload", {})
        output, release = upload_release(args.release, cfg, public_base_url=args.public_base_url)
    except Exception as exc:
        # SDK exceptions can embed signed URLs and request details; do not echo them.
        print(str(exc) if isinstance(exc, ValueError) else
              "上传或公网验证失败，请检查 R2 权限、网络和公开访问配置；尚未发布更新。", file=sys.stderr)
        return 1
    print("已校验：" + release["url"])
    print("后台导入：" + str(output))
    print("尚未修改服务端版本规则，请在网页后台选择最低可用版本后发布。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
