"""Respect ComfyUI 扩展 - 对象存储上传（图床）。

把本地图片/视频上传到你自己的 S3 兼容对象存储，返回公网 URL，供需要「公网链接」的接口用
（如 Seedance 通用异步视频 的 image_url / extra_video_urls）。

S3 兼容，覆盖市面大部分云存储——只是 endpoint/region 不同：
- Cloudflare R2 ：endpoint `https://<accountid>.r2.cloudflarestorage.com`，region `auto`
- 阿里云 OSS    ：endpoint `https://oss-cn-<region>.aliyuncs.com`，region 如 `oss-cn-hangzhou`
- 腾讯云 COS    ：endpoint `https://cos.<region>.myqcloud.com`，region 如 `ap-guangzhou`
- AWS S3        ：endpoint 留空，region 如 `us-east-1`
- MinIO/自建    ：endpoint 填你的地址

需要 boto3：`pip install boto3`。公网访问 URL 建议填 `public_base_url`（你的 CDN/公开域名）。
注意：密钥会存在工作流里，别把带密钥的工作流分享出去。
"""

from __future__ import annotations

import io
import mimetypes
import os
import time
import uuid
from typing import Any, Optional

import torch

from .utils import tensor_to_pil

CATEGORY = "Respect"


def _guess_ct(name: str) -> str:
    return mimetypes.guess_type(name)[0] or "application/octet-stream"


class RespectCloudUpload:
    """上传图片/视频到 S3 兼容对象存储（R2/OSS/COS/S3/MinIO），返回公网 URL。

    - `file_path` 填了就上传该本地文件（视频等）；否则上传接入的 `image`（转 JPEG）
    - `public_base_url` 填你的公开域名（如 https://cdn.xxx.com）→ 返回 `<域名>/<key>`
    - R2 不支持 ACL：`set_public_acl` 关掉，靠「公开桶 + 公开域名」访问
    """

    DESCRIPTION = ("上传本地图片/视频到 S3 兼容对象存储(R2/OSS/COS/S3/MinIO)返回公网URL。填 endpoint/region/bucket/key，"
                   "public_base_url 填公开域名。需要 pip install boto3。")

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "bucket": ("STRING", {"default": "", "multiline": False, "tooltip": "桶名"}),
                "access_key": ("STRING", {"default": "", "multiline": False, "tooltip": "Access Key ID"}),
                "secret_key": ("STRING", {"default": "", "multiline": False, "tooltip": "Secret Access Key"}),
                "endpoint_url": ("STRING", {"default": "", "multiline": False, "placeholder": "R2/OSS/COS 的 endpoint；AWS 留空", "tooltip": "S3 endpoint；AWS S3 留空用默认"}),
                "region": ("STRING", {"default": "auto", "multiline": False, "tooltip": "区域；R2=auto，OSS/COS 填各自区域，AWS 如 us-east-1"}),
                "public_base_url": ("STRING", {"default": "", "multiline": False, "placeholder": "公开访问域名，如 https://cdn.xxx.com（留空按 endpoint/bucket 拼）", "tooltip": "返回 URL 的域名前缀"}),
            },
            "optional": {
                "image": ("IMAGE", {"tooltip": "上传图片（未填 file_path 时用）"}),
                "file_path": ("STRING", {"default": "", "multiline": False, "placeholder": "本地文件路径（视频等），优先于 image", "tooltip": "接视频节点的 local_path 即可上传视频"}),
                "key_prefix": ("STRING", {"default": "respect/", "multiline": False, "tooltip": "对象名前缀（目录）"}),
                "filename": ("STRING", {"default": "", "multiline": False, "placeholder": "对象名，留空自动", "tooltip": "留空=自动 时间戳_hash"}),
                "set_public_acl": ("BOOLEAN", {"default": False, "tooltip": "设 public-read ACL；R2 不支持要关掉，靠公开桶"}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("url", "key")
    FUNCTION = "upload"
    OUTPUT_NODE = True
    CATEGORY = CATEGORY

    def upload(self, bucket, access_key, secret_key, endpoint_url, region, public_base_url,
               image=None, file_path="", key_prefix="respect/", filename="", set_public_acl=False):
        try:
            import boto3
        except ImportError:
            raise RuntimeError("需要 boto3：在 ComfyUI 的 Python 执行 pip install boto3（S3/R2/OSS/COS 通用）")

        if not bucket or not access_key or not secret_key:
            raise ValueError("bucket / access_key / secret_key 必填")

        file_path = (file_path or "").strip().strip('"')
        # 准备要上传的数据 + 对象名
        if file_path:
            if not os.path.isfile(file_path):
                raise FileNotFoundError(f"找不到本地文件: {file_path}")
            with open(file_path, "rb") as f:
                data = f.read()
            base = (filename or "").strip() or os.path.basename(file_path)
            content_type = _guess_ct(base)
        else:
            if image is None or (hasattr(image, "numel") and image.numel() == 0):
                raise ValueError("请接入 image 或填 file_path")
            pil_list = tensor_to_pil(image[:1])
            if not pil_list:
                raise ValueError("image 为空")
            buf = io.BytesIO()
            pil_list[0].save(buf, format="JPEG", quality=92)
            data = buf.getvalue()
            base = (filename or "").strip() or f"img_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}.jpg"
            content_type = "image/jpeg"
        if "." not in os.path.basename(base):
            base += ".bin"

        key = (key_prefix or "").strip().lstrip("/") + base
        key = key.replace("\\", "/")

        client = boto3.session.Session().client(
            "s3",
            endpoint_url=(endpoint_url.strip() or None),
            region_name=(region.strip() or None),
            aws_access_key_id=access_key.strip(),
            aws_secret_access_key=secret_key.strip(),
        )
        put_kwargs = {"Bucket": bucket, "Key": key, "Body": data, "ContentType": content_type}
        try:
            if set_public_acl:
                client.put_object(ACL="public-read", **put_kwargs)
            else:
                client.put_object(**put_kwargs)
        except Exception as exc:
            if set_public_acl:
                # 部分兼容存储(如 R2)不支持 ACL，退回不带 ACL 重试
                print(f"[Respect] 带 ACL 上传失败，退回无 ACL 重试: {exc}")
                client.put_object(**put_kwargs)
            else:
                raise

        base_url = (public_base_url or "").strip().rstrip("/")
        if base_url:
            url = f"{base_url}/{key}"
        elif endpoint_url.strip():
            url = f"{endpoint_url.strip().rstrip('/')}/{bucket}/{key}"
        else:
            url = f"https://{bucket}.s3.amazonaws.com/{key}"
        print(f"[Respect] 已上传到对象存储: {url}")
        return (url, key)


NODE_CLASS_MAPPINGS = {
    "RespectCloudUpload": RespectCloudUpload,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "RespectCloudUpload": "Respect 对象存储上传（图床/S3）",
}
