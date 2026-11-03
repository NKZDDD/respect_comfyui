"""Reference upload copies: byte budget applies to decoded files, never source assets."""
import hashlib
import io
import os
import tempfile
from pathlib import Path

DEFAULT_MAX_BYTES = 9_500_000  # below decimal 10 MB, with room for gateway differences


def limit_bytes(raw, maximum=DEFAULT_MAX_BYTES, required_format=''):
    from PIL import Image
    from .apiutil import ApiError, TASK_FATAL
    if len(raw) <= maximum:
        return raw, '', '', ''
    try:
        with Image.open(io.BytesIO(raw)) as src:
            src.load()
            im = src.copy()
            alpha = im.mode in ('RGBA', 'LA', 'PA') or 'transparency' in src.info
            if alpha:
                im = im.convert('RGBA')
            elif im.mode not in ('RGB', 'L'):
                im = im.convert('RGB')
        original = im.size
        fmt = (required_format or ('PNG' if alpha else 'JPEG')).upper().replace('JPG', 'JPEG')
        lossless = fmt == 'PNG'
        for _ in range(20):
            for quality in ([None] if lossless else [95, 90, 85, 80]):
                buf = io.BytesIO()
                im.save(buf, format=fmt, **({'optimize': True} if lossless else {'quality': quality, 'optimize': True}))
                data = buf.getvalue()
                if len(data) <= maximum:
                    ext, mime = ('.jpg', 'image/jpeg') if fmt == 'JPEG' else ('.'+fmt.lower(), 'image/'+fmt.lower())
                    note = (f'参考图上传副本 {len(raw)/1e6:.2f}→{len(data)/1e6:.2f} MB，'
                            f'{original[0]}×{original[1]}→{im.width}×{im.height}，{fmt}；原图保留')
                    return data, mime, ext, note
            if min(im.size) <= 32:
                break
            im = im.resize((max(1, int(im.width*.85)), max(1, int(im.height*.85))), Image.Resampling.LANCZOS)
        raise ValueError('无法在保持有效图片的情况下压到上限')
    except Exception as exc:
        raise ApiError(f'参考图超过 {maximum/1e6:g} MB，准备上传副本失败：{exc}', kind=TASK_FATAL) from exc


def local_copy(path, root, *, max_side=0, fmt='', maximum=DEFAULT_MAX_BYTES, log=print):
    """All transports use the same prepared file, including multipart and object storage."""
    from .apiutil import encode_ref
    if os.path.getsize(path) <= maximum and not max_side and not fmt:
        return str(path)
    raw, mime, ext, note = encode_ref(str(path), max_side=max_side, fmt=fmt, max_bytes=maximum)
    folder = Path(root) / '07_检查与记录' / 'reference-cache'
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / (hashlib.sha256(raw).hexdigest() + ext)
    if not dest.exists():
        fd, temporary = tempfile.mkstemp(prefix='.ref-', dir=folder)
        try:
            with os.fdopen(fd, 'wb') as f:
                f.write(raw)
            try:
                os.replace(temporary, dest)
            except PermissionError:
                # 并发任务可能已发布同一内容哈希，Windows 上正在读取的文件不能替换。
                if not dest.is_file():
                    raise
        finally:
            if os.path.exists(temporary):
                os.remove(temporary)
    if note:
        log(note)
    return str(dest)


def remote_copy(url, root, log=print):
    """Fetch a public reference without provider credentials before measuring its bytes."""
    import requests
    from .apiutil import ApiError, TASK_FATAL
    folder = Path(root) / '07_检查与记录' / 'reference-cache'
    folder.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.download-', dir=folder)
    try:
        with os.fdopen(fd, 'wb') as f, requests.get(url, stream=True, timeout=(15, 60)) as r:
            r.raise_for_status()
            total = 0
            for chunk in r.iter_content(64 << 10):
                total += len(chunk)
                if total > 100_000_000:
                    raise ValueError('远程参考图超过 100 MB 下载检查上限')
                f.write(chunk)
        from PIL import Image
        with Image.open(temporary) as im:
            im.verify()
            ext = {'JPEG': '.jpg', 'PNG': '.png', 'WEBP': '.webp'}.get(im.format)
        with Image.open(temporary) as im:
            im.load()  # JPEG verify 只看头部；截断的像素流也必须拒绝。
        if not ext:
            raise ValueError('参考图必须为 PNG/JPEG/WebP')
        raw = Path(temporary).read_bytes()
        dest = folder / (hashlib.sha256(raw).hexdigest() + ext)
        if not dest.exists():
            try:
                os.replace(temporary, dest)
            except PermissionError:
                if not dest.is_file():
                    raise
        return str(dest)
    except Exception as exc:
        raise ApiError(f'远程参考图检查失败：{exc}', kind=TASK_FATAL) from exc
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)
