"""Build a login-only distribution. No provider profile or credential file is read."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.managed import VERSION
from tools.release_page import render


def page():
    text = render((ROOT / 'web/index.html').read_text(encoding='utf-8')).decode('utf-8')
    if text.count('\nboot();') != 1:
        raise ValueError('发行页面启动入口已变化，请更新构建器')
    scripts = '\n'.join((ROOT / 'web' / name).read_text(encoding='utf-8') for name in ('managed.js', 'updates.js'))
    text = text.replace('\nboot();', '\n' + scripts)
    return text.encode('utf-8')


def stage(target):
    target = Path(target)
    target.mkdir(parents=True, exist_ok=False)
    shutil.copytree(ROOT / 'core', target / 'core', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    shutil.copy2(ROOT / 'release_main.py', target / 'release_main.py')
    module = ('ENABLED = True\nMANAGED = True\n'
              'def profile():\n    from .managed import manager\n    return manager.snapshot()\n'
              f'def page():\n    return {page()!r}\n')
    (target / 'core/distribution.py').write_text(module, encoding='utf-8')
    return target


def manifests(exe, destination):
    digest = hashlib.sha256(exe.read_bytes()).hexdigest()
    build = dict(version=VERSION, exe=exe.name, sha256=digest)
    registration = dict(version=VERSION, application='batch', flavor='batch', build_sha256=digest)
    for name, data in [('batch-build.json', build), ('batch-registration.json', registration)]:
        (destination / name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    return registration


def main():
    parser = argparse.ArgumentParser(description='构建在线授权批量版（不读取或封装 Key）')
    parser.add_argument('--build', type=Path, required=True, help='新的构建根目录，建议选择 D 盘')
    parser.add_argument('--stage-only', action='store_true')
    parser.add_argument('--jobs', type=int, default=4)
    args = parser.parse_args()
    root = args.build.resolve()
    source = stage(root / ('source-' + uuid.uuid4().hex[:8]))
    if args.stage_only:
        print(source)
        return
    env = os.environ.copy()
    env['NUITKA_CACHE_DIR'] = str(root / 'cache')
    env['NUITKA_CACHE_DIR_DOWNLOADS'] = str(root / 'cache/downloads')
    env.setdefault('CFLAGS', '-O1')
    (root / 'temp').mkdir(exist_ok=True)
    env['TEMP'] = env['TMP'] = str(root / 'temp')
    subprocess.run([sys.executable, '-m', 'nuitka', '--mode=onefile', '--onefile-no-dll',
        '--mingw64', '--assume-yes-for-downloads', '--enable-plugin=tk-inter', '--include-package=core',
        # Managed uploads use HTTPS signatures; the S3 credential SDK is not used in this build.
        '--nofollow-import-to=pytest,numpy,matplotlib,boto3,botocore', '--python-flag=isolated', '--python-flag=no_site',
        '--windows-console-mode=force', '--lto=no', f'--jobs={max(1,args.jobs)}',
        f'--output-dir={root / "compiled"}', '--output-filename=RespectBatch-User.exe', 'release_main.py'],
        cwd=source, env=env, check=True)
    exe = root / 'compiled/RespectBatch-User.exe'
    if not exe.is_file() or exe.stat().st_size < 1024:
        raise RuntimeError('编译未生成完整程序')
    delivery = root / 'delivery'
    delivery.mkdir(exist_ok=True)
    target = delivery / exe.name
    shutil.copy2(exe, target)
    manifests(target, delivery)
    shutil.copy2(ROOT / 'MANAGED-CLIENT.md', delivery / '使用说明.md')
    print(f'在线授权批量版：{delivery}；请先在后台登记 batch-registration.json，再分发 EXE 与 batch-build.json')


if __name__ == '__main__':
    main()
