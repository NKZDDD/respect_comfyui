"""Wrap the batch EXE and its build manifest in a separate per-user installer."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def build(payload, makensis):
    payload = Path(payload).resolve()
    info = json.loads((payload / 'batch-build.json').read_text(encoding='utf-8'))
    exe = payload / 'RespectBatch-User.exe'
    with exe.open('rb') as fp:
        if hashlib.file_digest(fp, 'sha256').hexdigest() != info['sha256']:
            raise ValueError('批量版程序与构建清单不一致')
    output = payload / f"Respect-Batch-Setup-{info['version']}.exe"
    subprocess.run([str(makensis), '/V2', '/INPUTCHARSET', 'UTF8', '/DVERSION='+info['version'],
        '/DPAYLOAD='+str(payload), '/DOUTPUT='+str(output), str(Path(__file__).with_name('batch-installer.nsi'))], check=True)
    with output.open('rb') as fp:
        sha = hashlib.file_digest(fp, 'sha256').hexdigest()
    manifest = dict(application='batch', flavor='batch', version=info['version'], build_sha256=info['sha256'],
                    sha256=sha, bytes=output.stat().st_size, url='', notes='批量版支持独立下载安装更新', mandatory=False)
    (payload / 'release.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(output)
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--payload', required=True, type=Path)
    parser.add_argument('--makensis', required=True, type=Path)
    args = parser.parse_args()
    build(args.payload, args.makensis)
