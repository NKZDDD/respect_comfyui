"""用本机配置只读刷新全部服务商；输出无凭据的打包快照和状态。"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core import paths
from core import model_catalog, providers


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path, action='append', default=[])
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
    cfg = {}
    for path in args.config:
        data = json.loads(path.read_text(encoding='utf-8-sig'))
        cfg.update(data.get('config', data).get('providers', {}))
    def pull(pid):
        result = model_catalog.fetch(pid, cfg.get(pid, {}))
        print(json.dumps({'provider': pid, 'ok': result['ok'],
            'count': len(result.get('models', [])), 'msg': result['msg']}, ensure_ascii=False))
        return pid, result
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = dict(pool.map(pull, list(providers.REGISTRY)))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
