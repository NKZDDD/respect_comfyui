"""编译独立的自用单文件 EXE；仅复制源码和无密钥模型快照。"""
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

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--jobs', type=int, default=4)
    parser.add_argument('--reuse-build', default='', help='复用尚未交付的自用构建目录')
    args = parser.parse_args()
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
    if args.reuse_build and not re.fullmatch(r'personal-[0-9a-f]{12}', args.reuse_build):
        raise ValueError('构建目录格式错误')
    build_id = args.reuse_build or 'personal-' + uuid.uuid4().hex[:12]
    stage = ROOT / 'release-build' / build_id
    stage.mkdir(exist_ok=bool(args.reuse_build))
    shutil.copytree(ROOT / 'core', stage / 'core', dirs_exist_ok=bool(args.reuse_build),
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    shutil.copytree(ROOT / 'web', stage / 'web', dirs_exist_ok=bool(args.reuse_build))
    for name in ('run.py', 'personal_main.py'):
        shutil.copy2(ROOT / name, stage / name)
    for path in (stage / 'run.py', stage / 'web' / 'index.html'):
        text = path.read_text(encoding='utf-8')
        text = text.replace('Respect 批量并发', 'Respect 创作服务 · 自用版')
        text = text.replace('Respect 创作服务</title>', 'Respect 创作服务 · 自用版</title>')
        path.write_text(text, encoding='utf-8')
    snapshot = json.loads(args.snapshot.read_text(encoding='utf-8'))
    (stage / 'model-snapshot.json').write_text(json.dumps(snapshot, ensure_ascii=False), encoding='utf-8')
    out = ROOT / 'release-dist' / build_id
    env = os.environ.copy()
    env.setdefault('NUITKA_CACHE_DIR_DOWNLOADS', str(ROOT / 'release-build' / 'tool-cache'))
    env.setdefault('CFLAGS', '-O1')
    name = 'Respect-Creative-Personal-1.2.0.exe'
    cmd = [sys.executable, '-m', 'nuitka', '--mode=onefile', '--onefile-no-dll', '--mingw64',
        '--assume-yes-for-downloads', '--enable-plugin=tk-inter', '--include-package=core',
        '--include-data-dir=web=web', '--include-data-files=model-snapshot.json=model-snapshot.json',
        '--nofollow-import-to=pytest,numpy,matplotlib', '--python-flag=isolated',
        '--python-flag=no_site', '--python-flag=no_docstrings', '--company-name=Respect Team',
        '--product-name=Respect Creative Personal', '--file-description=Respect Creative Personal',
        '--file-version=1.2.0.0', '--windows-console-mode=force', f'--jobs={max(1,args.jobs)}',
        '--lto=no', f'--output-dir={out}', f'--output-filename={name}', 'personal_main.py']
    print('构建目录：' + str(stage), flush=True)
    subprocess.run(cmd, cwd=stage, env=env, check=True)
    bundle = out / 'personal_main.dist'
    assert not any(p.suffix.lower() in ('.py', '.pyc', '.pyw') for p in bundle.rglob('*'))
    assert not (bundle / 'config.json').exists()
    exe = out / name
    report = {'exe': str(exe), 'sha256': hashlib.sha256(exe.read_bytes()).hexdigest(),
              'mode': 'onefile', 'credentials_embedded': False,
              'refreshed_providers': [k for k,v in snapshot.items() if v['ok']]}
    (out / 'build-report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
